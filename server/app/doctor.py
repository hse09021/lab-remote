"""`labremote doctor` — 설치와 환경을 점검한다 (v3).

docs/v3/PLAN.md 4.1 의 점검 목록: conda 환경, Claude Code 설치·로그인, tmux,
systemd --user, 자동 시작(linger), 터널. 거기에 웹 빌드 · GPU·드라이버 · 비밀값 권한을 더 본다.

**읽기만 한다.** `~/.claude`·`.bashrc`·`.condarc`·apt 설정을 고치지 않는다 —
고칠 명령은 `hint` 로 알려 준다.
"""

from __future__ import annotations

import os
import shutil
import subprocess
import sys

__all__ = ["run", "render", "Check", "warn", "LEVELS", "MARKS"]

LEVELS = ("ok", "warn", "bad")

MARKS = {"ok": "✔", "warn": "⚠", "bad": "✘"}

#: lab.remote 가 도는 conda 환경 이름 (PLAN 1.1)
ENV_NAME = "labremote"


class Check(dict):
    """`level` 이 참 무게다. `ok` 는 호환을 위해 남겨 둔 거울이다.

    - `Check(True, …)` → `level="ok"`
    - `Check(False, …)` → `level="bad"`
    - `Check(False, …, level="warn")` → ⚠ (종료코드 0)
    """

    def __init__(
        self, ok: bool, title: str, detail: str = "", hint: str = "", level: str = ""
    ):
        if level:
            if level not in LEVELS:
                raise ValueError(f"모르는 점검 무게예요: {level!r}")
        else:
            level = "ok" if ok else "bad"
        super().__init__(
            ok=(level == "ok"), level=level, title=title, detail=detail, hint=hint
        )


def warn(title: str, detail: str = "", hint: str = "") -> Check:
    """⚠ — 알려는 주지만 종료코드를 바꾸지 않는다."""
    return Check(False, title, detail, hint, level="warn")


def _run(argv: list[str], timeout: int = 10) -> tuple[int, str]:
    """명령을 돌려 `(종료코드, 출력)`. 못 띄우면 `(-1, 사유)`. 던지지 않는다."""
    try:
        done = subprocess.run(argv, capture_output=True, text=True, timeout=timeout)
    except (OSError, subprocess.SubprocessError) as exc:
        return -1, str(exc)
    return done.returncode, (done.stdout or "") + (done.stderr or "")


# --- 설치 ----------------------------------------------------------------


def conda_env_check() -> Check:
    """서버가 conda 환경 `labremote`에서 도는가."""
    prefix = os.path.realpath(sys.prefix)
    if os.path.basename(prefix) == ENV_NAME:
        return Check(True, "conda 환경", f"{ENV_NAME} · {prefix}")
    return warn(
        "conda 환경",
        f"지금 파이썬이 {ENV_NAME} 환경이 아니에요: {prefix}",
        hint=f"conda activate {ENV_NAME}",
    )


def _login_probe() -> dict:
    """SDK 로 연결만 해서 계정 정보를 본다(메시지를 보내지 않아 사용량을 안 쓴다)."""
    import asyncio

    from . import registry
    from .agents.claude import probe_account

    return asyncio.run(asyncio.wait_for(probe_account(registry.data_dir()), timeout=60))


