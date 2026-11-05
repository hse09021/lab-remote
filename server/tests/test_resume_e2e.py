"""🔁 승인 → 재개 → 훅 소비 → 요청 닫힘 을 **사람 개입 없이** 끝까지.

## 왜 이 파일이 생겼나 (2026-11-05, 9단계 1번에서 교착)

S9 e2e 는 `--resume` 을 **사람이 직접** 돌려서 쟀다. 그래서 루프가 스스로
재개하는 경로가 한 번도 안 돌았고, 거기 교착이 있었다.

    approve  →  허가 생김, 요청 파일은 **안 닫힘** (훅이 소비할 때 닫는다)
    up --once → 허가 있음 → 재개
                  ↳ 재개한 세션이 **그 호출을 다시 하지 않음** (실측: 도구
                    호출 0건, 훅 이벤트 0건, num_turns 2)
                  ↳ 훅이 소비 못 함 → 요청 파일 그대로
                  ↳ 재개가 끝나며 허가는 지워짐 (S3)
    up --once → "요청 열림 + 허가 없음" → **바로 멈춤**
    (사람이 또 승인해도 같은 자리로 돌아온다 — 풀릴 길이 없다)

그래서 두 갈래를 다 고정한다.

| 갈래 | 기대 |
|---|---|
| 재개한 세션이 **같은 호출을 다시 함** | 훅이 허가를 소비하고 요청이 닫히고 루프가 간다 |
| 재개한 세션이 **다시 안 함** | 요청을 닫고(기록 남기고) 루프가 **앞으로 간다** |
"""

import json
import os

import pytest

from app import approval_log as A
from app import audit, grants
from app.orchestrator import approvals as AP_ORCH
from app.orchestrator.__main__ import once, usable_grants
from app.store import approvals as AP
from app.store import loops as LP

from test_orchestrator_loop import (  # noqa: F401
    FakeClaude,
    ctx_for,
    healthy_gpu,
    plan_writes_run_json,
    ready,
    review_writes_journal,
)

COMMAND = 'grep -n -i "EXP-00" logs/Approval_log.csv | tail -30'
REQUEST_ID = "toolu_재개시험"


# --- 가짜 Claude: 막히고, 승인 뒤에 다시 하거나 안 한다 --------------------------


class AskingClaude(FakeClaude):
    """설계 세션에서 **한 번 막히고**, 재개하면 고른 대로 행동한다."""

    def __init__(self, root, *, retries_on_resume: bool):
        super().__init__(root)
        self.retries = retries_on_resume
        self.blocked_once = False
        self.hook_calls = []
        self.on_plan = plan_writes_run_json
        self.on_review = review_writes_journal

    def _hook(self, session_id):
        """훅이 그 명령을 다시 받는 것을 흉내 낸다.

        **진짜 훅 코드를 부른다** — `grants.consume` 과 요청 파일 닫기까지
        실제 경로를 지나가야 이 시험이 의미가 있다.
        """
        event = {
            "tool_name": "Bash",
            "tool_input": {"command": COMMAND},
            "session_id": session_id,
        }
        got = grants.consume(
            self.project, event=event,
            needs=[("unclassified", None)], running=False,
        )
        self.hook_calls.append({"sessionId": session_id, "grant": got})
        if got:
            A.close_request(
                self.project, REQUEST_ID,
                result="허용 · 1회용 승인", grant_id=str(got.get("grantId") or ""),
            )
        return got

    def __call__(self, made):
        prompt = made["argv"][-1]
        session_id = str(made.get("sessionId") or "")
        if "승인이 났어요" in prompt:
            # 재개 세션
            if self.retries:
                self._hook(session_id)
                # 막혀서 못 끝낸 설계를 이어서 끝낸다 (진짜 재개가 하는 일)
                plan_writes_run_json(self.root, "experiments/EXP-001/")
                return {"ok": True, "text": "같은 명령을 다시 하고 설계를 끝냈어요",
                        "stopReason": "end_turn", "raw": "", "denials": []}
            # **실측에서 이랬다** — 도구를 한 번도 안 부르고 말로만 끝냈다
            return {"ok": True, "text": "이미 필요한 정보를 다 봤어요",
                    "stopReason": "end_turn", "raw": "", "denials": []}

        if "설계 (A)" in prompt and not self.blocked_once:
            # 첫 설계: 그 명령이 막힌다 (훅이 요청 파일을 남기고, 결과 JSON 에
            # permission_denials 로 올라온다)
            self.blocked_once = True
            A.open_request(self.project, REQUEST_ID, {
                "tool": "Bash", "actionKey": "unclassified", "request": COMMAND,
                "reason": "분류 못 한 명령이에요", "sessionId": session_id,
                "fingerprint": grants.fingerprint("Bash", {"command": COMMAND}),
                "actions": [{"action": "unclassified", "name": "분류 못 한 명령"}],
            })
            return {
                "ok": True, "text": "명령이 막혀서 멈췄어요",
                "stopReason": "end_turn", "raw": "",
                "denials": [{
                    "tool_use_id": REQUEST_ID, "tool_name": "Bash",
                    "tool_input": {"command": COMMAND},
                }],
            }
        return super().__call__(made)

    @property
    def project(self):
        return "hook-sandbox"


