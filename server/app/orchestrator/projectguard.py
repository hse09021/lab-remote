"""프로젝트 설정이 **정본과 같은가.** 다르면 되돌린다. — 보안 경계다.

## 왜 필요한가 (M6 실측)

작업 디렉터리는 샌드박스에서 **언제나 쓰기 가능**하고 좁힐 수 없다(M4).
그래서 AI 가 쓴 코드(`pytest`·`python`)가 프로젝트
`.claude/settings.json` 을 고칠 수 있다. 실측에서 이렇게 됐다.

| 심은 것 | 결과 |
|---|---|
| `hooks.PreToolUse` | 훅은 샌드박스 **밖**에서 돈다(M1) → 그 명령이 **사용자 권한으로 실행됐다** |
| `sandbox.enabled: false` | 샌드박스가 꺼졌고 AI 코드가 `server/data/runstate/` 에 **실제로 썼다** |
| `.mcp.json` 의 서버 | 훅이 못 보는 도구가 **실제로 떴다** |

런처는 `--setting-sources user` + `--strict-mcp-config` 로 그 파일을 **안
읽는다**(T2). 하지만 사람이 맨손 `claude` 로 열면 읽힌다. 그래서 두 겹이다.

1. **안 읽기** — 런처 (`agent/launch.py`)
2. **되돌리기** — 이 모듈. 루프 시작 전 · 각 Claude 세션 종료 직후 · 기록 커밋 전

## 정본은 **생성기 템플릿**이다

`templates/project/claude/settings.json.tmpl` 에는 변수가 없다. 그래서 정본이
코드 안에 있고, 비교는 **파싱한 JSON** 으로 한다(공백·줄바꿈 차이로 싸우지
않게). `.mcp.json` 의 정본은 **없음**이다 — 생기면 지운다.

되돌리기 전에 원본을 `server/data/tamper/<프로젝트>/<시각>/` 에 **증거로**
남긴다. 그 폴더는 샌드박스 안에서 쓸 수 없으므로(M1b) AI 가 증거를 지울 수
없다.
"""

from __future__ import annotations

import json
import os
import shutil
from datetime import datetime

from .. import paths, registry

__all__ = [
    "GUARDED",
    "expected_settings",
    "settings_path",
    "mcp_path",
    "tamper_dir",
    "check",
    "restore",
    "describe",
]

#: 지키는 파일. 둘 다 **훅의 `selfProtect`** 이기도 하다 — 훅은 도구 호출을
#: 막고, 이 모듈은 **코드가 고친 것**을 되돌린다.
GUARDED = (".claude/settings.json", ".mcp.json")

#: 정본 템플릿
_TEMPLATE = "claude/settings.json.tmpl"


def settings_path(root: str) -> str:
    return os.path.join(paths.real(root), ".claude", "settings.json")


def mcp_path(root: str) -> str:
    return os.path.join(paths.real(root), ".mcp.json")


def expected_settings() -> dict:
    """프로젝트 `.claude/settings.json` 의 **정본**. 템플릿에서 읽는다."""
    from ..generator import render

    return json.loads(render.read_template(_TEMPLATE))


def tamper_dir(project: str, *, now: datetime | None = None) -> str:
    """증거를 남길 폴더. `server/data/` 아래라 AI 가 못 지운다(M1b)."""
    stamp = (now or datetime.now().astimezone()).strftime("%Y%m%d-%H%M%S")
    return os.path.join(registry.data_dir(), "tamper", project, stamp)


def _load(path: str):
    """`(값, 사유)`. 파일이 없으면 `(None, "")`, 깨졌으면 `(None, 사유)`."""
    try:
        with open(path, encoding="utf-8") as fh:
            return json.load(fh), ""
    except FileNotFoundError:
        return None, ""
    except (json.JSONDecodeError, UnicodeDecodeError) as exc:
        return None, f"JSON 이 깨졌어요: {exc}"
    except OSError as exc:
        return None, f"읽을 수 없어요: {exc}"


