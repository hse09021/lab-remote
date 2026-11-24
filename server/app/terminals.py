"""웹 터미널 — WebSocket ↔ tmux (PLAN 4.1 · 6장 4단계).

- 셸 터미널은 프로젝트마다 tmux 서버 하나(`-L labremote-term-<프로젝트>`)에 세션으로
  만든다. 브라우저를 닫아도 셸이 남고, 다시 열면 그대로 붙는다.
- tmux 서버는 **사용자 서비스로** 띄운다(`process.service_prefix`) — 서버의
  nice 19 · ionice idle을 물려받지 않게(터미널에서 학습을 돌릴 수 있다).
- 학습 실행에 붙을 때는 그 실행의 tmux에 붙는다. 기본은 **보기 전용**(`-r`) —
  잘못 누른 Ctrl+C로 학습이 멈추지 않게. 입력을 허용하려면 화면에서 켠다.
- 화면 쪽 tmux 클라이언트는 PTY 하나로 띄우고 WebSocket과 잇는다.
"""

from __future__ import annotations

import asyncio
import fcntl
import os
import pty
import re
import signal
import struct
import subprocess
import termios

from . import files, projects, runs
from .runner import process

__all__ = ["TerminalError", "socket_of", "list_sessions", "create", "kill", "attach_argv", "Pty"]

NAME_RE = re.compile(r"\At-[0-9]{1,4}\Z")


class TerminalError(ValueError):
    """사람에게 그대로 보여 줄 수 있는 거절 사유."""


def socket_of(project: str) -> str:
    return "labremote-term-" + re.sub(r"[^A-Za-z0-9_-]", "-", project)[:60]


def _env() -> dict[str, str]:
    env = dict(os.environ)
    # 키가 섞이면 종량제로 과금된다 · 안쪽 tmux로 착각하지 않게
    for key in ("ANTHROPIC_API_KEY", "ANTHROPIC_AUTH_TOKEN", "TMUX", "TMUX_PANE"):
        env.pop(key, None)
    env["TERM"] = "xterm-256color"
    env.setdefault("LANG", "C.UTF-8")
    return env


def _tmux(*args: str, timeout: int = 10) -> subprocess.CompletedProcess:
    tmux = runs.tmux_bin()
    if not tmux:
        raise TerminalError("tmux가 없어요 — sudo apt install tmux")
    return subprocess.run([tmux, *args], capture_output=True, text=True, timeout=timeout, env=_env())


def list_sessions(project: str) -> list[dict]:
    projects.require(project)
    done = _tmux("-L", socket_of(project), "list-sessions", "-F", "#{session_name}\t#{session_created}\t#{pane_current_path}\t#{session_attached}")
    if done.returncode != 0:
        return []  # 서버가 없다 = 터미널이 없다
    out = []
    for line in done.stdout.splitlines():
        parts = line.split("\t")
        if len(parts) == 4 and NAME_RE.match(parts[0]):
            out.append({"name": parts[0], "createdAt": int(parts[1] or 0), "cwd": parts[2], "attached": parts[3] != "0"})
    out.sort(key=lambda t: int(t["name"][2:]))
    return out


def create(project: str, tree: str = "") -> dict:
    """새 셸. 위치는 프로젝트 안(worktree 포함)만."""
    root = projects.require(project)
    try:
        cwd = files.base_of(root, tree)
    except files.FileRefused as exc:
        raise TerminalError(str(exc)) from None
    existing = list_sessions(project)
    used = {int(t["name"][2:]) for t in existing}
    n = next(i for i in range(1, 10000) if i not in used)
    name = f"t-{n}"
    sock = socket_of(project)
    argv = [runs.tmux_bin(), "-L", sock, "new-session", "-d", "-s", name, "-c", cwd, "-x", "200", "-y", "50"]
    env = _env()
    if not existing and runs._scope_ok(process.scrub_env(dict(os.environ))):
        # 서버가 아직 없으면 사용자 서비스로 띄운다 — nice 0
        argv = process.service_prefix(f"{sock}-{n}", f"lab.remote 터미널 {project}", env) + argv
    done = subprocess.run(argv, capture_output=True, text=True, timeout=20, env=env)
    if done.returncode != 0:
        raise TerminalError("터미널을 열지 못했어요: " + (done.stderr or done.stdout).strip()[:300])
    return {"name": name, "cwd": cwd}


