"""정책 파일 읽기·쓰기와 권한 판정.

정책 파일은 **프로젝트 밖**(`server/data/policies/<이름>.json`)에 있다.
AI 가 `Edit` 한 번으로 `block` 을 `allow` 로 바꾸지 못하게 하는 게 목적이고,
그 경로 자체가 "프로젝트 폴더 밖" 이라 잠긴 항목 ①에 자동으로 걸린다.

판정의 원칙은 **fail-closed** 다. 파일이 없거나 깨졌거나 판이 다르면
`PolicyError` 를 던지고, 훅은 그걸 받아 deny + 사유로 끝낸다.

표준 라이브러리만 쓴다 (훅 경로에서 import 된다).
"""

from __future__ import annotations

import json
import os
import shutil
from datetime import datetime

from . import paths
from . import policy_defaults as D
from . import registry

__all__ = [
    "PolicyError",
    "Policy",
    "load",
    "ensure",
    "save",
    "template_path",
    "render_template",
    "write_template",
    "seed_default",
    "migrate",
    "conflicting_writable_roots",
    "claude_settings_path",
    "ensure_permission_mode",
]


class PolicyError(RuntimeError):
    """정책을 신뢰할 수 없을 때. 받는 쪽은 반드시 deny 로 끝내야 한다."""


def template_path() -> str:
    """커밋되는 기본 템플릿. `server/data/` 는 gitignore 라 여기 둔다."""
    return os.path.join(os.path.dirname(os.path.abspath(__file__)), "templates", "policy.default.json")


def render_template() -> dict:
    """커밋되는 템플릿의 내용. `policy_defaults` 가 단일 출처다.

    결정론적이어야 한다 (`updatedAt` 을 비운다) — 그래야
    tests/test_policy.py 가 디스크의 파일과 코드를 대조할 수 있다.
    """
    data = D.default_policy()
    data["updatedAt"] = ""
    data["updatedBy"] = "template"
    return data


def write_template() -> str:
    """템플릿 파일을 코드에서 다시 만든다 (`labremote policy sync-template`)."""
    registry.write_json(template_path(), render_template())
    return template_path()


def seed_default() -> str:
    """`server/data/policy.default.json` 이 없으면 템플릿에서 복사한다."""
    dst = os.path.join(registry.data_dir(), "policy.default.json")
    if not os.path.exists(dst):
        os.makedirs(os.path.dirname(dst), exist_ok=True)
        shutil.copyfile(template_path(), dst)
    return dst


