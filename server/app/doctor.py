"""`labremote doctor` — 설치와 설정을 점검한다.

훅은 조용히 안 뜨는 게 제일 위험하다. 그래서 "안 걸려 있다" 를 눈에 보이게 한다.
"""

from __future__ import annotations

import json
import os
import shutil

from . import loop_layout, paths, policy, registry, runstate
from . import policy_defaults as D
from .hooks import check as hooks_check
from .hooks import install

__all__ = [
    "run",
    "Check",
    "permission_mode_check",
    "project_secrets",
    "sandbox_check",
    "bash_sandbox_check",
    "cache_check",
]


def _read_json(path: str) -> dict:
    try:
        with open(path, encoding="utf-8") as fh:
            data = json.load(fh)
    except (FileNotFoundError, json.JSONDecodeError, OSError):
        return {}
    return data if isinstance(data, dict) else {}


def _default_mode(data: dict) -> str:
    """`permissions.defaultMode` (없으면 최상위 `defaultMode`)."""
    perms = data.get("permissions")
    if isinstance(perms, dict) and perms.get("defaultMode"):
        return str(perms["defaultMode"])
    return str(data.get("defaultMode") or "")


def permission_mode_check(root: str, name: str) -> Check:
    """권한 기본 모드가 고정돼 있는가.

    2.1.317 은 **사용자 설정에 defaultMode 가 없으면 `auto`** 로 뜬다
    (실측: `claude --remote-control` 로 새로 띄운 세션이 auto 였다). 그래서
    프로젝트 `.claude/settings.json` 에 박아 두는 게 유일하게 확실한 방법이고,
    프로젝트 설정이 사용자 설정보다 우선한다.
    """
    project_mode = _default_mode(_read_json(policy.claude_settings_path(root)))
    if project_mode:
        ok = project_mode in ("default", "plan")
        return Check(
            ok,
            f"권한 기본 모드 · {name}",
            f"프로젝트 설정 defaultMode={project_mode}",
            hint="default 나 plan 이어야 승인창이 떠요. .claude/settings.json 을 고쳐 주세요.",
        )

    user_mode = _default_mode(_read_json(install.settings_path()))
    if user_mode in ("default", "plan"):
        return Check(
            True,
            f"권한 기본 모드 · {name}",
            f"사용자 설정 defaultMode={user_mode} (프로젝트 설정에도 넣어 두면 더 안전해요)",
        )
    return Check(
        False,
        f"권한 기본 모드 · {name}",
        f"어디에도 없어요 (사용자 설정 {user_mode or '없음'})",
        hint="2.1.317 은 기본이 auto 예요 → labremote policy migrate " + name,
    )


def project_secrets(root: str) -> list[str]:
    """프로젝트 **안**에 있는 비밀 파일. 예시 파일은 뺀다.

    훅은 "대상이 그 파일인 호출" 만 막는다. `grep -r` 처럼 폴더를 훑는 재귀
    읽기는 막을 수 없으므로, 비밀을 프로젝트 밖에 두는 게 1차 방어다.
    """
    found = []
    for base, dirs, files in os.walk(root):
        dirs[:] = [d for d in dirs if d not in (".git", "node_modules", "__pycache__")]
        for item in files:
            full = os.path.join(base, item)
            rel = os.path.relpath(full, root)
            if paths.match_globs(rel, D.SECRET_EXEMPT) or paths.match_abs_globs(
                full, D.SECRET_EXEMPT
            ):
                continue
            if paths.match_abs_globs(full, D.SECRET_FILES):
                found.append(rel)
    return sorted(found)


#: 점검 한 줄의 무게. `warn` 은 **종료코드를 바꾸지 않는다.**
#:
#: 전에는 `ok` 참/거짓뿐이어서 하나만 거짓이면 exit 1 이었다. 그래서
#: "GPU 조회 실패"·"캐시가 프로젝트 안"·"셸 함수가 없음" 같은 **권고**가
#: `labremote doctor` 를 통째로 빨갛게 만들었고, 고칠 수 없는 ✘(드라이버
#: 불일치는 재부팅해야 한다)가 섞여 사람이 ✘ 를 무시하게 된다.
LEVELS = ("ok", "warn", "bad")

MARKS = {"ok": "✔", "warn": "⚠", "bad": "✘"}


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


def sandbox_check(root: str) -> Check:
    """학습 샌드박스를 **실제로 띄워 보고** 점검한다.

    학습 스크립트는 AI 가 쓴 코드다. 훅은 도구 호출만 보므로 `train.py` 안의
    파일 쓰기는 훅을 거치지 않는다. 막는 수단은 샌드박스뿐이라, 꺼져 있으면
    정책·자격 증명·허가 키가 그대로 열린다.
    """
    from .runner import sandbox

    state = sandbox.available(root)
    if state["ok"]:
        hidden = sandbox.hidden_paths(root)
        return Check(True, "학습 샌드박스", f"{state['bwrap']} · 가리는 곳 {len(hidden)}개")
    return Check(
        False,
        "학습 샌드박스",
        state["reason"],
        hint=(
            "학습 스크립트가 정책·자격 증명·허가 키를 건드릴 수 있어요. "
            "sudo apt install bubblewrap 과 /etc/apparmor.d/ 의 bwrap 프로파일을 "
            "확인해 주세요 (docs/operations.md 의 '사람이 해야 하는 것')."
        ),
    )


