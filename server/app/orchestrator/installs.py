"""📦 설치 요청 흐름 — 요청 읽기 → 승인 → 설치 → 결과 알려 주기.

```
Claude 가 state/Install_request.json 을 쓴다 (이름·버전만)
  → 세션이 끝나면 오케스트레이터가 읽고 pkgspec 으로 검증
  → approvals 에 1건 (action_key='install') + Discord
  → labremote installs approve <id> [--allow-source]
  → 오케스트레이터가 **샌드박스 밖에서** conda run … pip install --no-cache-dir
  → 결과를 lab.db(진본) 와 state/Install_result.json(AI 가 읽는 쪽) 에
  → 다음 프롬프트가 결과를 싣고 이어 간다
```

## 진본은 `lab.db` 다

`state/Install_result.json` 은 프로젝트 안이라 AI 가 쓴 코드가 고칠 수
있다(M4). 그건 **AI 에게 알려 주는 쪽**이고, 승인·설치 기록의 진본은
`approvals` 표다. `server/data/` 아래라 샌드박스 안에서 쓰기가 실패한다(M1b).

## 사람이 승인한 것과 설치되는 것이 같아야 한다

승인할 때 지문(`pkgspec.fingerprint`)을 적어 두고, 설치 직전에 요청 파일을
**다시 읽어 지문을 대조**한다. 그 사이에 AI 가 요청 파일을 바꿔 치면
지문이 달라져 설치하지 않는다 — 사람이 본 목록과 다른 것을 깔지 않는다.
"""

from __future__ import annotations

import json
import os

from .. import loop_layout as L
from .. import notifier, paths, registry
from ..runner import pkginstall, pkgspec
from ..store import approvals as AP
from ..store import events as E

__all__ = [
    "ACTION",
    "request_path",
    "result_path",
    "read_request",
    "sync",
    "pending",
    "approve",
    "deny",
    "write_result",
]

#: `approvals.action_key`. 훅이 만드는 `pkg` 요청과 구분한다 — 이쪽은
#: 오케스트레이터가 요청 파일을 읽어 만든 것이다.
ACTION = "install"


def request_path(root: str) -> str:
    return os.path.join(paths.real(root), L.LOOP_LAYOUT["install_request"])


def result_path(root: str) -> str:
    return os.path.join(paths.real(root), L.LOOP_LAYOUT["install_result"])


def read_request(root: str) -> dict:
    """요청 파일을 읽고 검증한다. `{"ok", "parsed"|"reason"}`. 던지지 않는다."""
    path = request_path(root)
    if not os.path.exists(path):
        return {"ok": False, "reason": "", "found": False}
    try:
        with open(path, encoding="utf-8") as fh:
            data = json.load(fh)
    except (json.JSONDecodeError, UnicodeDecodeError) as exc:
        return {"ok": False, "found": True, "reason": f"JSON 이 깨졌어요: {exc}"}
    except OSError as exc:
        return {"ok": False, "found": True, "reason": f"읽을 수 없어요: {exc}"}
    try:
        parsed = pkgspec.parse(data)
    except pkgspec.SpecError as exc:
        return {"ok": False, "found": True, "reason": str(exc)}
    return {
        "ok": True,
        "found": True,
        "parsed": parsed,
        "fingerprint": pkgspec.fingerprint(parsed),
        "summary": pkgspec.summary(parsed),
    }


def _request_id(fingerprint: str) -> str:
    return f"install:{fingerprint.split(':', 1)[-1][:16]}"


