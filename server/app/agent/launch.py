"""`claude -p` 인자 조립 — **보안 경계다.**

②가 ①의 경계를 약하게 만들 수 있는 자리는 여기뿐이다. 플래그 한 줄이면 훅이
통째로 사라진다 (`claude --help` 원문):

| 플래그 | 무엇 | 결과 |
|---|---|---|
| `--bare` | *"Minimal mode: **skip hooks**"* | 잠금 전부 사라짐 |
| `--safe-mode` | *"all customizations (… hooks …) disabled"* | 같음 |
| `--setting-sources` | user 를 빼면 `~/.claude/settings.json` 을 안 읽음 | 훅 등록이 거기 있음. **값만 검사**한다 — 우리는 `user` 로 써야 한다 |
| `--restricted` | 설정 파일 무시 | 훅 등록 무시 |
| `--dangerously-skip-permissions` | 권한 검사 우회 | 훅이 뜨는지 미확인 |
| `--permission-mode bypassPermissions`·`auto`·`dontAsk` | 승인 경로 소실 | `auto` 는 ①에서 사고가 난 모드 |

그래서 **허용 목록**으로 간다 — 아는 플래그만 넣고, 금지 플래그가 섞이면
`LaunchRefused` 로 띄우지 않는다.

### 반대로 **반드시 붙이는** 플래그 셋 (M6 실측)

프로젝트 `.claude/settings.json` 은 AI 가 쓴 코드가 고칠 수 있다(M4). 실측에서
거기에 심은 훅이 **샌드박스 밖에서 사용자 권한으로 돌았고**,
`sandbox.enabled:false` 한 줄로 샌드박스가 꺼져 AI 코드가
`server/data/runstate/` 에 실제로 썼다. 그래서 그 파일을 **아예 안 읽는다.**

    --setting-sources user      프로젝트·local 설정을 안 읽음
    --settings <data>/agent/headless-settings.json   우리가 정한 샌드박스
    --strict-mcp-config         프로젝트 `.mcp.json` 을 안 읽음

세 개는 `build_argv` 가 **항상** 붙인다 — 헤드리스든 대화형이든.

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
    "check_setting_sources",
    "check_settings_file",
    "SETTING_SOURCES",
    "build_argv",
    "build_env",
    "check_sandbox",
    "render_settings",
    "plan",
]

#: 훅을 끄거나 경계를 넓히는 플래그. **하나라도 있으면 안 띄운다.**
#:
#: `--setting-sources` 는 여기 **없다** — 우리가 `--setting-sources user` 로
#: 써야 한다(M6). 값을 따로 검사한다(`check_setting_sources`).
FORBIDDEN_FLAGS = frozenset(
    {
        "--bare",
        "--safe-mode",
        "--restricted",
        "--dangerously-skip-permissions",
        "--no-hooks",
        "--disable-hooks",
        # MCP 는 `--strict-mcp-config` 만 쓴다. 서버를 더하면 훅이 못 보는
        # 도구가 생긴다 (M6d 에서 프로젝트 `.mcp.json` 의 서버가 실제로 떴다).
        "--mcp-config",
        # 작업 디렉터리를 넓히면 "폴더 밖 쓰기" 의 기준이 넓어진다.
        "--add-dir",
        # 도구 화이트리스트는 경로·명령 기반 판정과 축이 달라 진실이 둘이 된다.
        "--tools",
        "--allowedTools",
        # 플러그인·서브에이전트·시스템 프롬프트로 지침을 갈아끼우는 길
        "--plugin-dir",
        "--agents",
        "--system-prompt",
        "--system-prompt-file",
        "--append-system-prompt",
    }
)

#: 우리가 항상 넘기는 설정 출처. `project`·`local` 을 빼는 것이 요점이다 —
#: 프로젝트 `.claude/settings.json` 에 훅·`sandbox.enabled:false`·
#: `permissions.allow` 를 써 넣는 길을 닫는다 (M6a·M6b·M6c).
SETTING_SOURCES = "user"

#: `--setting-sources` 에 올 수 있는 값
SETTING_SOURCE_NAMES = frozenset({"user", "project", "local"})

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

#: 대화형(`labremote claude`)에 더 물려주는 것. 사람이 쓰는 터미널이라
#: 색·입력기·클립보드가 죽으면 쓸 수 없다. **`ANTHROPIC_*` 는 여전히 지운다.**
ENV_KEEP_INTERACTIVE = ENV_KEEP + (
    "COLORTERM", "TERM_PROGRAM", "DISPLAY", "WAYLAND_DISPLAY", "XAUTHORITY",
    "DBUS_SESSION_BUS_ADDRESS", "XDG_SESSION_TYPE", "XDG_DATA_DIRS",
    "LC_CTYPE", "LINES", "COLUMNS", "EDITOR", "PAGER", "GIT_EDITOR",
    "SSH_CONNECTION", "SSH_TTY", "NO_COLOR", "FORCE_COLOR",
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
    #: 공용 캐시. 샌드박스 안에서 `/tmp` 는 **읽기 전용**이라(실측) 임시
    #: 파일을 여기로 돌린다.
    cache_dir: str = ""
    resume: bool = False
    extra_flags: list[str] = field(default_factory=list)
    binary: str = "claude"
    output_format: str = "json"
    #: `--settings` 로 넘길 파일. 비어 있으면 `policy.launch_settings_path()`.
    settings_path: str = ""
    #: 사람이 쓰는 대화형 세션(`labremote claude`). 헤드리스 전용 플래그를
    #: 빼고 프롬프트도 붙이지 않는다. 경계 플래그 셋은 **그대로** 붙는다.
    interactive: bool = False


def check_setting_sources(value: str) -> str:
    """`--setting-sources` 의 **값**을 검사한다.

    `user` 가 빠지면 `~/.claude/settings.json` 을 안 읽고, **훅 등록이 거기
    있다** — 잠금이 통째로 사라진다. 그래서 `user` 없는 값만 거부한다.
    """
    items = [s.strip() for s in str(value or "").split(",") if s.strip()]
    if not items:
        raise LaunchRefused("--setting-sources 가 비어 있어요")
    unknown = sorted(set(items) - SETTING_SOURCE_NAMES)
    if unknown:
        raise LaunchRefused(
            f"--setting-sources 에 모르는 값이 있어요: {', '.join(unknown)} · "
            f"쓸 수 있는 것: {', '.join(sorted(SETTING_SOURCE_NAMES))}"
        )
    if "user" not in items:
        raise LaunchRefused(
            "--setting-sources 에 user 가 없으면 훅 등록을 안 읽어요 "
            "(~/.claude/settings.json) — 잠금이 전부 사라져요."
        )
    return ",".join(items)


def check_settings_file(value: str) -> str:
    """`--settings` 로 넘기는 파일이 **우리 것**인지.

    AI 가 쓴 코드가 프로젝트 안에 설정 파일을 만들어 두고 그걸 `--settings`
    로 넘기게 만드는 길을 닫는다. 우리 파일은 `server/data/agent/` 아래이고,
    샌드박스 안에서 그 폴더 쓰기가 실패한다(M1b).
    """
    from .. import policy as policy_mod

    expected = policy_mod.launch_settings_path()
    given = paths.real(str(value or ""))
    if given != expected:
        raise LaunchRefused(
            f"--settings 는 {expected} 만 쓸 수 있어요 (받은 값: {value!r}) — "
            "AI 가 고칠 수 있는 파일을 설정으로 넘기면 경계가 무의미해져요."
        )
    return given


def check_flags(flags) -> None:
    """금지 플래그가 섞였는지. 섞였으면 `LaunchRefused`.

    `--setting-sources=user` 처럼 `=` 로 붙여 쓰는 꼴도 잡고, 값이 있는
    두 플래그(`--setting-sources`·`--settings`)는 **값까지** 본다.
    """
    items = [str(x) for x in (flags or [])]
    for index, raw in enumerate(items):
        head, _, inline = raw.partition("=")
        head = head.strip()
        if head in FORBIDDEN_FLAGS:
            raise LaunchRefused(
                f"{head} 는 쓸 수 없어요 — 훅(권한 잠금)이 꺼지거나 경계가 넓어져요."
            )
        if head in ("--setting-sources", "--settings"):
            value = inline if inline else (items[index + 1] if index + 1 < len(items) else "")
            if head == "--setting-sources":
                check_setting_sources(value)
            else:
                check_settings_file(value)


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
    from .. import policy as policy_mod

    check_flags(run.extra_flags)
    mode = check_mode(run.permission_mode, headless=run.headless)
    if not run.settings_path:
        run.settings_path = policy_mod.launch_settings_path()
    if not run.session_id:
        raise LaunchRefused("세션 ID 가 없어요 — 승인 뒤 이어 가려면 미리 정해야 해요.")

    argv = [run.binary]
    if not run.interactive:
        argv.append("-p")
    if run.resume:
        # **`--fork-session` 은 쓰지 않는다** — 세션 ID 가 바뀌면 재시도 상한
        # 추적이 끊긴다.
        argv += ["--resume", run.session_id]
    elif not run.interactive:
        argv += ["--session-id", run.session_id]

    # 🔑 경계 플래그 셋. **헤드리스와 대화형이 똑같이** 붙는다 (M6).
    #   --setting-sources user  : 프로젝트 `.claude/settings.json` 을 안 읽는다
    #   --settings <우리 파일>   : 샌드박스·바깥 차단을 우리가 정한다
    #   --strict-mcp-config     : 프로젝트 `.mcp.json` 을 안 읽는다
    argv += ["--setting-sources", SETTING_SOURCES]
    argv += ["--settings", check_settings_file(run.settings_path)]
    argv.append("--strict-mcp-config")

    argv += ["--permission-mode", mode]
    if run.headless and not run.interactive:
        # 훅이 못 보는 MCP 승인창까지 닫는 안전망
        argv += ["--permission-prompts", "none"]
        for tool in DISALLOWED_TOOLS:
            argv += ["--disallowedTools", tool]
        if run.output_format:
            argv += ["--output-format", run.output_format]
    argv += list(run.extra_flags)
    if not run.interactive:
        argv.append(run.prompt)
    return argv


def build_env(run: AgentRun, *, base: dict | None = None) -> dict[str, str]:
    """`claude` 가 받을 환경.

    `ANTHROPIC_API_KEY` 를 **지운다.** 키가 섞이면 구독이 아니라 종량제로
    과금된다. systemd 유닛에도 넣지 않고, 여기서 한 번 더 지우고,
    `doctor` 가 설정돼 있으면 경고한다.
    """
    source = os.environ if base is None else base
    keep = ENV_KEEP_INTERACTIVE if run.interactive else ENV_KEEP
    out = {k: source[k] for k in keep if k in source}
    if run.cache_dir:
        # 샌드박스 안에서 `/tmp` 는 읽기 전용이다 (실측). 캐시 아래로 돌린다.
        out["TMPDIR"] = os.path.join(run.cache_dir, "tmp")
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


def check_sandbox(root: str, *, headless: bool = True) -> dict:
    """Claude Bash 샌드박스가 **실제로** 켜져 있나. 헤드리스면 안 켜져 있을 때 거부.

    설정 파일을 매번 읽는다 — "한 번 켰으니 켜져 있겠지" 가 아니라 **지금**
    켜져 있는지를 본다. 꺼진 채로 헤드리스를 돌리면 AI 가 쓴 테스트 코드가
    `~/.ssh` 를 읽고 네트워크로 보낼 수 있다 (실측).
    """
    from .. import policy as policy_mod

    state = policy_mod.sandbox_state(root)
    if headless and not state["ok"]:
        raise LaunchRefused(
            "Claude Bash 샌드박스가 켜져 있지 않아요 — 헤드리스로 띄우지 않아요: "
            + " · ".join(state["reasons"])
            + f" · {policy_mod.launch_settings_path()} 를 "
            "labremote hooks install 로 다시 써 주세요."
        )
    return state


def render_settings(root: str, *, project: str = "") -> str:
    """`--settings` 로 넘길 파일을 **지금 코드대로 다시 쓰고** 경로를 돌려준다.

    디스크에 있는 걸 믿지 않는다. 캐시·conda 경로가 기계마다 달라서 정적
    파일로는 못 쓴다.
    """
    from .. import policy as policy_mod

    cache_dir = ""
    conda_roots: list[str] = []
    try:
        from ..runner import cache as cache_mod
        from ..runner import sandbox as sandbox_mod

        pol = policy_mod.load(project) if project else None
        cache_dir = cache_mod.cache_dir(pol)
        conda_roots = sandbox_mod.conda_roots()
    except Exception:
        # 못 찾아도 샌드박스는 켠다 — `doctor` 가 allowRead 가 비었다고 알린다.
        pass
    return policy_mod.render_launch_settings(
        root, cache_dir=cache_dir, conda_roots=conda_roots
    )["path"]


def plan(run: AgentRun, *, preset: str = "", base_env: dict | None = None) -> dict:
    """띄우기 직전 한 덩어리. 검사를 **전부** 통과해야 나온다.

    순서가 중요하다 — `--settings` 파일을 **먼저 다시 쓰고** 그 다음에
    샌드박스 상태를 본다. 그래야 "디스크에 오래된 설정이 있었다" 가 없다.
    """
    check_mode(run.permission_mode, preset=preset, headless=run.headless)
    root = check_cwd(run)
    run.settings_path = render_settings(root, project=run.project)
    sandbox = check_sandbox(root, headless=run.headless)
    return {
        "argv": build_argv(run),
        "env": build_env(run, base=base_env),
        "cwd": root,
        "sessionId": run.session_id,
        "settings": run.settings_path,
        "sandbox": sandbox,
    }
