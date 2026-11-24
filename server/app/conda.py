"""Conda 화면 — 환경 · 패키지 보기, 미리 보기(dry-run) → 확인 → 설치, 보호와 잠금.

PLAN 4.1 conda:
- `conda env list --json`, `conda list --json -n <환경>`으로 읽는다.
- 설치 · 업데이트 · 제거는 **먼저 바뀌는 것(dry-run)을 보여 주고** 사람이 확인한 뒤에만.
- `base` · `labremote`는 보호(`runner/condaenv.py`), 실행 중인 학습이 쓰는 환경은 잠금.
- 삭제는 이름을 입력해야 하고, 지우기 전에 `environment.yml`을 데이터 폴더에 남긴다.
- `.condarc`는 건드리지 않는다. 채널 옵션(`-c`)도 받지 않는다 — 사용자의 설정 그대로.
- 패키지 이름 · 버전은 `runner/pkgspec.py`가 검증한 것만 명령에 들어간다(셸 없이).

오래 걸리는 일은 백그라운드 작업으로 돌리고 화면이 상태를 읽어 간다.
"""

from __future__ import annotations

import json
import os
import subprocess
import threading
import time
import uuid

from . import paths, registry, runs
from .runner import condaenv, pkginstall, pkgspec

__all__ = ["CondaError", "list_envs", "env_detail", "start_job", "job", "export_yml", "TOOLS", "ACTIONS"]

TOOLS = ("conda", "pip")
ACTIONS = ("install", "update", "remove")
TIMEOUT_SEC = 30 * 60
_cache: dict[str, tuple[float, object]] = {}
_jobs: dict[str, dict] = {}
_lock = threading.Lock()


class CondaError(ValueError):
    """사람에게 그대로 보여 줄 수 있는 거절 사유."""


def _conda() -> str:
    exe = runs.conda_bin()
    if not exe:
        raise CondaError("conda를 찾지 못했어요 (CONDA_EXE · ~/miniconda3 등).")
    return exe


def _env() -> dict[str, str]:
    env = pkginstall.build_env()
    env.setdefault("PATH", os.environ.get("PATH", "/usr/bin:/bin"))
    return env


def _run(argv: list[str], timeout: int = 120) -> subprocess.CompletedProcess:
    return subprocess.run(argv, capture_output=True, text=True, timeout=timeout, env=_env())


def _json(argv: list[str], timeout: int = 120):
    done = _run(argv, timeout)
    try:
        return json.loads(done.stdout or "null")
    except json.JSONDecodeError:
        raise CondaError("conda 결과를 읽지 못했어요: " + (done.stderr or done.stdout).strip()[-300:]) from None


def _cached(key: str, ttl: float, fn):
    now = time.time()
    hit = _cache.get(key)
    if hit and now - hit[0] < ttl:
        return hit[1]
    value = fn()
    _cache[key] = (now, value)
    return value


def _forget(name: str = "") -> None:
    for key in list(_cache):
        if key == "envs" or (name and key == f"pkgs:{name}"):
            _cache.pop(key, None)


# --- 읽기 ---------------------------------------------------------------------


def _busy_envs() -> dict[str, list[str]]:
    """실행 중인 학습이 쓰는 환경 → 실행 이름들."""
    out: dict[str, list[str]] = {}
    for _root, name in registry.load().items():
        try:
            items = runs.list_runs(name)
        except Exception:
            continue
        for r in items:
            if r["state"] == "running" and r.get("env"):
                out.setdefault(r["env"], []).append(f"{name} · {r['id']}")
    return out


def _protection(name: str) -> str:
    got = condaenv.check(name)
    return "" if got["ok"] else got["reason"]


def list_envs() -> list[dict]:
    data = _cached("envs", 10, lambda: _json([_conda(), "env", "list", "--json"]))
    details = (data or {}).get("envs_details") or {}
    busy = _busy_envs()
    out = []
    for prefix in (data or {}).get("envs") or []:
        name = (details.get(prefix) or {}).get("name") or os.path.basename(prefix)
        if not name:
            continue
        protected = _protection(name)
        out.append({
            "name": name,
            "prefix": prefix,
            "protected": bool(protected),
            "protectedReason": protected,
            "usedBy": busy.get(name, []),
        })
    out.sort(key=lambda e: (not e["protected"], e["name"]))
    return out


def env_detail(name: str) -> dict:
    env = next((e for e in list_envs() if e["name"] == name), None)
    if env is None:
        raise CondaError(f"없는 환경이에요: {name}")
    pkgs = _cached(f"pkgs:{name}", 30, lambda: _json([_conda(), "list", "-n", name, "--json"]))
    items = [
        {
            "name": p.get("name"),
            "version": p.get("version"),
            "source": "pip" if p.get("channel") == "pypi" else "conda",
            "channel": p.get("channel"),
            "build": p.get("build_string"),
        }
        for p in pkgs or []
        if isinstance(p, dict)
    ]
    python = next((p["version"] for p in items if p["name"] == "python"), "")
    return {**env, "python": python, "packages": items, "lock": _lock_reason(name)}


