"""루프 한 바퀴 — A(설계) → B(실행) → C(분석).

PDF 9쪽은 *"한 번의 요청에서는 실험 루프를 정확히 1회 수행한다"* 이고 8단계 중
4번이 "실험 실행" 이다. 학습을 오케스트레이터가 직접 띄우기로 했으므로
**루프 1회는 유지하되 Claude 호출을 둘로 쪼갠다.**

| 토막 | 주체 | PDF 8단계 | 산출물 |
|---|---|---|---|
| **A · 설계** | `claude -p` | 1~3 | `EXP-NNN/config.yaml`, `run.json` (명세만) |
| **B · 실행** | 오케스트레이터 (Claude 없음) | 4 | `output/train.log`, `exit_code`, 체크포인트 |
| **C · 분석** | `claude -p` | 5~8 | `result.csv`·`analysis.md`·로그·`State.yaml` + Final Report |

**AI 의 말을 믿지 않는다** (spec III-4) — `result.csv` 에서 직접 읽은 값과
Final Report 의 성공 판정이 어긋나면 자동 진행을 멈추고 사람을 부른다.

Claude 를 띄우는 부분은 `runner` 를 주입받는다. 시험에서는 **가짜 Claude** 를
끼워 Claude 없이 루프를 완주시킨다.
"""

from __future__ import annotations

import os
import re
import time
from datetime import datetime

from .. import approval_log as A
from .. import audit as audit_mod
from .. import grants as grants_mod
from .. import loop_layout as L
from .. import notifier
from .. import loopstate, registry
from ..agent import launch as launch_mod
from ..agent import prompts as prompts_mod
from ..agent import report as report_mod
from ..agent import session as session_mod
from ..monitor import metrics as metrics_mod
from ..runner import cache as cache_mod
from ..runner import process as process_mod
from ..runner import spec as spec_mod
from ..store import agent_calls as AC
from ..store import events as E
from ..store import usage as U_STORE
from ..store import experiments as X
from ..store import jobs as J
from ..store import loops as LP
from . import approvals as approvals_mod
from . import installs as installs_mod
from . import usage as usage_mod
from ..git import anchor as anchor_mod
from ..git import bundle as bundle_mod
from ..git import ops as ops_mod
from . import gitflow, guards, projectguard

__all__ = [
    "UsageWait",
    "EXP_RE",
    "next_experiment_id",
    "reusable_numbers",
    "design_landed",
    "unfinished_numbers",
    "numbering_note",
    "plan_step",
    "train_step",
    "review_step",
    "resume_step",
    "waiting_approval",
    "update_order",
    "fill_journal",
    "DEFAULT_METRIC",
    "DIRECTIONS",
]

#: `EXP-007`
EXP_RE = re.compile(r"\AEXP-([0-9]{3,})\Z")

#: PDF 9쪽 Update Order. C 토막이 끝나면 이게 다 갱신됐어야 한다.
UPDATE_ORDER = (
    ("result", "{exp}/result.csv"),
    ("analysis", "{exp}/analysis.md"),
    ("experiment_log", None),
    ("decision_log", None),
    ("state", None),
)


def reusable_numbers(conn, project: str, root: str) -> list[str]:
    """배정만 되고 **한 번도 시작되지 않은** 번호. 되써도 되는 것.

    설계 세션이 멈추면(승인 대기·자기 거절) 번호와 브랜치는 이미 생겼는데
    학습은 안 돌았다. 그 번호를 버리고 다음 번호로 넘어가면 **멈출 때마다
    번호가 하나씩 죽는다** — 실측에서 EXP-003~007 다섯이 그렇게 죽었고,
    브랜치만 남아 Claude 가 매번 "이게 돌았는지 알 수 없다" 로 멈췄다.

    되쓰는 조건은 셋 다 만족할 때만이다. 하나라도 걸리면 손대지 않는다.

    * `started_at` 이 없다 = 학습을 띄운 적이 없다
    * `runstate.started` 에 없다 = 잠금이 걸린 적이 없다
    * 실험 폴더가 **아예 없다** = 아무것도 안 쓰였다
    """
    from .. import runstate

    started = set(runstate.load(project).started or [])
    out: list[str] = []
    for row in X.listing(conn, project, limit=1000):
        exp_id = str(row.get("exp_id") or "")
        if not EXP_RE.match(exp_id) or exp_id in started:
            continue
        if row.get("started_at") or str(row.get("state") or "") in ("running", "done"):
            continue
        if os.path.isdir(os.path.join(root, L.experiments_dir(), exp_id)):
            continue
        out.append(exp_id)
    return sorted(out)


def next_experiment_id(conn, project: str, root: str) -> str:
    """다음 실험 번호. **한 번이라도 시작된 번호는 다시 쓰지 않는다.**

    **맨 끝 번호가 안 쓰였으면 그걸 되쓴다.** 설계가 멈출 때마다 번호를
    버리면 멈춘 횟수만큼 번호가 죽는다 (실측: EXP-003~007 다섯).

    되쓰기는 **맨 끝 번호에만** 적용한다. 중간에 죽은 번호로 되돌아가면
    번호가 거꾸로 가고, 이미 돌아간 실험보다 작은 번호로 새 실험을 만드는
    셈이 된다. 그 번호들은 그대로 두고 `numbering_note` 가 설명한다.
    """
    used = {e["exp_id"] for e in X.listing(conn, project, limit=1000)}
    try:
        used |= {
            name
            for name in os.listdir(os.path.join(root, L.experiments_dir()))
            if EXP_RE.match(name)
        }
    except OSError:
        pass
    from .. import runstate

    used |= set(runstate.load(project).started or [])
    highest = 0
    for name in used:
        found = EXP_RE.match(name)
        if found:
            highest = max(highest, int(found.group(1)))

    top = f"EXP-{highest:03d}"
    if highest and top in reusable_numbers(conn, project, root):
        return top
    return f"EXP-{highest + 1:03d}"


