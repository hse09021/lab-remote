"""1회용 허가.

승인이 "그 호출 하나" 만 열어야 한다. 여기서 새면 ②의 승인 대기열 전체가
무의미해지므로, 안전벨트를 하나씩 못박는다.

핵심 둘:
  - **서명 없는 가짜 허가는 잠기지 않은 `ask` 항목에도 안 먹힌다.**
  - **잠긴 항목은 허가 파일을 손으로 넣어도 안 열린다.**
"""

import json
import os
import subprocess
import sys

import pytest

from app import config, grants, registry


#: `hook_event` 픽스처가 쓰는 세션 ID. 허가는 **그 세션에서만** 먹는다(S3).
SESSION = "sess-테스트"


def _issue(project, **kw):
    """시험용 발급. 세션 ID 를 기본으로 채운다.

    S3 에서 `grants.issue` 가 `session_id` 를 **요구**한다 — 허가가 읽기
    전용이 되면서 "그 세션 안에서만" 이 1회용 보장의 한 겹이 됐다.
    """
    kw.setdefault("session_id", SESSION)
    return grants.issue(project, **kw)


TOOL_INPUT = {"command": "pip install peft"}


@pytest.fixture()
def project(isolated_data, project_root):
    registry.register(project_root, "hook-sandbox")
    return "hook-sandbox"


def event(tool="Bash", tool_input=None):
    # 세션 ID 를 꼭 넣는다 — 허가는 **그 세션에서만** 먹는다(S3).
    return {
        "tool_name": tool,
        "tool_input": tool_input if tool_input is not None else TOOL_INPUT,
        "session_id": SESSION,
    }


def grant_file(project, fingerprint):
    return os.path.join(
        registry.grants_dir(project), fingerprint.split(":", 1)[-1] + ".json"
    )


# --- 지문 ---------------------------------------------------------------------


def test_지문은_같은_입력에_같다():
    first = grants.fingerprint("Bash", {"command": "ls", "timeout": 1})
    second = grants.fingerprint("Bash", {"timeout": 1, "command": "ls"})
    assert first == second  # 키 순서는 상관없다
    assert first.startswith("sha256:")


def test_지문은_한_글자만_달라도_달라진다():
    assert grants.fingerprint("Bash", {"command": "ls"}) != grants.fingerprint(
        "Bash", {"command": "ls "}
    )
    assert grants.fingerprint("Bash", {"command": "ls"}) != grants.fingerprint(
        "Write", {"command": "ls"}
    )


def test_입력_요약은_본문을_남기지_않는다():
    summary = grants.summarize_input(
        {"file_path": "src/train.py", "content": "비밀이 섞일 수 있는 본문" * 10}
    )
    assert summary["file_path"] == "src/train.py"
    assert set(summary["content"]) == {"len", "sha256"}
    assert "비밀" not in json.dumps(summary, ensure_ascii=False)


# --- 서명 ---------------------------------------------------------------------


def test_서명이_맞으면_통과(grant_key):
    key = config.grant_key()
    grant = {"grantId": "g-1", "project": "p"}
    grant["sig"] = grants.sign(grant, key)
    assert grants.verify(grant, key) is True


def test_한_글자_고치면_서명이_깨진다(grant_key):
    key = config.grant_key()
    grant = {"grantId": "g-1", "project": "p", "actionKey": "pkg"}
    grant["sig"] = grants.sign(grant, key)
    grant["actionKey"] = "outside"
    assert grants.verify(grant, key) is False


def test_키가_없으면_서명이_전부_무효(grant_key):
    key = config.grant_key()
    grant = {"grantId": "g-1"}
    grant["sig"] = grants.sign(grant, key)
    assert grants.verify(grant, None) is False


def test_서명이_없으면_무효(grant_key):
    assert grants.verify({"grantId": "g-1"}, config.grant_key()) is False


# --- 발급 ---------------------------------------------------------------------


def test_발급하면_파일이_생긴다(project, grant_key):
    grant = _issue(
        project, tool="Bash", tool_input=TOOL_INPUT, action_key="pkg", summary="pip install peft"
    )
    assert os.path.exists(grant_file(project, grant["fingerprint"]))
    assert grant["uses"] == 1
    assert grants.verify(grant, config.grant_key())


def test_잠긴_행동은_발급을_거절한다(project, grant_key):
    for action in sorted(grants.LOCKED_ACTIONS):
        with pytest.raises(grants.GrantError):
            _issue(project, tool="Write", tool_input={"file_path": "/etc/x"}, action_key=action)