def _lock_reason(name: str) -> str:
    """바꿀 수 없는 이유. 바꿀 수 있으면 빈 문자열."""
    protected = _protection(name)
    if protected:
        return protected
    busy = _busy_envs().get(name)
    if busy:
        return f"실행 중인 학습이 사용 중이라 잠겨 있어요 ({', '.join(busy[:3])}). 학습이 끝나면 변경할 수 있어요."
    return ""


def export_yml(name: str) -> str:
    if not condaenv.NAME_RE.match(name or ""):
        raise CondaError("환경 이름이 올바르지 않아요.")
    done = _run([_conda(), "env", "export", "-n", name, "--no-builds"], timeout=180)
    if done.returncode != 0:
        raise CondaError("environment.yml을 만들지 못했어요: " + done.stderr.strip()[-300:])
    return done.stdout


# --- 작업 (미리 보기 · 설치 · 만들기 · 삭제) ---------------------------------------


def _history(entry: dict) -> None:
    folder = os.path.join(registry.data_dir(), "conda")
    os.makedirs(folder, exist_ok=True)
    with open(os.path.join(folder, "history.jsonl"), "a", encoding="utf-8") as fh:
        fh.write(json.dumps({"at": time.time(), **entry}, ensure_ascii=False) + "\n")


def _specs(packages) -> tuple[list[str], list[str]]:
    """`(명령에 넣을 요구 문자열, 이름만)`. 하나라도 규칙에 안 맞으면 전체 거부."""
    try:
        parsed = pkgspec.parse({"version": 1, "packages": packages})
    except pkgspec.SpecError as exc:
        raise CondaError(str(exc)) from None
    items = pkgspec.requirements(parsed)
    if not items:
        raise CondaError("패키지를 선택해 주세요.")
    return items, [p["name"] for p in parsed["packages"]]


def _argv(kind: str, env: str, *, tool: str = "", action: str = "", specs: list[str] = (), names: list[str] = (), dry: bool = False, extra: dict | None = None) -> list[str]:
    conda = _conda()
    extra = extra or {}
    if kind == "change" and tool == "conda":
        verb = {"install": "install", "update": "update", "remove": "remove"}[action]
        argv = [conda, verb, "-n", env, "--json", "-y"]
        # 제거 · 업데이트는 이름만 (버전 지정은 설치 때만)
        return argv + (["--dry-run"] if dry else []) + list(specs if action == "install" else names)
    if kind == "change" and tool == "pip":
        pip = [conda, "run", "-n", env, "--no-capture-output", "python", "-m", "pip"]
        common = ["--no-input", "--disable-pip-version-check"]
        if action == "remove":
            return pip + ["uninstall", "-y", *common, *names]
        argv = pip + ["install", *common, "--no-cache-dir", "--only-binary=:all:"]
        if action == "update":
            argv.append("--upgrade")
        if dry:
            argv += ["--dry-run", "--quiet", "--report", "-"]
        return argv + list(specs)
    if kind == "create":
        argv = [conda, "create", "-n", env, "-y", "--json"]
        if extra.get("clone"):
            return argv + ["--clone", extra["clone"]]
        return argv + [f"python={extra.get('python') or '3.11'}"]
    if kind == "delete":
        return [conda, "env", "remove", "-n", env, "-y"]
    raise CondaError("알 수 없는 작업이에요.")


def _changes_from(tool: str, action: str, names: list[str], out: str, env: str) -> list[dict]:
    """dry-run 결과 → `[{name, from, to, action}]`."""
    try:
        data = json.loads(out or "null")
    except json.JSONDecodeError:
        data = None
    changes: list[dict] = []
    if tool == "conda" and isinstance(data, dict):
        acts = data.get("actions") or {}
        old = {x.get("name"): x.get("version") for x in acts.get("UNLINK") or []}
        new = {x.get("name"): x.get("version") for x in acts.get("LINK") or []}
        for n in sorted(set(old) | set(new)):
            kind = "추가" if n not in old else "제거" if n not in new else "변경"
            changes.append({"name": n, "from": old.get(n) or "", "to": new.get(n) or "", "action": kind})
        if not changes and data.get("message"):
            changes.append({"name": "", "from": "", "to": "", "action": str(data["message"])})
    elif tool == "pip" and action != "remove" and isinstance(data, dict):
        installed = {p["name"].lower(): p["version"] for p in env_detail(env)["packages"] if p.get("name")}
        for item in data.get("install") or []:
            meta = item.get("metadata") or {}
            n = str(meta.get("name") or "")
            prev = installed.get(n.lower(), "")
            changes.append({"name": n, "from": prev, "to": str(meta.get("version") or ""), "action": "변경" if prev else "추가"})
    elif tool == "pip" and action == "remove":
        installed = {p["name"].lower(): p["version"] for p in env_detail(env)["packages"] if p.get("name")}
        for n in names:
            changes.append({"name": n, "from": installed.get(n.lower(), "?"), "to": "", "action": "제거"})
    return changes