def design_landed(root: str, exp_id: str) -> bool:
    """설계가 **실제로 떨어졌나.**

    `run.json` 이 있는지만 본다 — B 토막이 돌 수 있는 유일한 조건이고,
    AI 의 말이 아니라 파일이 근거다.
    """
    return os.path.isfile(
        os.path.join(root, L.experiments_dir(), exp_id, "run.json")
    )


def unfinished_numbers(conn, project: str, root: str) -> list[str]:
    """**번호만 잡히고 설계가 없는** 실험 번호.

    설계 세션이 승인 대기나 자기 거절로 끝나면 번호와 브랜치는 이미 생겨
    있다. 그걸 `planned` 로 적어 두면 두 가지가 깨진다.

    * `_resuming_experiment` 가 그 번호를 "이어 갈 실험" 으로 집어 간다 —
      `run.json` 이 없으니 B 토막이 바로 실패한다.
    * 다음 설계 세션이 *"003~005 는 planned 라는데 폴더가 없다"* 를 보고
      **무엇이 진실인지 알 수 없어 멈춘다** (실측 2026-11-05).
    """
    seen: dict[str, str] = {}
    for row in X.listing(conn, project, limit=1000):
        exp_id = str(row.get("exp_id") or "")
        if EXP_RE.match(exp_id):
            seen[exp_id] = str(row.get("state") or "")

    # **브랜치도 센다.** Claude 가 보는 건 DB 가 아니라 `git branch` 다
    # (`lab.db` 는 막혀 있다). 설계가 멈추면 브랜치만 남으므로, 설명해
    # 주지 않으면 거기서 어긋남을 발견하고 또 멈춘다.
    try:
        for name in ops_mod.branches(root):
            tail = str(name).strip().lower()
            if not tail.startswith(gitflow.BRANCH_PREFIX):
                continue
            exp_id = f"EXP-{tail[len(gitflow.BRANCH_PREFIX):]}"
            if EXP_RE.match(exp_id):
                seen.setdefault(exp_id, "")
    except (ops_mod.GitError, ops_mod.GitRefused):
        pass  # git 저장소가 아니거나 믿을 수 없으면 브랜치는 세지 않는다

    return sorted(
        exp_id
        for exp_id, state in seen.items()
        if state != "running" and not design_landed(root, exp_id)
    )


def numbering_note(conn, project: str, root: str, *, exclude: object = ()) -> str:
    """번호 상황을 **사람 말로** 적어 설계 프롬프트에 싣는다.

    Claude 가 번호 어긋남을 스스로 조사할 길이 없다 — DB 는 못 읽고
    (`lab.db` 는 막혀 있다) 브랜치만으로는 돌았는지 알 수 없다. 그래서
    **우리가 말해 준다.** 모르는 걸 추측하게 두면 멈추거나 지어낸다.
    """
    # 🔑 **지금 쓰는 번호는 빼야 한다** (실측 2026-11-05).
    #
    # 안 빼면 프롬프트가 자기 모순이 된다 — 위에서는 "`EXP-007/` 을 만들어
    # 주세요", 아래에서는 "EXP-007 은 지금 와서 채우지 않아요". Claude 는
    # 번호를 짐작하지 않고 **맞게** 멈췄다.
    skip = {str(x) for x in (exclude or ())}
    left = [x for x in unfinished_numbers(conn, project, root) if x not in skip]
    if not left:
        return ""
    shown = ", ".join(left)
    return (
        f"- 번호 {shown} 는 **설계가 시작되기 전에 멈춘 번호**예요 "
        f"(폴더도 `run.json` 도 없어요). 돌아간 실험이 아니라서 비교 대상이 "
        f"아니고, 지금 와서 그 번호를 채우지 않아요. 브랜치만 남아 있어요.\n"
        f"- 결과가 있는 실험만 보세요 — `{L.experiments_dir()}/` 에 폴더가 "
        f"있는 것들이에요.\n"
    )


def waiting_approval(conn, project: str) -> list[dict]:
    """훅이 막아 둔 요청이 있나. **파일이 진실이다** (`requests/`)."""
    approvals_mod.sync(conn, project)
    return approvals_mod.pending(conn, project)


def resume_step(ctx, conn, session_id: str, *, request: dict | None = None) -> dict:
    """승인이 난 뒤 **처음부터 다시 돌리지 않고** 이어 간다 (계획 6-1).

    프롬프트가 *"같은 도구·같은 입력으로 한 번만"* 이라고 못박는다 — 입력이
    달라지면 지문이 안 맞아 허가가 또 안 먹는다.
    """
    item = request or {}
    file_info = item.get("file") or {}
    names = [
        a.get("name") or a.get("action")
        for a in (file_info.get("actions") or [])
        if a.get("name") or a.get("action")
    ]
    prompt = prompts_mod.render(
        "resume_after_approval",
        {
            "request": str(file_info.get("request") or item.get("request") or ""),
            "actions": " · ".join(names) or str(item.get("action_key") or ""),
            "context": ctx.context,
        },
    )
    LP.set_state(conn, ctx.project, "planning")
    got = _claude(
        ctx, conn, prompt=prompt, session_id=session_id, resume=True, stage="resume"
    )

    # 🔑 **재개한 세션이 끝난 뒤** 허가 파일을 지운다 (S3).
    #
    # 허가는 읽기 전용이 됐다 — 훅이 `grants/` 에 쓸 수 있으면 AI 가 쓴 코드도
    # 쓸 수 있고, 샌드박스 안에서 그 폴더 쓰기가 실패하는 것(M1b)이 허가를
    # 믿는 유일한 근거다. 그래서 "파일이 사라짐" 으로 1회용을 보장하지 못하고,
    # **지우는 일을 오케스트레이터가** 한다.
    #
    # ⚠ **재개 직후가 아니라 끝난 뒤**다. 재개하자마자 지우면 세션이 도는
    # 동안 훅이 그 파일을 못 찾는다.
    dropped = grants_mod.drop_for_session(ctx.project, session_id)
    if dropped:
        E.add(
            conn, ctx.project, "승인",
            f"재개가 끝나서 허가를 지웠어요: {', '.join(dropped)}",
        )
    return {
        "ok": bool(got.get("ok")),
        "stage": "resume",
        "sessionId": session_id,
        "droppedGrants": dropped,
        "result": got,
    }