class Policy:
    """정책 파일 하나. 훅이 도구 호출마다 새로 읽는다."""

    def __init__(self, name: str, data: dict, path: str) -> None:
        self.name = name
        self.data = data
        self.path = path

    # --- 읽기 ---------------------------------------------------------------

    @property
    def root(self) -> str:
        return str((self.data.get("project") or {}).get("root") or "")

    @property
    def paths(self) -> dict:
        return self.data.get("paths") or {}

    @property
    def bash(self) -> dict:
        return self.data.get("bash") or {}

    @property
    def headless(self) -> dict:
        return self.data.get("headless") or {}

    @property
    def runner(self) -> dict:
        """실행기 설정. 옛 판에는 없어서 빈 dict 로 떨어진다."""
        return self.data.get("runner") or {}

    @property
    def locks(self) -> dict:
        return self.data.get("locks") or {}

    @property
    def internal_actions(self) -> dict:
        return self.data.get("internalActions") or {}

    @property
    def saved(self) -> dict | None:
        value = self.data.get("saved")
        return value if isinstance(value, dict) else None

    def effective_mode(self) -> str:
        """저장해 둔 프리셋이 있으면 그걸, 없으면 기본 프리셋."""
        saved = self.saved
        mode = (saved or {}).get("mode") or self.data.get("defaultMode")
        if mode not in D.MODE_IDS:
            raise PolicyError(f"정책의 프리셋 값이 이상해요: {mode!r}")
        return str(mode)

    def overrides(self) -> dict[str, str]:
        raw = (self.saved or {}).get("overrides")
        return {str(k): str(v) for k, v in raw.items()} if isinstance(raw, dict) else {}

    def action(self, key: str) -> dict:
        for item in self.data.get("actions") or []:
            if item.get("key") == key:
                return item
        raise PolicyError(f"정책에 없는 행동 유형이에요: {key!r}")

    def action_name(self, key: str) -> str:
        """승인 로그의 `action` 칸에 쓰는 한국어 이름."""
        return str(self.action(key).get("name") or key)

    def resolve(self, key: str) -> str:
        """행동 유형의 최종 권한. `allow` / `ask` / `block`.

        잠긴 항목은 `overrides` 로 뚫리지 않는다.
        """
        action = self.action(key)
        mode = self.effective_mode()
        defaults = action.get("defaults") or {}
        base = defaults.get(mode)

        if action.get("locked"):
            if base not in D.PERMISSIONS:
                raise PolicyError(f"잠긴 항목 {key!r} 의 기본값이 이상해요: {base!r}")
            return str(base)

        override = self.overrides().get(key)
        if override in D.PERMISSIONS:
            return str(override)
        if base not in D.PERMISSIONS:
            raise PolicyError(f"{key!r}/{mode!r} 의 기본값이 이상해요: {base!r}")
        return str(base)

    def is_locked(self, key: str) -> bool:
        return bool(self.action(key).get("locked"))

    # --- 쓰기 ---------------------------------------------------------------

    def set_saved(self, mode: str, overrides: dict[str, str] | None = None) -> None:
        """웹 UI 의 "변경 사항 저장". 실행 중 실험에는 적용되지 않는다 —
        훅이 매 호출마다 파일을 새로 읽으므로 다음 작업부터 반영된다.
        """
        if mode not in D.MODE_IDS:
            raise PolicyError(f"모르는 프리셋이에요: {mode!r}")
        clean: dict[str, str] = {}
        for key, value in (overrides or {}).items():
            if key not in D.ACTION_KEYS:
                raise PolicyError(f"모르는 행동 유형이에요: {key!r}")
            if value not in D.PERMISSIONS:
                raise PolicyError(f"모르는 권한 값이에요: {value!r}")
            if self.is_locked(key):
                # 조용히 버리지 않고 알려 준다. 잠긴 항목은 UI 에서도 비활성이다.
                raise PolicyError(f"잠긴 항목은 바꿀 수 없어요: {key!r}")
            clean[key] = value
        self.data["saved"] = {"mode": mode, "overrides": clean}
        self.data["updatedAt"] = datetime.now().astimezone().isoformat(timespec="seconds")
        self.data["updatedBy"] = "user"


def _validate(name: str, data, path: str) -> Policy:
    if not isinstance(data, dict):
        raise PolicyError(f"정책 파일이 JSON 객체가 아니에요: {path}")

    version = data.get("version")
    if version != D.POLICY_VERSION:
        raise PolicyError(
            f"정책 파일의 판이 맞지 않아요 (파일 {version!r}, 프로그램 {D.POLICY_VERSION}): {path}"
        )

    keys = [a.get("key") for a in (data.get("actions") or [])]
    missing = [k for k in D.ACTION_KEYS if k not in keys]
    if missing:
        raise PolicyError(f"정책에 빠진 행동 유형이 있어요: {', '.join(missing)} · {path}")

    mode_ids = [m.get("id") for m in (data.get("modes") or [])]
    if [m for m in D.MODE_IDS if m not in mode_ids]:
        raise PolicyError(f"정책에 빠진 프리셋이 있어요: {path}")

    for key in D.LOCKED_KEYS:
        action = next(a for a in data["actions"] if a.get("key") == key)
        if not action.get("locked"):
            raise PolicyError(f"잠긴 항목이 풀려 있어요: {key!r} · {path}")

    policy = Policy(name, data, path)
    policy.effective_mode()  # 프리셋 값 검사
    for key in D.ACTION_KEYS:
        policy.resolve(key)  # 9개 전부 판정이 되는지
    return policy