def claude_check() -> Check:
    """Claude Code 가 설치돼 있고 로그인돼 있나.

    로그인은 `claude-agent-sdk` 로 **연결만** 해서 Claude Code 가 알려 주는 계정
    정보(구독 종류)로 본다. 자격 증명 파일은 읽지 않고, 이메일은 찍지 않는다.
    """
    binary = shutil.which("claude")
    if not binary:
        return Check(
            False, "Claude Code", "claude 명령을 찾을 수 없어요",
            hint="Claude Code 를 설치하고 로그인해 주세요 (lab.remote 는 로그인을 대신하지 않아요).",
        )
    code, out = _run([binary, "--version"], timeout=20)
    head = (out.strip().splitlines() or [""])[-1]
    if code != 0 or not head:
        return warn("Claude Code", f"판을 못 읽었어요: {head[:120]}")
    try:
        got = _login_probe()
    except Exception as exc:  # SDK 가 없거나 연결이 안 됨
        return warn("Claude Code", f"{head} · 로그인을 확인하지 못했어요 ({type(exc).__name__})",
                    hint="터미널에서 claude 를 한 번 열어 로그인돼 있는지 봐 주세요.")
    if not got.get("loggedIn"):
        return Check(False, "Claude Code", f"{head} · 로그인이 안 돼 있어요",
                     hint="터미널에서 claude 를 열고 /login 으로 로그인해 주세요 (lab.remote 는 로그인을 대신하지 않아요).")
    return Check(True, "Claude Code", f"{head} · 로그인됨 · {got.get('plan') or '구독 종류 모름'}")


def tmux_check() -> Check:
    """`labremote run` · 자동 시작이 쓰는 그 tmux 가 있나 (PLAN 1.5)."""
    from . import runs

    binary = runs.tmux_bin()
    if not binary:
        return Check(False, "tmux", "없어요 — 실행이 접속과 떨어져 돌 수 없어요",
                     hint="sudo apt install tmux")
    code, out = _run([binary, "-V"])
    lines = [l for l in out.splitlines() if l.startswith("tmux ")]
    if code != 0 or not lines:
        return warn("tmux", f"판을 못 읽었어요: {out.strip()[:120]}")
    return Check(True, "tmux", f"{lines[-1]} · {binary}")


def systemd_scope_check() -> Check:
    """`systemd-run --user --scope` 가 실제로 되나 — 실행을 자기 cgroup 에 담는 길."""
    from .runner import process

    if process.scope_available():
        return Check(True, "systemd --user", "systemd-run --user --scope 돼요")
    return warn(
        "systemd --user",
        "systemd-run --user --scope 가 안 돼요 — 서버를 재시작하면 실행이 같이 죽을 수 있어요",
        hint="로그인 세션의 사용자 systemd 가 떠 있는지 봐 주세요 (systemctl --user status).",
    )


def linger_check() -> Check:
    """자동 시작 — 켤 때만 필요하다 (PLAN 1.1). 꺼져 있는 건 정상이다."""
    from .service import units

    got = units.status()
    if not got["systemctl"]:
        return warn("자동 시작", "systemctl 이 없어요 — systemd 가 아닌 환경이에요")
    unit = got["units"].get(units.NAME) or next(iter(got["units"].values()), {})
    enabled = str(unit.get("enabled") or "")
    active = str(unit.get("active") or "")
    linger = got["linger"]
    if not unit.get("file"):
        return Check(True, "자동 시작", "꺼져 있어요 (켜려면 labremote autostart install)")
    if linger is False:
        return warn(
            "자동 시작",
            f"유닛 {enabled or '?'} · linger 꺼짐 — 로그아웃하면 서버가 내려가요",
            hint="loginctl enable-linger $USER  (또는 labremote autostart install 을 다시)",
        )
    if active and active != "active":
        return warn("자동 시작", f"유닛 {enabled or '?'} · {active} — 서버가 안 떠 있어요",
                    hint="journalctl --user -u labremote-session -n 50 · labremote autostart status")
    restarts = unit.get("restarts")
    extra = f" · 재시작 {restarts}회" if isinstance(restarts, int) and restarts else ""
    return Check(True, "자동 시작", f"유닛 {enabled or '?'} · {active or '?'} · linger {'켜짐' if linger else '못 읽음'}{extra}")