def guard_anchor(ctx, conn, *, when: str, with_fsck: bool = True) -> bool:
    """git 기록이 **앵커와 맞나.** 어긋나면 멈추고 사람을 부른다.

    T4 는 `.git` 이 **코드를 실행하게** 만드는 설정을 막았다. 이건 **기록
    자체**다 — `branch -D`·`commit --amend`·`reset --hard` 로 실험 기록을
    위조할 수 있다. 학습 bwrap 은 `.git` 을 읽기 전용으로 덮지만(T5) Claude 의
    Bash 샌드박스는 작업 폴더 쓰기를 못 막는다(M4).

    앵커는 `lab.db` 에 있고 샌드박스 안에서 그 파일 쓰기가 실패한다(M1b).
    **되돌리지 않는다** — 무엇이 정본인지 알 수 없다. 사람이 본다.
    """
    try:
        report = anchor_mod.check(conn, ctx.project, ctx.root, with_fsck=with_fsck)
    except ops_mod.GitRefused as exc:
        guard_git(ctx, conn, exc)
        return False
    except ops_mod.GitError:
        # git 저장소가 아니거나 아직 커밋이 없다 — 앵커도 없다.
        return True
    if report["ok"]:
        return True
    text = anchor_mod.describe(report)
    E.add(conn, ctx.project, "보안", f"git 기록이 앵커와 어긋나요 ({when})", tone="bad")
    try:
        notifier.send(
            conn,
            "blocked",
            project=ctx.project,
            subject=notifier.subject_of("gitanchor", ctx.project),
            title=f"git 기록이 바뀌었어요",
            body=text[:1500],
        )
    except Exception:
        pass
    LP.set_state(
        conn, ctx.project, "blocked",
        stop_reason=f"git 기록이 앵커와 어긋나요 ({when}) — 이전 기록이 바뀌었을 수 있어요",
    )
    return False


def _approval_csv(ctx) -> str:
    """승인 로그 CSV 경로. 정책의 `logPath` 를 본다 (못 읽으면 기본값)."""
    from .. import policy as policy_mod

    try:
        pol = policy_mod.load(ctx.project)
    except Exception:
        pol = None
    return A.log_path(ctx.root, pol)


def guard_audit(ctx, conn, *, when: str) -> bool:
    """승인 기록이 **진본과 같은가.** 다르면 멈추고 사람을 부른다.

    프로젝트의 `logs/Approval_log.csv` 는 AI 가 쓴 코드가 고칠 수 있다(M4 —
    샌드박스는 작업 디렉터리 쓰기를 못 막는다). 진본은
    `server/data/audit/<프로젝트>.jsonl` 에 있고 AI 는 거기에 못 쓴다(M1b).

    **되돌리지 않는다** — 되살리는 것은 사람이 `labremote audit <프로젝트>
    --rebuild` 로 한다. 자동으로 덮어쓰면 "무엇이 바뀌었나" 를 볼 기회가
    사라진다.
    """
    report = audit_mod.compare(ctx.project, _approval_csv(ctx))
    if report["ok"]:
        return True
    text = audit_mod.describe(report)
    E.add(conn, ctx.project, "보안", f"승인 기록이 진본과 달라요 ({when})", tone="bad")
    try:
        notifier.send(
            conn,
            "blocked",
            project=ctx.project,
            subject=notifier.subject_of("audit", ctx.project),
            title=f"승인 기록이 바뀌었어요",
            body=text[:1500],
        )
    except Exception:
        pass
    LP.set_state(
        conn, ctx.project, "blocked",
        stop_reason=f"승인 기록이 진본과 달라요 ({when}) — labremote audit 로 봐 주세요",
    )
    return False


def guard_git(ctx, conn, exc) -> None:
    """`.git` 이 거부됐다 — 멈추고 사람을 부른다.

    오케스트레이터의 git 은 **샌드박스 밖에서 사용자 권한으로** 돈다. `.git`
    에 `core.hooksPath`·`filter.*` 같은 게 심겼으면 그걸 실행해 주는 셈이다.
    되돌릴 수 없으니(무엇이 정본인지 모른다) **멈추고 사람이 본다.**
    """
    text = str(exc)
    E.add(conn, ctx.project, "보안", ".git 설정이 위험해서 git 을 돌리지 않았어요", tone="bad")
    try:
        notifier.send(
            conn,
            "blocked",
            project=ctx.project,
            subject=notifier.subject_of("gitguard", ctx.project),
            title=f".git 설정이 위험해요",
            body=text[:1500],
        )
    except Exception:
        pass
    LP.set_state(
        conn, ctx.project, "blocked",
        stop_reason=".git 이 코드를 실행하게 만드는 설정을 가졌어요 — git 을 돌리지 않았어요",
    )


