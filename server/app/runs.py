"""실행 — `labremote run` 과 화면의 "새 실행" 이 같은 함수를 쓴다.

    systemd-run --user -p Type=forking -p Nice=0 -- tmux -L <소켓> new-session -d -s <세션> bash run.sh
    run.sh:  cd <위치> ; conda run -s -p <환경> bash -c <명령> 2>&1 | tee -a output.log
             ; echo <종료코드> > exit_code

- **접속이 끊겨도, 서버가 다시 떠도 학습은 계속된다**(PLAN 1.5). scope 가
  서버와 다른 cgroup 의 사용자 서비스이고(서버의 nice 19 를 물려받지 않음), tmux 서버는 실행마다 **따로**(`-L`) 띄운다 — 이미
  떠 있는 tmux 서버에 세션을 만들면 학습이 그 서버의 cgroup 으로 들어가
  scope 가 소용없어진다.
- 실행 기록은 프로젝트 안 `<root>/.labremote/runs/<EXP-NNN>/` 에 있다
  (`run.json` · `run.sh` · `output.log` · `exit_code`). 그래서 프로젝트를
  옮기면 기록도 같이 간다.
- **AI 자동화 없음**(PLAN 1.4): 끝난 실행을 다시 돌리거나 이어서 돌리지 않는다.
  재부팅으로 끊긴 실행은 "끊김" 으로 **표시만** 한다.

상태: `running` 실행 중 · `done` 끝남 · `failed` 실패 · `stopped` 중지됨 ·
`cut` 끊김(재부팅·프로세스가 사라짐).
"""

from __future__ import annotations

import csv
import fcntl
import glob as glob_mod
import io
import json
import os
import re
import shlex
import shutil
import subprocess
import threading
import time

from . import files, paths, projects, registry
from .monitor import logs as logs_mod
from .runner import condaenv, process

__all__ = [
    "RunError",
    "STATES",
    "STATE_LABELS",
    "DEFAULT_METRIC_GLOBS",
    "boot_id",
    "start",
    "list_runs",
    "get",
    "refresh",
    "stop",
    "ack",
    "log_tail",
    "metrics_summary",
    "busy_dirs",
]

STATES = ("running", "done", "failed", "stopped", "cut")
STATE_LABELS = {
    "running": "실행 중",
    "done": "끝남",
    "failed": "실패",
    "stopped": "중지됨",
    "cut": "끊김",
}

ID_RE = re.compile(r"\AEXP-(\d{3,6})\Z")
NAME_RE = re.compile(r"\A[^\x00-\x1f/]{1,64}\Z")
MAX_COMMAND = 4000

#: 설정에 지표 규칙이 없을 때 찾아보는 흔한 자리 (실행 위치 기준)
DEFAULT_METRIC_GLOBS = (
    "metrics.csv",
    "runs/*/metrics.csv",
    "outputs/*/metrics.csv",
    "results/*.csv",
    "logs/*.csv",
)

LOG_NAME = "output.log"


class RunError(ValueError):
    """사람에게 그대로 보여 줄 수 있는 거절 사유."""


# --- 바깥 도구 ---------------------------------------------------------------

_scope_cache: dict[str, bool] = {}
_scope_lock = threading.Lock()


def boot_id() -> str:
    """이번 부팅의 id. 바뀌었으면 그 사이 재부팅했다."""
    try:
        with open("/proc/sys/kernel/random/boot_id", encoding="ascii") as fh:
            return fh.read().strip()
    except OSError:
        return ""


def tmux_bin() -> str:
    """시스템 tmux 를 먼저 쓴다 (conda base 의 tmux 는 라이브러리 경고를 낸다)."""
    for candidate in ("/usr/bin/tmux", "/usr/local/bin/tmux"):
        if os.access(candidate, os.X_OK):
            return candidate
    return shutil.which("tmux") or ""


def conda_bin() -> str:
    exe = os.environ.get("CONDA_EXE") or ""
    if exe and os.access(exe, os.X_OK):
        return exe
    for root in condaenv.conda_roots():
        for rel in ("condabin/conda", "bin/conda"):
            path = os.path.join(root, rel)
            if os.access(path, os.X_OK):
                return path
    return shutil.which("conda") or ""


def _scope_ok(env: dict) -> bool:
    if env.get(process.NO_SCOPE_ENV) == "1" or os.environ.get(process.NO_SCOPE_ENV) == "1":
        return False
    with _scope_lock:
        if "ok" not in _scope_cache:
            _scope_cache["ok"] = process.scope_available(env)
        return _scope_cache["ok"]