@pytest.fixture()
def grant_ready(ready, grant_key):
    """허가에 서명할 키가 있어야 한다 — 없으면 `verify()` 가 전부 거짓이다."""
    return ready


def approve(conn):
    """사람이 하는 일을 **CLI 와 같은 함수**로."""
    return AP_ORCH.approve(conn, "hook-sandbox", REQUEST_ID)


# --- 갈래 1: 재개한 세션이 같은 호출을 다시 한다 ----------------------------------


def test_승인_재개_소비_닫힘이_사람_없이_돈다(conn, grant_ready, capsys):
    claude = AskingClaude(grant_ready, retries_on_resume=True)
    kw = ctx_for(grant_ready, claude)

    # 1) 설계에서 막힌다
    first = once(conn, "hook-sandbox", grant_ready, **kw)
    assert first["stoppedAt"] == "approval", first
    assert AP.by_request(conn, "hook-sandbox", REQUEST_ID)["state"] == "open"

    # 2) 사람이 승인한다 — 요청 파일은 **아직 열려 있다**
    grant = approve(conn)
    conn.commit()
    assert AP.by_request(conn, "hook-sandbox", REQUEST_ID)["state"] == "approved"
    assert A.list_requests("hook-sandbox"), "승인이 요청 파일을 닫으면 안 돼요"
    assert usable_grants("hook-sandbox"), "허가가 안 보여요"

    # 3) 루프가 **스스로** 재개한다 (사람이 --resume 을 안 돌린다)
    second = once(conn, "hook-sandbox", grant_ready, **kw)

    # 훅이 허가를 소비했다
    assert claude.hook_calls, "재개 세션에서 훅이 안 불렸어요"
    used = claude.hook_calls[0]["grant"]
    assert used and used["grantId"] == grant["grantId"]

    # 요청이 닫혔다
    assert A.list_requests("hook-sandbox") == []
    assert AP_ORCH.pending(conn, "hook-sandbox") == []

    # 허가도 지워졌다 (1회용)
    assert usable_grants("hook-sandbox") == []

    # 루프가 끝까지 갔다 — 여기서 멈추면 교착이다
    assert second["stoppedAt"] is None, second
    assert second["ok"] is True, second
    assert [s["stage"] for s in second["steps"]] == [
        "resume", "resume", "train", "review",
    ]


def test_같은_허가를_두_번_못_쓴다(conn, grant_ready):
    claude = AskingClaude(grant_ready, retries_on_resume=True)
    kw = ctx_for(grant_ready, claude)
    once(conn, "hook-sandbox", grant_ready, **kw)
    approve(conn)
    conn.commit()
    once(conn, "hook-sandbox", grant_ready, **kw)

    # 훅이 같은 입력으로 또 물어도 없다
    again = grants.consume(
        "hook-sandbox",
        event={
            "tool_name": "Bash",
            "tool_input": {"command": COMMAND},
            "session_id": claude.hook_calls[0]["sessionId"],
        },
        needs=[("unclassified", None)], running=False,
    )
    assert again is None


# --- 갈래 2: 재개했는데 다시 안 한다 (실측에서 교착이 난 쪽) ----------------------


def test_재개가_다시_안_하면_요청을_닫고_앞으로_간다(conn, grant_ready):
    """**이게 교착이었다.** 닫지 않으면 다음 바퀴가 영원히 바로 멈춘다."""
    claude = AskingClaude(grant_ready, retries_on_resume=False)
    kw = ctx_for(grant_ready, claude)

    once(conn, "hook-sandbox", grant_ready, **kw)
    approve(conn)
    conn.commit()

    second = once(conn, "hook-sandbox", grant_ready, **kw)

    # 훅은 안 불렸다 (Claude 가 그 호출을 다시 안 했다)
    assert claude.hook_calls == []
    # 그래도 요청은 닫혔다
    assert A.list_requests("hook-sandbox") == []
    assert AP.by_request(conn, "hook-sandbox", REQUEST_ID)["state"] == "expired"
    # 그리고 루프는 **앞으로 갔다**
    assert second["stoppedAt"] != "approval", second