def guard_project(ctx, conn, *, when: str, block: bool = True) -> dict:
    """프로젝트 설정이 정본과 다르면 **되돌리고 알린다.** — 보안 경계다.

    작업 디렉터리는 샌드박스에서 언제나 쓰기 가능하므로(M4) AI 가 쓴 코드가
    `.claude/settings.json` 에 훅을 써 넣거나 `sandbox.enabled:false` 로
    다음 세션의 샌드박스를 끌 수 있다 — 실측에서 둘 다 됐다(M6).

    런처는 그 파일을 안 읽지만(`--setting-sources user`), **맨손 `claude`** 로
    열면 읽힌다. 그래서 되돌린다.

    | 부르는 자리 | `block` | 왜 |
    |---|---|---|
    | 루프 시작 전 | False | 이미 손댄 흔적이다. 되돌리고 계속한다 |
    | Claude 세션 종료 직후 | **True** | 그 세션이 범인이다. 멈추고 사람을 부른다 |
    | 기록 커밋 전 | **True** | 오염을 커밋에 넣지 않는다 |
    """
    got = projectguard.restore(ctx.root, ctx.project)
    if got.get("ok"):
        return got
    text = projectguard.describe(got)
    E.add(conn, ctx.project, "보안", f"프로젝트 설정이 바뀌어 있었어요 ({when}) — 되돌렸어요", tone="bad")
    try:
        notifier.send(
            conn,
            "blocked",
            project=ctx.project,
            subject=notifier.subject_of("projectguard", when),
            title=f"프로젝트 설정이 바뀌어 있었어요",
            body=text,
            fields=[
                ("언제", when),
                ("되돌린 파일", ", ".join(got.get("restored") or []) or "없음"),
                ("증거", got.get("evidence") or "[못 남겼어요]"),
            ],
        )
    except Exception:
        # 알림 실패가 루프를 멈추지 않는다 (notify 의 예외 삼킴 원칙).
        pass
    if block:
        LP.set_state(
            conn, ctx.project, "blocked",
            stop_reason=f"프로젝트 설정이 바뀌어 있었어요 ({when}) — 되돌렸어요",
        )
    return got


class UsageWait(Exception):
    """사용량 한도로 **기다리는 중**이다. AI 세션을 띄우지 않는다.

    🔑 `orchestrator/usage.py` 는 다 만들어져 있었는데 **아무도 안 불렀다**
    (실측 2026-11-05: `record_failure`·`wait_state`·`resumed` 전부 미사용,
    `loop_state` 의 `usage_limited` 도 라벨로만 있었다). 그러면 한도에
    걸렸을 때 루프가 `IDLE_SEC`(10초)마다 Claude 를 다시 띄우고, 매번 실패
    원문만 쌓이고 알림도 없다 — 자리를 비운 사이에 조용히 망가진다.

    **학습은 건드리지 않는다** (spec V). 멈추는 건 AI 의 의사결정뿐이다.
    """

    def __init__(self, state: dict):
        self.state = dict(state or {})
        super().__init__(self.state.get("reason") or "사용량 한도로 기다려요")


def _usage_reason(row: dict, *, first: bool = False) -> str:
    resume_at = str((row or {}).get("resume_at") or "")[:19].replace("T", " ")
    head = "응답이 막혀서 기다려요" if first else "아직 막혀 있어요"
    tail = f" · 다음 시도 {resume_at}" if resume_at else ""
    return f"{head} (추가 결제 없이 기다려요){tail}"


def _usage_gate(ctx, conn) -> None:
    """AI 세션을 띄우기 **전에** 본다. 기다리는 중이면 띄우지 않는다."""
    state = usage_mod.wait_state(conn, ctx.project)
    if not state["waiting"]:
        return
    row = state["row"] or {}
    newest = state.get("newest") or row
    if state["notify"]:
        _usage_notify(ctx, conn, newest, first=True)
    elif state["renotify"]:
        _usage_notify(ctx, conn, newest, first=False)
    if state["ready"]:
        return  # 다시 해 볼 때가 됐다
    LP.set_state(conn, ctx.project, "usage_limited")
    raise UsageWait({"reason": _usage_reason(newest), "usageId": row.get("id")})


def _usage_notify(ctx, conn, row: dict, *, first: bool) -> None:
    """대기에 들어갈 때 **한 번만.** 오래 막혀 있으면 한 번 더."""
    detected = str((row or {}).get("detected_by") or "backoff")
    title = (
        f"Claude 응답이 막혔어요 · {ctx.project}"
        if first
        else f"오래 막혀 있어요 · 한도가 아닐 수 있어요 · {ctx.project}"
    )
    body = (
        "추가 결제 없이 기다려요. 돌고 있는 학습은 건드리지 않아요."
        if first
        else "인증 만료 같은 다른 오류일 수 있어요. `labremote usage` 로 원문을 보세요."
    )
    notifier.send(
        conn,
        "usage_limit",
        project=ctx.project,
        subject=notifier.subject_of("usage", f"{row.get('id')}:{'1' if first else '2'}"),
        title=title,
        body=body,
        fields=[
            ("감지 근거", "패턴 일치" if detected == "pattern" else "원인 구분 없이 백오프"),
            ("다음 재시도", str((row or {}).get("resume_at") or "[미확인]")),
            ("원문", "`labremote usage` · lab.db 의 usage_limits"),
        ],
    )
    if first and row.get("id"):
        try:
            U_STORE.mark_notified(conn, int(row["id"]))
        except Exception:
            pass