def sync(conn, project: str, root: str, *, job_id: int | None = None) -> dict:
    """세션이 끝난 뒤 요청 파일을 보고 승인 대기를 연다.

    같은 지문이 이미 열려 있으면 **새로 열지 않는다**(횟수만 올린다) —
    루프가 돌 때마다 같은 요청으로 알림이 쏟아지면 안 된다.
    """
    got = read_request(root)
    if not got["found"]:
        return {"ok": True, "opened": None, "reason": ""}
    if not got["ok"]:
        E.add(conn, project, "설치", f"설치 요청을 못 읽었어요: {got['reason'][:120]}", tone="bad")
        _write(root, {
            "ok": False, "state": "rejected", "reason": got["reason"],
            "hint": "이름과 버전만 적어 주세요. URL·경로·옵션은 받지 않아요.",
        })
        return {"ok": False, "opened": None, "reason": got["reason"]}

    request_id = _request_id(got["fingerprint"])
    existing = AP.by_request(conn, project, request_id)
    if existing and existing["state"] == "open":
        AP.bump(conn, project, request_id)
        return {"ok": True, "opened": existing["id"], "reason": "이미 열려 있어요"}
    if existing and existing["state"] in ("approved", "denied"):
        # 이미 결정된 요청이다. 결과 파일이 그대로 남아 있으면 AI 가 다시
        # 쓴 것이니 횟수만 올린다 (반복은 `attempts` 상한이 잡는다).
        AP.bump(conn, project, request_id)
        return {"ok": True, "opened": existing["id"], "reason": f"이미 {existing['state']} 예요"}

    row = AP.open_request(
        conn,
        project=project,
        request_id=request_id,
        job_id=job_id,
        tool="Install",
        action_key=ACTION,
        rel=L.LOOP_LAYOUT["install_request"],
        request=got["summary"],
        reason=got["parsed"]["reason"],
        fingerprint=got["fingerprint"],
    )
    E.add(conn, project, "설치", f"설치 승인이 필요해요 · {got['summary']}", tone="attention")
    try:
        notifier.send(
            conn,
            "approval",
            project=project,
            subject=notifier.subject_of("install", got["fingerprint"]),
            title=f"패키지 설치 승인이 필요해요 · {project}",
            body=got["parsed"]["reason"] or "(사유가 비어 있어요)",
            fields=[
                ("패키지", "\n".join(pkgspec.requirements(got["parsed"]))),
                ("소스 배포", "요청했어요" if got["parsed"]["allowSource"] else "아니요 (휠만)"),
                ("승인", f"labremote installs approve {project} {row['id']}"),
                ("거절", f"labremote installs deny {project} {row['id']}"),
            ],
        )
    except Exception:
        pass
    _write(root, {
        "ok": False, "state": "waiting",
        "reason": "사람의 승인을 기다리고 있어요. 다른 방법으로 돌아가지 말고 기다려 주세요.",
        "packages": pkgspec.requirements(got["parsed"]),
    })
    return {"ok": True, "opened": row["id"], "reason": ""}


def pending(conn, project: str | None = None) -> list[dict]:
    """열려 있는 설치 승인만."""
    return [a for a in AP.pending(conn, project) if a.get("action_key") == ACTION]


def approve(
    conn,
    project: str,
    approval_id: int,
    *,
    allow_source: bool = False,
    by: str = "cli",
    note: str = "",
    runner=None,
) -> dict:
    """승인하고 **바로 설치한다.** 결과를 돌려준다. 던지지 않는다."""
    row = AP.get(conn, approval_id)
    if not row or row["project"] != project:
        return {"ok": False, "reason": f"그런 승인 건이 없어요: {approval_id}"}
    if row.get("action_key") != ACTION:
        return {"ok": False, "reason": "설치 요청이 아니에요"}
    if row["state"] != "open":
        return {"ok": False, "reason": f"이미 {row['state']} 예요"}

    root = registry.root_of(project)
    if not root:
        return {"ok": False, "reason": f"등록된 프로젝트가 아니에요: {project}"}

    # 🔑 승인한 내용과 설치할 내용이 같은지. 그 사이에 AI 가 요청 파일을
    # 바꿔 치면 지문이 달라진다 — 사람이 본 것과 다른 걸 깔지 않는다.
    got = read_request(root)
    if not got.get("ok"):
        return {"ok": False, "reason": f"요청 파일을 다시 읽을 수 없어요: {got.get('reason')}"}
    if got["fingerprint"] != row["fingerprint"]:
        AP.decide(conn, project, row["request_id"], "denied", by=by)
        E.add(conn, project, "설치", "승인 뒤 요청 파일이 바뀌어 있었어요 — 설치하지 않았어요", tone="bad")
        return {
            "ok": False,
            "reason": (
                "승인한 내용과 요청 파일이 달라요 — 그 사이에 바뀌었어요. "
                "설치하지 않았어요. 새 요청으로 다시 승인해 주세요."
            ),
        }
    parsed = got["parsed"]
    if allow_source and not parsed["allowSource"]:
        return {
            "ok": False,
            "reason": "요청에 allowSource 가 없어요 — --allow-source 는 요청에도 있어야 해요",
        }

    env_name = _conda_env(root)
    if not env_name:
        return {
            "ok": False,
            "reason": "specifications/Config.yaml 의 env.conda 를 읽을 수 없어요",
        }

    AP.decide(conn, project, row["request_id"], "approved", by=by)
    if note:
        E.add(conn, project, "설치", f"승인 메모: {note}")
    result = pkginstall.install(
        parsed, env_name, allow_source=allow_source, cwd=root, runner=runner
    )
    write_result(conn, project, root, approval_id, parsed, result)
    return {"ok": bool(result["ok"]), "result": result, "env": env_name}


