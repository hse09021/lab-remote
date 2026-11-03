"""템플릿 렌더링.

`string.Template.substitute()` 만 쓴다. 빠진 키에서 **예외가 나야** 자리표시가
그대로 새어 나가지 않는다 (`safe_substitute` 금지).

Jinja2 는 쓰지 않는다 — 의존성만 늘고 얻는 게 없다.
"""

from __future__ import annotations

import os
from string import Template

__all__ = ["templates_dir", "read_template", "render"]


def templates_dir() -> str:
    here = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    return os.path.join(here, "templates", "project")


def read_template(name: str) -> str:
    with open(os.path.join(templates_dir(), name), encoding="utf-8") as fh:
        return fh.read()


def render(name: str, values: dict[str, str]) -> str:
    return Template(read_template(name)).substitute(values)
