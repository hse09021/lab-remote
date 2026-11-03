"""계획 -> `docs/File_directory.md` 의 트리와 역할 표.

생성기가 **자기 계획으로** 찍으므로 문서와 실제 디스크가 항상 일치한다.
"""

from __future__ import annotations

from .plan import PlannedFile

__all__ = ["render_tree", "render_roles"]


def render_tree(name: str, plan: list[PlannedFile]) -> str:
    """`tree` 비슷한 텍스트. 폴더는 한 번만, 파일은 이름만."""
    root: dict = {}
    for item in sorted(plan, key=lambda x: x.path):
        node = root
        parts = item.path.split("/")
        for part in parts[:-1]:
            node = node.setdefault(part, {})
        node[parts[-1]] = None

    lines = [f"{name}/"]

    def walk(node: dict, prefix: str) -> None:
        entries = sorted(node.items(), key=lambda kv: (kv[1] is None, kv[0]))
        for index, (key, child) in enumerate(entries):
            last = index == len(entries) - 1
            lines.append(f"{prefix}{'└── ' if last else '├── '}{key}{'/' if child is not None else ''}")
            if child is not None:
                walk(child, prefix + ("    " if last else "│   "))

    walk(root, "")
    return "\n".join(lines)


def render_roles(plan: list[PlannedFile]) -> str:
    rows = []
    for item in sorted(plan, key=lambda x: x.path):
        if item.path.endswith(".gitkeep") and not item.role:
            continue
        mark = {"lock": " 🔒", "hook": " 🔒", "gen": "", "ai": "", "user": ""}.get(item.owner, "")
        rows.append(f"| `{item.path}`{mark} | {item.role} |")
    return "\n".join(rows)