def _run_env() -> dict[str, str]:
    env = process.scrub_env(dict(os.environ))
    for key in ("TMUX", "TMUX_PANE"):
        env.pop(key, None)
    return env


# --- 기록 ---------------------------------------------------------------------


def runs_dir(root: str) -> str:
    return os.path.join(projects.labremote_dir(root), "runs")


def _run_dir(root: str, run_id: str) -> str:
    if not isinstance(run_id, str) or not ID_RE.match(run_id):
        raise RunError(f"실행 번호가 올바르지 않아요: {run_id!r}")
    return os.path.join(runs_dir(root), run_id)


def _load(root: str, run_id: str) -> dict:
    try:
        with open(os.path.join(_run_dir(root, run_id), "run.json"), encoding="utf-8") as fh:
            data = json.load(fh)
    except FileNotFoundError:
        raise RunError(f"없는 실행이에요: {run_id}") from None
    except (OSError, json.JSONDecodeError) as exc:
        raise RunError(f"실행 기록을 읽지 못했어요: {run_id} ({type(exc).__name__})") from None
    return data if isinstance(data, dict) else {}


def _save(root: str, record: dict) -> None:
    registry.write_json(os.path.join(_run_dir(root, record["id"]), "run.json"), record)


def _next_id(root: str) -> str:
    best = 0
    try:
        for name in os.listdir(runs_dir(root)):
            m = ID_RE.match(name)
            if m:
                best = max(best, int(m.group(1)))
    except FileNotFoundError:
        pass
    return f"EXP-{best + 1:03d}"


def _session(run_id: str, project: str) -> tuple[str, str]:
    """tmux 소켓·세션 이름. 소켓이 실행마다 따로라 서로 섞이지 않는다."""
    sock = "labremote-" + re.sub(r"[^A-Za-z0-9_-]", "-", f"{project}-{run_id}")[:80]
    return sock, "run"


# --- 시작 ---------------------------------------------------------------------


def _script(*, cwd: str, folder: str, command: str, conda: str, prefix: str, run_id: str) -> str:
    q = shlex.quote
    log = os.path.join(folder, LOG_NAME)
    if prefix:
        inner = f"{q(conda)} run -s -p {q(prefix)} bash -c {q(command)}"
    else:
        inner = f"bash -c {q(command)}"
    return f"""#!/usr/bin/env bash
# lab.remote 실행 {run_id} — lab.remote 가 만든 파일이에요. 고쳐도 이미 시작한 실행에는 안 먹어요.
# 중지(Ctrl+C)는 프로그램에만 가게 한다 — 이 셸은 끝까지 남아 종료코드를 적고,
# tee 는 SIGINT 를 무시해 프로그램이 정리하며 찍는 출력도 받는다(안 그러면 SIGPIPE 로 죽는다).
trap 'true' INT
cd -- {q(cwd)} || {{ echo 97 > {q(os.path.join(folder, "exit_code"))}; exit 97; }}
echo $$ > {q(os.path.join(folder, "pid"))}
printf '▶ %s · %s\\n' "$(date '+%F %T')" {q(command)} >> {q(log)}
{inner} 2>&1 | ( trap '' INT; exec tee -a {q(log)} )
code=${{PIPESTATUS[0]}}
printf '■ %s · 종료코드 %s\\n' "$(date '+%F %T')" "$code" >> {q(log)}
echo "$code" > {q(os.path.join(folder, "exit_code.tmp"))} && mv -f {q(os.path.join(folder, "exit_code.tmp"))} {q(os.path.join(folder, "exit_code"))}
exit "$code"
"""