def _diff(expected: dict, found) -> list[str]:
    """사람이 읽을 차이 목록. 위험한 키는 **이름을 대고** 말한다."""
    out: list[str] = []
    if not isinstance(found, dict):
        return ["내용이 JSON 객체가 아니에요"]

    # 가장 위험한 것부터. 전부 M6 에서 실제로 효력이 있었다.
    if "hooks" in found:
        out.append("hooks 가 들어가 있어요 — 훅은 샌드박스 밖에서 실행돼요")
    box = found.get("sandbox")
    if isinstance(box, dict):
        if box.get("enabled") is False:
            out.append("sandbox.enabled 가 꺼져 있어요 — 샌드박스가 안 떠요")
        else:
            out.append("sandbox 절이 들어가 있어요 — 샌드박스는 런처가 정해요")
    elif box is not None:
        out.append("sandbox 절이 들어가 있어요")
    perms = found.get("permissions")
    if isinstance(perms, dict):
        for key in ("allow", "deny", "ask", "additionalDirectories"):
            if key in perms:
                out.append(f"permissions.{key} 가 들어가 있어요 — 승인 경로가 바뀌어요")
    for key in sorted(set(found) - set(expected) - {"hooks", "sandbox", "permissions"}):
        out.append(f"모르는 키가 있어요: {key}")

    exp_perms = expected.get("permissions") or {}
    if not isinstance(perms, dict):
        out.append("permissions 절이 없어요")
    else:
        for key, want in exp_perms.items():
            if key not in perms:
                out.append(f"permissions.{key} 가 없어요 (정본: {want!r})")
            elif perms[key] != want:
                out.append(
                    f"permissions.{key} 가 달라요: {perms[key]!r} (정본: {want!r})"
                )
    return out


def check(root: str) -> dict:
    """정본과 대조한다. **아무것도 고치지 않는다.**

    돌려주는 것:
        ok       전부 정본과 같은가
        settings "ok" | "changed" | "missing" | "broken"
        mcp      "ok" | "present"
        problems 사람이 읽을 사유 목록
    """
    root = paths.real(root)
    expected = expected_settings()
    out = {
        "ok": False,
        "root": root,
        "settings": "ok",
        "mcp": "ok",
        "problems": [],
        "expected": expected,
    }

    path = settings_path(root)
    found, why = _load(path)
    if why:
        out["settings"] = "broken"
        out["problems"].append(f".claude/settings.json · {why}")
    elif found is None:
        out["settings"] = "missing"
        out["problems"].append(".claude/settings.json 이 없어요 — 훅 설정이 사라졌어요")
    else:
        problems = _diff(expected, found)
        if problems:
            out["settings"] = "changed"
            out["problems"] += [f".claude/settings.json · {p}" for p in problems]

    if os.path.exists(mcp_path(root)):
        out["mcp"] = "present"
        out["problems"].append(
            ".mcp.json 이 있어요 — 훅이 못 보는 도구가 생겨요 (정본은 '없음' 이에요)"
        )

    out["ok"] = not out["problems"]
    return out


def restore(root: str, project: str = "", *, now: datetime | None = None) -> dict:
    """정본으로 되돌린다. 원본은 **증거로 보관**한다.

    `.claude/settings.json` 은 템플릿 내용으로 덮어쓰고, `.mcp.json` 은
    **지운다**(정본이 '없음' 이다).
    """
    root = paths.real(root)
    project = project or (registry.lookup(root) or (None, ""))[1] or "unknown"
    report = check(root)
    if report["ok"]:
        return {"changed": False, "evidence": "", "restored": [], **report}

    folder = tamper_dir(project, now=now)
    os.makedirs(folder, exist_ok=True)
    restored: list[str] = []

    for rel in GUARDED:
        src = os.path.join(root, rel)
        if not os.path.exists(src):
            continue
        dest = os.path.join(folder, rel.replace("/", "__"))
        try:
            shutil.copy2(src, dest)
        except OSError:
            # 증거를 못 남겨도 되돌리는 건 한다 — 열려 있는 구멍이 더 급하다.
            pass

    if report["settings"] != "ok":
        os.makedirs(os.path.dirname(settings_path(root)), exist_ok=True)
        registry.write_json(settings_path(root), report["expected"])
        restored.append(".claude/settings.json")
    if report["mcp"] == "present":
        try:
            os.unlink(mcp_path(root))
            restored.append(".mcp.json")
        except OSError:
            pass

    with open(os.path.join(folder, "report.json"), "w", encoding="utf-8") as fh:
        json.dump(
            {
                "project": project,
                "root": root,
                "at": (now or datetime.now().astimezone()).isoformat(timespec="seconds"),
                "problems": report["problems"],
                "restored": restored,
            },
            fh,
            ensure_ascii=False,
            indent=2,
        )
    return {
        "changed": bool(restored),
        "evidence": folder,
        "restored": restored,
        **report,
    }


def describe(report: dict) -> str:
    """알림·CLI 에 쓸 한 덩어리 글."""
    if report.get("ok"):
        return "프로젝트 설정이 정본과 같아요."
    lines = ["프로젝트 설정이 정본과 달라요:"]
    lines += [f"  · {p}" for p in report.get("problems") or []]
    if report.get("restored"):
        lines.append("되돌린 파일: " + ", ".join(report["restored"]))
    if report.get("evidence"):
        lines.append(f"원본은 증거로 남겼어요: {report['evidence']}")
    return "\n".join(lines)
