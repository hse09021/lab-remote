"""루프를 **시작해도 되는가**. 산술로 판정한다.

spec III-4: *"루프 반복과 종료 조건 판정은 **시스템**이 담당"*. AI 가
"계속해도 될 것 같아요" 라고 적어도 여기서 막으면 막힌다.

| 언제 | 보는 것 |
|---|---|
| 루프 시작 전 | `Config.yaml` 의 `max_runs`·`gpu_hours`·`deadline` vs 누적치 |
| 학습 시작 전 | GPU 드라이버 불일치 · 디스크 여유 · 샌드박스 |
| 어느 때나 | 사람이 멈춤(`loop_state.paused`) |

**막는 이유를 사람 말로** 돌려준다 — Discord 에 그대로 실린다.
"""

from __future__ import annotations

import os
from datetime import datetime

from .. import approval_log as A
from .. import audit
from ..agent import version as version_mod
from .. import loop_layout as L
from ..monitor import gpu as gpu_mod
from ..monitor import host as host_mod
from ..monitor import metrics as metrics_mod
from ..store import experiments as X
from ..store import loops as LP

__all__ = ["Verdict", "limits_of", "check_loop", "check_train", "read_config"]

#: 종료 조건 이름 -> 사람이 읽는 말
LIMIT_NAMES = {
    "max_runs": "최대 실행 횟수",
    "gpu_hours": "GPU 시간",
    "deadline": "마감",
}


class Verdict(dict):
    """`{"ok": bool, "reason": str, "stop": bool}`.

    `stop` 은 "종료 조건에 닿았다" 다 — 기다린다고 풀리지 않는다.
    `ok=False, stop=False` 는 "지금은 안 되지만 나중엔 될 수도" 다.
    """

    @property
    def ok(self) -> bool:
        return bool(self.get("ok"))


def _ok() -> Verdict:
    return Verdict(ok=True, reason="", stop=False)


def _no(reason: str, *, stop: bool = False) -> Verdict:
    return Verdict(ok=False, reason=reason, stop=stop)


def read_config(root: str) -> dict:
    """`specifications/Config.yaml`. 못 읽으면 빈 dict (던지지 않는다)."""
    import yaml

    try:
        with open(os.path.join(root, L.LOOP_LAYOUT["config"]), encoding="utf-8") as fh:
            data = yaml.safe_load(fh)
    except (OSError, Exception) as exc:  # noqa: B014
        if isinstance(exc, (OSError,)) or exc.__class__.__name__.endswith("Error"):
            return {}
        raise
    return data if isinstance(data, dict) else {}


def _number(value):
    """`[최대 실행 횟수]` 같은 자리표시는 **없는 것**으로 본다."""
    if value is None:
        return None
    text = str(value).strip()
    if not text or text.startswith("["):
        return None
    try:
        return float(text)
    except ValueError:
        return None


def limits_of(config: dict) -> dict:
    """`Config.yaml` 의 종료 조건. 자리표시는 빠진다."""
    section = config.get("limits")
    section = section if isinstance(section, dict) else {}
    out = {}
    for key in ("max_runs", "gpu_hours"):
        value = _number(section.get(key))
        if value is not None:
            out[key] = value
    deadline = str(section.get("deadline") or "").strip()
    if deadline and not deadline.startswith("["):
        out["deadline"] = deadline
    return out


def _past_deadline(deadline: str, now: datetime) -> bool:
    for shape in ("%Y-%m-%d %H:%M", "%Y-%m-%d", "%Y/%m/%d"):
        try:
            when = datetime.strptime(deadline, shape)
            return now.replace(tzinfo=None) > when
        except ValueError:
            continue
    try:
        return now > datetime.fromisoformat(deadline)
    except ValueError:
        return False  # 못 읽는 마감은 **없는 것**으로 본다 (틀리게 멈추지 않게)