def start_job(kind: str, env: str, *, tool: str = "", action: str = "", packages=None, dry: bool = False,
              confirm: str = "", python: str = "", clone: str = "") -> dict:
    """작업을 백그라운드로 시작하고 바로 돌아온다. 화면은 `job(id)`로 읽는다."""
    if not condaenv.NAME_RE.match(env or ""):
        raise CondaError(f"환경 이름이 규칙에 맞지 않아요: {env!r}")
    specs: list[str] = []
    names: list[str] = []
    if kind == "change":
        if tool not in TOOLS or action not in ACTIONS:
            raise CondaError("도구는 conda나 pip, 작업은 설치 · 업데이트 · 제거 중에서 선택해 주세요.")
        specs, names = _specs(packages or [])
        if not dry:
            reason = _lock_reason(env)
            if reason:
                raise CondaError(reason)
    elif kind == "create":
        if any(e["name"] == env for e in list_envs()):
            raise CondaError(f"이미 있는 환경이에요: {env}")
        check = condaenv.check(env)
        if not check["ok"]:
            raise CondaError(check["reason"])
        if clone and not any(e["name"] == clone for e in list_envs()):
            raise CondaError(f"복제할 환경이 없어요: {clone}")
        if python and not python.replace(".", "").isdigit():
            raise CondaError("파이썬 버전은 3.11처럼 숫자로 입력해 주세요.")
    elif kind == "delete":
        if confirm != env:
            raise CondaError("삭제하려면 환경 이름을 똑같이 입력해 주세요.")
        reason = _lock_reason(env)
        if reason:
            raise CondaError(reason)
        if not any(e["name"] == env for e in list_envs()):
            raise CondaError(f"없는 환경이에요: {env}")
    else:
        raise CondaError("알 수 없는 작업이에요.")

    with _lock:
        if any(j["env"] == env and j["state"] == "running" for j in _jobs.values()):
            raise CondaError("이 환경에서 다른 작업이 아직 진행 중이에요.")
        jid = uuid.uuid4().hex[:10]
        record = {
            "id": jid, "kind": kind, "env": env, "tool": tool, "action": action, "dry": dry,
            "specs": specs, "names": names, "state": "running", "startedAt": time.time(), "log": "", "changes": None,
            "error": "", "backup": "",
        }
        _jobs[jid] = record
    argv = _argv(kind, env, tool=tool, action=action, specs=specs, names=names, dry=dry, extra={"python": python, "clone": clone})
    threading.Thread(target=_work, args=(record, argv), name=f"conda-{jid}", daemon=True).start()
    return dict(record)


def _work(record: dict, argv: list[str]) -> None:
    final = "failed"
    try:
        if record["kind"] == "delete":
            # 지우기 전에 environment.yml을 남긴다
            yml = export_yml(record["env"])
            folder = os.path.join(registry.data_dir(), "conda", "backups")
            os.makedirs(folder, exist_ok=True)
            path = os.path.join(folder, f"{record['env']}-{time.strftime('%Y%m%d-%H%M%S')}.yml")
            with open(path, "w", encoding="utf-8") as fh:
                fh.write(yml)
            record["backup"] = path
        done = _run(argv, timeout=TIMEOUT_SEC)
        record["log"] = ((done.stdout or "") + ("\n" + done.stderr if done.stderr else ""))[-20000:]
        if record["dry"]:
            record["changes"] = _changes_from(record["tool"], record["action"], record["names"], done.stdout, record["env"])
        ok = done.returncode == 0
        if not ok:
            tail = (done.stderr or done.stdout or "").strip().splitlines()[-3:]
            record["error"] = " / ".join(tail)[-500:] or f"종료 코드 {done.returncode}"
        final = "done" if ok else "failed"
    except subprocess.TimeoutExpired:
        final = "failed"
        record["error"] = f"{TIMEOUT_SEC // 60}분 안에 끝나지 않았어요"
    except Exception as exc:
        final = "failed"
        record["error"] = f"{type(exc).__name__}: {exc}"[:500]
    finally:
        # 기록을 다 남긴 뒤에 끝난 것으로 보이게 — 화면 · 시험이 "끝남"을 보고 기록을 읽어도 있게
        record["endedAt"] = time.time()
        _forget(record["env"])
        if not record["dry"]:
            _history({**{k: record.get(k) for k in ("kind", "env", "tool", "action", "specs", "error", "backup")}, "state": final})
        record["state"] = final


def job(jid: str) -> dict:
    found = _jobs.get(jid)
    if not found:
        raise CondaError("없는 작업이에요.")
    return dict(found)


def conda_root_paths() -> list[str]:  # System 화면 · 시험에서 쓴다
    return [paths.real(r) for r in condaenv.conda_roots()]