def test_Bash_는_느슨한_일치를_못_쓴다(project, grant_key):
    with pytest.raises(grants.GrantError) as exc:
        _issue(project, tool="Bash", tool_input=TOOL_INPUT, action_key="pkg", loose=True)
    assert "명령 전체가 의미" in str(exc.value)


def test_서명_키가_없으면_발급을_거절한다(project, isolated_config):
    with pytest.raises(grants.GrantError) as exc:
        _issue(project, tool="Bash", tool_input=TOOL_INPUT, action_key="pkg")
    assert "서명 키가 없어요" in str(exc.value)


# --- 소비 ---------------------------------------------------------------------


def test_허가가_없으면_None(project, grant_key):
    assert grants.consume(project, event=event(), needs=[("pkg", None)]) is None


def test_발급한_허가를_소비한다(project, grant_key):
    issued = _issue(project, tool="Bash", tool_input=TOOL_INPUT, action_key="pkg")
    used = grants.consume(project, event=event(), needs=[("pkg", None)])
    assert used and used["grantId"] == issued["grantId"]


def test_소비가_파일을_한_바이트도_안_바꾼다(project, grant_key):
    """🔑 S3 의 핵심.

    전에는 `os.rename` 으로 claim 한 뒤 `.consumed/` 로 옮겼다 — 그게 1회용
    보장이었다. 하지만 훅이 `grants/` 에 쓸 수 있으면 **AI 가 쓴 코드도 쓸 수
    있다.** 샌드박스 안에서 `server/data` 쓰기가 실패하는 것(M1b)이 허가를
    믿는 **유일한 근거**이므로 그 폴더는 통째로 읽기 전용이어야 한다.
    """
    issued = _issue(project, tool="Bash", tool_input=TOOL_INPUT, action_key="pkg")
    path = grant_file(project, issued["fingerprint"])
    folder = registry.grants_dir(project)
    before = {n: open(os.path.join(folder, n), "rb").read() for n in sorted(os.listdir(folder))}

    assert grants.consume(project, event=event(), needs=[("pkg", None)])

    after = {n: open(os.path.join(folder, n), "rb").read() for n in sorted(os.listdir(folder))}
    assert after == before, "소비가 파일을 바꿨어요"
    assert os.path.exists(path)
    # `.consumed/` 를 더 이상 만들지 않는다
    assert not os.path.exists(os.path.join(folder, ".consumed"))


def test_같은_세션_안에서는_또_먹는다(project, grant_key):
    """⚠ **약해진 점.** 훅이 아무것도 안 쓰는 대가다.

    1회용은 세 겹으로 옮겼다 — 세션 일치 · TTL 10분 ·
    **오케스트레이터가 재개한 세션이 끝난 뒤 파일을 지움**.
    `docs/operations.md` 에 한계로 적었다.
    """
    _issue(project, tool="Bash", tool_input=TOOL_INPUT, action_key="pkg")
    assert grants.consume(project, event=event(), needs=[("pkg", None)])
    assert grants.consume(project, event=event(), needs=[("pkg", None)])


def test_오케스트레이터가_세션_뒤에_지우면_안_먹힌다(project, grant_key):
    issued = _issue(project, tool="Bash", tool_input=TOOL_INPUT, action_key="pkg")
    assert grants.consume(project, event=event(), needs=[("pkg", None)])

    dropped = grants.drop_for_session(project, SESSION)

    assert dropped == [issued["grantId"]]
    assert not os.path.exists(grant_file(project, issued["fingerprint"]))
    assert grants.consume(project, event=event(), needs=[("pkg", None)]) is None


def test_다른_세션의_허가는_안_지운다(project, grant_key):
    kept = _issue(project, tool="Bash", tool_input=TOOL_INPUT, action_key="pkg",
                  session_id="다른세션")
    assert grants.drop_for_session(project, SESSION) == []
    assert os.path.exists(grant_file(project, kept["fingerprint"]))
    assert grants.drop_for_session(project, "") == []


def test_만료되면_안_먹힌다(project, grant_key):
    _issue(project, tool="Bash", tool_input=TOOL_INPUT, action_key="pkg", ttl_sec=1)
    from datetime import datetime, timedelta

    later = datetime.now().astimezone() + timedelta(seconds=5)
    assert grants.consume(project, event=event(), needs=[("pkg", None)], now=later) is None