def check_loop(conn, project: str, root: str, *, now: datetime | None = None) -> Verdict:
    """루프를 한 번 더 돌려도 되나."""
    now = now or datetime.now().astimezone()
    loop = LP.ensure(conn, project)
    if loop.get("paused"):
        return _no(f"사람이 멈춰 뒀어요: {loop.get('paused_reason') or '사유 없음'}")
    if loop.get("state") in ("stopped", "done"):
        return _no(f"이미 멈춘 루프예요: {loop.get('stop_reason') or loop.get('state')}", stop=True)

    # 📌 Claude Code 판이 바뀌었으면 **루프를 시작하지 않는다.**
    #
    # 2.1.317 → 2.1.318 에서 서브에이전트 도구 이름이 Task → Agent 가 됐고
    # `--disallowedTools Task` 가 무효가 되어 서브에이전트가 열린 채로 돌았다.
    # 그 틈은 **조용하다** — 루프는 사람이 안 보는 동안 몇 시간씩 돈다.
    # 멈추는 비용은 명령 하나다: `labremote tools --probe`.
    seen = version_mod.check()
    if not seen["ok"]:
        return _no(seen["reason"])

    # 📒 승인 기록이 진본과 같은가. 다르면 **루프를 시작하지 않는다.**
    #
    # 프로젝트의 `logs/Approval_log.csv` 는 AI 가 쓴 코드가 고칠 수 있다(M4).
    # 진본은 `server/data/audit/` 에 있고 AI 는 거기에 못 쓴다(M1b).
    # 되살릴 수 있으므로(`labremote audit <프로젝트> --rebuild`) `stop` 은 아니다.
    seen = audit.compare(project, A.log_path(root, _policy_of(project)))
    if not seen["ok"]:
        return _no(audit.describe(seen).splitlines()[0] + " · labremote audit 로 보세요")

    limits = limits_of(read_config(root))
    done = [e for e in X.listing(conn, project) if e.get("state") in ("done", "failed", "stopped")]

    if "max_runs" in limits and len(done) >= limits["max_runs"]:
        return _no(
            f"{LIMIT_NAMES['max_runs']}에 닿았어요: {len(done)}/{int(limits['max_runs'])}회",
            stop=True,
        )
    if "gpu_hours" in limits:
        used = sum(int(e.get("gpu_sec") or 0) for e in X.listing(conn, project)) / 3600.0
        if used >= limits["gpu_hours"]:
            return _no(
                f"{LIMIT_NAMES['gpu_hours']}을 다 썼어요: {used:.1f}/{limits['gpu_hours']}시간",
                stop=True,
            )
    if "deadline" in limits and _past_deadline(limits["deadline"], now):
        return _no(f"{LIMIT_NAMES['deadline']}이 지났어요: {limits['deadline']}", stop=True)
    return _ok()


def check_train(root: str, *, cache_dir: str = "", config: dict | None = None) -> Verdict:
    """학습을 띄워도 되나. **기다리면 풀릴 수 있는 것들**이다.

    드라이버가 불일치면 어차피 실패할 학습이다 — GPU 시간과 사용량을 버리지
    않게 **시작하지 않는다.**
    """
    driver = gpu_mod.driver_state()
    if not driver["ok"]:
        return _no("GPU 드라이버 문제로 학습을 시작하지 않아요: " + (driver["reason"] or "불일치"))

    cfg = (config or {}).get("monitor") or {}
    threshold = float(cfg.get("diskFreeGb") or metrics_mod.DEFAULTS["diskFreeGb"])
    disk = host_mod.disk(cache_dir or root)
    if disk.get("ok") and disk["freeGb"] < threshold:
        return _no(f"디스크 여유가 {disk['freeGb']}GB 뿐이에요 (임계 {threshold}GB)")
    return _ok()


def _policy_of(project: str):
    """`log_path` 가 정책의 `logPath` 를 본다. 못 읽으면 기본값으로."""
    from .. import policy as policy_mod

    try:
        return policy_mod.load(project)
    except Exception:
        return None