def load(name: str) -> Policy:
    """정책 파일을 읽어 검사까지 한다. 못 믿을 상태면 `PolicyError`.

    이름이 규칙에 안 맞는 경우도 `PolicyError` 로 바꿔 던진다 — 훅은
    한 종류의 예외만 잡고 deny 로 끝낼 수 있어야 한다.
    """
    try:
        path = registry.policy_path(name)
    except registry.InvalidName as exc:
        raise PolicyError(str(exc)) from None
    try:
        with open(path, encoding="utf-8") as fh:
            data = json.load(fh)
    except FileNotFoundError:
        raise PolicyError(
            f"정책 파일이 없어요: {path} · labremote init-project 로 만들었는지 확인해 주세요."
        ) from None
    except json.JSONDecodeError as exc:
        raise PolicyError(f"정책 파일을 읽을 수 없어요 ({exc.lineno}행): {path}") from None
    except OSError as exc:
        raise PolicyError(f"정책 파일을 열 수 없어요: {path} · {exc}") from None
    return _validate(name, data, path)


def save(policy: Policy) -> None:
    bad = conflicting_writable_roots(policy)
    if bad:
        raise PolicyError(
            "extraWritableRoots 에 서버 보호 경로가 들어 있어 저장하지 않았어요: "
            + ", ".join(bad)
            + " · 이 경로는 어떤 설정에서도 막히니 목록에서 빼 주세요."
        )
    registry.write_json(policy.path, policy.data)


def conflicting_writable_roots(policy: Policy) -> list[str]:
    """`extraWritableRoots` 중 보호 목록과 겹치는 것.

    판정은 보호 목록이 먼저라 겹쳐도 뚫리지 않는다. 그래도 조용히 두면
    설정한 사람이 "열렸다" 고 오해하므로 `doctor` 가 알리고 `policy set` 이
    저장을 거부한다.
    """
    protected = [paths.real(p) for p in D.hard_protected_roots()]
    bad = []
    for item in (policy.paths.get("extraWritableRoots") or []):
        if not item:
            continue
        target = paths.real(str(item))
        # 어느 쪽이 상위든 겹치는 것이다
        if any(
            paths.is_inside(p, target) or paths.is_inside(target, p) for p in protected
        ):
            bad.append(str(item))
    return bad


# --- 프로젝트 쪽 권한 모드 ---------------------------------------------------


def claude_settings_path(root: str) -> str:
    return os.path.join(root, ".claude", "settings.json")


#: Claude 의 Bash 가 바깥으로 나갈 수 있는 곳. **프록시 허용 목록**이다 —
#: 생 DNS 는 막히고(유출 차단) 여기 적힌 도메인만 HTTPS 로 나간다 (실측).
#: [더 필요한 도메인 — 정책의 paths.sandboxDomains 에 적어 주세요]
SANDBOX_DOMAINS = (
    "pypi.org",
    "files.pythonhosted.org",
    "huggingface.co",
    "cdn-lfs.huggingface.co",
    "cdn-lfs-us-1.hf.co",
    "github.com",
    "codeload.github.com",
    "raw.githubusercontent.com",
    "objects.githubusercontent.com",
    "repo.anaconda.com",
    "conda.anaconda.org",
)


#: 런처가 `--settings` 로 넘기는 파일. **`server/data/` 아래**다 — 샌드박스
#: 안에서 그 폴더 쓰기가 실패하는 것을 실측(M1b)으로 확인했으므로 AI 가 쓴
#: 코드가 이 파일을 고칠 수 없다.
LAUNCH_SETTINGS_NAME = "headless-settings.json"


def launch_settings_path() -> str:
    """`<data>/agent/headless-settings.json`."""
    return os.path.join(registry.data_dir(), "agent", LAUNCH_SETTINGS_NAME)


