"""`claude -p` 인자 조립 — **보안 경계다.**

②가 ①의 경계를 약하게 만들 수 있는 자리는 여기뿐이다. 플래그 한 줄이면 훅이
통째로 사라진다 (`claude --help` 원문):

| 플래그 | 무엇 | 결과 |
|---|---|---|
| `--bare` | *"Minimal mode: **skip hooks**"* | 잠금 전부 사라짐 |
| `--safe-mode` | *"all customizations (… hooks …) disabled"* | 같음 |
| `--setting-sources` | user 를 빼면 `~/.claude/settings.json` 을 안 읽음 | 훅 등록이 거기 있음 |
| `--restricted` | 설정 파일 무시 | 훅 등록 무시 |
| `--dangerously-skip-permissions` | 권한 검사 우회 | 훅이 뜨는지 미확인 |
| `--permission-mode bypassPermissions`·`auto`·`dontAsk` | 승인 경로 소실 | `auto` 는 ①에서 사고가 난 모드 |

그래서 **허용 목록**으로 간다 — 아는 플래그만 넣고, 금지 플래그가 섞이면
`LaunchRefused` 로 띄우지 않는다.

### 구독으로만 돈다

`ANTHROPIC_API_KEY` 를 환경에서 **지운다.** 키가 섞이면 구독 한도가 아니라
종량제 과금이다. 추가 결제·API 키 전환은 어떤 경우에도 하지 않는다.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field

from .. import paths, registry

__all__ = [
    "FORBIDDEN_FLAGS",
    "FORBIDDEN_MODES",
    "ALLOWED_MODES",
    "ENV_STRIP",
    "HEADLESS_ENV",
    "LaunchRefused",
    "AgentRun",
    "check_flags",
    "build_argv",
    "build_env",
]

#: 훅을 끄거나 설정을 무시하는 플래그. **하나라도 있으면 안 띄운다.**
FORBIDDEN_FLAGS = frozenset(
    {
        "--bare",
        "--safe-mode",
        "--restricted",
        "--setting-sources",
        "--dangerously-skip-permissions",
        "--no-hooks",
        "--disable-hooks",
    }
)

#: 승인 경로가 사라지는 권한 모드
FORBIDDEN_MODES = frozenset({"bypassPermissions", "auto", "dontAsk"})

#: 쓸 수 있는 권한 모드. `default` 는 플래그의 choices 목록에 없지만 실측에서
#: 오류 없이 돌았고 훅 덤프의 `permission_mode` 가 `"default"` 였다.
ALLOWED_MODES = frozenset({"default", "manual", "acceptEdits", "plan"})

#: 환경에서 반드시 지우는 것 (구독으로만 돈다)
ENV_STRIP = ("ANTHROPIC_API_KEY", "ANTHROPIC_AUTH_TOKEN", "ANTHROPIC_BASE_URL")

#: 훅이 "헤드리스" 를 아는 유일한 길. stdin 으로는 구분할 수 없다.
HEADLESS_ENV = "LABREMOTE_HEADLESS"

#: 물려주는 환경. 나머지는 지운다.
ENV_KEEP = (
    "HOME", "USER", "LOGNAME", "SHELL", "LANG", "LC_ALL", "TZ", "TERM", "PATH",
    "XDG_RUNTIME_DIR", "XDG_CONFIG_HOME", "SSH_AUTH_SOCK",
)

#: 헤드리스에서 끄는 도구. 서브에이전트는 ①에서 가장 성가셨고 루프에 필요 없다.
DISALLOWED_TOOLS = ("Task",)

#: 전부 막혀서 루프가 한 발짝도 못 나가는 조합
MANUAL_PRESET = "manual"


class LaunchRefused(RuntimeError):
    """띄우면 안 되는 조합. **띄우지 않고 사람에게 알린다.**"""


@dataclass
class AgentRun:
    """한 번의 `claude -p` 호출에 필요한 것 전부."""

    project: str
    root: str
    prompt: str
    session_id: str
    #: 정책에서 읽은 권한 모드
    permission_mode: str = "default"
    headless: bool = True
    resume: bool = False
    extra_flags: list[str] = field(default_factory=list)
    binary: str = "claude"
    output_format: str = "json"


def check_flags(flags) -> None:
    """금지 플래그가 섞였는지. 섞였으면 `LaunchRefused`.

    `--setting-sources=user` 처럼 `=` 로 붙여 쓰는 꼴도 잡는다.
    """
    for raw in flags or []:
        head = str(raw).split("=", 1)[0].strip()
        if head in FORBIDDEN_FLAGS:
            raise LaunchRefused(
                f"{head} 는 쓸 수 없어요 — 훅(권한 잠금)이 꺼져요. "
                "이 플래그를 쓰면 잠긴 항목이 막히지 않아요."
            )


def check_mode(mode: str, *, preset: str = "", headless: bool = True) -> str:
    """권한 모드를 검사해 돌려준다."""
    value = str(mode or "").strip() or "default"
    if value in FORBIDDEN_MODES:
        raise LaunchRefused(
            f"권한 모드 {value!r} 로는 띄우지 않아요 — 승인 경로가 사라져요. "
            f"쓸 수 있는 것: {', '.join(sorted(ALLOWED_MODES))}"
        )
    if value not in ALLOWED_MODES:
        raise LaunchRefused(
            f"모르는 권한 모드예요: {value!r} · 쓸 수 있는 것: "
            f"{', '.join(sorted(ALLOWED_MODES))}"
        )
    if headless and preset == MANUAL_PRESET:
        # 수동제어는 code·hparam 까지 전부 ask 다. 헤드리스에서는 전부 거절돼
        # 루프가 한 발짝도 못 나간다.
        raise LaunchRefused(
            "수동제어 프리셋에서는 헤드리스 루프를 띄우지 않아요 — 모든 행동이 "
            "승인 대기로 떨어져서 한 발짝도 못 나가요. 권한 단계를 올리거나 "
            "직접 터미널에서 돌려 주세요."
        )
    return value


def build_argv(run: AgentRun) -> list[str]:
    """실제로 `Popen` 에 넘길 argv."""
    check_flags(run.extra_flags)
    mode = check_mode(run.permission_mode, headless=run.headless)
    if not run.session_id:
        raise LaunchRefused("세션 ID 가 없어요 — 승인 뒤 이어 가려면 미리 정해야 해요.")

    argv = [run.binary, "-p"]
    if run.resume:
        # **`--fork-session` 은 쓰지 않는다** — 세션 ID 가 바뀌면 재시도 상한
        # 추적이 끊긴다.
        argv += ["--resume", run.session_id]
    else:
        argv += ["--session-id", run.session_id]
    argv += ["--permission-mode", mode]
    if run.headless:
        # 훅이 못 보는 MCP 승인창까지 닫는 안전망
        argv += ["--permission-prompts", "none"]
        for tool in DISALLOWED_TOOLS:
            argv += ["--disallowedTools", tool]
    if run.output_format:
        argv += ["--output-format", run.output_format]
    argv += list(run.extra_flags)
    argv.append(run.prompt)
    return argv


def build_env(run: AgentRun, *, base: dict | None = None) -> dict[str, str]:
    """`claude` 가 받을 환경.

    `ANTHROPIC_API_KEY` 를 **지운다.** 키가 섞이면 구독이 아니라 종량제로
    과금된다. systemd 유닛에도 넣지 않고, 여기서 한 번 더 지우고,
    `doctor` 가 설정돼 있으면 경고한다.
    """
    source = os.environ if base is None else base
    out = {k: source[k] for k in ENV_KEEP if k in source}
    if run.headless:
        out[HEADLESS_ENV] = "1"
    for name in ENV_STRIP:
        out.pop(name, None)
    return out


def check_cwd(run: AgentRun) -> str:
    """작업 디렉터리는 **등록된 프로젝트 루트**여야 한다.

    래퍼가 `cwd` 로만 판정하므로 그 밖에서 띄우면 훅이 아예 안 뜬다.
    """
    root = paths.real(run.root or (registry.root_of(run.project) or ""))
    if not root or not os.path.isdir(root):
        raise LaunchRefused(f"프로젝트 폴더가 없어요: {run.root!r}")
    found = registry.lookup(root)
    if not found or found[1] != run.project:
        raise LaunchRefused(
            f"등록된 실험 프로젝트가 아니에요: {root} · "
            "여기서 띄우면 권한 훅이 뜨지 않아요."
        )
    return root


def plan(run: AgentRun, *, preset: str = "", base_env: dict | None = None) -> dict:
    """띄우기 직전 한 덩어리. 검사를 **전부** 통과해야 나온다."""
    check_mode(run.permission_mode, preset=preset, headless=run.headless)
    root = check_cwd(run)
    return {
        "argv": build_argv(run),
        "env": build_env(run, base=base_env),
        "cwd": root,
        "sessionId": run.session_id,
    }