def bash_sandbox_check(root: str, name: str = "") -> Check:
    """Claude 의 Bash 샌드박스가 켜져 있나.

    꺼져 있으면 AI 가 쓴 **테스트 코드**(`pytest`)가 그대로 돈다 — 실측에서
    `~/.claude.json` 과 정책 파일까지 읽혔다. 런처도 헤드리스를 안 띄운다.
    """
    state = policy.sandbox_state(root)
    if state["ok"]:
        detail = (
            f"{state['source']} · 쓰기 {len(state['allowWrite'])}곳 · "
            f"도메인 {len(state['domains'])}개"
        )
        title = f"Bash 샌드박스 · {name}" if name else "Bash 샌드박스"
        if state["notes"]:
            # 켜져 있긴 하다. conda 가 안 보이면 `python`·`pytest` 가 exit 127
            # 이라 허용 목록이 죽은 줄이 된다 (M3).
            return warn(title, detail, hint=" · ".join(state["notes"]))
        return Check(True, title, detail)
    # ⚠ 다 — 꺼져 있으면 런처가 **헤드리스를 안 띄운다**(fail-closed). 위험한
    # 상태로 도는 게 아니라 **안 도는** 상태라서 종료코드를 바꾸지 않는다.
    return warn(
        f"Bash 샌드박스 · {name}" if name else "Bash 샌드박스",
        "헤드리스 루프가 안 떠요 (launch.check_sandbox 가 거부해요) · "
        + " · ".join(state["reasons"])[:120],
        hint=(
            "labremote hooks install 로 "
            f"{policy.launch_settings_path()} 를 다시 써 주세요."
        ),
    )


def project_settings_check(root: str, name: str = "") -> Check:
    """프로젝트 설정이 **정본과 같은가.** — 샌드박스 탈출을 막는 둘째 겹.

    작업 디렉터리는 샌드박스에서 언제나 쓰기 가능하므로(M4) AI 가 쓴 코드가
    `.claude/settings.json` 을 고칠 수 있다. 실측(M6)에서 거기 심은 훅이
    샌드박스 **밖에서 사용자 권한으로** 돌았고, `sandbox.enabled:false` 로
    AI 코드가 `server/data/runstate/` 에 **실제로 썼다.**

    런처는 그 파일을 안 읽지만(`--setting-sources user`) 맨손 `claude` 는
    읽는다. 그래서 ✘ 다.
    """
    from .orchestrator import projectguard

    title = f"프로젝트 설정 정본 · {name}" if name else "프로젝트 설정 정본"
    report = projectguard.check(root)
    if report["ok"]:
        return Check(True, title, "템플릿과 같아요 (훅·sandbox·permissions 추가 없음)")
    return Check(
        False,
        title,
        " · ".join(report["problems"])[:200],
        hint=(
            f"labremote claude {name or '<이름>'} --force 로 되돌릴 수 있어요. "
            "AI 가 쓴 코드가 고쳤을 수 있으니 무엇이 바뀌었는지 먼저 보세요."
        ),
    )


def git_anchor_check(root: str, name: str = "") -> Check:
    """git 기록이 **앵커와 맞나.** — 이전 커밋 바꿔치기를 잡는다.

    `.git` 은 프로젝트 안이고 샌드박스는 작업 디렉터리 쓰기를 못 막으므로(M4)
    AI 가 쓴 코드가 `branch -D`·`commit --amend`·`reset --hard` 로 실험 기록을
    위조할 수 있다. 앵커는 `lab.db` 에 있고 샌드박스 안에서 그 파일 쓰기가
    실패한다(M1b).
    """
    from .git import anchor as anchor_mod
    from .git import ops as ops_mod

    title = f"git 기록 앵커 · {name}" if name else "git 기록 앵커"
    try:
        from . import db as db_mod

        with db_mod.open_db() as conn:
            report = anchor_mod.check(conn, name, root)
    except ops_mod.GitRefused as exc:
        return Check(False, title, str(exc).splitlines()[0][:160],
                     hint="`.git` 설정을 먼저 봐 주세요 (labremote doctor 의 위 줄).")
    except ops_mod.GitError:
        return Check(True, title, "git 저장소가 아니거나 커밋이 아직 없어요")
    except Exception as exc:  # pragma: no cover - DB 를 못 열는 환경
        return Check(True, title, f"못 봤어요: {exc}")
    if report["ok"]:
        return Check(True, title, f"브랜치 {report['checked']}개가 앵커와 맞아요")
    return Check(
        False,
        title,
        " · ".join(report["problems"])[:200],
        hint=(
            "이전 기록이 바뀌었을 수 있어요. 되돌리지 않았어요 — 무엇이 "
            "사라졌는지 먼저 보세요 (git reflog 가 남아 있을 수 있어요)."
        ),
    )


def project_env_check(root: str, name: str = "") -> Check:
    """실험용 conda 환경이 **우리 환경이 아닌지.**

    `.pth` 는 인터프리터가 뜰 때 실행된다. 훅은 도구 호출마다 그 파이썬으로
    뜨고 오케스트레이터도 같은 환경에서 돈다 — 둘 다 샌드박스 **밖**이다.
    그래서 실험용 환경이 `labremote`·`base` 면 **사람이 승인한 패키지 하나가**
    잠금 판정 코드 안의 임의 코드 실행이 된다.
    """
    import yaml

    from . import loop_layout as L
    from .runner import condaenv

    title = f"실험 conda 환경 · {name}" if name else "실험 conda 환경"
    path = os.path.join(root, L.LOOP_LAYOUT["config"])
    try:
        with open(path, encoding="utf-8") as fh:
            data = yaml.safe_load(fh) or {}
    except (OSError, yaml.YAMLError) as exc:
        return Check(False, title, f"Config.yaml 을 읽을 수 없어요: {exc}")
    env = (data.get("env") or {}) if isinstance(data, dict) else {}
    env_name = str((env or {}).get("conda") or "").strip()

    got = condaenv.check(env_name)
    if got["ok"]:
        where = got["prefix"] or "아직 만들지 않았어요"
        return Check(True, title, f"{env_name} · {where}")
    return Check(
        False,
        title,
        got["reason"][:200],
        hint=(
            "실험용 환경을 따로 만들고 specifications/Config.yaml 의 env.conda "
            "를 고쳐 주세요: conda create -n <이름> python=3.11"
        ),
    )