def test_만료된_허가도_치우지_않는다(project, grant_key):
    """읽기 전용이라 아무것도 치우지 않는다. 쓸 수 없는 건 `_usable` 이 막는다.

    쌓인 파일은 오케스트레이터가 세션 뒤에 지우고(`drop_for_session`),
    사람은 `labremote approvals revoke` 로 지운다.
    """
    issued = _issue(project, tool="Bash", tool_input=TOOL_INPUT, action_key="pkg", ttl_sec=1)
    from datetime import datetime, timedelta

    later = datetime.now().astimezone() + timedelta(seconds=5)
    seen = []
    assert grants.consume(
        project, event=event(), needs=[("pkg", None)], now=later, log=seen.append
    ) is None
    assert os.path.exists(grant_file(project, issued["fingerprint"]))
    # 사람이 알아야 하므로 기록은 남는다
    assert [e["event"] for e in seen] == ["grantExpired"]


def test_기본_TTL_은_10분이다():
    """허가가 읽기 전용이 되면서 창을 좁혔다 (전에는 30분)."""
    assert grants.DEFAULT_TTL_SEC == 600


def test_입력이_다르면_안_먹힌다(project, grant_key):
    _issue(project, tool="Bash", tool_input=TOOL_INPUT, action_key="pkg")
    other = event(tool_input={"command": "pip install torch"})
    assert grants.consume(project, event=other, needs=[("pkg", None)]) is None


def test_안_맞는_허가는_그대로_있다(project, grant_key):
    """남의 허가를 소비해 버리면 그 승인이 사라진다. 이제는 아무것도 안 건드린다."""
    issued = _issue(project, tool="Bash", tool_input=TOOL_INPUT, action_key="pkg")
    grants.consume(project, event=event(tool_input={"command": "다른 명령"}), needs=[("pkg", None)])
    assert os.path.exists(grant_file(project, issued["fingerprint"]))
    assert grants.consume(project, event=event(), needs=[("pkg", None)])  # 원래 호출엔 여전히 먹힌다


def test_행동_유형이_다르면_안_먹힌다(project, grant_key):
    _issue(project, tool="Bash", tool_input=TOOL_INPUT, action_key="pkg")
    assert grants.consume(project, event=event(), needs=[("net", None)]) is None


def test_다른_프로젝트의_허가는_안_먹힌다(project, grant_key, tmp_path):
    other_root = str(tmp_path / "projects" / "다른프로젝트")
    os.makedirs(other_root, exist_ok=True)
    registry.register(other_root, "other-proj")
    issued = _issue("other-proj", tool="Bash", tool_input=TOOL_INPUT, action_key="pkg")
    # 파일을 이 프로젝트 폴더로 옮겨 놓아도 project 칸이 안 맞는다.
    target = grant_file(project, issued["fingerprint"])
    os.makedirs(os.path.dirname(target), exist_ok=True)
    os.replace(grant_file("other-proj", issued["fingerprint"]), target)
    assert grants.consume(project, event=event(), needs=[("pkg", None)]) is None


# --- 잠금과 실행 중 조건 -----------------------------------------------------


def test_잠긴_항목은_손으로_넣어도_안_열린다(project, grant_key):
    """7종 각각. `decide` 는 이들에 DENY 를 바로 return 하지만, 두 번째
    자물쇠로 여기서도 막는다."""
    key = config.grant_key()
    for action in (
        "outside",
        "selfProtect",
        "hardProtect",
        "secret",
        "outputProtect",
        "schema-unknown",
        "denied-command",
    ):
        grant = {
            "version": 1,
            "grantId": f"g-손으로-{action}",
            "project": project,
            "fingerprint": grants.fingerprint("Bash", TOOL_INPUT),
            "looseKey": grants.loose_key("Bash", None),
            "looseMatch": False,
            "tool": "Bash",
            "actionKey": action,
            "rel": None,
            "expiresAt": "2099-01-01T00:00:00+09:00",
            "uses": 1,
        }
        grant["sig"] = grants.sign(grant, key)  # 서명까지 맞게 만들어도
        registry.write_json(grant_file(project, grant["fingerprint"]), grant)
        assert grants.consume(project, event=event(), needs=[(action, None)]) is None, action