def _claude(
    ctx, conn, *, prompt: str, session_id: str, resume: bool, stage: str = ""
) -> dict:
    """Claude 를 한 번 띄운다. `ctx.runner` 가 실제 실행을 맡는다.

    한도로 기다리는 중이면 **띄우지 않고** `UsageWait` 를 던진다. 실패하면
    원문을 보관하고 대기에 들어간다 — 10초마다 다시 때리지 않는다.
    """
    _usage_gate(ctx, conn)
    run = launch_mod.AgentRun(
        project=ctx.project,
        root=ctx.root,
        prompt=prompt,
        session_id=session_id,
        permission_mode=ctx.permission_mode,
        headless=True,
        resume=resume,
        cache_dir=ctx.cache_dir,
    )
    made = launch_mod.plan(run, preset=ctx.preset)
    began = time.monotonic()
    got = ctx.runner(made)
    wall_ms = int((time.monotonic() - began) * 1000)

    # 📊 사용량과 시간을 **버리지 않는다.** `result.parse` 가 읽어 둔 숫자를
    # 루프가 끝나면 되살릴 수 없었다 (9단계 검증표가 루프 1회당 사용량을
    # 요구한다). 기록이 실패해도 루프는 계속 간다.
    try:
        state = LP.get(conn, ctx.project) or {}
        AC.record(
            conn, ctx.project, stage,
            got,
            loop_no=state.get("loop_no"),
            session_id=session_id,
            resumed=resume,
            wall_ms=wall_ms,
        )
    except Exception:
        pass

    # 📉 **한도 판정.** 실패 원문은 어떤 경우에도 보관한다 — 나중에 실제로
    # 한도에 걸리면 그 문구로 "한도 대기" 를 구분할 수 있다 (패턴은 코드에
    # 박지 않고 `~/.config/labremote/usage_patterns.json` 에 둔다).
    if got.get("ok"):
        try:
            if usage_mod.resumed(conn, ctx.project):
                E.add(conn, ctx.project, "한도", "응답이 다시 와요 — 이어 가요", tone="good")
                LP.set_state(conn, ctx.project, "planning")
        except Exception:
            pass
    else:
        hit = None
        try:
            hit = usage_mod.record_failure(conn, ctx.project, got)
        except Exception:
            pass
        if hit:
            E.add(
                conn, ctx.project, "한도",
                "Claude 응답이 막혔어요 (추가 결제 없이 기다려요) · 다음 시도 "
                + str(hit.get("resumeAt") or "[미확인]"),
                tone="attention",
            )
            LP.set_state(conn, ctx.project, "usage_limited")
            state = usage_mod.wait_state(conn, ctx.project)
            row = state.get("newest") or state["row"] or {}
            if state["notify"]:
                _usage_notify(ctx, conn, row, first=True)
            raise UsageWait(
                {"reason": _usage_reason(row, first=True), "usageId": hit.get("usageId")}
            )

    # 🔑 승인 내용과 지문은 **자기 자식의 결과 JSON** 에서 만든다 (원칙 (나)).
    # 훅의 요청 파일보다 먼저 이걸 본다 — 본문이 여기에만 있어서 지문을
    # 직접 계산할 수 있고, 훅이 파일을 못 썼어도 무엇이 막혔는지 안다.
    try:
        approvals_mod.sync_from_result(
            conn, ctx.project, got, session_id=session_id
        )
    except Exception:
        # 승인 거울이 루프를 멈추지 않는다. 훅의 요청 파일이 보조로 남는다.
        pass

    # 세션이 끝난 **직후**가 가장 짧은 창이다. 이 세션이 쓴 코드가 프로젝트
    # 설정을 고쳤으면 다음 세션(과 사람의 대화형 세션)이 그걸 읽는다.
    guard_project(ctx, conn, when="Claude 세션 종료 직후")
    # 📦 Claude 가 설치 요청을 남겼으면 승인 대기를 연다. 설치는 사람이
    # 승인한 뒤 **오케스트레이터가 샌드박스 밖에서** 한다 (M3: Claude 의
    # Bash 로는 조용히 실패한다).
    try:
        installs_mod.sync(conn, ctx.project, ctx.root, session_id=session_id)
    except Exception:
        # 설치 요청 처리가 루프를 멈추지 않는다.
        pass
    return got