#: 셸 함수를 찾아볼 파일
SHELL_FILES = ("~/.bashrc", "~/.zshrc", "~/.bash_aliases", "~/.profile")

#: 그 파일에 이 문자열이 있으면 "넣었다" 로 본다
SHELL_MARK = "labremote claude"


#: `apt-config dump` 에서 `Unattended-Upgrade::Package-Blacklist` 에 꼭 있어야
#: 하는 접두사. 드라이버가 저절로 올라가고 재부팅이 안 되면 `nvidia-smi` 가
#: 통째로 죽는다 — ①의 실측 중 실제로 당했다.
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
    있는지로는 알 수 없다. `apt-config dump` 는 apt 자신이 해석한 결과다.

    `{"ok", "entries", "autoReboot", "reason"}`. 던지지 않는다.
    """
    import subprocess

    try:
        done = subprocess.run(
            ["apt-config", "dump"], capture_output=True, text=True, timeout=20
        )
    except (OSError, subprocess.SubprocessError) as exc:
        return {"ok": False, "entries": [], "autoReboot": None, "reason": str(exc)}
    if done.returncode != 0:
        return {
            "ok": False, "entries": [], "autoReboot": None,
            "reason": (done.stderr or "").strip()[:160],
        }

    entries, auto = [], None
    for line in (done.stdout or "").splitlines():
        text = line.strip()
        if text.startswith("Unattended-Upgrade::Package-Blacklist::"):
            value = text.split('"', 1)[-1].rsplit('"', 1)[0]
            if value:
                entries.append(value)
        elif text.startswith("Unattended-Upgrade::Automatic-Reboot "):
            auto = text.split('"', 1)[-1].rsplit('"', 1)[0].lower()
    return {"ok": True, "entries": entries, "autoReboot": auto, "reason": ""}


def nvidia_hold_check() -> Check:
    """nvidia 드라이버가 **저절로 올라가지 않게** 묶여 있나.

    ①의 실측 중 당한 문제다 — 우분투 자동 업데이트가 드라이버를 올리고
    재부팅을 안 하면 커널·유저랜드 판이 어긋나 `nvidia-smi` 가 죽는다.
    그러면 진짜 학습이 전부 실패한다.

    **`apt-config dump` 의 적용값**을 본다 — 파일 이름이 아니라. 설정이 여러
    파일에 흩어지고 나중 파일이 앞을 덮으므로 파일 존재로는 알 수 없다.

    `⚠` 인 이유: 묶여 있지 않아도 지금 당장은 돈다. 다음 업데이트에서
    깨지는 종류라 종료코드를 바꾸지 않는다.
    """
    got = apt_blacklist()
    if not got["ok"]:
        return warn(
            "nvidia 자동 업데이트 제외",
            "apt-config 를 읽지 못했어요: " + str(got["reason"])[:120],
            hint="우분투가 아닌 기계면 정상이에요.",
        )
    missing = [item for item in NVIDIA_BLACKLIST if item not in got["entries"]]
    auto_reboot_on = got["autoReboot"] in ("true", "1", "yes")
    if missing or auto_reboot_on:
        detail = []
        if missing:
            detail.append("빠진 항목: " + ", ".join(missing))
        if auto_reboot_on:
            detail.append("Automatic-Reboot 가 켜져 있어요")
        return warn(
            "nvidia 자동 업데이트 제외",
            " · ".join(detail)[:200],
            hint=(
                "드라이버가 저절로 올라가고 재부팅이 안 되면 nvidia-smi 가 "
                "죽어요 (커널·유저랜드 판 불일치). docs/SETUP.md 를 봐 주세요."
            ),
        )
    detail = f"{len(NVIDIA_BLACKLIST)}개 다 묶여 있어요"
    if got["autoReboot"] is not None:
        detail += f" · Automatic-Reboot {got['autoReboot']}"
    return Check(True, "nvidia 자동 업데이트 제외", detail)


def api_key_check() -> Check:
    """`ANTHROPIC_API_KEY` 가 환경에 있으면 **경고.**

    키가 섞이면 구독 한도가 아니라 **종량제로 과금**된다. 런처가
    `ENV_STRIP` 으로 지우고(`agent/launch.py`) systemd 유닛에도 넣지 않지만,
    사람이 셸에 export 해 두면 다른 자리에서 새어 들어갈 수 있다.
    """
    from .agent import launch as launch_mod

    found = [name for name in launch_mod.ENV_STRIP if os.environ.get(name)]
    if not found:
        return Check(True, "추가 결제 차단", "ANTHROPIC_* 가 환경에 없어요")
    return warn(
        "추가 결제 차단",
        "환경에 있어요: " + ", ".join(found),
        hint=(
            "런처가 지우고 띄우지만(ENV_STRIP), 셸에서 export 해 두면 다른 "
            "자리에서 새어요. 구독만 쓰려면 지워 주세요."
        ),
    )


def webhook_check() -> Check:
    """웹훅 설정 파일 권한이 **0600** 인가. 주소는 읽지 않는다."""
    from . import config, notify

    path = config.config_path()
    mode = config.mode_of(path)
    has_env = bool(os.environ.get("LAB_DISCORD_WEBHOOK", "").strip())
    if mode is None:
        if has_env:
            return Check(True, "웹훅 설정", "환경 변수로 들어와요 (파일 없음)")
        return warn(
            "웹훅 설정",
            f"없어요: {path} · 알림이 안 가요",
            hint="docs/SETUP.md 의 웹훅 단계를 해 주세요.",
        )
    if not config.is_private(path):
        return Check(
            False,
            "웹훅 설정",
            f"권한이 넓어요: {oct(mode)[2:]} · 남이 웹훅 주소를 읽을 수 있어요",
            hint=f"chmod 600 {path}",
        )
    # 주소 자체는 **찍지 않는다** — 비어 있는지만 본다
    if not notify.webhook_url():
        return warn(
            "웹훅 설정",
            f"{path} 는 있는데 주소가 비어 있어요",
            hint="[discord] webhook = \"…\" 을 채워 주세요.",
        )
    return Check(True, "웹훅 설정", f"{path} · 권한 {oct(mode)[2:]}")


def schema_check() -> Check:
    """`lab.db` 스키마 판이 이 코드가 아는 판인가."""
    from . import db as db_mod

    try:
        with db_mod.open_db() as conn:
            got = db_mod.version(conn)
    except db_mod.DbError as exc:
        return Check(False, "DB 스키마", str(exc)[:200],
                     hint="코드를 올리거나 데이터를 백업하고 지워 주세요.")
    except Exception as exc:  # pragma: no cover - DB 를 못 열는 환경
        return warn("DB 스키마", f"못 읽었어요: {exc}")
    if got == db_mod.SCHEMA_VERSION:
        return Check(True, "DB 스키마", f"판 {got} · {db_mod.path()}")
    return Check(
        False,
        "DB 스키마",
        f"판 {got} · 코드는 판 {db_mod.SCHEMA_VERSION} 를 알아요",
        hint="labremote doctor 를 다시 돌리면 이행돼요 (open_db 가 올려요).",
    )


def deny_commands_check(pol=None) -> Check:
    """정책의 `bash.denyCommands` 에 **0-1 의 명령이 다** 들어 있나.

    자기 승인 차단(`labremote`·`sqlite3`·`systemctl`·`pkill` …)과 격리 깨기
    (`bwrap`·`unshare`·`docker` …)가 여기 있다. 정책 파일은 사람이 고칠 수
    있어서(프로젝트 밖) 빠질 수 있다.
    """
    from . import policy_defaults as D

    title = "금지 명령"
    listed = set((getattr(pol, "bash", {}) or {}).get("denyCommands") or [])
    if not listed:
        return Check(False, title, "정책에 denyCommands 가 비어 있어요",
                     hint="labremote policy migrate <이름> 으로 다시 써 주세요.")
    missing = sorted(set(D.DENY_COMMANDS) - listed)
    if missing:
        return Check(
            False,
            title,
            f"{len(missing)}개 빠졌어요: " + ", ".join(missing[:8]),
            hint="labremote policy migrate <이름> 으로 다시 써 주세요.",
        )
    return Check(True, title, f"{len(listed)}개 다 있어요")


def loop_state_check(root: str, name: str = "") -> Check:
    """`state/Current.yaml` 과 서버 쪽 `runstate` 가 **같은 말을 하나.**

    ①의 숙제였다 — 실측에서 둘이 어긋나(loop 0 vs EXP-002 running) Claude 가
    잠금의 이유를 설명하지 못했다. `Current.yaml` 은 AI 가 못 고치는
    근거 파일이므로(selfProtect) 서버 쪽과 어긋나면 그 근거가 깨진다.
    """
    from . import loopstate, runstate

    title = f"루프 상태 정합 · {name}" if name else "루프 상태 정합"
    live = runstate.load(name) if name else runstate.RunState()
    current = loopstate.read_current(root)
    if not current:
        if getattr(live, "running", False):
            return Check(
                False, title,
                "Current.yaml 이 없는데 서버는 실행 중이라고 해요",
                hint="labremote run-state <이름> --idle 로 맞춰 주세요.",
            )
        return Check(True, title, "둘 다 안 돌고 있어요 (Current.yaml 아직 없음)")

    said = bool(current.get("running"))
    real = bool(getattr(live, "running", False))
    exp_said = str(current.get("current_experiment") or "")
    exp_real = str(getattr(live, "experiment_id", "") or "")
    if said != real or (real and exp_said != exp_real):
        return Check(
            False,
            title,
            f"어긋나요 — Current.yaml: {exp_said or '없음'}/{said} · "
            f"서버: {exp_real or '없음'}/{real}",
            hint=(
                "오케스트레이터가 둘을 같이 갱신해요(app/loopstate.py). "
                "어긋났으면 labremote run-state <이름> 으로 맞춰 주세요."
            ),
        )
    return Check(True, title, f"{exp_real or '안 돌고 있어요'} · 둘이 같아요")


def leftover_requests_check(name: str) -> Check:
    """`requests/` 에 닫히지 않은 승인 요청이 남아 있나. — ⚠ 다.

    쌓이기만 하면 사람이 무엇을 승인해야 하는지 흐려진다. 오래된 것은
    `labremote requests clear` 로 치운다.
    """
    from . import approval_log as A

    title = f"승인 요청 잔여 · {name}" if name else "승인 요청 잔여"
    try:
        items = A.list_requests(name)
    except Exception as exc:  # pragma: no cover
        return warn(title, f"못 읽었어요: {exc}")
    if not items:
        return Check(True, title, "없어요")
    return warn(
        title,
        f"{len(items)}건 남아 있어요: "
        + ", ".join(str(i.get("requestId") or "")[:18] for i in items[:3]),
        hint=(
            f"labremote approvals list 로 보고, 오래된 것은 "
            f"labremote requests clear {name} 로 치워 주세요."
        ),
    )


def gpu_check() -> Check:
    """GPU 를 조회할 수 있나. — **⚠ 다** (실험 자체는 돌 수 있습니다).

    `monitor/gpu.probe()` 는 실패를 **정상 경로**로 돌려줍니다(예외를 던지지
    않습니다). 조회가 안 되면 대시보드에 "조회 불가" 로 나가고 가짜 학습은
    그대로 돕니다 — 그래서 ⚠ 입니다.

    ⚠ 이게 `doctor` 에 **없었습니다**(계획 7단계에 "GPU 조회(⚠)" 로 적혀
    있었는데 빠졌습니다). `monitor/gpu.py` 에 함수는 다 있었고 `doctor` 가
    부르지 않았습니다 — `grant_key` 와 같은 종류의 빠짐입니다.
    """
    from .monitor import gpu

    got = gpu.probe()
    if got.get("available"):
        devices = got.get("devices") or []
        head = devices[0] if devices else {}
        detail = f"{len(devices)}개"
        if head.get("name"):
            detail += f" · {head['name']}"
        if head.get("memoryTotalMb"):
            detail += f" · {head['memoryTotalMb']}MB"
        return Check(True, "GPU", detail)
    return warn(
        "GPU",
        "조회 불가: " + str(got.get("reason") or "사유 없음")[:140],
        hint=(
            "가짜 학습은 돌 수 있어요. 진짜 학습은 안 돼요 — "
            "아래 'GPU 드라이버' 줄을 봐 주세요."
        ),
    )


def gpu_driver_check() -> Check:
    """커널 드라이버와 유저랜드 드라이버의 판이 **같은가.**

    ①의 실측 중 실제로 당한 문제입니다 — 우분투 자동 업데이트가 드라이버를
    올리고 재부팅을 안 하면 `nvidia-smi` 가 통째로 죽습니다
    (`Failed to initialize NVML`).

    | 판정 | 조건 |
    |---|---|
    | ✘ | 판이 **다르다** — 재부팅 전에는 학습이 실패합니다 |
    | ⚠ | 재부팅 대기 목록에 **nvidia** 가 있다 — 아직 안 깨졌지만 곧 깨집니다 |
    | ✔ | 같다 |

    `guards.check_train` 이 불일치면 `train` 작업을 **시작하지 않습니다** —
    어차피 실패할 학습으로 GPU 시간과 사용량을 버리지 않습니다.
    """
    from .monitor import gpu

    state = gpu.driver_state()
    kernel = str(state.get("kernel") or "?")
    user = str(state.get("userland") or "?")
    if state.get("mismatch"):
        return Check(
            False,
            "GPU 드라이버",
            f"판이 달라요 — 커널 {kernel} · 유저랜드 {user}",
            hint=(
                "재부팅이 필요해요. 그 전에는 실험을 시작하면 실패해요 "
                "(guards 가 train 작업을 안 띄워요)."
            ),
        )
    pending = gpu.reboot_pending()
    if pending.get("nvidia"):
        return warn(
            "GPU 드라이버",
            f"{kernel} · 재부팅 대기에 nvidia 가 있어요: "
            + ", ".join(pending["nvidia"])[:80],
            hint=(
                "아직 안 깨졌지만 다음 재부팅 전까지 `nvidia-smi` 가 죽을 수 "
                "있어요. 지금 재부팅해 두는 게 안전해요."
            ),
        )
    if not state.get("ok"):
        return warn(
            "GPU 드라이버",
            "판을 못 읽었어요: " + str(state.get("reason") or "")[:120],
            hint="nvidia 드라이버가 없는 기계면 정상이에요.",
        )
    detail = f"{kernel} (커널·유저랜드 같아요)"
    if pending.get("pending"):
        detail += " · 재부팅 대기 있음 (nvidia 는 아님)"
    return Check(True, "GPU 드라이버", detail)


def grant_key_check() -> Check:
    """🔑 허가 서명 키가 있고 **남이 못 읽는가.**

    없으면 `config.grant_key()` 가 `None` 이고 `grants.verify` 가 전부 거짓이
    되어 **헤드리스 승인이 아예 안 된다** — 훅이 허가를 무시하고 그대로
    막는다(fail-closed). 승인 대기열 전체가 멈춘다.

    ⚠ 이게 `doctor` 에 **없었다**(S9 e2e 가 잡았다). 사람이 `approve` 를
    돌려서 실패할 때까지 알 수 없었고, 그때의 안내는 **없는 명령**
    (`labremote service install` — 8단계)을 가리켰다.

    `✘` 인 이유: 한 명령으로 고쳐지고(`labremote keys init`), 고치면 바로
    사라진다. 권한이 넓은 것도 `✘` 다 — 키가 새면 AI 가 쓴 코드가 허가를
    위조할 수 있다.
    """
    from . import config

    path = config.grant_key_path()
    mode = config.mode_of(path)
    if mode is None:
        return Check(
            False,
            "허가 서명 키",
            f"없어요: {path} · 헤드리스 승인이 안 돼요",
            hint="labremote keys init 로 만들어 주세요 (그 명령만 돌리면 돼요).",
        )
    if not config.is_private(path):
        return Check(
            False,
            "허가 서명 키",
            f"권한이 넓어요: {oct(mode)[2:]} · 남이 읽으면 허가를 위조할 수 있어요",
            hint="labremote keys init --fix-mode 로 0600 으로 고쳐 주세요.",
        )
    if not config.grant_key():
        return Check(
            False,
            "허가 서명 키",
            f"비어 있어요: {path}",
            hint="지우고 labremote keys init 로 다시 만들어 주세요.",
        )
    return Check(True, "허가 서명 키", f"{path} · 권한 {oct(mode)[2:]}")


def audit_check(root: str, name: str = "", pol=None) -> Check:
    """승인 기록이 **진본과 같은가.**

    프로젝트의 `logs/Approval_log.csv` 는 AI 가 쓴 코드가 고칠 수 있다(M4 —
    샌드박스는 작업 디렉터리 쓰기를 못 막고 좁힐 수도 없다). 진본은
    `server/data/audit/<프로젝트>.jsonl` 이고 AI 는 거기에 못 쓴다(M1b).
    """
    from . import approval_log as A
    from . import audit

    title = f"승인 기록 진본 · {name}" if name else "승인 기록 진본"
    report = audit.compare(name, A.log_path(root, pol))
    if report["ok"]:
        return Check(True, title, f"사본이 진본과 같아요 ({report['truth']}줄)")
    return Check(
        False,
        title,
        audit.describe(report).splitlines()[0][:200],
        hint=(
            f"labremote audit {name or '<이름>'} 로 어디가 다른지 보고, "
            "--rebuild 로 사본을 다시 만들 수 있어요."
        ),
    )


def claude_version_check() -> Check:
    """Claude Code 판이 **도구 목록을 실측한 판**과 같은가. — ⚠ 다.

    2.1.317 → 2.1.318 이 저절로 바뀌면서 서브에이전트 도구 이름이
    `Task` → `Agent` 가 됐고, `--disallowedTools Task` 가 무효가 되어
    서브에이전트가 열린 채로 돌았다. **조용한 실패**였다.

    `doctor` 는 ⚠ 지만 **헤드리스 루프는 멈춥니다**(`guards.check_loop`) —
    루프는 사람이 안 보는 동안 도므로 조용한 틈이 가장 나쁘다. 대화형은
    막지 않는다 (사람이 보고 있고, 막으면 재는 것도 못 한다).
    """
    from .agent import version as version_mod

    got = version_mod.check()
    if got["ok"]:
        return Check(
            True,
            "Claude Code 판",
            f"{got['current']} · 도구 목록 실측 {got['at']}",
        )
    return warn(
        "Claude Code 판",
        got["reason"][:200],
        hint=(
            "labremote tools --probe 로 세션에 도구 목록을 물어 다시 재고 "
            "기록해 주세요. 그때까지 헤드리스 루프는 멈춰 있어요."
        ),
    )


def shell_guard_check() -> Check:
    """맨손 `claude` 를 멈춰 세우는 셸 함수가 있나. — ⚠ 다.

    T3 뒤에도 남는 구멍 하나: **사람이 실험 프로젝트 폴더에서 맨손 `claude`
    를 치면** 프로젝트 설정이 그대로 먹는다(M6). `CLAUDE.md`·`README` 가
    안내하지만 습관은 안내보다 세다.

    `doctor` 는 대화형 셸의 함수를 볼 수 없으니 **셸 설정 파일을 읽는다.**
    읽기만 한다 — 사람의 셸 설정을 코드가 고치지 않는다(규칙 0 과 같은 이유).

    **✘ 가 아닌 이유**: 없어도 루프는 정상이다. 사람의 습관을 돕는 장치라
    종료코드를 바꾸면 "고칠 수 없는 ✘" 가 된다.
    """
    found = []
    unreadable = []
    for item in SHELL_FILES:
        path = os.path.expanduser(item)
        if not os.path.exists(path):
            continue
        try:
            with open(path, encoding="utf-8", errors="replace") as fh:
                if SHELL_MARK in fh.read():
                    found.append(item)
        except OSError:
            unreadable.append(item)
    if found:
        return Check(True, "셸 보호 함수", "있어요: " + ", ".join(found))
    detail = "맨손 claude 를 멈춰 세우는 셸 함수가 없어요"
    if unreadable:
        detail += f" (못 읽은 파일: {', '.join(unreadable)})"
    return warn(
        "셸 보호 함수",
        detail,
        hint=(
            "docs/SETUP.md 의 \"맨손 claude 를 멈춰 세우기\" 문구를 ~/.bashrc 에 "
            "붙여 주세요. 프로젝트 폴더에서 claude 를 치면 "
            "labremote claude <이름> 으로 열라고 알려 줘요."
        ),
    )


def user_sandbox_check() -> Check:
    """사용자 설정에 `sandbox` 절이 있으면 **이 PC 의 모든 세션**이 갇힌다.

    우리 코드는 그 파일에 샌드박스를 쓰지 않는다(규칙 0). 사람이 넣었거나
    옛 판이 넣어 둔 것이면 개발 세션까지 갇히므로 알려 준다.
    """
    import json as _json

    path = policy.user_settings_path()
    try:
        with open(path, encoding="utf-8") as fh:
            data = _json.load(fh)
    except (FileNotFoundError, ValueError, OSError):
        return Check(True, "사용자 설정 샌드박스", "없어요 (맞아요)")
    if isinstance(data, dict) and isinstance(data.get("sandbox"), dict):
        return Check(
            False,
            "사용자 설정 샌드박스",
            f"{path} 에 sandbox 절이 있어요",
            hint=(
                "이 PC 의 **모든** Claude 세션(개발 세션까지)이 갇혀요. "
                "샌드박스는 런처가 "
                f"{policy.launch_settings_path()} 로 넘겨요 — 그 절을 지워 주세요."
            ),
        )
    return Check(True, "사용자 설정 샌드박스", "없어요 (맞아요)")


def cache_check(root: str, pol=None) -> Check:
    """공용 캐시 폴더가 보호 경로와 겹치지 않는지.

    겹치면 **학습 코드에 정책·자격 증명을 쓰기로 열어 주는 셈**이다.
    런처도 거부하지만(`runner/cache.check`), 돌리기 전에 알려 주는 게 낫다.
    """
    from .runner import cache

    state = cache.describe(root, pol)
    if not state["ok"]:
        return Check(
            False,
            "공용 캐시",
            state["reason"],
            hint="정책의 paths.cacheDir 을 프로젝트·보호 경로 밖으로 바꿔 주세요.",
        )
    detail = state["dir"]
    if not state["exists"]:
        detail += " (아직 없어요 — 첫 학습에서 만들어요)"
    elif "freeGb" in state:
        detail += f" · 여유 {state['freeGb']}GB"
    if state["warnings"]:
        # 권고다 — 캐시가 프로젝트 안이면 저장소가 커지지만 루프는 돈다.
        return warn("공용 캐시", detail, hint=state["warnings"][0])
    return Check(True, "공용 캐시", detail)


def run() -> dict:
    checks: list[Check] = []

    # --- 폴더 구조 ---------------------------------------------------------
    left = loop_layout.pending_keys()
    checks.append(
        Check(
            not left,
            "Loop Engineering 경로",
            "모두 확정됐어요" if not left else f"자리표시가 남아 있어요: {', '.join(left)}",
            hint="docs/Loop*.pdf 를 읽고 app/loop_layout.py 를 채워 주세요.",
        )
    )

    # --- 훅 설치 -----------------------------------------------------------
    state = install.status()
    mode = (state.get("state") or {}).get("mode")
    checks.append(
        Check(
            bool(state["installed"]),
            "훅 등록",
            f"{', '.join(sorted(state['installed'])) or '없음'}" + (f" · {mode} 모드" if mode else ""),
            hint="labremote hooks install --mode enforce",
        )
    )

    # 설치한 뒤에 이벤트가 늘어나면 조용히 빠진다 (UserPromptSubmit 이 그 예).
    if state["installed"]:
        want = install.expected_events(mode or "enforce")
        missing_events = sorted(want - set(state["installed"]))
        checks.append(
            Check(
                not missing_events,
                "훅 이벤트",
                "전부 걸려 있어요" if not missing_events else f"빠진 이벤트: {', '.join(missing_events)}",
                hint="labremote hooks install 을 다시 돌려 주세요. UserPromptSubmit 이 "
                "없으면 거부로 끊긴 턴의 승인 대기 건이 세션 끝까지 남아요.",
            )
        )
    checks.append(
        Check(
            state["wrapperExists"] and os.access(state["wrapper"], os.X_OK),
            "래퍼 파일",
            state["wrapper"],
            hint="labremote hooks install 을 다시 돌려 주세요.",
        )
    )

    interpreter = (state.get("state") or {}).get("python") or ""
    checks.append(
        Check(
            bool(interpreter) and os.access(interpreter, os.X_OK),
            "훅이 쓸 파이썬",
            interpreter or "(모름)",
            hint="인터프리터가 사라지면 실험 프로젝트에서 모든 작업이 막혀요.",
        )
    )

    if mode == "dump":
        checks.append(
            Check(False, "판정 모드", "dump — 받아 적기만 하고 아무것도 막지 않아요",
                  hint="labremote hooks install --mode enforce")
        )

    baked = (state.get("state") or {}).get("roots") or ""
    live = registry.projects_root()
    checks.append(
        Check(
            baked == live if baked else False,
            "프로젝트 루트",
            f"래퍼에 박힌 값 {baked or '(모름)'} · 지금 설정 {live}",
            hint="다르면 labremote hooks install 을 다시 돌려 주세요.",
        )
    )

    # --- 프로젝트 ----------------------------------------------------------
    projects = registry.load()
    checks.append(
        Check(bool(projects), "등록된 프로젝트", f"{len(projects)}개", hint="labremote init-project <이름>")
    )
    for root, name in sorted(projects.items()):
        checks.append(Check(os.path.isdir(root), f"프로젝트 폴더 · {name}", root))
        pol = None  # 정책을 못 읽어도 뒤 점검은 돌아야 한다
        try:
            pol = policy.load(name)
            checks.append(
                Check(True, f"정책 · {name}", f"{pol.effective_mode()} · {pol.path}")
            )
            locked = [k for k in ("outside", "stop", "prev") if pol.resolve(k) != "block"]
            checks.append(
                Check(not locked, f"잠금 · {name}", "3개 다 잠겨 있어요" if not locked else f"풀린 항목: {locked}")
            )
            # extraWritableRoots 가 보호 목록을 건드리는가 (판정은 보호 목록이
            # 이기지만, 조용히 두면 "열었다" 고 오해한다)
            conflicts = policy.conflicting_writable_roots(pol)
            checks.append(
                Check(
                    not conflicts,
                    f"쓰기 예외 · {name}",
                    "겹치는 곳이 없어요" if not conflicts else f"보호 경로와 겹쳐요: {conflicts}",
                    hint="이 경로는 어떤 설정에서도 막혀요. extraWritableRoots 에서 빼 주세요.",
                )
            )
        except policy.PolicyError as exc:
            hint = ""
            if "판이 맞지 않아요" in str(exc):
                hint = f"labremote policy migrate {name}"
            checks.append(Check(False, f"정책 · {name}", str(exc), hint=hint))

        checks.append(permission_mode_check(root, name))

        secrets = project_secrets(root)
        checks.append(
            Check(
                not secrets,
                f"비밀 파일 위치 · {name}",
                "프로젝트 안에 없어요" if not secrets else f"프로젝트 안에 있어요: {secrets}",
                hint="재귀 읽기(grep -r)는 훅이 못 막아요. "
                f"~/.config/labremote/{name}.env 로 옮기고 .env.example 만 남겨 주세요.",
            )
        )

        state_now = runstate.load(name)
        detail = "안 돌고 있어요" if not state_now.running else f"{state_now.experiment_id} 실행 중"
        if state_now.started:
            detail += f" · 시작된 실험 {len(state_now.started)}개"
        checks.append(Check(not state_now.stale, f"실행 상태 · {name}", detail,
                            hint="running 인데 프로세스가 없어요. labremote run-state --idle 로 정리해 주세요."))
        checks.append(
            Check(
                paths.rel_or_none(root, paths.real(registry.policy_path(name))) is None,
                f"정책 위치 · {name}",
                "프로젝트 밖에 있어요 (AI 가 못 고쳐요)",
            )
        )

        # 학습 샌드박스 — 학습은 AI 가 쓴 코드다. 막는 수단은 이것뿐이다.
        checks.append(sandbox_check(root))
        # Claude 의 Bash 샌드박스 — AI 가 쓴 **테스트 코드**를 가두는 수단
        checks.append(bash_sandbox_check(root, name))
        # 프로젝트 설정 정본 — 샌드박스 탈출을 막는 둘째 겹 (M6)
        checks.append(project_settings_check(root, name))
        # git 기록 앵커 — 이전 커밋 바꿔치기를 잡는다
        checks.append(git_anchor_check(root, name))
        # 실험 conda 환경이 우리 환경이 아닌지 (.pth 자동 실행)
        checks.append(project_env_check(root, name))
        # 승인 기록 사본이 진본과 같은지
        checks.append(audit_check(root, name, pol))
        # 정책의 금지 명령이 다 있는지 (자기 승인 차단·격리 깨기)
        checks.append(deny_commands_check(pol))
        # Current.yaml ↔ runstate 정합 (①의 숙제)
        checks.append(loop_state_check(root, name))
        # 닫히지 않은 승인 요청 (⚠)
        checks.append(leftover_requests_check(name))
        # 공용 캐시 — 샌드박스 안에서 쓸 수 있는 유일한 바깥
        checks.append(cache_check(root, pol))

    # GPU — 조회 실패는 ⚠ (가짜 학습은 돈다), 드라이버 불일치는 ✘
    checks.append(gpu_check())
    checks.append(gpu_driver_check())
    # nvidia 가 저절로 올라가면 드라이버 판이 어긋난다 (apt 적용값으로 본다)
    checks.append(nvidia_hold_check())
    # 구독만 쓴다 — 키가 섞이면 종량제 과금이다
    checks.append(api_key_check())
    # 웹훅 설정 권한 (주소는 읽지 않는다)
    checks.append(webhook_check())
    # lab.db 스키마 판
    checks.append(schema_check())
    # 허가 서명 키 — 없으면 헤드리스 승인이 아예 안 된다
    checks.append(grant_key_check())
    # 사용자 설정에 sandbox 가 있으면 이 PC 의 모든 세션이 갇힌다
    checks.append(user_sandbox_check())
    # Claude Code 판이 바뀌면 도구 이름이 바뀔 수 있다 (⚠ · 루프는 멈춘다)
    checks.append(claude_version_check())
    # 맨손 `claude` 를 멈춰 세우는 셸 함수 (권고 — ⚠)
    checks.append(shell_guard_check())

    # 자가 점검이 중간에 죽으면 임시 프로젝트 폴더가 남는다
    leftovers = hooks_check.scratch_leftovers()
    checks.append(
        Check(
            not leftovers,
            "자가 점검 잔해",
            "없어요" if not leftovers else f"{len(leftovers)}개 남아 있어요: {leftovers}",
            hint="labremote hooks check 를 다시 돌리면 스스로 지워요 (rm -rf 해도 돼요).",
        )
    )

    # --- 바깥 도구 ----------------------------------------------------------
    checks.append(Check(bool(shutil.which("git")), "git", shutil.which("git") or "없음"))
    data_dir = registry.data_dir()
    checks.append(
        Check(
            os.path.isdir(data_dir),
            "런타임 폴더",
            data_dir,
            hint="server/data/ 는 gitignore 라 백업되지 않아요. ②에서 붙입니다.",
        )
    )

    return {
        # ⚠ 는 종료코드를 바꾸지 않는다 — 고칠 수 없는 ✘ 가 섞이면 사람이
        # ✘ 를 무시하게 된다.
        "ok": not any(c.get("level", "bad" if not c["ok"] else "ok") == "bad" for c in checks),
        "warnings": [c for c in checks if c.get("level") == "warn"],
        "checks": checks,
        "limitations": install.limitations(),
    }


def render(report: dict) -> str:
    lines = []
    for check in report["checks"]:
        mark = MARKS.get(check.get("level") or ("ok" if check["ok"] else "bad"), "✘")
        line = f"{mark} {check['title']:<24} {check['detail']}"
        lines.append(line)
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
    for note in report["limitations"]:
        lines.append(f"· {note}")
    return "\n".join(lines)