def test_서명_없는_가짜_허가는_잠기지_않은_ask_에도_안_먹힌다(project, grant_key):
    """`pkg` 는 잠긴 항목이 아니다. 그래도 서명이 없으면 안 먹혀야 한다 —
    샌드박스가 뚫려 AI 가 쓴 코드가 허가 파일을 만들어도 못 쓰게."""
    fingerprint = grants.fingerprint("Bash", TOOL_INPUT)
    fake = {
        "version": 1,
        "grantId": "g-가짜",
        "project": project,
        "fingerprint": fingerprint,
        "looseMatch": False,
        "tool": "Bash",
        "actionKey": "pkg",
        "expiresAt": "2099-01-01T00:00:00+09:00",
        "uses": 1,
    }
    registry.write_json(grant_file(project, fingerprint), fake)
    seen = []
    assert grants.consume(project, event=event(), needs=[("pkg", None)], log=seen.append) is None
    assert [e["event"] for e in seen] == ["grantBadSignature"]


def test_서명이_틀린_허가는_안_먹힌다(project, grant_key):
    fingerprint = grants.fingerprint("Bash", TOOL_INPUT)
    registry.write_json(
        grant_file(project, fingerprint),
        {"project": project, "fingerprint": fingerprint, "actionKey": "pkg", "sig": "hmac-sha256:틀림"},
    )
    seen = []
    assert grants.consume(
        project, event=event(), needs=[("pkg", None)], log=seen.append
    ) is None
    # 파일은 그대로 둔다 (읽기 전용) — 사람이 보고 지운다
    assert os.path.exists(grant_file(project, fingerprint))
    assert [e["event"] for e in seen] == ["grantBadSignature"]


def test_실험이_도는_중이면_stop_허가가_안_먹힌다(project, grant_key):
    """승인할 때는 멈춰 있었어도, 쓸 때 돌고 있으면 안 된다 (spec III-4)."""
    tool_input = {"file_path": "docs/Evaluation.md", "old_string": "a", "new_string": "b"}
    _issue(project, tool="Edit", tool_input=tool_input, action_key="stop", rel="docs/Evaluation.md")
    ev = event("Edit", tool_input)
    assert grants.consume(project, event=ev, needs=[("stop", "docs/Evaluation.md")], running=True) is None
    assert grants.consume(project, event=ev, needs=[("stop", "docs/Evaluation.md")], running=False)


def test_덧붙일_수_없는_이전_실험_파일은_안_먹힌다(project, grant_key):
    tool_input = {"file_path": "experiments/EXP-001/result.csv", "content": "x"}
    rel = "experiments/EXP-001/result.csv"
    _issue(project, tool="Write", tool_input=tool_input, action_key="prev", rel=rel)
    ev = event("Write", tool_input)
    assert grants.consume(project, event=ev, needs=[("prev", rel)], appendable=["analysis.md"]) is None


def test_덧붙일_수_있는_analysis_는_먹힌다(project, grant_key):
    tool_input = {"file_path": "experiments/EXP-001/analysis.md", "content": "x"}
    rel = "experiments/EXP-001/analysis.md"
    _issue(project, tool="Write", tool_input=tool_input, action_key="prev", rel=rel)
    ev = event("Write", tool_input)
    assert grants.consume(project, event=ev, needs=[("prev", rel)], appendable=["analysis.md"])


# --- 느슨한 일치 -------------------------------------------------------------


def test_느슨한_일치는_켜야_쓴다(project, grant_key):
    rel = "src/train.py"
    tool_input = {"file_path": rel, "content": "처음 내용"}
    _issue(project, tool="Write", tool_input=tool_input, action_key="code", rel=rel, loose=True)
    changed = event("Write", {"file_path": rel, "content": "다시 쓴 내용"})
    used = grants.consume(project, event=changed, needs=[("code", rel)])
    assert used and used["looseUsed"] is True


def test_느슨한_일치도_경로가_다르면_안_먹힌다(project, grant_key):
    rel = "src/train.py"
    _issue(
        project,
        tool="Write",
        tool_input={"file_path": rel, "content": "x"},
        action_key="code",
        rel=rel,
        loose=True,
    )
    other = event("Write", {"file_path": "src/eval.py", "content": "x"})
    assert grants.consume(project, event=other, needs=[("code", "src/eval.py")]) is None


# --- 원자적 소비 -------------------------------------------------------------