def sandbox_block(root: str, *, cache_dir: str = "", conda_roots=(), domains=()) -> dict:
    """런처가 `--settings` 로 넘기는 `sandbox` 절. 실측으로 정한 값이다.

    | 칸 | 값 | 왜 |
    |---|---|---|
    | `enabled` | true | AI 가 쓴 **코드**(`pytest`·`python`)를 가두는 유일한 수단 |
    | `failIfUnavailable` | true | 기본이 `false` 라 못 쓰면 경고만 내고 **그냥 돈다** |
    | `autoAllowBashIfSandboxed` | **false** | 기본이 `true` 다. 안 끄면 Bash 가 자동 허용돼 게이트가 무의미해진다 |
    | `filesystem.allowWrite` | **공용 캐시만** | 작업 폴더는 이미 쓰기 가능하다(M4). 부모(`~/projects`)를 넣으면 **다른 프로젝트까지** 열린다 |
    | `filesystem.allowRead` | conda 설치 폴더 | **없으면 `python`·`pytest` 가 exit 127 이다** (M3) |
    | `network.allowedDomains` | pypi·HF·github… | 생 DNS 는 막히고 이 도메인만 프록시로 나간다 |

    실측으로 확정된 전제 셋 (`docs/operations.md` 의 S1·M6):

    - **훅은 샌드박스 밖에서 돈다**(M1). 그래서 `server/data/` 를 `allowWrite`
      에 넣지 않는다 — 넣으면 AI 가 쓴 코드가 `runstate`·`grants` 를 고쳐
      `stop`·`prev` 잠금을 풀 수 있다.
    - **작업 디렉터리는 언제나 쓰기 가능하고 좁힐 수 없다**(M4). `denyWrite`
      키는 없다. 그래서 프로젝트 안 보호 파일은 이 절로 못 지킨다 —
      훅(도구 호출) · 학습 bwrap(`--ro-bind`) · 감사 체계가 맡는다.
    - **이 절은 프로젝트 설정에서 안 먹는다**(M3). `--settings` 파일에 둬야
      `filesystem` 이 먹는다. 사용자 설정에는 **쓰지 않는다**(규칙 0).

    `denyRead` 는 따로 적지 않는다 — 허용한 것 말고는 애초에 안 보인다(실측:
    `~/.ssh`·`~/.claude.json`·정책 파일 전부 `FileNotFoundError`).
    """
    # 작업 디렉터리는 `allowWrite` 와 무관하게 **언제나** 쓰기 가능하다(M4).
    # 그래서 프로젝트 루트를 적지 않는다 — 적어도 달라지는 게 없고, 부모
    # 폴더를 적으면 다른 실험 프로젝트까지 열린다. 캐시만 더한다.
    write = []
    if cache_dir:
        write.append(paths.real(cache_dir))
    read = [paths.real(item) for item in conda_roots if item]
    return {
        "enabled": True,
        "failIfUnavailable": True,
        "autoAllowBashIfSandboxed": False,
        "allowUnsandboxedCommands": False,
        "excludedCommands": [],
        "filesystem": {
            "allowWrite": sorted(dict.fromkeys(write)),
            "allowRead": sorted(dict.fromkeys(read)),
        },
        "network": {"allowedDomains": sorted(dict.fromkeys(list(domains) or list(SANDBOX_DOMAINS)))},
    }


