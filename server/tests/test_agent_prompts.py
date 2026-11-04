"""루프 프롬프트 렌더.

**`safe_substitute` 는 쓰지 않는다** — 빠진 키에서 예외가 나야 `$next_exp` 가
그대로 Claude 에게 새어 나가지 않는다.
"""

import pytest

from app.agent import prompts as P
from app.agent import report as R


def test_네_개가_다_있다():
    assert set(P.PROMPTS) == {
        "loop_plan",
        "loop_review",
        "resume_after_approval",
        "fill_missing_journal",
    }
    for name in P.PROMPTS:
        assert P.read(name).strip()


def test_모르는_이름은_거부한다():
    with pytest.raises(KeyError):
        P.read("없는프롬프트")


def test_빠진_값이_있으면_예외():
    """자리표시가 그대로 새어 나가면 Claude 가 `$next_exp` 를 폴더 이름으로 쓴다."""
    with pytest.raises(KeyError):
        P.render("loop_plan", {"loop_no": 1})


def test_설계_프롬프트가_채워진다():
    text = P.render("loop_plan", {"loop_no": 3, "next_exp": "EXP-004", "context": "맥락"})
    assert "루프 3 회차" in text
    assert "experiments/EXP-004/" in text
    assert "$" not in text


def test_설계_프롬프트가_run_json_규약을_적는다():
    """AI 가 이걸 보고 명세를 쓴다. 규약이 어긋나면 실행기가 거절한다."""
    text = P.render("loop_plan", {"loop_no": 1, "next_exp": "EXP-001", "context": ""})
    assert "entrypoint" in text and "run.entrypoints" in text
    assert "문자열 배열" in text
    assert "학습을 직접 돌리지 마세요" in text
    assert "state/Current.yaml" in text  # 잠금의 이유를 읽게 한다


def test_분석_프롬프트가_Update_Order_를_적는다():
    text = P.render(
        "loop_review",
        {"loop_no": 2, "exp_id": "EXP-002", "exit_state": "done", "exit_code": 0,
         "elapsed": "12분", "context": ""},
    )
    for name in ("result.csv", "analysis.md", "Experiment_log.csv", "Decision_log.md",
                 "Failures.md", "State.yaml"):
        assert name in text
    assert "step,split,metric,value" in text  # 열 규약


def test_분석_프롬프트의_Final_Report_모양이_파서와_맞는다():
    """프롬프트가 요구하는 모양을 파서가 못 읽으면 매 루프가 "기록 빠짐" 이 된다.

    빈 양식 그대로는 값이 없어서 파서가 "안 채움" 으로 본다 — 그게 맞는
    동작이다. 여기서는 **항목 이름이 파서의 이름과 같은지**와, 채워진
    보고서가 9/9 로 읽히는지를 본다.
    """
    text = P.render(
        "loop_review",
        {"loop_no": 1, "exp_id": "EXP-001", "exit_state": "done", "exit_code": 0,
         "elapsed": "1분", "context": ""},
    )
    assert R.parse(text)["hasHeading"] is True
    for _, label, _ in R.FIELDS:
        assert f"- {label}:" in text, label

    # 사람(AI)이 채운 모양으로 바꾸면 9항목이 전부 읽혀야 한다
    filled = "\n".join(
        line + " 채운 값" if line.rstrip().endswith(":") else line
        for line in text.splitlines()
    )
    assert R.parse(filled)["missing"] == []


def test_재개_프롬프트가_같은_입력을_쓰라고_한다():
    text = P.render(
        "resume_after_approval",
        {"request": "pip install peft", "actions": "패키지 설치", "context": ""},
    )
    assert "같은 도구·같은 입력으로 한 번만" in text
    assert "그 호출 하나" in text


def test_기록_보충_프롬프트는_빠진_것만_말한다():
    text = P.render(
        "fill_missing_journal",
        {"exp_id": "EXP-003", "missing": "- analysis.md", "context": ""},
    )
    assert "빠진 것만" in text
    assert "지어내지 마세요" in text


def test_참고_프롬프트와_폴더가_다르다():
    """위 폴더는 사람이 읽는 참고 프롬프트다. `{중괄호}` 를 써서 섞이면 안 된다."""
    import os

    assert P.prompts_dir().endswith(os.path.join("prompts", "loop"))