def deny(conn, project: str, approval_id: int, *, reason: str = "", by: str = "cli") -> dict:
    row = AP.get(conn, approval_id)
    if not row or row["project"] != project or row.get("action_key") != ACTION:
        return {"ok": False, "reason": f"그런 설치 승인 건이 없어요: {approval_id}"}
    if row["state"] != "open":
        return {"ok": False, "reason": f"이미 {row['state']} 예요"}
    AP.decide(conn, project, row["request_id"], "denied", by=by)
    root = registry.root_of(project) or ""
    if root:
        _write(root, {
            "ok": False, "state": "denied",
            "reason": reason or "사람이 거절했어요.",
            "hint": "다른 방법을 찾아 주세요. 같은 요청을 다시 쓰지 말아 주세요.",
        })
    E.add(conn, project, "설치", f"설치를 거절했어요: {reason or '사유 없음'}", tone="attention")
    return {"ok": True, "reason": ""}


def write_result(conn, project: str, root: str, approval_id: int, parsed: dict, result: dict) -> None:
    """결과를 `lab.db`(진본) 와 프로젝트 안 파일(AI 가 읽는 쪽) 양쪽에."""
    row = AP.get(conn, approval_id) or {}
    if row:
        AP.decide(
            conn, project, row["request_id"],
            "consumed" if result["ok"] else "blocked",
            by="orchestrator",
        )
    E.add(
        conn, project, "설치",
        ("설치했어요: " if result["ok"] else "설치가 실패했어요: ")
        + ", ".join(pkgspec.requirements(parsed)),
        tone="good" if result["ok"] else "bad",
    )
    _write(root, {
        "ok": bool(result["ok"]),
        "state": "installed" if result["ok"] else "failed",
        "packages": pkgspec.requirements(parsed),
        "exitCode": result["exitCode"],
        "reason": result["reason"][:2000],
        "hint": (
            "설치됐어요. 요청 파일은 지워도 돼요."
            if result["ok"]
            else "실패했어요. 다른 방법을 찾아 주세요 — 같은 요청을 다시 쓰지 말아 주세요."
        ),
    })


def _write(root: str, payload: dict) -> None:
    """결과 파일. **진본이 아니다** — AI 가 읽는 쪽이다."""
    try:
        registry.write_json(result_path(root), payload)
    except OSError:
        pass


def _conda_env(root: str) -> str:
    """`specifications/Config.yaml` 의 `env.conda`.

    **요청이 아니라 Config.yaml 에서 읽는다** — 그 파일은 실험이 도는 중에
    잠겨 있고(`stop` 잠금), AI 가 환경 이름을 정하게 두면 다른 환경에 깔 수 있다.
    """
    import yaml

    path = os.path.join(paths.real(root), L.LOOP_LAYOUT["config"])
    try:
        with open(path, encoding="utf-8") as fh:
            data = yaml.safe_load(fh) or {}
    except (OSError, yaml.YAMLError):
        return ""
    env = data.get("env") if isinstance(data, dict) else None
    if not isinstance(env, dict):
        return ""
    return str(env.get("conda") or "").strip()