def test_두_프로세스가_같이_소비하면_둘_다_먹는다(project, grant_key, tmp_path):
    """⚠ 전에는 `os.rename` 한 줄이 상호배제였다. 읽기 전용이 되면서 그
    보장이 사라졌다 — **의도된 거래**다. 쓰기를 없애는 대가로 "같은 세션·
    같은 입력·TTL 안에서는 여러 번" 을 받아들였다."""
    _issue(project, tool="Bash", tool_input=TOOL_INPUT, action_key="pkg")
    code = (
        "import json, os, sys\n"
        "from app import grants\n"
        "used = grants.consume(sys.argv[1], event={'tool_name':'Bash',"
        "'session_id':'sess-테스트',"
        "'tool_input':{'command':'pip install peft'}}, needs=[('pkg', None)])\n"
        "print(json.dumps(bool(used)))\n"
    )
    env = {**os.environ, "PYTHONPATH": os.getcwd()}
    procs = [
        subprocess.Popen(
            [sys.executable, "-c", code, project],
            stdout=subprocess.PIPE,
            text=True,
            env=env,
            cwd=os.getcwd(),
        )
        for _ in range(2)
    ]
    outs = [json.loads(p.communicate()[0].strip()) for p in procs]
    assert outs == [True, True], outs


def test_읽을_수_없는_허가_파일은_건너뛴다(project, grant_key):
    fingerprint = grants.fingerprint("Bash", TOOL_INPUT)
    path = grant_file(project, fingerprint)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as fh:
        fh.write("{반쯤 쓰인 JSON")
    seen = []
    assert grants.consume(project, event=event(), needs=[("pkg", None)], log=seen.append) is None
    # 치우지 않는다 (읽기 전용)
    assert os.path.exists(path)
    assert [e["event"] for e in seen] == ["grantUnreadable"]


# --- 목록·취소 ---------------------------------------------------------------


def test_목록에_서명_상태가_같이_나온다(project, grant_key):
    _issue(project, tool="Bash", tool_input=TOOL_INPUT, action_key="pkg")
    listed = grants.list_grants(project)
    assert len(listed) == 1
    assert listed[0]["signatureOk"] is True
    assert listed[0]["expired"] is False


def test_취소하면_안_먹힌다(project, grant_key):
    issued = _issue(project, tool="Bash", tool_input=TOOL_INPUT, action_key="pkg")
    assert grants.revoke(project, issued["grantId"]) is True
    assert grants.consume(project, event=event(), needs=[("pkg", None)]) is None
    assert grants.revoke(project, issued["grantId"]) is False


def test_이_호출의_허가가_아니면_되돌려_둔다(project, grant_key):
    """복합 명령은 한 호출에서 findings 가 여럿이라 action 이 여럿 들어온다.
    먼저 온 action 이 남의 허가를 태워 버리면 승인이 조용히 사라진다."""
    issued = _issue(project, tool="Bash", tool_input=TOOL_INPUT, action_key="pkg")
    assert grants.consume(project, event=event(), needs=[("net", None)]) is None
    assert os.path.exists(grant_file(project, issued["fingerprint"]))
    used = grants.consume(project, event=event(), needs=[("pkg", None)])
    assert used and used["grantId"] == issued["grantId"]


def test_실행_중이라_못_쓴_허가는_남아_있다(project, grant_key):
    """실험이 끝나면 같은 승인으로 고칠 수 있어야 한다."""
    tool_input = {"file_path": "docs/Evaluation.md", "old_string": "a", "new_string": "b"}
    issued = _issue(
        project, tool="Edit", tool_input=tool_input, action_key="stop", rel="docs/Evaluation.md"
    )
    ev = event("Edit", tool_input)
    grants.consume(project, event=ev, needs=[("stop", "docs/Evaluation.md")], running=True)
    assert os.path.exists(grant_file(project, issued["fingerprint"]))


# --- 🔑 세션 (S3) -----------------------------------------------------------


def test_세션이_다르면_안_먹힌다(project, grant_key):
    """오케스트레이터는 `--resume <같은 UUID>` 로 이어 간다 — 세션 ID 가
    그대로다(`--fork-session` 은 쓰지 않는다). 다른 세션이 주워 쓰면 안 된다."""
    _issue(project, tool="Bash", tool_input=TOOL_INPUT, action_key="pkg")
    other = {**event(), "session_id": "남의세션"}
    assert grants.consume(project, event=other, needs=[("pkg", None)]) is None
    # 같은 세션이면 먹는다
    mine = {**event(), "session_id": SESSION}
    assert grants.consume(project, event=mine, needs=[("pkg", None)])