def test_닫은_것을_기록에_남긴다(conn, grant_ready):
    """사람이 승인한 건이다 — "그래서 어떻게 됐나" 에 답할 수 있어야 한다."""
    from app import policy as policy_mod

    claude = AskingClaude(grant_ready, retries_on_resume=False)
    kw = ctx_for(grant_ready, claude)
    once(conn, "hook-sandbox", grant_ready, **kw)
    approve(conn)
    conn.commit()
    once(conn, "hook-sandbox", grant_ready, **kw)

    csv_path = A.log_path(grant_ready, policy_mod.load("hook-sandbox"))
    body = open(csv_path, encoding="utf-8").read()
    assert "승인 미사용" in body
    assert "다시 시도하지 않았어요" in body
    # 진본에도 — 사본만 있으면 AI 가 쓴 코드가 지울 수 있다
    assert any(r.get("toolUseId") == REQUEST_ID for r in audit.read("hook-sandbox"))


def test_다음_바퀴가_설계부터_간다(conn, grant_ready):
    """닫은 뒤에는 "요청 열림" 이 아니므로 평소 경로로 돌아가야 한다."""
    claude = AskingClaude(grant_ready, retries_on_resume=False)
    kw = ctx_for(grant_ready, claude)
    once(conn, "hook-sandbox", grant_ready, **kw)
    approve(conn)
    conn.commit()
    once(conn, "hook-sandbox", grant_ready, **kw)

    third = once(conn, "hook-sandbox", grant_ready, **kw)
    assert [s["stage"] for s in third["steps"]][0] == "plan", third


# --- 허가가 없으면 지금처럼 기다린다 ---------------------------------------------


def test_승인이_없으면_재개하지_않는다(conn, grant_ready):
    """승인도 안 났는데 띄우면 같은 자리에서 또 막히고 사용량만 쓴다."""
    claude = AskingClaude(grant_ready, retries_on_resume=True)
    kw = ctx_for(grant_ready, claude)
    once(conn, "hook-sandbox", grant_ready, **kw)
    before = len(claude.calls)

    second = once(conn, "hook-sandbox", grant_ready, **kw)
    assert second["stoppedAt"] == "approval"
    assert len(claude.calls) == before, "허가도 없이 Claude 를 띄웠어요"


def _expire_grants(project):
    """허가를 **제대로** 만료시킨다.

    `issue()` 는 음수 TTL 을 기본값으로 바꾼다(이미 만료된 허가를 만들지
    않으려고). 그래서 파일의 `expiresAt` 을 과거로 돌리고 **서명을 다시**
    한다 — 서명을 안 고치면 "만료" 가 아니라 "서명 틀림" 으로 걸려서 다른
    것을 재는 시험이 된다.
    """
    import json
    import os
    from datetime import datetime, timedelta

    from app import config as config_mod
    from app import registry

    key = config_mod.grant_key()
    folder = registry.grants_dir(project)
    changed = 0
    for name in sorted(os.listdir(folder)):
        if not name.endswith(".json") or name.startswith("."):
            continue
        path = os.path.join(folder, name)
        with open(path, encoding="utf-8") as fh:
            data = json.load(fh)
        past = datetime.now().astimezone() - timedelta(minutes=5)
        data["expiresAt"] = past.isoformat(timespec="seconds")
        data.pop("sig", None)
        data["sig"] = grants.sign(data, key)
        with open(path, "w", encoding="utf-8") as fh:
            json.dump(data, fh, ensure_ascii=False)
        changed += 1
    return changed


def test_만료된_허가로는_재개하지_않는다(conn, grant_ready):
    claude = AskingClaude(grant_ready, retries_on_resume=True)
    kw = ctx_for(grant_ready, claude)
    once(conn, "hook-sandbox", grant_ready, **kw)
    approve(conn)
    conn.commit()
    assert _expire_grants("hook-sandbox") == 1

    # 서명은 맞고 **만료만** 됐다 — 그래야 만료를 재는 시험이 된다
    listed = grants.list_grants("hook-sandbox")
    assert listed and listed[0]["signatureOk"] and listed[0]["expired"]

    assert usable_grants("hook-sandbox", request={"request_id": REQUEST_ID}) == []

    second = once(conn, "hook-sandbox", grant_ready, **kw)

    # **재개하지 않는다** — 만료된 허가로는 훅이 소비를 못 하니 세션만 버린다
    assert "resume" not in [s["stage"] for s in second["steps"]], second

    # 그래도 **닫고 앞으로 간다**: 승인은 났고 허가는 되살아나지 않는다.
    # 열어 두면 다음 바퀴마다 바로 멈추고 풀릴 길이 없다.
    assert A.list_requests("hook-sandbox") == []
    assert AP.by_request(conn, "hook-sandbox", REQUEST_ID)["state"] == "expired"
    assert [s["stage"] for s in second["steps"]][0] == "plan", second


