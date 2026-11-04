"""루프 프롬프트 렌더.

`app/templates/prompts/loop/*.md` 를 `string.Template` 로 채운다.
**`safe_substitute` 는 쓰지 않는다** — 빠진 키에서 예외가 나야 `$next_exp` 가
그대로 Claude 에게 새어 나가지 않는다 (생성기의 `render.py` 와 같은 원칙).

`app/templates/prompts/*.md`(한 단계 위)는 **사람이 읽는 참고 프롬프트**다.
거기는 `{중괄호}` 를 쓰고 코드가 읽지 않는다. 섞이지 않게 폴더를 나눴다.
"""

from __future__ import annotations

import os
from string import Template

__all__ = ["PROMPTS", "prompts_dir", "read", "render"]

#: 루프가 쓰는 프롬프트. 이름이 곧 파일 이름이다.
PROMPTS = ("loop_plan", "loop_review", "resume_after_approval", "fill_missing_journal")


def prompts_dir() -> str:
    here = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    return os.path.join(here, "templates", "prompts", "loop")


def read(name: str) -> str:
    if name not in PROMPTS:
        raise KeyError(f"모르는 프롬프트예요: {name!r} · 있는 것: {', '.join(PROMPTS)}")
    with open(os.path.join(prompts_dir(), f"{name}.md"), encoding="utf-8") as fh:
        return fh.read()


def render(name: str, values: dict) -> str:
    """빠진 키가 있으면 `KeyError` 다. 자리표시가 새어 나가지 않게."""
    return Template(read(name)).substitute({k: str(v) for k, v in values.items()})