def kill(project: str, name: str) -> None:
    projects.require(project)
    if not NAME_RE.match(name or ""):
        raise TerminalError("터미널 이름이 올바르지 않아요.")
    _tmux("-L", socket_of(project), "kill-session", "-t", name)
    # 마지막 터미널이었으면 tmux 서버도 끝난다 — 남은 소켓 파일을 치운다
    runs.clear_socket(socket_of(project))


def attach_argv(project: str, *, name: str = "", run: str = "", write: bool = False) -> list[str]:
    """화면이 붙을 tmux 클라이언트 명령."""
    projects.require(project)
    tmux = runs.tmux_bin()
    if run:
        got = runs.get(project, run)
        t = got.get("tmux") or {}
        if got["state"] != "running" or not t.get("socket"):
            raise TerminalError("실행 중이 아니라 접속할 수 없어요. 로그는 실행 목록에서 볼 수 있어요.")
        argv = [tmux, "-L", t["socket"], "attach-session", "-t", t.get("session") or "run"]
        return argv if write else argv + ["-r"]
    if not NAME_RE.match(name or "") or name not in {t["name"] for t in list_sessions(project)}:
        raise TerminalError("없는 터미널이에요.")
    return [tmux, "-L", socket_of(project), "attach-session", "-t", name]


class Pty:
    """tmux 클라이언트를 PTY에 띄우고 바이트를 주고받는다."""

    def __init__(self, argv: list[str], cols: int = 120, rows: int = 32) -> None:
        self.master, slave = pty.openpty()
        self.resize(cols, rows)
        self.proc = subprocess.Popen(
            argv, stdin=slave, stdout=slave, stderr=slave, env=_env(), start_new_session=True, close_fds=True
        )
        os.close(slave)
        os.set_blocking(self.master, False)

    def resize(self, cols: int, rows: int) -> None:
        cols = max(10, min(int(cols), 500))
        rows = max(4, min(int(rows), 200))
        fcntl.ioctl(self.master, termios.TIOCSWINSZ, struct.pack("HHHH", rows, cols, 0, 0))

    def write(self, data: bytes) -> None:
        try:
            os.write(self.master, data)
        except (BlockingIOError, OSError):
            pass

    def read(self) -> bytes:
        try:
            return os.read(self.master, 65536)
        except BlockingIOError:
            return b""
        except OSError:  # 클라이언트가 끝났다
            return b"" if self.proc.poll() is None else None  # type: ignore[return-value]

    def close(self) -> None:
        """화면만 떨어진다 — tmux 세션(셸·학습)은 남는다."""
        try:
            os.killpg(self.proc.pid, signal.SIGHUP)
        except (ProcessLookupError, PermissionError):
            pass
        try:
            self.proc.wait(timeout=2)
        except subprocess.TimeoutExpired:
            self.proc.kill()
        try:
            os.close(self.master)
        except OSError:
            pass

    async def pump(self, send) -> None:
        """출력이 오면 `send(bytes)`. 클라이언트가 끝나면 돌아온다."""
        loop = asyncio.get_running_loop()
        ready = asyncio.Event()
        loop.add_reader(self.master, ready.set)
        try:
            while True:
                await ready.wait()
                ready.clear()
                chunk = self.read()
                if chunk is None:
                    break
                if chunk:
                    await send(chunk)
                elif self.proc.poll() is not None:
                    break
        finally:
            loop.remove_reader(self.master)