def plan_step(ctx, conn) -> dict:
    """A · 설계. Claude 가 `run.json` 까지 쓴다."""
    # 루프를 시작하기 전에 프로젝트 설정을 정본으로 맞춘다. 지난 루프나
    # 사람의 대화형 세션 뒤에 남은 흔적이 있을 수 있다. 되돌리고 **계속**한다.
    guard_project(ctx, conn, when="루프 시작 전", block=False)
    # git 기록이 앵커와 맞나. 어긋나면 **루프를 시작하지 않는다** — 위조된
    # 기록 위에 실험을 더 쌓지 않는다.
    if not guard_anchor(ctx, conn, when="루프 시작 전"):
        return {
            "ok": False, "stage": "plan", "blocked": True,
            "reason": "git 기록이 앵커와 어긋나요",
        }
    verdict = guards.check_loop(conn, ctx.project, ctx.root)
    if not verdict.ok:
        LP.set_state(
            conn, ctx.project, "stopped" if verdict["stop"] else "paused", stop_reason=verdict["reason"]
        )
        return {"ok": False, "stage": "plan", "reason": verdict["reason"], "stop": verdict["stop"]}

    exp_id = next_experiment_id(conn, ctx.project, ctx.root)
    loop_no = LP.bump_loop(conn, ctx.project)
    LP.set_state(conn, ctx.project, "planning")
    try:
        gitflow.start_experiment(ctx.root, exp_id, running=False)
        # 우리가 만든 브랜치의 HEAD 를 기준값으로 남긴다.
        anchor_mod.record_all(conn, ctx.project, ctx.root, note=f"{exp_id} 시작")
    except ops_mod.GitRefused as exc:
        guard_git(ctx, conn, exc)
        return {
            "ok": False, "stage": "plan", "blocked": True,
            "reason": str(exc).splitlines()[0],
        }
    except ops_mod.GitError:
        pass  # git 저장소가 아니면 기록도 앵커도 없다

    session_id = session_mod.new_id()
    prompt = prompts_mod.render(
        "loop_plan",
        {"loop_no": loop_no, "next_exp": exp_id, "context": ctx.context},
    )
    got = _claude(
        ctx, conn, prompt=prompt, session_id=session_id, resume=False, stage="plan"
    )
    # 🔑 **설계가 떨어졌을 때만 `planned`** 이다 (실측 2026-11-05).
    #
    # 전에는 세션이 무엇을 했든 `planned` 로 적었다. 승인 대기나 자기
    # 거절로 끝나면 폴더도 `run.json` 도 없는 번호가 `planned` 로 남아,
    # `_resuming_experiment` 가 그걸 집어 가고(→ B 가 바로 실패) 다음 설계
    # 세션은 *"planned 라는데 폴더가 없다"* 로 멈췄다.
    landed = design_landed(ctx.root, exp_id)
    X.upsert(
        conn, ctx.project, exp_id,
        state="planned" if landed else "stopped",
        branch=gitflow.branch_name(exp_id),
        report=None if landed else "설계 전에 멈췄어요 (run.json 이 없어요)",
    )

    # 훅이 막아 둔 요청이 있으면 거기서 멈춘다. 사람이 승인하면 **이어 간다.**
    waiting = waiting_approval(conn, ctx.project)
    if waiting:
        LP.set_state(conn, ctx.project, "waiting_approval")
        E.add(
            conn, ctx.project, "승인",
            f"{len(waiting)}건의 승인을 기다려요", tone="attention", ref=exp_id,
        )
        return {
            "ok": False,
            "stage": "plan",
            "experimentId": exp_id,
            "loopNo": loop_no,
            "sessionId": session_id,
            "waiting": waiting,
            "reason": f"승인을 기다려요 ({len(waiting)}건)",
            "result": got,
        }

    if not landed:
        # 세션은 끝났는데 명세가 없다. **다음 토막으로 넘기지 않는다** —
        # `run.json` 없이 B 를 부르면 `SpecError` 로 실패 기록만 남는다.
        E.add(
            conn, ctx.project, "설계",
            f"{exp_id} 는 설계 없이 끝났어요 (run.json 이 없어요)",
            tone="attention", ref=exp_id,
        )
        return {
            "ok": False,
            "stage": "plan",
            "experimentId": exp_id,
            "loopNo": loop_no,
            "sessionId": session_id,
            "reason": "설계가 없어요 (run.json 을 안 썼어요)",
            "result": got,
        }

    E.add(conn, ctx.project, "설계", f"{exp_id} 를 설계했어요", ref=exp_id)
    return {
        "ok": bool(got.get("ok")),
        "stage": "plan",
        "experimentId": exp_id,
        "loopNo": loop_no,
        "sessionId": session_id,
        "result": got,
    }


def train_step(ctx, conn, exp_id: str) -> dict:
    """B · 실행. **Claude 는 끼지 않는다.**"""
    config = guards.read_config(ctx.root)
    verdict = guards.check_train(ctx.root, cache_dir=ctx.cache_dir, config=config)
    if not verdict.ok:
        return {"ok": False, "stage": "train", "reason": verdict["reason"], "blocked": True}

    try:
        spec = spec_mod.load(ctx.project, ctx.root, exp_id)
    except spec_mod.SpecError as exc:
        X.set_state(conn, ctx.project, exp_id, "failed")
        E.add(conn, ctx.project, "실행", f"{exp_id} 의 run.json 을 믿을 수 없어요: {exc}", tone="bad", ref=exp_id)
        return {"ok": False, "stage": "train", "reason": str(exc), "blocked": True}

    job_id = J.add(conn, ctx.project, "train", experiment_id=exp_id, timeout_sec=spec.timeout_sec)
    J.lease(conn, ctx.project, kinds=("train",))
    LP.set_state(conn, ctx.project, "running", current_job_id=job_id)
    X.set_state(conn, ctx.project, exp_id, "running")

    launched = ctx.launcher(spec)
    J.start(conn, job_id, pid=launched.pid, pgid=launched.pgid, log_path=launched.log_path)
    loopstate.set_running(ctx.project, exp_id, pid=launched.pid, root=ctx.root)
    E.add(conn, ctx.project, "실행", f"{exp_id} 을 시작했어요", ref=exp_id)

    outcome = ctx.waiter(launched, spec)
    J.finish(
        conn,
        job_id,
        "done" if outcome.state == "done" else ("timeout" if outcome.state == "timeout" else "failed"),
        exit_code=outcome.exit_code,
        error=None if outcome.state == "done" else outcome.state,
    )
    X.upsert(conn, ctx.project, exp_id, gpu_sec=int(outcome.seconds))
    # 학습은 끝났지만 **아직 그 실험 안에 있다.** C 가 자기 폴더에 쓰고,
    # 그때까지 `Config.yaml`·`Evaluation.md` 는 잠겨 있어야 한다.
    loopstate.set_reviewing(ctx.project, exp_id, root=ctx.root)
    return {
        "ok": outcome.state == "done",
        "stage": "train",
        "experimentId": exp_id,
        "jobId": job_id,
        "outcome": outcome,
        "spec": spec,
    }


