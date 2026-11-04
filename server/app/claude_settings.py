"""프로젝트 `.claude/settings.json` 을 우리가 쓰는 모양으로 맞춘다.

권한 모드 · 바깥 읽기·쓰기 차단 · Bash 샌드박스를 한 번에 본다. 경로가
기계마다 달라서(공용 캐시·conda 설치 폴더) 정적 템플릿으로는 못 쓴다.

이 파일은 **훅 경로가 아니다** — `runner` 를 불러 캐시·conda 를 찾는다.
훅은 `policy.sandbox_state()` 만 본다 (읽기만, 표준 라이브러리만).
"""

from __future__ import annotations

__all__ = ["ensure_claude_settings"]


def ensure_claude_settings(root: str, *, project: str = "") -> dict:
    """프로젝트 `.claude/settings.json` 을 **우리가 쓰는 모양**으로 맞춘다.

    권한 모드·바깥 읽기 차단·Bash 샌드박스 셋을 한 번에 본다. 경로가
    기계마다 달라서(캐시·conda) 정적 템플릿으로는 못 쓴다.
    """
    from . import policy as policy_mod

    modes = policy_mod.ensure_permission_mode(root)
    cache_dir = ""
    conda_roots: list[str] = []
    try:
        from .runner import cache as cache_mod
        from .runner import sandbox as sandbox_mod

        pol = policy_mod.load(project) if project else None
        cache_dir = cache_mod.cache_dir(pol)
        conda_roots = sandbox_mod.conda_roots()
    except Exception:
        # 캐시·conda 를 못 찾아도 샌드박스는 켠다 — 사람이 allowRead 를 더하면 된다.
        pass
    try:
        box = policy_mod.ensure_claude_sandbox(
            root, cache_dir=cache_dir, conda_roots=conda_roots
        )
    except OSError as exc:
        # 사용자 설정을 못 쓰는 환경(샌드박스 안 등). 설치는 계속하고 상태만 알린다.
        box = {"changed": False, "state": policy_mod.sandbox_state(root), "error": str(exc)}
    return {
        "path": modes["path"],
        "changed": bool(modes["changed"] or box["changed"]),
        "mode": modes["mode"],
        "sandbox": box["state"],
    }