def tunnel_check() -> Check:
    """code tunnel — **켜는 건 사람이** `code tunnel service install` (2026-11-23 결정). 읽기만 한다.

    밖에서 접속하지 않으면 없어도 된다 — 그래서 ✘ 가 아니라 ⚠ 다.
    """
    from . import tunnel

    t = tunnel.status(fresh=True)
    if t["state"] == "absent":
        return warn("code tunnel", "VS Code CLI 가 없어요 — 밖(휴대폰 · 다른 PC)에서 열 수 없어요",
                    hint="밖에서 쓸 때만: VS Code 를 설치하고 docs/SETUP.md 의 '밖에서 접속' 을 따라 주세요.")
    if t["state"] == "unknown":
        return warn("code tunnel", f"상태를 못 읽었어요: {t['detail']}")
    if t["loggedIn"] is False:
        return warn("code tunnel", "로그인 안 함 · 꺼져 있어요",
                    hint="code tunnel user login --provider github  →  code tunnel service install")
    if t["state"] == "off":
        return warn("code tunnel", "꺼져 있어요" + (" (서비스는 설치됨)" if t["service"] else ""),
                    hint="code tunnel service install  (재부팅 뒤에도 켜져 있게)")
    how = "서비스" if t["service"] else "손으로 띄움 — 재부팅하면 꺼져요"
    return Check(True, "code tunnel", f"켜져 있어요 · {how}" + (f" · {t['url']}" if t["url"] else ""))


def web_build_check() -> Check:
    """서버가 내줄 웹 화면(`web/dist`)이 빌드돼 있나."""
    from .main import WEB_DIST

    index = os.path.join(WEB_DIST, "index.html")
    if os.path.exists(index):
        return Check(True, "웹 화면", WEB_DIST)
    return Check(False, "웹 화면", "빌드되지 않았어요 — 서버를 열어도 빈 화면이에요",
                 hint="cd web && npm ci && npm run build")


# --- 비밀값 ----------------------------------------------------------------


def api_key_check() -> Check:
    """`ANTHROPIC_API_KEY` 가 환경에 있으면 **경고.**

    키가 섞이면 구독 한도가 아니라 **종량제로 과금**된다.
    """
    from .runner import process

    found = [name for name in process.ENV_STRIP if name.startswith("ANTHROPIC_") and os.environ.get(name)]
    if not found:
        return Check(True, "추가 결제 차단", "ANTHROPIC_* 가 환경에 없어요")
    return warn(
        "추가 결제 차단",
        "환경에 있어요: " + ", ".join(found),
        hint="구독만 쓰려면 셸에서 지워 주세요.",
    )


def webhook_check() -> Check:
    """웹훅 설정 파일 권한이 **0600** 인가. **주소는 찍지 않는다.**"""
    from . import config, notify

    path = config.discord_path()
    mode = config.mode_of(path)
    has_env = bool(os.environ.get("LAB_DISCORD_WEBHOOK", "").strip())
    if mode is None:
        if has_env:
            return Check(True, "Discord 웹훅", "환경 변수로 들어와요 (파일 없음)")
        return warn("Discord 웹훅", "아직 없어요 · 알림이 안 가요",
                    hint="Inbox 화면에서 웹훅 주소를 넣어 주세요.")
    if not config.is_private(path):
        return Check(
            False, "Discord 웹훅",
            f"권한이 넓어요: {oct(mode)[2:]} · 남이 웹훅 주소를 읽을 수 있어요",
            hint=f"chmod 600 {path}",
        )
    if not notify.webhook_url():
        return warn("Discord 웹훅", "설정 파일은 있는데 주소가 비어 있어요")
    return Check(True, "Discord 웹훅", f"{config.masked_webhook()} · 권한 {oct(mode)[2:]}")


def schema_check() -> Check:
    """`lab.db` 스키마 판이 이 코드가 아는 판인가."""
    from . import db as db_mod

    try:
        with db_mod.open_db() as conn:
            got = db_mod.version(conn)
    except db_mod.DbError as exc:
        return Check(False, "DB 스키마", str(exc)[:200])
    except Exception as exc:  # pragma: no cover - DB 를 못 여는 환경
        return warn("DB 스키마", f"못 읽었어요: {exc}")
    if got == db_mod.SCHEMA_VERSION:
        return Check(True, "DB 스키마", f"판 {got} · {db_mod.path()}")
    return Check(False, "DB 스키마", f"판 {got} · 코드는 판 {db_mod.SCHEMA_VERSION} 를 알아요")