def fill_journal(ctx, conn, exp_id: str, session_id: str, order: dict, *, trained_ok: bool = True) -> dict:
    """빠진 기록을 **한 번** 더 부탁한다 (`fill_missing_journal`).

    🔑 이 프롬프트는 **정의만 돼 있고 아무도 안 불렀다** (실측 2026-11-05:
    EXP-008 이 `analysis.md` 하나 빠져서 멈췄다). 계획에는 "빠지면
    `--resume` 으로 `fill_missing_journal` **1회**" 라고 적혀 있었는데
    연결이 없었다 — 그러면 사람이 직접 파일을 쓰거나 루프를 포기해야 한다.

    **1회뿐이다.** 그래도 안 채우면 그대로 보고하고 사람을 부른다. 같은
    부탁을 반복하면 사용량만 쓴다.

    같은 세션을 `--resume` 으로 이어 간다 — 결과를 이미 본 세션이라 빠진
    자리를 다시 설명할 필요가 없다.
    """
    missing = list(order.get("missing") or [])
    if not missing:
        return order
    prompt = prompts_mod.render(
        "fill_missing_journal",
        {
            "exp_id": exp_id,
            "missing": "\n".join(f"- `{name}`" for name in missing),
            "context": ctx.context,
        },
    )
    _claude(
        ctx, conn, prompt=prompt, session_id=session_id, resume=True, stage="journal_fix"
    )
    after = update_order(ctx.root, exp_id, trained_ok=trained_ok)
    if after["ok"]:
        E.add(
            conn, ctx.project, "기록",
            f"{exp_id} 의 빠진 기록을 채웠어요: {', '.join(missing)}",
            ref=exp_id,
        )
    else:
        E.add(
            conn, ctx.project, "기록",
            f"{exp_id} 의 기록이 아직 비어 있어요: {', '.join(after['missing'])}"
            " (한 번 더 부탁했는데도요)",
            tone="attention", ref=exp_id,
        )
    return after


def update_order(root: str, exp_id: str, *, trained_ok: bool = True) -> dict:
    """PDF 9쪽 Update Order 가 실제로 갱신됐는가.

    **AI 가 "기록했어요" 라고 적어도 파일을 직접 본다.**

    🔑 **학습이 실패했으면 요구가 달라진다** (실측 2026-11-05).

    `result.csv` 는 학습이 쓰는 파일이다. 학습이 아무것도 못 내놨으면 AI 는
    그걸 만들 수 없고, **만들면 지어낸 값**이다 — 실측에서 AI 는 맞게
    거절했다(*"값을 지어내지 않음"*). 그런데 검수는 `result.csv` 가 없다고
    매번 어긋났다. 실패한 실험은 **영원히 검수를 못 지나간다.**

    그래서 실패했을 때는 `result.csv` 를 빼고 `Failures.md` 를 요구한다 —
    같은 실패를 두 번 하지 않는 게 실패 때의 기록 의무다 (spec III).
    """
    exp_dir = os.path.join(root, L.experiments_dir(), exp_id)
    wanted = {
        "analysis.md": os.path.join(exp_dir, "analysis.md"),
        L.LOOP_LAYOUT["experiment_log"]: os.path.join(root, L.LOOP_LAYOUT["experiment_log"]),
        L.LOOP_LAYOUT["decision_log"]: os.path.join(root, L.LOOP_LAYOUT["decision_log"]),
        L.LOOP_LAYOUT["state"]: os.path.join(root, L.LOOP_LAYOUT["state"]),
    }
    if trained_ok:
        wanted["result.csv"] = os.path.join(exp_dir, "result.csv")
    else:
        failures = L.LOOP_LAYOUT["failures"]
        wanted[failures] = os.path.join(root, failures)
    missing = []
    for name, path in wanted.items():
        try:
            if os.path.getsize(path) <= 0:
                missing.append(name)
        except OSError:
            missing.append(name)
    return {"ok": not missing, "missing": missing, "checked": sorted(wanted)}


def review_step(ctx, conn, exp_id: str, outcome) -> dict:
    """C · 분석. 끝나고 **AI 의 말과 숫자를 대조한다.**

    끝나면 **무슨 일이 있어도** 실행 표시를 내린다 — 안 내리면
    `Config.yaml`·`Evaluation.md` 가 계속 잠겨 사람도 못 고친다.
    """
    try:
        return _review(ctx, conn, exp_id, outcome)
    finally:
        try:
            loopstate.set_idle(ctx.project, root=ctx.root)
        except Exception:
            pass


def _review(ctx, conn, exp_id: str, outcome) -> dict:
    LP.set_state(conn, ctx.project, "reviewing")
    session_id = session_mod.new_id()
    prompt = prompts_mod.render(
        "loop_review",
        {
            "loop_no": LP.get(conn, ctx.project).get("loop_no") or 0,
            "exp_id": exp_id,
            "exit_state": getattr(outcome, "state", "unknown"),
            "exit_code": getattr(outcome, "exit_code", None),
            "elapsed": f"{getattr(outcome, 'seconds', 0):.0f}초",
            "context": ctx.context,
        },
    )
    got = _claude(
        ctx, conn, prompt=prompt, session_id=session_id, resume=False, stage="review"
    )

    report = report_mod.parse(str(got.get("text") or ""))
    said = report_mod.success_of(report)
    numbers = _numbers(ctx.root, exp_id)
    trained_ok = getattr(outcome, "state", "") == "done"
    order = update_order(ctx.root, exp_id, trained_ok=trained_ok)
    if not order["ok"]:
        order = fill_journal(ctx, conn, exp_id, session_id, order, trained_ok=trained_ok)

    disagree = said is not None and numbers["success"] is not None and said != numbers["success"]
    X.upsert(
        conn,
        ctx.project,
        exp_id,
        state="done" if trained_ok else "failed",
        report=str(report["fields"].get("result") or "")[:500],
        metric_name=numbers.get("metric"),
        metric_value=numbers.get("value"),
    )
    if numbers.get("value") is not None:
        X.record_result(
            conn,
            ctx.project,
            exp_id,
            metric_name=numbers.get("metric") or "loss",
            metric_value=numbers["value"],
        )
    # 커밋에 오염이 들어가지 않게 **커밋 전에** 한 번 더 본다.
    guard_project(ctx, conn, when="기록 커밋 전")
    # 커밋 전에 승인 기록이 진본과 같은지. 어긋난 사본을 커밋하지 않는다.
    audit_ok = guard_audit(ctx, conn, when="기록 커밋 전")
    # 커밋 전에 기록이 앵커와 맞는지. 어긋나면 **커밋하지 않는다.**
    if audit_ok and guard_anchor(ctx, conn, when="기록 커밋 전", with_fsck=False):
        try:
            gitflow.record_and_return(ctx.root, exp_id, running=False)
            anchor_mod.record_all(conn, ctx.project, ctx.root, note=f"{exp_id} 기록")
            # 앵커가 위조를 잡았을 때 **되살릴 정본**을 남긴다. `server/data`
            # 아래라 AI 가 쓴 코드가 지울 수도 고칠 수도 없다(M1b).
            saved = bundle_mod.create(ctx.root, ctx.project, note=f"{exp_id} 기록 커밋 뒤")
            if not saved["ok"]:
                E.add(conn, ctx.project, "기록", f"git 백업을 못 떴어요: {saved['reason'][:120]}", tone="attention")
        except ops_mod.GitRefused as exc:
            # `.git` 이 코드를 실행하게 만드는 설정을 가졌다. **커밋하지 않는다.**
            guard_git(ctx, conn, exc)
        except ops_mod.GitError:
            pass

    if disagree:
        LP.set_state(
            conn, ctx.project, "blocked",
            stop_reason=f"AI 의 성공 판정({said})과 result.csv 판정({numbers['success']})이 달라요",
        )
        E.add(conn, ctx.project, "검수", "AI 의 판정과 숫자가 어긋나요 — 사람 확인이 필요해요", tone="bad", ref=exp_id)
    return {
        "ok": bool(got.get("ok")) and not disagree and order["ok"],
        "stage": "review",
        "experimentId": exp_id,
        "report": report,
        "saidSuccess": said,
        "numbers": numbers,
        "updateOrder": order,
        "disagree": disagree,
        "result": got,
    }