def start(project: str, command: str, *, env: str = "", cwd: str = "", name: str = "") -> dict:
    """실행을 띄운다. 띄우기만 하고 기다리지 않는다.

    `env` 가 비면 conda 없이 `bash -c` 로 돈다. `cwd` 는 프로젝트 안 상대 경로
    (worktree 등)다.
    """
    root = projects.require(project)
    command = (command or "").strip()
    if not command:
        raise RunError("실행할 명령을 적어 주세요.")
    if len(command) > MAX_COMMAND or "\x00" in command:
        raise RunError("명령이 너무 길거나 쓸 수 없는 글자가 있어요.")
    name = (name or "").strip()
    if name and not NAME_RE.match(name):
        raise RunError("실행 이름이 올바르지 않아요 (64자까지, / 는 쓸 수 없어요).")
    try:
        workdir = files.base_of(root, cwd)
    except files.FileRefused as exc:
        raise RunError(f"실행 위치가 올바르지 않아요: {exc}") from None

    prefix = ""
    conda = ""
    if env:
        try:
            prefix = condaenv.require_made(env)
        except condaenv.EnvRefused as exc:
            raise RunError(str(exc)) from None
        conda = conda_bin()
        if not conda:
            raise RunError("conda 를 찾지 못했어요 (CONDA_EXE · ~/miniconda3 등).")
    tmux = tmux_bin()
    if not tmux:
        raise RunError("tmux 가 없어요 — sudo apt install tmux")

    projects.ensure_labremote(root)
    os.makedirs(runs_dir(root), exist_ok=True)
    with open(os.path.join(runs_dir(root), ".lock"), "a+") as lock:
        fcntl.flock(lock.fileno(), fcntl.LOCK_EX)
        try:
            run_id = _next_id(root)
            folder = _run_dir(root, run_id)
            os.makedirs(folder)
        finally:
            fcntl.flock(lock.fileno(), fcntl.LOCK_UN)

    sock, session = _session(run_id, project)
    script = os.path.join(folder, "run.sh")
    with open(script, "w", encoding="utf-8") as fh:
        fh.write(_script(cwd=workdir, folder=folder, command=command, conda=conda, prefix=prefix, run_id=run_id))
    os.chmod(script, 0o700)

    run_env = _run_env()
    use_scope = _scope_ok(run_env)
    unit = process.scope_name(project, run_id) if use_scope else ""
    argv = [tmux, "-L", sock, "new-session", "-d", "-s", session, "-x", "200", "-y", "50", "bash", script]
    if use_scope:
        # scope 가 아니라 서비스로 — 서버의 nice 19 · ionice idle 을 물려받지 않게
        argv = process.service_prefix(unit, f"lab.remote {project} {run_id}", run_env) + argv

    record = {
        "version": 1,
        "id": run_id,
        "project": project,
        "name": name,
        "command": command,
        "env": env,
        "cwd": paths.rel_or_none(root, workdir) or ".",
        "startedAt": time.time(),
        "bootId": boot_id(),
        "tmux": {"socket": sock, "session": session},
        "scope": unit,
        "state": "running",
        "endedAt": None,
        "exitCode": None,
        "reason": "",
        "stopRequested": False,
        "ack": False,
        # 끝난 걸 Inbox·Discord 로 알렸나. 누가 먼저 알아채든(화면·CLI·감시)
        # 감시(watch.tick)가 이 값을 보고 한 번만 알린다.
        "announced": False,
    }
    _save(root, record)
    try:
        done = subprocess.run(argv, capture_output=True, text=True, timeout=30, env=run_env, cwd=workdir)
    except (OSError, subprocess.SubprocessError) as exc:
        record.update(state="failed", endedAt=time.time(), reason=f"띄우지 못했어요: {type(exc).__name__}")
        _save(root, record)
        raise RunError(record["reason"]) from None
    if done.returncode != 0:
        record.update(
            state="failed",
            endedAt=time.time(),
            reason="띄우지 못했어요: " + (done.stderr or done.stdout or "").strip()[:300],
        )
        _save(root, record)
        raise RunError(record["reason"])
    return view(root, record)


# --- 상태 ---------------------------------------------------------------------


def _tmux_alive(record: dict) -> bool:
    tmux = tmux_bin()
    t = record.get("tmux") or {}
    if not tmux or not t.get("socket"):
        return False
    try:
        done = subprocess.run(
            [tmux, "-L", t["socket"], "has-session", "-t", t.get("session") or "run"],
            capture_output=True, timeout=5, env=_run_env(),
        )
    except (OSError, subprocess.SubprocessError):
        return False
    return done.returncode == 0


def _pid_alive(folder: str) -> bool:
    try:
        with open(os.path.join(folder, "pid"), encoding="ascii") as fh:
            pid = int(fh.read().strip())
    except (OSError, ValueError):
        return False
    try:
        with open(f"/proc/{pid}/cmdline", "rb") as fh:
            return b"run.sh" in fh.read()
    except OSError:
        return False