# --- GPU -------------------------------------------------------------------


#: `apt-config dump`에서 `Unattended-Upgrade::Package-Blacklist` 에 꼭 있어야
#: 하는 접두사. 드라이버가 저절로 올라가고 재부팅이 안 되면 `nvidia-smi` 가
#: 통째로 죽는다 — 실제로 당했다.
NVIDIA_BLACKLIST = (
    "nvidia-",
    "libnvidia-",
    "cuda-",
    "linux-image-",
    "linux-headers-",
    "linux-modules-",
    "linux-objects-nvidia-",
    "linux-signatures-nvidia-",
)


def apt_blacklist() -> dict:
    """`apt-config dump` 의 **적용값**을 읽는다. 파일 이름을 보지 않는다.

    설정이 여러 파일에 흩어지고 나중 파일이 앞 파일을 덮으므로, 파일이
    있는지로는 알 수 없다. `{"ok", "entries", "autoReboot", "reason"}`.
    """
    code, out = _run(["apt-config", "dump"], timeout=20)
    if code != 0:
        return {"ok": False, "entries": [], "autoReboot": None, "reason": out.strip()[:160]}
    entries, auto = [], None
    for line in out.splitlines():
        text = line.strip()
        if text.startswith("Unattended-Upgrade::Package-Blacklist::"):
            value = text.split('"', 1)[-1].rsplit('"', 1)[0]
            if value:
                entries.append(value)
        elif text.startswith("Unattended-Upgrade::Automatic-Reboot "):
            auto = text.split('"', 1)[-1].rsplit('"', 1)[0].lower()
    return {"ok": True, "entries": entries, "autoReboot": auto, "reason": ""}


def nvidia_hold_note() -> str | None:
    """참고 한 줄 — nvidia 드라이버가 **저절로 올라가지 않게** 묶여 있나.

    점검(✔ ⚠ ✘)이 아니다. 시스템 설정(apt)을 바꾸라는 권유라서, lab.remote 는
    바꾸지 않고 원하는 사람이 직접 하도록 알려 주기만 한다(사람이 고름, 2026-11-23).
    드라이버가 실제로 어긋났을 때는 `gpu_driver_check` 가 ✘ 로 알린다.
    """
    got = apt_blacklist()
    if not got["ok"]:
        return None  # 우분투가 아닌 기계 — 할 말이 없다
    missing = [item for item in NVIDIA_BLACKLIST if item not in got["entries"]]
    auto_reboot_on = got["autoReboot"] in ("true", "1", "yes")
    if not missing and not auto_reboot_on:
        return None
    why = []
    if missing:
        why.append(f"Unattended-Upgrade::Package-Blacklist 에 {', '.join(missing[:4])}{' 등' if len(missing) > 4 else ''} 이 없어요")
    if auto_reboot_on:
        why.append("Automatic-Reboot 가 켜져 있어요")
    return (
        "참고 · 드라이버 자동 업데이트를 막고 싶으면 직접 설정해요 (" + " · ".join(why) + "). "
        "lab.remote 는 바꾸지 않아요 — 방법은 docs/v1/SETUP.md 의 Package-Blacklist 예시."
    )


def gpu_check() -> Check:
    """GPU 를 조회할 수 있나. 조회 실패는 ⚠ 다 (화면에 "조회 불가" 로 나간다)."""
    from .monitor import gpu

    got = gpu.probe()
    if got.get("available"):
        devices = got.get("devices") or []
        head = devices[0] if devices else {}
        detail = f"{len(devices)}개"
        if head.get("name"):
            detail += f" · {head['name']}"
        return Check(True, "GPU", detail)
    return warn("GPU", "조회 불가: " + str(got.get("reason") or "사유 없음")[:140],
                hint="아래 'GPU 드라이버' 줄을 봐 주세요.")