def test_다른_요청의_허가로는_재개하지_않는다(conn, grant_ready):
    """아무 허가 하나라도 있으면 재개하던 것을 요청 기준으로 좁혔다."""
    once(conn, "hook-sandbox", grant_ready,
         **ctx_for(grant_ready, AskingClaude(grant_ready, retries_on_resume=True)))
    item = AP_ORCH.pending(conn, "hook-sandbox")[0]
    picked = usable_grants(
        "hook-sandbox",
        request={"request_id": "toolu_다른것", "session_id": "다른세션"},
    )
    assert picked == []


# --- 목록이 상태를 가른다 --------------------------------------------------------


def test_목록이_승인됨을_따로_보여_준다(conn, grant_ready, capsys):
    """"승인했는데 왜 아직 떠 있지" 로 막힌 자리다."""
    from app import cli

    claude = AskingClaude(grant_ready, retries_on_resume=True)
    once(conn, "hook-sandbox", grant_ready, **ctx_for(grant_ready, claude))
    approve(conn)
    conn.commit()

    assert AP_ORCH.granted_waiting(conn, "hook-sandbox")
    capsys.readouterr()
    assert cli.main(["approvals", "list", "hook-sandbox"]) == 0
    out = capsys.readouterr().out
    assert "승인됨 · 이어 가기 대기" in out
    assert "up --once" in out


# --- 승인됐는데 허가가 이미 지나간 상태 (교착이 난 그 상태) ----------------------


def test_승인됐는데_허가가_없으면_닫고_앞으로_간다(conn, grant_ready):
    """재개가 그 호출을 다시 안 하면 요청은 열린 채 남고 허가는 지워진다(S3).

    그 상태를 "대기" 로 두면 다음 바퀴마다 바로 멈추고, **사람이 또 승인해도
    같은 자리로 돌아온다** — 실제로 이 상태에서 교착이었다.
    """
    claude = AskingClaude(grant_ready, retries_on_resume=False)
    kw = ctx_for(grant_ready, claude)
    once(conn, "hook-sandbox", grant_ready, **kw)
    approve(conn)
    conn.commit()

    # 교착 상태를 손으로 만든다: 승인됨 + 요청 파일 있음 + 허가 없음
    AP.decide(conn, "hook-sandbox", REQUEST_ID, "approved", by="cli")
    conn.commit()
    for item in grants.list_grants("hook-sandbox"):
        grants.revoke("hook-sandbox", item["grantId"])
    assert A.list_requests("hook-sandbox"), "요청 파일이 있어야 교착이에요"
    assert usable_grants("hook-sandbox") == []

    before = len(claude.calls)
    got = once(conn, "hook-sandbox", grant_ready, **kw)

    # 닫혔고
    assert A.list_requests("hook-sandbox") == []
    assert AP.by_request(conn, "hook-sandbox", REQUEST_ID)["state"] == "expired"
    # 재개로 사용량을 또 쓰지 않았고 (허가가 없으니 재개하지 않는다)
    # 설계부터 평소대로 갔다
    assert [s["stage"] for s in got["steps"]][0] == "plan", got
    assert len(claude.calls) > before


def test_승인_전이면_그대로_기다린다(conn, grant_ready):
    """`open` 은 승인 대기의 본래 뜻이다 — 닫으면 안 된다."""
    claude = AskingClaude(grant_ready, retries_on_resume=False)
    kw = ctx_for(grant_ready, claude)
    once(conn, "hook-sandbox", grant_ready, **kw)
    assert AP.by_request(conn, "hook-sandbox", REQUEST_ID)["state"] == "open"

    got = once(conn, "hook-sandbox", grant_ready, **kw)
    assert got["stoppedAt"] == "approval"
    assert A.list_requests("hook-sandbox"), "승인 전인데 요청을 닫았어요"
    assert AP.by_request(conn, "hook-sandbox", REQUEST_ID)["state"] == "open"