def sandbox_state(root: str) -> dict:
    """지금 **실제로 적용되는** `sandbox` 절이 기대대로인가.

    런처가 매 실행 전에 보고, 아니면 헤드리스 루프를 띄우지 않는다
    (fail-closed). 훅도 이걸 보고 `pytest` 같은 코드 실행을 열지 말지 정한다.

    보는 순서가 **곧 적용 순서**다 (M3·M6 실측).

    | # | 어디 | 누가 쓰나 |
    |---|---|---|
    | 1 | `<data>/agent/headless-settings.json` | 런처가 `--settings` 로 넘긴다. **헤드리스와 `labremote claude` 가 쓰는 것** |
    | 2 | 프로젝트 `.claude/settings.json` | 맨손 `claude` 로 열 때만 읽힌다. `filesystem` 은 **안 먹는다**(M3) |
    | 3 | 사용자 `~/.claude/settings.json` | 우리 코드는 여기에 **쓰지 않는다**(규칙 0). 사람이 넣었으면 기계 전체에 걸린다 |

    표준 라이브러리만 쓴다 — 훅 경로에서 불린다.
    """
    out = {
        "ok": False, "reasons": [], "notes": [], "allowWrite": [], "allowRead": [],
        "domains": [], "source": "",
    }
    block = None
    sources = (
        ("launch", launch_settings_path()),
        ("project", claude_settings_path(root)),
        ("user", user_settings_path()),
    )
    for label, path in sources:
        try:
            with open(path, encoding="utf-8") as fh:
                data = json.load(fh)
        except (FileNotFoundError, json.JSONDecodeError, OSError):
            continue
        if isinstance(data, dict) and isinstance(data.get("sandbox"), dict):
            block, out["source"] = data["sandbox"], label
            break
    if block is None:
        out["reasons"].append(
            "sandbox 설정이 없어요 — labremote hooks install 로 "
            f"{launch_settings_path()} 를 다시 써 주세요"
        )
        return out
    if out["source"] == "project":
        # M3: 프로젝트 설정의 `filesystem` 은 무시된다. 켜진 것처럼 보여도
        # conda 가 안 보이고 캐시 쓰기가 버려진다.
        out["reasons"].append(
            "sandbox 가 프로젝트 설정에만 있어요 — filesystem 이 안 먹어요(실측 M3)"
        )

    if block.get("enabled") is not True:
        out["reasons"].append("sandbox.enabled 가 켜져 있지 않아요")
    if block.get("failIfUnavailable") is not True:
        # 기본이 false 다. 그대로 두면 샌드박스를 못 쓸 때 경고만 내고 그냥 돈다.
        out["reasons"].append("sandbox.failIfUnavailable 이 켜져 있지 않아요")
    if block.get("autoAllowBashIfSandboxed") is not False:
        # 기본이 true 다. 안 끄면 Bash 가 자동 허용돼 승인 게이트가 무의미해진다.
        out["reasons"].append("sandbox.autoAllowBashIfSandboxed 를 꺼야 해요")
    if block.get("allowUnsandboxedCommands"):
        out["reasons"].append("sandbox.allowUnsandboxedCommands 가 켜져 있어요")
    excluded = block.get("excludedCommands") or []
    if excluded:
        out["reasons"].append(f"sandbox.excludedCommands 가 비어 있지 않아요: {excluded}")

    filesystem = block.get("filesystem") if isinstance(block.get("filesystem"), dict) else {}
    out["allowWrite"] = list(filesystem.get("allowWrite") or [])
    out["allowRead"] = list(filesystem.get("allowRead") or [])
    out["domains"] = list((block.get("network") or {}).get("allowedDomains") or [])
    # allowWrite 에 **넓은 곳**이 들어 있으면 거부한다. 작업 폴더는 어차피
    # 열려 있으니(M4) 여기 적힌 것은 전부 "프로젝트 밖에 추가로 여는 곳" 이다.
    #
    # | 대상 | 어떤 방향이 위험한가 |
    # |---|---|
    # | `~/projects`·`server/data`·`server/` | **양방향.** 안이면 다른 프로젝트·정책·허가·runstate 가 열리고, 밖이면 그걸 포함한다 |
    # | 홈·`/` | **포함하는 방향만.** 캐시가 `~/lab-cache` 라 "홈 안" 은 정상이다 |
    target = paths.real(root)
    home = paths.real("~")
    server_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    both_ways = [registry.projects_root(), registry.data_dir(), server_dir]
    contains_only = [home, os.sep]
    for item in out["allowWrite"]:
        real = paths.real(item)
        if not real or real == target or paths.is_inside(target, real):
            continue  # 프로젝트 안 — 어차피 열려 있다
        hit = next(
            (
                bad
                for bad in both_ways
                if bad and (paths.is_inside(bad, real) or paths.is_inside(real, bad))
            ),
            None,
        ) or next(
            (bad for bad in contains_only if bad and paths.is_inside(real, bad)),
            None,
        )
        if hit:
            out["reasons"].append(
                f"allowWrite 가 너무 넓어요: {item} ({hit} 과 겹쳐요)"
            )
    if not out["allowRead"]:
        # 막는 사유는 아니다 — 켜져 있긴 하다. 다만 conda 가 안 보여
        # `python`·`pytest` 가 exit 127 이 된다 (M3). `doctor` 가 ⚠ 로 알린다.
        out["notes"].append(
            "sandbox.filesystem.allowRead 가 비어 있어요 — conda 가 안 보여서 "
            "python·pytest 가 안 돌아요"
        )

    out["ok"] = not out["reasons"]
    return out


def user_settings_path() -> str:
    """`~/.claude/settings.json` — 훅 등록이 있는 곳. `hardProtect` 다.

    `LAB_CLAUDE_SETTINGS` 로 바꿀 수 있다 (`hooks/install.py` 와 같은 장치).
    """
    override = os.environ.get("LAB_CLAUDE_SETTINGS")
    if override:
        return os.path.abspath(override)
    return os.path.join(os.path.expanduser("~"), ".claude", "settings.json")


