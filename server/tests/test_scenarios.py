"""Scenario — 가짜 에이전트 답으로 저장 · 해시 · 바뀜 감지 · 읽기 전용 옵션을 시험한다."""

import asyncio
import json
import os

import pytest
from claude_agent_sdk import AssistantMessage, ResultMessage, ToolUseBlock

from app import scenarios


def fake_answer(root, answer, *, read=("src/train.py",), seen=None):
    async def run(options, prompt):
        if seen is not None:
            seen.append(options)
        blocks = [ToolUseBlock(id=f"t{i}", name="Read", input={"file_path": os.path.join(root, r)}) for i, r in enumerate(read)]
        yield AssistantMessage(content=blocks, model="claude-test")
        yield ResultMessage(subtype="success", duration_ms=1, duration_api_ms=1, is_error=False, num_turns=1,
                            session_id="x", structured_output=answer)
    return run


ANSWER = {
    "summary": "작은 학습 프로젝트",
    "steps": [
        {"name": "학습", "command": "python src/train.py", "inputs": ["data/"], "outputs": ["runs/r16/"],
         "env": "lora-env", "code": ["src/train.py"], "note": ""},
        {"name": "평가", "command": "python src/eval.py", "inputs": ["runs/r16/"], "outputs": ["runs/r16/eval.json"],
         "env": "", "code": ["src/eval.py"], "note": ""},
    ],
    "files": ["README.md", "./src/eval.py", "runs/r16/metrics.csv", ".gitignore"],
}


@pytest.fixture()
def proj(project):
    for rel, text in (("src/train.py", "lr = 1\n"), ("src/eval.py", "print(1)\n"), ("README.md", "# x\n"), (".gitignore", "runs/\n")):
        with open(os.path.join(project, rel), "w") as fh:
            fh.write(text)
    os.makedirs(os.path.join(project, "runs", "r16"))
    with open(os.path.join(project, "runs", "r16", "metrics.csv"), "w") as fh:
        fh.write("epoch,loss\n")
    return project


def test_그리고_저장하고_바뀜을_알아챈다(proj):
    seen = []
    out = asyncio.run(scenarios.draw("demo", query_fn=fake_answer(proj, ANSWER, seen=seen)))
    assert [s["name"] for s in out["steps"]] == ["학습", "평가"]
    # 내는 파일(runs/…)은 해시에서 빠지고, 점으로 시작하는 파일 이름은 그대로
    assert sorted(out["hashes"]) == [".gitignore", "README.md", "src/eval.py", "src/train.py"]
    assert os.path.exists(os.path.join(proj, ".labremote", "scenarios", "main.json"))
    # 🔑 읽기 전용으로 연다
    opts = seen[0]
    assert opts.permission_mode == "plan" and opts.tools == ["Read", "Glob", "Grep"]
    assert opts.output_format["type"] == "json_schema"

    assert scenarios.load("demo")["changed"] == []
    with open(os.path.join(proj, "runs", "r16", "metrics.csv"), "a") as fh:
        fh.write("1,0.5\n")  # 학습 결과가 바뀌어도 "바뀜"이 아니다
    assert scenarios.load("demo")["changed"] == []
    with open(os.path.join(proj, "src", "train.py"), "a") as fh:
        fh.write("lr = 2\n")
    got = scenarios.load("demo")
    assert got["changed"] == ["src/train.py"]
    assert [(s["name"], s["changed"]) for s in got["scenario"]["steps"]] == [("학습", ["src/train.py"]), ("평가", [])]


def test_모양이_틀리면_저장하지_않는다(proj):
    with pytest.raises(scenarios.ScenarioError, match="모양"):
        asyncio.run(scenarios.draw("demo", query_fn=fake_answer(proj, "그냥 글")))
    assert scenarios.load("demo")["scenario"] is None
    assert scenarios.status("demo")["state"] == "error"


def test_없으면_비어_있다(project):
    assert scenarios.load("demo")["scenario"] is None


def test_프로젝트_밖_경로는_해시하지_않는다(proj, tmp_path):
    (tmp_path / "secret.txt").write_text("x")
    got = scenarios.file_hashes(proj, [str(tmp_path / "secret.txt"), "../secret.txt", "src/train.py"])
    assert got.get("src/train.py") and not any(v for k, v in got.items() if "secret" in k)
