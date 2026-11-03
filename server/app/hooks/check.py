"""`labremote hooks check` — 설치된 command 를 실제로 띄워 보는 자가진단.

픽스처가 아니라 **지금 설치돼 있는 래퍼**에 이벤트를 먹인다. 그래야
"코드는 맞는데 설치가 틀린" 경우를 잡는다.

**실제 프로젝트에는 아무 기록도 남기지 않는다.** 1차 실측에서 이 명령이
`logs/Approval_log.csv` 에 시험 기록 네 줄과 영원히 안 닫히는 대기 건을
남겼다. 래퍼는 설치할 때 박힌 루트 아래만 처리하므로 `/tmp` 로는 옮길 수
없어서, **박힌 루트 아래의 임시 프로젝트 + 임시 `LAB_DATA_DIR`** 로 돌린다.
정책은 대상 프로젝트의 **실제 내용**을 복사해 쓰므로 프리셋·예외는 그대로
시험된다.

tests/test_hook_e2e.py 와 같은 시나리오다 — 거기서 초록이면 여기서도 초록이어야 한다.
"""

from __future__ import annotations

import glob
import json
import os
import shutil
import subprocess
import tempfile

from .. import paths, policy as policy_mod, registry, runstate
from . import install

__all__ = ["PROBES", "run_check", "SCRATCH_PREFIX", "scratch_leftovers", "clean_leftovers"]

#: 임시 프로젝트 폴더 이름의 앞머리. `registry.valid_name` 규칙에 맞아야 한다.
SCRATCH_PREFIX = "labremote-check-"

