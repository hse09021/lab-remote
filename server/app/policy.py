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


def ensure_permission_mode(root: str, mode: str = D.DEFAULT_PERMISSION_MODE) -> dict:
    """프로젝트 `.claude/settings.json` 에 `permissions.defaultMode` 를 박는다.

    **왜 프로젝트 설정인가** — 2.1.317 은 사용자 설정에 `defaultMode` 가 없으면
    `auto` 로 뜬다(실측: `claude --remote-control` 로 새로 띄운 세션이 auto 였고
    훅이 "권한 우회 모드" 를 남겼다). 프로젝트 설정이 사용자 설정보다 우선하고,
    `.claude/**` 는 `selfProtect` 라 AI 가 되돌릴 수 없다.

    이미 값이 있으면 **건드리지 않는다.** 다른 키도 그대로 둔다 (병합).
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
    if before:
        return {"path": path, "changed": False, "mode": str(before)}

    perms["defaultMode"] = mode
    data["permissions"] = perms
    registry.write_json(path, data)
    return {"path": path, "changed": True, "mode": mode}


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
