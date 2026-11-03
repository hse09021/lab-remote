"""기록용 훅들이 같이 쓰는 조각.

PreToolUse 와 달리 이쪽(PostToolUse·Stop·SessionEnd)은 판정을 하지 않는다.
실패해도 조용히 지나가야 하므로 예외를 전부 None 으로 돌린다.

표준 라이브러리만 쓴다.
"""

from __future__ import annotations

import os

from .. import policy as policy_mod
from .. import registry

__all__ = ["project_of"]


def project_of(event: dict):
    """등록된 실험 프로젝트면 `(root, name, policy)`, 아니면 None."""
    try:
        cwd = str(event.get("cwd") or os.environ.get("CLAUDE_PROJECT_DIR") or "")
        if not cwd:
            return None
        found = registry.lookup(cwd)
        if not found:
            return None
        root, name = found
        return root, name, policy_mod.load(name)
    except Exception:
        return None