#: 프로브가 쓰는 실험 ID. 임시 프로젝트에서 "한 번 시작된 실험" 으로 심는다.
PROBE_EXP = "EXP-001"


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

    def inside(rel):
        return os.path.join(root, rel)

    return [
        ("폴더 밖 쓰기", event("Write", {"file_path": "/tmp/labremote-check.txt"}), "deny"),
        ("평가 기준 수정", event("Edit", {
            "file_path": inside("docs/Evaluation.md"),
            "old_string": "a", "new_string": "b"}), "ask"),
        ("프로젝트 안 .claude", event("Write", {"file_path": inside(".claude/settings.json")}), "deny"),
        ("승인 로그 수정", event("Write", {"file_path": inside("logs/Approval_log.csv")}), "deny"),
        ("기록 갱신", event("Write", {"file_path": inside("logs/Decision_log.md")}), "allow"),
        ("패키지 설치", event("Bash", {"command": "pip install peft"}), "ask"),
        ("sed 우회", event("Bash", {"command": "sed -i 's/a/b/' docs/Evaluation.md"}), "ask"),
        ("읽기 명령", event("Bash", {"command": "ls -la"}), "defer"),
        # 실측에서 `2>/dev/null` 이 "폴더 밖 쓰기" 로 막혔다
        ("버린 출력", event("Bash", {"command": "ls -la .claude 2>/dev/null"}), "defer"),
        ("치환이 섞인 명령", event("Bash", {"command": 'eval "$(echo x)"'}), "ask"),
        # 잠금 3종 + 판 2 에서 늘어난 보호
        ("서버 보호 파일", event("Write", {"file_path": install.wrapper_path()}), "deny"),
        ("MCP 설정", event("Write", {"file_path": os.path.expanduser("~/.claude.json")}), "deny"),
        ("비밀 파일 읽기", event("Read", {"file_path": inside(".env")}), "deny"),
        ("예시 파일 읽기", event("Read", {"file_path": inside(".env.example")}), "defer"),
        ("산출물 삭제", event("Bash", {
            "command": f"rm -rf experiments/{PROBE_EXP}/output"}), "deny"),
        ("산출물 비우기", event("Bash", {
            "command": f": > experiments/{PROBE_EXP}/output/train.log"}), "deny"),
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


def _baked_roots() -> str:
    """래퍼에 박힌 프로젝트 루트. 임시 프로젝트는 **그 아래**여야 한다."""
    baked = (install.status().get("state") or {}).get("roots")
    return paths.real(str(baked)) if baked else registry.projects_root()


def scratch_leftovers(roots: str | None = None) -> list[str]:
    """죽은 실행이 남긴 임시 프로젝트 폴더. `doctor` 가 이걸로 알려 준다."""
    base = roots or _baked_roots()
    try:
        return sorted(glob.glob(os.path.join(base, SCRATCH_PREFIX + "*")))
    except OSError:
        return []


def clean_leftovers(roots: str | None = None) -> list[str]:
    """잔해를 지운다. 이름이 우리 것이라 다른 프로젝트를 건드릴 일은 없다."""
    gone = []
    for path in scratch_leftovers(roots):
        try:
            shutil.rmtree(path)
            gone.append(path)
        except OSError:
            pass
    return gone


def _make_scratch(roots: str, source_policy: dict | None) -> tuple[str, str, str]:
    """`(스크래치 루트, 프로젝트 이름, 임시 데이터 폴더)`.

    `os.environ` 을 이미 임시 데이터 폴더로 돌려 둔 상태에서 불러야 한다.
    """
    name = f"{SCRATCH_PREFIX}{os.getpid()}"
    root = os.path.join(roots, name)
    for sub in ("docs", "logs", "specifications", "state", "src",
                f"experiments/{PROBE_EXP}/output"):
        os.makedirs(os.path.join(root, sub), exist_ok=True)
    # 프로브가 읽는 파일 몇 개만 만든다 (존재 여부로 갈리는 판정이 있다)
    for rel in (".env", ".env.example", f"experiments/{PROBE_EXP}/output/train.log"):
        with open(os.path.join(root, rel), "w", encoding="utf-8") as fh:
            fh.write("# labremote hooks check\n")

    root = registry.register(root, name)
    if source_policy:
        data = json.loads(json.dumps(source_policy))  # 원본을 건드리지 않는다
        data["project"] = {"name": name, "root": root}
        registry.write_json(registry.policy_path(name), data)
    else:
        policy_mod.ensure(name, root)
    # 산출물 보존 판정을 보려면 "한 번 시작된 실험" 이 있어야 한다.
    # **멈춘 상태**로 둔다 — 종료 조건 수정이 ask 로 나오는지도 같이 보려면
    # 실험이 돌고 있으면 안 된다(실행 중에는 deny 가 맞다).
    runstate.mark_started(name, PROBE_EXP)
    return root, name, root


def run_check(project: str | None = None) -> dict:
    """결과 보고서. `ok` 가 False 면 어딘가 틀렸다."""
    projects = registry.load()
    if not projects:
        return {"ok": False, "reason": "등록된 실험 프로젝트가 없어요. labremote init-project 를 먼저 해 주세요."}

    if project:
        real_root = registry.root_of(project)
        if not real_root:
            return {"ok": False, "reason": f"등록되지 않은 프로젝트예요: {project}"}
    else:
        real_root, project = sorted(projects.items())[0]

    argv = _command()
    if not argv:
        return {"ok": False, "reason": "설치된 labremote 훅이 없어요. labremote hooks install 을 해 주세요."}

    state = install.status()
    mode = (state.get("state") or {}).get("mode")
    if mode == "dump":
        return {
            "ok": False,
            "reason": "지금은 dump 모드라 판정을 하지 않아요. "
            "labremote hooks install --mode enforce 로 바꾼 뒤에 다시 해 주세요.",
            "mode": mode,
        }

    # 환경을 바꾸기 **전에** 실제 정책을 읽어 둔다 (임시 폴더로 돌리면 못 읽는다).
    try:
        source_policy = policy_mod.load(project).data
    except policy_mod.PolicyError as exc:
        return {"ok": False, "reason": f"정책을 읽을 수 없어요: {exc}", "project": project}

    roots = _baked_roots()
    clean_leftovers(roots)

    data_dir = tempfile.mkdtemp(prefix="labremote-check-data-")
    before = {k: os.environ.get(k) for k in ("LAB_DATA_DIR", "LAB_PROJECTS_DIR")}
    scratch = None
    try:
        os.environ["LAB_DATA_DIR"] = data_dir
        os.environ["LAB_PROJECTS_DIR"] = roots
        scratch, scratch_name, _ = _make_scratch(roots, source_policy)

        rows = []
        for label, event, expected in PROBES(scratch):
            result = subprocess.run(
                argv,
                input=json.dumps(event),
                capture_output=True,
                text=True,
                env={
                    **os.environ,
                    "CLAUDE_PROJECT_DIR": scratch,
                    "LAB_DATA_DIR": data_dir,
                    "LAB_PROJECTS_DIR": roots,
                },
            )
            got = "(출력 없음)" if not result.stdout.strip() else None
            if got is None:
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
    finally:
        if scratch:
            shutil.rmtree(scratch, ignore_errors=True)
        shutil.rmtree(data_dir, ignore_errors=True)
        for key, value in before.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value

    return {
        "ok": all(row["ok"] for row in rows) and all(row["exitCode"] == 0 for row in rows),
        "project": project,
        "root": real_root,
        "mode": mode,
        "scratch": True,
        "rows": rows,
    }