def _numbers(root: str, exp_id: str) -> dict:
    """`result.csv` 에서 **직접** 읽은 값. AI 의 말과 대조할 근거다.

    지표 이름·임계값·비교 방향은 **`Config.yaml` 의 `goal` 에서 읽는다.**
    전에는 이름이 `"loss"` 로 박혀 있고 비교가 `<=` 로 박혀 있었다 —
    `goal.metric: accuracy` 라고 적어도 `loss` 를 읽었고, 클수록 좋은 지표의
    성공 판정이 **뒤집혀** 있었다. 둘 다 조용했다 (2026-11-05).
    """
    path = os.path.join(root, L.experiments_dir(), exp_id, "result.csv")
    got = metrics_mod.read_result(path)
    rows = got["rows"]
    goal = _goal(root)
    name = goal["metric"]
    series = (
        metrics_mod.series_of(rows, name, "val")
        or metrics_mod.series_of(rows, name)
    )
    value = next((r["value"] for r in reversed(series) if r["value"] is not None), None)
    threshold = goal["threshold"]
    success = None
    if value is not None and threshold is not None and goal["direction"]:
        success = (
            value <= threshold if goal["direction"] == "lower" else value >= threshold
        )
    return {
        "metric": name if series else None,
        "value": value,
        "threshold": threshold,
        "direction": goal["direction"],
        "goalMetric": name,
        "success": success,
        "format": got["format"],
        "warnings": got["warnings"],
        "notes": goal["notes"],
    }


#: 기본 지표 이름. `goal.metric` 이 비었거나 자리표시일 때.
DEFAULT_METRIC = "loss"

#: 비교 방향. `lower` = 작을수록 좋다 (loss), `higher` = 클수록 좋다 (accuracy).
DIRECTIONS = {
    "lower": ("lower", "min", "minimize", "작을수록", "낮을수록", "down"),
    "higher": ("higher", "max", "maximize", "클수록", "높을수록", "up"),
}


def _direction(raw: str) -> tuple[str, str]:
    """(`lower`|`higher`|`""`, 사유). 모르는 값은 **추측하지 않는다.**

    틀린 방향으로 비교하면 실패를 성공으로 읽는다 — 그건 아무 판정도 안 하는
    것보다 나쁘다. 그래서 모르면 비교를 **접고** 사유를 남긴다.
    """
    text = str(raw or "").strip().lower()
    if not text or text.startswith("["):
        return "lower", ""  # 안 적으면 작을수록 좋은 것으로 본다 (loss 가 기본)
    for key, words in DIRECTIONS.items():
        if text in words:
            return key, ""
    return "", (
        f"goal.direction 을 못 읽었어요: {raw!r} · "
        f"쓸 수 있는 값: lower (작을수록 좋음) · higher (클수록 좋음) — "
        "성공 판정을 접었어요"
    )


def _goal(root: str) -> dict:
    """`Config.yaml` 의 `goal` 절. 자리표시는 **없는 것**으로 본다.

    **`docs/Evaluation.md` 는 읽기만 한다** — 실행 중에는 잠겨 있다.
    """
    goal = guards.read_config(root).get("goal")
    goal = goal if isinstance(goal, dict) else {}
    notes = []

    name = str(goal.get("metric") or "").strip()
    if not name or name.startswith("["):
        name = DEFAULT_METRIC
        notes.append(
            f"goal.metric 이 비어 있어서 {DEFAULT_METRIC!r} 로 봤어요"
        )

    text = str(goal.get("threshold") or "").strip()
    threshold = None
    if text and not text.startswith("["):
        try:
            threshold = float(text)
        except ValueError:
            notes.append(f"goal.threshold 가 숫자가 아니에요: {text!r}")
    else:
        notes.append("goal.threshold 가 비어 있어서 성공 판정을 못 해요")

    direction, why = _direction(goal.get("direction"))
    if why:
        notes.append(why)

    return {
        "metric": name,
        "threshold": threshold,
        "direction": direction,
        "notes": notes,
    }


def _threshold(root: str):
    """`Config.yaml` 의 `goal.threshold`. 자리표시면 `None`. (옛 이름)"""
    return _goal(root)["threshold"]
