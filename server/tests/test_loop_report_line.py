"""`up --once` 가 **왜** 멈췄는지 한 줄로 말하는가 + 앞단 실행도 로그에 남는가.

실측 2026-11-05: 출력이 `hook-sandbox: 멈춤 · resume` 뿐이어서 사람이
`lab.db` 와 세션 전사를 직접 뒤져야 원인을 알 수 있었다. 사유는 이미
`steps` 안에 있었는데 **화면에 안 나왔다.** 그리고 앞단으로 돌리면
`data/logs/orchestrator.log` 가 아예 안 생겨서 나중에 찾을 길이 없었다.
"""

import os

import pytest

from app.orchestrator.__main__ import line_for, log_path, say, stop_reason


def test_완주는_실험_번호까지_말한다():
    assert line_for("p", {"ok": True, "experimentId": "EXP-007"}) == "p: 완주 · EXP-007"


def test_멈춘_단계의_사유를_가져온다():
    got = {
        "ok": False,
        "stoppedAt": "plan",
        "steps": [{"stage": "plan", "reason": "설계가 없어요 (run.json 을 안 썼어요)"}],
    }
    assert stop_reason(got) == "설계가 없어요 (run.json 을 안 썼어요)"
    assert line_for("p", got) == "p: 멈춤 · plan · 설계가 없어요 (run.json 을 안 썼어요)"


def test_맨_위의_사유가_이긴다():
    got = {"ok": False, "stoppedAt": "resume", "reason": "이어 갔는데 설계가 안 끝났어요", "steps": []}
    assert stop_reason(got) == "이어 갔는데 설계가 안 끝났어요"


def test_승인_대기는_무엇을_기다리는지_말한다():
    got = {
        "ok": False,
        "stoppedAt": "approval",
        "waiting": [
            {"action_key": "unclassified", "request": "git -C /x diff"},
            {"action_key": "net", "request": "https://pypi.org/x"},
        ],
    }
    said = stop_reason(got)
    assert "2건" in said and "unclassified" in said and "git -C /x diff" in said
    assert "외 1건" in said
    assert "approvals list" in said


def test_승인_대기가_단계_안에_있어도_찾는다():
    got = {
        "ok": False,
        "stoppedAt": "approval",
        "steps": [{"stage": "plan", "waiting": [{"action_key": "pkg", "request": "pip install peft"}]}],
    }
    assert "pip install peft" in stop_reason(got)


def test_판정_어긋남을_말한다():
    got = {
        "ok": False,
        "stoppedAt": "review",
        "steps": [
            {
                "stage": "review",
                "disagree": True,
                "saidSuccess": True,
                "numbers": {"success": False},
            }
        ],
    }
    said = stop_reason(got)
    assert "판정" in said and "result.csv" in said


def test_기록이_덜_갱신된_것도_말한다():
    got = {
        "ok": False,
        "stoppedAt": "review",
        "steps": [
            {"stage": "review", "updateOrder": {"ok": False, "missing": ["analysis", "state"]}}
        ],
    }
    assert "analysis, state" in stop_reason(got)


def test_사유를_모르면_지어내지_않는다():
    got = {"ok": False, "stoppedAt": "train", "steps": [{"stage": "train"}]}
    assert stop_reason(got) == ""
    assert line_for("p", got) == "p: 멈춤 · train"


def test_앞단_실행도_로그에_남는다(sandboxed):
    """`say()` 는 화면과 로그에 **같은 문장**을 남긴다."""
    say("hook-sandbox: 멈춤 · plan · 설계가 없어요")
    path = log_path()
    assert os.path.exists(path), path
    with open(path, encoding="utf-8") as fh:
        body = fh.read()
    assert "hook-sandbox: 멈춤 · plan · 설계가 없어요" in body
    assert body.startswith("20")  # 시각이 앞에 붙는다


def test_로그를_못_써도_멈추지_않는다(sandboxed, monkeypatch):
    """로그는 진단용이다. 쓰기 실패가 루프를 멈추면 안 된다."""
    import app.orchestrator.__main__ as M

    def boom(*a, **kw):
        raise OSError("디스크가 꽉 찼어요")

    monkeypatch.setattr(M.os, "makedirs", boom)
    say("한 줄")  # 던지지 않는다


def test_학습_실패가_먼저_나온다():
    """실패해도 C 는 돌린다 — 그러면 멈춘 자리는 `review` 가 된다.

    실측 2026-11-05: `systemd-run` 이 버스를 못 찾아 학습이 즉사했는데 화면에는
    `멈춤 · review · 기록이 덜 갱신됐어요` 만 나왔다. 진짜 원인이 한 칸 뒤로
    밀려서 사람이 로그를 직접 뒤져야 했다.
    """

    class Outcome:
        state = "failed"
        exit_code = 1

    got = {
        "ok": False,
        "stoppedAt": "review",
        "steps": [
            {"stage": "plan", "ok": True, "experimentId": "EXP-007"},
            {"stage": "train", "ok": False, "experimentId": "EXP-007", "outcome": Outcome()},
            {"stage": "review", "updateOrder": {"ok": False, "missing": ["result.csv"]}},
        ],
    }
    said = stop_reason(got)
    assert said.startswith("학습이 안 됐어요 (failed · 종료코드 1)")
    assert "experiments/EXP-007/output/train.log" in said
    assert "기록이 덜 갱신됐어요: result.csv" in said


def test_학습이_됐으면_그_말은_안_붙는다():
    got = {
        "ok": False,
        "stoppedAt": "review",
        "steps": [
            {"stage": "train", "ok": True},
            {"stage": "review", "updateOrder": {"ok": False, "missing": ["analysis.md"]}},
        ],
    }
    assert stop_reason(got) == "기록이 덜 갱신됐어요: analysis.md"