def launch_settings(root: str, *, cache_dir: str = "", conda_roots=(), domains=()) -> dict:
    """런처가 `--settings` 로 넘길 설정 **전체**. 파일로 쓰지 않고 돌려준다."""
    return {
        "permissions": {
            # 프로젝트 설정을 안 읽으므로(`--setting-sources user`) 거기 있던
            # 값을 여기로 옮겨야 한다. 홈의 자격 증명을 경로마다 적지 않고
            # 통째로 막는다 (실측 2026-11-04).
            "blockReadsOutsideWorkingDirectories": True,
            "blockWritesOutsideWorkingDirectories": True,
            # [읽어야 할 바깥 경로 — 비어 있음. 예: ~/datasets]
            "blockReadsExemptPaths": [],
        },
        "sandbox": sandbox_block(
            root, cache_dir=cache_dir, conda_roots=conda_roots, domains=domains
        ),
        # 훅은 **일부러 안 넣는다.** 사용자 설정에 있고 `--setting-sources user`
        # 가 그걸 읽는다. 양쪽에 두면 **훅이 두 번 돈다** (실측 M6f).
    }


def render_launch_settings(
    root: str, *, cache_dir: str = "", conda_roots=(), domains=()
) -> dict:
    """`<data>/agent/headless-settings.json` 을 **지금 코드대로 다시 쓴다.**

    디스크에 있는 걸 믿지 않는다 — 런처가 매 실행 전에 부른다. 이 파일이
    `server/data/` 아래인 것이 요점이다: 샌드박스 안에서 그 폴더 쓰기가
    실패하므로(M1b) AI 가 쓴 코드가 자기 울타리를 고칠 수 없다.

    **사용자 설정(`~/.claude/settings.json`)에는 쓰지 않는다.** 전에
    `hooks install` 이 거기에 `sandbox` 절을 넣어 이 PC 의 모든 Claude 세션이
    갇혔다. 규칙 0 을 코드로 강제한다.
    """
    path = launch_settings_path()
    data = launch_settings(
        root, cache_dir=cache_dir, conda_roots=conda_roots, domains=domains
    )
    before = None
    try:
        with open(path, encoding="utf-8") as fh:
            before = json.load(fh)
    except (FileNotFoundError, json.JSONDecodeError, OSError):
        before = None
    changed = json.dumps(before, sort_keys=True) != json.dumps(data, sort_keys=True)
    if changed:
        os.makedirs(os.path.dirname(path), exist_ok=True)
        registry.write_json(path, data)
    return {"path": path, "changed": changed, "state": sandbox_state(root)}


def ensure_permission_mode(root: str, mode: str = D.DEFAULT_PERMISSION_MODE) -> dict:
    """프로젝트 `.claude/settings.json` 에 `permissions.defaultMode` 를 박는다.

    **왜 프로젝트 설정인가** — 2.1.317 은 사용자 설정에 `defaultMode` 가 없으면
    `auto` 로 뜬다(실측: `claude --remote-control` 로 새로 띄운 세션이 auto 였고
    훅이 "권한 우회 모드" 를 남겼다). 프로젝트 설정이 사용자 설정보다 우선하고,
    `.claude/**` 는 `selfProtect` 라 AI 가 되돌릴 수 없다.

    이미 값이 있으면 **건드리지 않는다.** 다른 키도 그대로 둔다 (병합).

    같이 박는 것 (실측 2026-11-04):

        permissions.blockReadsOutsideWorkingDirectories = true
        permissions.blockWritesOutsideWorkingDirectories = true

    홈의 자격 증명(`~/.ssh`·`~/.aws`·브라우저 프로필·`~/.bash_history` …)을
    **경로를 하나하나 적지 않고** 통째로 막는다. 네트워크가 열려 있으니 읽힌 건
    곧 나갈 수 있다. 실측에서 거절 메시지가 이렇게 나왔다:

        /etc/hostname is outside <프로젝트>; the
        permissions.blockReadsOutsideWorkingDirectories setting blocks reads
        outside the working directories

    읽어야 할 바깥 경로가 있으면 `permissions.blockReadsExemptPaths` 에
    적는다(`.claude/**` 는 selfProtect 라 사람만 고칠 수 있다).
    """
    path = claude_settings_path(root)
    data = {}
    try:
        with open(path, encoding="utf-8") as fh:
            loaded = json.load(fh)
        if isinstance(loaded, dict):
            data = loaded
    except (FileNotFoundError, json.JSONDecodeError, OSError):
        data = {}

    perms = data.get("permissions")
    if not isinstance(perms, dict):
        perms = {}
    before = perms.get("defaultMode")
    changed = False
    if not before:
        perms["defaultMode"] = mode
        changed = True
    for key in ("blockReadsOutsideWorkingDirectories", "blockWritesOutsideWorkingDirectories"):
        if key not in perms:
            perms[key] = True
            changed = True
    if "blockReadsExemptPaths" not in perms:
        # [읽어야 할 바깥 경로 — 비어 있음. 예: ~/miniconda3, ~/datasets]
        perms["blockReadsExemptPaths"] = []
        changed = True
    if not changed:
        return {"path": path, "changed": False, "mode": str(before)}
    data["permissions"] = perms
    registry.write_json(path, data)
    return {"path": path, "changed": True, "mode": str(perms["defaultMode"])}


