"""`labremote hooks check` — 설치된 command 를 실제로 띄워 보는 자가진단.

픽스처가 아니라 **지금 설치돼 있는 래퍼**에 이벤트를 먹인다. 그래야
"코드는 맞는데 설치가 틀린" 경우를 잡는다.

tests/test_hook_e2e.py 와 같은 시나리오다 — 거기서 초록이면 여기서도 초록이어야 한다.
"""

from __future__ import annotations

import json
import os
import subprocess

from .. import registry
from . import install

__all__ = ["PROBES", "run_check"]


def PROBES(root: str) -> list[tuple[str, dict, str]]:
    """(설명, PreToolUse 이벤트, 기대 결정)."""
    def event(tool, tool_input):
        return {
            "session_id": "labremote-check",
            "cwd": root,
            "prompt_id": "labremote-check",
            "permission_mode": "default",
            "hook_event_name": "PreToolUse",
            "tool_name": tool,
            "tool_input": tool_input,
            "tool_use_id": "labremote-check",
        }

    return [
        ("폴더 밖 쓰기", event("Write", {"file_path": "/tmp/labremote-check.txt"}), "deny"),
        ("평가 기준 수정", event("Edit", {
            "file_path": os.path.join(root, "docs/Evaluation.md"),
            "old_string": "a", "new_string": "b"}), "ask"),
        ("프로젝트 안 .claude", event("Write", {"file_path": os.path.join(root, ".claude/settings.json")}), "deny"),
        ("승인 로그 수정", event("Write", {"file_path": os.path.join(root, "logs/Approval_log.csv")}), "deny"),
        ("기록 갱신", event("Write", {"file_path": os.path.join(root, "logs/Decision_log.md")}), "allow"),
        ("패키지 설치", event("Bash", {"command": "pip install peft"}), "ask"),
        ("sed 우회", event("Bash", {"command": "sed -i 's/a/b/' docs/Evaluation.md"}), "ask"),
        ("읽기 명령", event("Bash", {"command": "ls -la"}), "defer"),
        ("치환이 섞인 명령", event("Bash", {"command": 'eval "$(echo x)"'}), "ask"),
    ]


def _command() -> list[str] | None:
    """설치된 PreToolUse command. 없으면 None."""
    state = install.status()
    entries = state["installed"].get("PreToolUse") or []
    for entry in entries:
        for hook in entry.get("hooks") or []:
            raw = str(hook.get("command") or "")
            if install.MARKER in raw:
                import shlex

                return shlex.split(raw)
    return None


def run_check(project: str | None = None) -> dict:
    """결과 보고서. `ok` 가 False 면 어딘가 틀렸다."""
    projects = registry.load()
    if not projects:
        return {"ok": False, "reason": "등록된 실험 프로젝트가 없어요. labremote init-project 를 먼저 해 주세요."}

    if project:
        root = registry.root_of(project)
        if not root:
            return {"ok": False, "reason": f"등록되지 않은 프로젝트예요: {project}"}
    else:
        root, project = sorted(projects.items())[0]

    argv = _command()
    if not argv:
        return {"ok": False, "reason": "설치된 labremote 훅이 없어요. labremote hooks install 을 해 주세요."}

    mode = (install.status().get("state") or {}).get("mode")
    if mode == "dump":
        return {
            "ok": False,
            "reason": "지금은 dump 모드라 판정을 하지 않아요. "
            "labremote hooks install --mode enforce 로 바꾼 뒤에 다시 해 주세요.",
            "mode": mode,
        }

    rows = []
    for label, event, expected in PROBES(root):
        result = subprocess.run(
            argv,
            input=json.dumps(event),
            capture_output=True,
            text=True,
            env={**os.environ, "CLAUDE_PROJECT_DIR": root},
        )
        got = "(출력 없음)"
        if result.stdout.strip():
            try:
                got = json.loads(result.stdout)["hookSpecificOutput"]["permissionDecision"]
            except (json.JSONDecodeError, KeyError):
                got = f"(읽을 수 없음: {result.stdout[:60]})"
        rows.append(
            {
                "label": label,
                "expected": expected,
                "got": got,
                "ok": got == expected,
                "exitCode": result.returncode,
            }
        )

    return {
        "ok": all(row["ok"] for row in rows) and all(row["exitCode"] == 0 for row in rows),
        "project": project,
        "root": root,
        "mode": mode,
        "rows": rows,
    }