def gpu_driver_check() -> Check:
    """커널 드라이버와 유저랜드 드라이버의 판이 **같은가.**

    다르면 `nvidia-smi` 가 통째로 죽는다(`Failed to initialize NVML`). 재부팅
    대기 목록에 nvidia 가 있으면 아직 안 깨졌지만 곧 깨진다.
    """
    from .monitor import gpu

    state = gpu.driver_state()
    kernel = str(state.get("kernel") or "?")
    user = str(state.get("userland") or "?")
    if state.get("mismatch"):
        return Check(False, "GPU 드라이버", f"판이 달라요 — 커널 {kernel} · 유저랜드 {user}",
                     hint="재부팅이 필요해요. 그 전에는 학습이 실패해요.")
    pending = gpu.reboot_pending()
    if pending.get("nvidia"):
        return warn(
            "GPU 드라이버",
            f"{kernel} · 재부팅 대기에 nvidia 가 있어요: " + ", ".join(pending["nvidia"])[:80],
            hint="다음 재부팅 전까지 nvidia-smi 가 죽을 수 있어요.",
        )
    if not state.get("ok"):
        return warn("GPU 드라이버", "판을 못 읽었어요: " + str(state.get("reason") or "")[:120],
                    hint="nvidia 드라이버가 없는 기계면 정상이에요.")
    detail = f"{kernel} (커널·유저랜드 같아요)"
    if pending.get("pending"):
        detail += " · 재부팅 대기 있음 (nvidia 는 아님)"
    return Check(True, "GPU 드라이버", detail)


# --- 모으기 ----------------------------------------------------------------


#: 점검하지 못하는 것 — 사람이 확인해 주세요.
LIMITATIONS = (
    "터널로 전달한 바깥 주소가 실제로 열리는지는 밖(휴대폰 등)에서 직접 열어 봐야 알아요.",
)


def tunnel_note() -> str | None:
    """터널을 쓰면 늘 붙이는 보안 안내 (System 화면과 같은 말)."""
    from . import tunnel

    t = tunnel.status()
    if t["state"] == "up" or t["service"]:
        return ("터널이 열려 있으면 그 GitHub 계정만 있으면 이 데스크톱의 터미널과 파일에 들어올 수 있어요. "
                "GitHub 2단계 인증을 켜 두세요.")
    return None


def run() -> dict:
    checks = [
        conda_env_check(),
        claude_check(),
        tmux_check(),
        systemd_scope_check(),
        linger_check(),
        tunnel_check(),
        web_build_check(),
        api_key_check(),
        webhook_check(),
        schema_check(),
        gpu_check(),
        gpu_driver_check(),
    ]
    notes = [n for n in (tunnel_note(), nvidia_hold_note()) if n]
    return {
        "ok": all(c["level"] != "bad" for c in checks),
        "checks": checks,
        "notes": notes,
        "limitations": list(LIMITATIONS),
    }


def render(report: dict) -> str:
    lines = []
    for check in report["checks"]:
        mark = MARKS.get(check.get("level") or ("ok" if check["ok"] else "bad"), "✘")
        lines.append(f"{mark} {check['title']:<24} {check['detail']}")
        if mark != "✔" and check["hint"]:
            lines.append(f"    → {check['hint']}")
    lines.append("")
    counts = {name: 0 for name in LEVELS}
    for check in report["checks"]:
        counts[check.get("level") or ("ok" if check["ok"] else "bad")] += 1
    if counts["bad"] or counts["warn"]:
        lines.append(
            f"✘ {counts['bad']}개 · ⚠ {counts['warn']}개 · ✔ {counts['ok']}개"
            + ("  (⚠ 는 종료코드를 바꾸지 않아요)" if counts["warn"] else "")
        )
        lines.append("")
    for note in report.get("notes") or []:
        lines.append(f"· {note}")
    for note in report["limitations"]:
        lines.append(f"· {note}")
    return "\n".join(lines)