def migrate(name: str) -> dict:
    """정책 파일을 지금 판으로 올린다. **`saved` 만 보존**한다.

    모드·행동 유형·경로 목록·bash·headless 는 코드가 단일 출처이므로 전부
    다시 쓴다. 사람이 고른 프리셋과 예외(`saved`)만 옮긴다.

    같이 이행하는 것
      - 프로젝트 `.claude/settings.json` 의 `permissions.defaultMode`
      - 승인 로그 CSV 헤더 (판 2 에서 `toolUseId` 열이 생겼다)
    """
    from . import approval_log

    try:
        path = registry.policy_path(name)
    except registry.InvalidName as exc:
        raise PolicyError(str(exc)) from None

    old: dict = {}
    try:
        with open(path, encoding="utf-8") as fh:
            loaded = json.load(fh)
        if isinstance(loaded, dict):
            old = loaded
    except (FileNotFoundError, json.JSONDecodeError, OSError):
        old = {}

    root = str((old.get("project") or {}).get("root") or "") or (registry.root_of(name) or "")
    if not root:
        raise PolicyError(
            f"프로젝트 루트를 알 수 없어요: {name!r} · labremote init-project 로 만든 "
            "프로젝트인지 확인해 주세요."
        )

    before_version = old.get("version")
    data = D.default_policy(name, paths.real(root))
    saved = old.get("saved")
    if isinstance(saved, dict):
        data["saved"] = saved
    data["updatedAt"] = datetime.now().astimezone().isoformat(timespec="seconds")
    data["updatedBy"] = "migrate"
    registry.write_json(path, data)

    policy = load(name)  # 올린 결과가 실제로 유효한지 (fail-closed 검사)
    settings = ensure_permission_mode(policy.root)
    log = approval_log.migrate_log(approval_log.log_path(policy.root, policy))

    approval_log.log_event(
        approval_log.event_path(policy.root, policy),
        {
            "event": "policy-migrate",
            "from": before_version,
            "to": D.POLICY_VERSION,
            "mode": policy.effective_mode(),
            "settings": settings,
            "log": log,
        },
    )
    return {
        "path": path,
        "from": before_version,
        "to": D.POLICY_VERSION,
        "mode": policy.effective_mode(),
        "overrides": policy.overrides(),
        "settings": settings,
        "log": log,
        "conflicts": conflicting_writable_roots(policy),
    }


def ensure(name: str, root: str) -> Policy:
    """정책 파일이 없으면 기본 템플릿에서 만든다 (생성기가 호출)."""
    path = registry.policy_path(name)
    if not os.path.exists(path):
        try:
            with open(seed_default(), encoding="utf-8") as fh:
                data = json.load(fh)
        except (OSError, json.JSONDecodeError):
            # 템플릿이 깨졌으면 코드의 기본값으로 떨어진다.
            data = D.default_policy()
        data["project"] = {"name": name, "root": paths.real(root)}
        data["updatedAt"] = datetime.now().astimezone().isoformat(timespec="seconds")
        data["updatedBy"] = "generator"
        registry.write_json(path, data)
    return load(name)
