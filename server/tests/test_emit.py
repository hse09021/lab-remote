"""stdout 출력 계약 시험.

반환 방식 두 가지(종료코드 · stdout JSON)는 배타적이라 섞으면 안 된다.
우리는 stdout JSON 만 쓰고 **종료코드는 언제나 0** 이다.
"""

import io
import json
import subprocess
import sys
import time

import pytest

from app.hooks import messages as M
from app.hooks.emit import ALLOW, ASK, DEFER, DENY, emit, payload


def test_모양이_계약대로():
    out = payload(DENY("안 돼요"))
    assert set(out) == {"hookSpecificOutput"}
    inner = out["hookSpecificOutput"]
    assert inner["hookEventName"] == "PreToolUse"
    assert inner["permissionDecision"] == "deny"
    assert inner["permissionDecisionReason"] == "안 돼요"


@pytest.mark.parametrize("make", [ALLOW, ASK, DENY, DEFER])
def test_네_가지_결정값(make):
    assert payload(make())["hookSpecificOutput"]["permissionDecision"] in (
        "allow",
        "ask",
        "deny",
        "defer",
    )


def test_사유가_없으면_키를_안_넣는다():
    assert "permissionDecisionReason" not in payload(DEFER())["hookSpecificOutput"]


def test_emit_은_항상_0():
    buf = io.StringIO()
    assert emit(DENY("x"), stream=buf) == 0
    assert json.loads(buf.getvalue())


def test_stdout_에_JSON_말고_아무것도_안_섞인다(project, project_root, hook_event):
    """디버그 print 가 새면 Claude Code 가 출력을 못 읽는다."""
    event = hook_event("Write", {"file_path": f"{project_root}/src/train.py"}, cwd=project_root)
    result = _run(event)
    assert result.returncode == 0
    assert json.loads(result.stdout)  # 통째로 JSON 하나


def test_깨진_입력도_0_으로_끝나고_차단():
    result = _run_raw("{ 이건 JSON 이 아니에요")
    assert result.returncode == 0
    inner = json.loads(result.stdout)["hookSpecificOutput"]
    assert inner["permissionDecision"] == "deny"
    assert M.NO_WORKAROUND in inner["permissionDecisionReason"]


def test_빈_입력도_0_으로_끝나고_차단():
    result = _run_raw("")
    assert result.returncode == 0
    assert json.loads(result.stdout)["hookSpecificOutput"]["permissionDecision"] == "deny"


def test_사유는_해요체(project, project_root, hook_event):
    event = hook_event("Write", {"file_path": "/etc/hosts"}, cwd=project_root)
    inner = json.loads(_run(event).stdout)["hookSpecificOutput"]
    assert inner["permissionDecision"] == "deny"
    assert inner["permissionDecisionReason"].rstrip().endswith("요.")


def test_판정이_충분히_빠르다(project, project_root, hook_event):
    """훅 timeout 을 10초로 잡았다. 판정은 그 근처에도 가면 안 된다."""
    event = hook_event("Bash", {"command": "pip install peft"}, cwd=project_root)
    start = time.monotonic()
    for _ in range(5):
        _run(event)
    each = (time.monotonic() - start) / 5
    assert each < 1.0, f"한 번에 {each:.2f}초"


# --- 도우미 ----------------------------------------------------------------


def _run_raw(raw: str):
    import os

    return subprocess.run(
        [sys.executable, "-m", "app.hooks.pretooluse"],
        input=raw,
        capture_output=True,
        text=True,
        env={**os.environ},
    )


def _run(event: dict):
    return _run_raw(json.dumps(event))