def refresh(root: str, record: dict) -> tuple[dict, bool]:
    """실행 중으로 적힌 기록의 실제 상태를 본다. `(기록, 바뀌었나)`.

    끝난 걸 처음 알아챈 쪽이 `run.json` 에 적는다 — 알림을 한 번만 보내려고.
    """
    if record.get("state") != "running":
        return record, False
    folder = _run_dir(root, record["id"])
    exit_file = os.path.join(folder, "exit_code")
    code = process.read_exit_code(exit_file)
    now = time.time()
    if code is None and not (_tmux_alive(record) or _pid_alive(folder)):
        # 두 확인 사이에 막 끝났을 수 있다 — 종료코드를 한 번 더 본다
        code = process.read_exit_code(exit_file)
        alive = False
    else:
        alive = code is None
    if code is not None:
        if record.get("stopRequested"):
            state = "stopped"
        else:
            state = "done" if code == 0 else "failed"
        ended = os.path.getmtime(os.path.join(folder, "exit_code"))
        record.update(state=state, exitCode=code, endedAt=ended)
    elif alive:
        return record, False
    else:
        rebooted = bool(record.get("bootId")) and record.get("bootId") != boot_id()
        if record.get("stopRequested"):
            record.update(state="stopped", reason="강제로 중지했어요")
        else:
            record.update(
                state="cut",
                reason="데스크톱이 다시 켜지면서 끝났어요" if rebooted else "프로세스가 종료코드 없이 사라졌어요",
            )
        try:
            ended = os.path.getmtime(os.path.join(folder, LOG_NAME))
        except OSError:
            ended = now
        record["endedAt"] = ended
    _save(root, record)
    # 끝난 실행의 tmux 소켓 파일이 /tmp 에 남지 않게
    try:
        clear_socket((record.get("tmux") or {}).get("socket", ""))
    except (OSError, subprocess.SubprocessError):
        pass
    return record, True


def socket_path(sock: str) -> str:
    """tmux 소켓 파일 자리 (`TMUX_TMPDIR` 또는 /tmp 아래 `tmux-<uid>/`)."""
    base = os.environ.get("TMUX_TMPDIR") or "/tmp"
    return os.path.join(base, f"tmux-{os.getuid()}", sock)


def clear_socket(sock: str) -> bool:
    """tmux 서버가 끝났는데 소켓 파일이 남았으면 치운다. 살아 있으면 건드리지 않는다."""
    tmux = tmux_bin()
    if not sock or not tmux:
        return False
    alive = subprocess.run([tmux, "-L", sock, "list-sessions"], capture_output=True, timeout=5, env=_run_env())
    path = socket_path(sock)
    if alive.returncode == 0 or not os.path.exists(path):
        return False
    try:
        os.unlink(path)
        return True
    except OSError:
        return False


def view(root: str, record: dict) -> dict:
    """화면에 내보낼 모양. tmux 에 붙는 명령도 같이."""
    out = dict(record)
    out["stateLabel"] = STATE_LABELS.get(record.get("state", ""), record.get("state", ""))
    t = record.get("tmux") or {}
    out["attach"] = f"tmux -L {t.get('socket')} attach -t {t.get('session') or 'run'}" if t.get("socket") else ""
    out["log"] = os.path.join(_run_dir(root, record["id"]), LOG_NAME)
    end = record.get("endedAt") or time.time()
    out["durationSec"] = max(0, round(end - (record.get("startedAt") or end)))
    return out


def list_runs(project: str, *, refresh_running: bool = True) -> list[dict]:
    """최근 것이 먼저."""
    root = projects.require(project)
    out = []
    try:
        names = sorted((n for n in os.listdir(runs_dir(root)) if ID_RE.match(n)), reverse=True)
    except FileNotFoundError:
        names = []
    for run_id in names:
        try:
            record = _load(root, run_id)
        except RunError:
            continue
        if refresh_running:
            record, _ = refresh(root, record)
        out.append(view(root, record))
    out.sort(key=lambda r: -(r.get("startedAt") or 0))
    return out


def get(project: str, run_id: str) -> dict:
    root = projects.require(project)
    record, _ = refresh(root, _load(root, run_id))
    return view(root, record)


def stop(project: str, run_id: str, *, force: bool = False) -> dict:
    """중지. 보통은 Ctrl+C(SIGINT) 를 보내 프로그램이 스스로 정리하게 하고,
    `force` 면 tmux 서버를 통째로 끈다(체크포인트를 못 남길 수 있다)."""
    root = projects.require(project)
    record = _load(root, run_id)
    if record.get("state") != "running":
        raise RunError("실행 중이 아니에요.")
    tmux = tmux_bin()
    t = record.get("tmux") or {}
    record["stopRequested"] = True
    _save(root, record)
    args = ["kill-server"] if force else ["send-keys", "-t", t.get("session") or "run", "C-c"]
    try:
        subprocess.run([tmux, "-L", t["socket"], *args], capture_output=True, timeout=10, env=_run_env())
    except (OSError, subprocess.SubprocessError, KeyError):
        pass
    if force:
        time.sleep(0.2)
    record, _ = refresh(root, record)
    return view(root, record)