def test_세션_없이는_발급하지_않는다(project, grant_key):
    """쓸 수 없는 허가를 만들 이유가 없다 — 발급에서 막는다."""
    with pytest.raises(grants.GrantError) as exc:
        grants.issue(project, tool="Bash", tool_input=TOOL_INPUT, action_key="pkg")
    assert "세션 ID" in str(exc.value)
    with pytest.raises(grants.GrantError):
        grants.issue(project, tool="Bash", tool_input=TOOL_INPUT, action_key="pkg",
                     session_id="   ")


def test_세션_칸이_빈_허가는_안_먹힌다(project, grant_key):
    """손으로 만든 옛 판 허가. fail-closed 다."""
    fingerprint = grants.fingerprint("Bash", TOOL_INPUT)
    body = {
        "version": 1, "grantId": "g-옛판", "project": project,
        "fingerprint": fingerprint, "actionKey": "pkg", "actions": ["pkg"],
        "expiresAt": "2099-01-01T00:00:00+09:00", "sessionId": "",
    }
    body["sig"] = grants.sign(body, config.grant_key())
    registry.write_json(grant_file(project, fingerprint), body)
    seen = []
    assert grants.consume(
        project, event=event(), needs=[("pkg", None)], log=seen.append
    ) is None
    assert [e["event"] for e in seen] == ["grantNoSession"]


# --- 🔑 훅은 `grants/` 에 한 바이트도 안 쓴다 (S3) ---------------------------


def test_훅_경로에_grants_쓰기가_없다():
    """소스에서 고정한다 — `_claim`·`_archive` 가 다시 생기면 잡힌다.

    훅이 `grants/` 에 쓸 수 있으면 **AI 가 쓴 코드도 쓸 수 있다.** 샌드박스
    안에서 `server/data` 쓰기가 실패하는 것(M1b)이 허가를 믿는 유일한 근거다.
    """
    import pathlib

    body = pathlib.Path(grants.__file__).read_text(encoding="utf-8")
    # 소비 경로에서 파일을 옮기거나 지우는 함수가 없어야 한다
    assert "def _claim(" not in body
    assert "def _archive(" not in body
    # 쓰기는 **발급**과 **삭제** 두 군데뿐이다
    writers = [
        line.strip()
        for line in body.splitlines()
        if ("os.rename(" in line or "os.replace(" in line or "os.unlink(" in line
            or "write_json(" in line)
        and not line.strip().startswith("#")
    ]
    assert len(writers) == 3, writers  # issue 의 write_json · drop/revoke 의 unlink 둘


def test_소비는_폴더를_안_만든다(project, grant_key):
    """`.consumed/` 를 만들면 그 자체가 `grants/` 쓰기다."""
    _issue(project, tool="Bash", tool_input=TOOL_INPUT, action_key="pkg")
    folder = registry.grants_dir(project)
    before = sorted(os.listdir(folder))
    grants.consume(project, event=event(), needs=[("pkg", None)])
    assert sorted(os.listdir(folder)) == before


def test_재개가_끝나면_오케스트레이터가_지운다(project, project_root, conn, grant_key, monkeypatch):
    """⚠ **재개 직후가 아니라 끝난 뒤**다 — 재개하자마자 지우면 세션이 도는
    동안 훅이 못 찾는다."""
    from app.orchestrator import loop as loop_mod
    from app.orchestrator import runner_ctx

    issued = _issue(project, tool="Bash", tool_input=TOOL_INPUT, action_key="pkg")
    seen = []

    def fake_runner(made):
        # 세션이 도는 **동안**에는 허가가 있어야 한다
        seen.append(os.path.exists(grant_file(project, issued["fingerprint"])))
        return {"ok": True, "result": "", "sessionId": SESSION}

    ctx = runner_ctx.LoopCtx(
        project=project, root=project_root, preset="full", runner=fake_runner
    )
    monkeypatch.setattr(loop_mod.notifier, "send", lambda *a, **k: {"ok": True})

    got = loop_mod.resume_step(ctx, conn, SESSION, request={})

    assert seen == [True], "세션이 도는 동안 허가가 있어야 해요"
    assert got["droppedGrants"] == [issued["grantId"]]
    assert not os.path.exists(grant_file(project, issued["fingerprint"]))