def ack(project: str, run_id: str) -> dict:
    """끊긴 실행 배너에서 "확인" — 배너에서만 빠지고 기록은 남는다."""
    root = projects.require(project)
    record = _load(root, run_id)
    record["ack"] = True
    _save(root, record)
    return view(root, record)


def log_tail(project: str, run_id: str, *, lines: int = 400) -> dict:
    root = projects.require(project)
    _load(root, run_id)  # 있는 실행인지
    got = logs_mod.tail(os.path.join(_run_dir(root, run_id), LOG_NAME), lines=max(1, min(int(lines), 5000)))
    return {"id": run_id, "text": got.get("text", ""), "size": got.get("size", 0), "ok": got.get("ok", False)}


def busy_dirs(root: str) -> list[str]:
    """실행 중인 학습이 쓰는 폴더(실행 위치 + 기록 폴더). 파일 삭제를 막는 데 쓴다."""
    out = []
    try:
        names = [n for n in os.listdir(runs_dir(root)) if ID_RE.match(n)]
    except FileNotFoundError:
        return out
    for run_id in names:
        try:
            record = _load(root, run_id)
        except RunError:
            continue
        if record.get("state") != "running":
            continue
        record, _ = refresh(root, record)
        if record.get("state") == "running":
            out.append(paths.real(os.path.join(root, record.get("cwd") or ".")))
            out.append(_run_dir(root, run_id))
    return out


# --- 지표 ---------------------------------------------------------------------


def _number(text: str):
    try:
        value = float(text)
    except (TypeError, ValueError):
        return text
    return int(value) if value.is_integer() and "." not in text and "e" not in text.lower() else value


def _read_tail_csv(path: str, limit: int = 64 * 1024) -> tuple[list[str], list[list[str]]]:
    with open(path, "rb") as fh:
        header = fh.readline().decode("utf-8", "replace")
        header_end = fh.tell()
        size = os.fstat(fh.fileno()).st_size
        start = max(header_end, size - limit)
        fh.seek(start)
        chunk = fh.read().decode("utf-8", "replace")
    if start > header_end:  # 중간에서 잘린 첫 줄은 버린다
        chunk = chunk.split("\n", 1)[1] if "\n" in chunk else ""
    head = next(csv.reader(io.StringIO(header)), [])
    body = [r for r in csv.reader(io.StringIO(chunk)) if r]
    return [h.strip() for h in head], body


def metrics_summary(project: str, run_id: str) -> dict:
    """실행이 남긴 지표 파일의 마지막 값. 파일은 설정의 규칙 → 흔한 자리 순으로 찾는다.

    실행이 시작된 뒤(1분 여유) 바뀐 파일만 그 실행의 것으로 본다.
    """
    root = projects.require(project)
    record = _load(root, run_id)
    base = paths.real(os.path.join(root, record.get("cwd") or "."))
    globs = projects.load_settings(root).get("metricGlobs") or list(DEFAULT_METRIC_GLOBS)
    since = (record.get("startedAt") or 0) - 60
    found: list[tuple[float, str]] = []
    for pattern in globs:
        for path in glob_mod.glob(os.path.join(glob_mod.escape(base), pattern)):
            real = paths.real(path)
            if not paths.is_inside(paths.real(root), real) or not os.path.isfile(real):
                continue
            mtime = os.path.getmtime(real)
            if mtime >= since:
                found.append((mtime, real))
    if not found:
        return {"id": run_id, "file": None, "rules": globs}
    found.sort(reverse=True)
    path = found[0][1]
    try:
        header, rows = _read_tail_csv(path)
    except OSError as exc:
        return {"id": run_id, "file": paths.rel_or_none(root, path), "error": type(exc).__name__, "rules": globs}
    lower = [h.lower() for h in header]
    last: dict = {}
    if lower[:4] == ["step", "split", "metric", "value"]:
        for r in rows:
            if len(r) >= 4 and r[0].strip().lower() != "step":
                key = f"{r[1].strip()}/{r[2].strip()}" if r[1].strip() else r[2].strip()
                last[key] = _number(r[3].strip())
                last["step"] = _number(r[0].strip())
        fmt = "long"
    else:
        for r in reversed(rows):
            if len(r) == len(header) and [c.strip().lower() for c in r] != lower:
                last = {h: _number(v.strip()) for h, v in zip(header, r)}
                break
        fmt = "wide"
    return {
        "id": run_id,
        "file": paths.rel_or_none(root, path),
        "format": fmt,
        "columns": header,
        "last": last,
        "mtime": found[0][0],
        "rules": globs,
    }
