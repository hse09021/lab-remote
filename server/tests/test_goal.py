"""🎯 `Config.yaml` 의 `goal` 을 **실제로** 읽는다.

전에는 `_numbers` 가 지표 이름을 `"loss"` 로 박아 두고 비교를 `<=` 로 박아
뒀다. 그래서

- `goal.metric: accuracy` 라고 적어도 `loss` 를 읽었고 (조용히)
- 클수록 좋은 지표의 성공 판정이 **뒤집혀** 있었다 (조용히)

둘 다 "AI 의 말을 믿지 않는다"(spec III-4)의 근거를 무너뜨린다 — 대조하는
숫자가 틀리면 대조가 거짓말이 된다.
"""

import os

import pytest

from app.orchestrator import loop as L

from test_orchestrator_loop import healthy_gpu, ready  # noqa: F401


def write_goal(root, body):
    path = os.path.join(root, "specifications", "Config.yaml")
    with open(path, encoding="utf-8") as fh:
        old = fh.read()
    head = old.split("goal:", 1)[1].split("\n\n", 1)
    rest = old.split("goal:", 1)[0]
    tail = ("\n\n" + head[1]) if len(head) > 1 else "\n"
    with open(path, "w", encoding="utf-8") as fh:
        fh.write(rest + body.rstrip("\n") + tail)


def write_result(root, exp_id, rows):
    folder = os.path.join(root, "experiments", exp_id)
    os.makedirs(folder, exist_ok=True)
    with open(os.path.join(folder, "result.csv"), "w", encoding="utf-8") as fh:
        fh.write("step,split,metric,value\n")
        for n, (metric, value) in enumerate(rows, 1):
            fh.write(f"{n},val,{metric},{value}\n")


# --- goal 읽기 -------------------------------------------------------------------


def test_metric_이름을_읽는다(ready):
    write_goal(ready, 'goal:\n  metric: accuracy\n  threshold: "0.9"\n  direction: higher')
    got = L._goal(ready)
    assert got["metric"] == "accuracy"
    assert got["threshold"] == pytest.approx(0.9)
    assert got["direction"] == "higher"


def test_비어_있으면_loss_로_본다(ready):
    write_goal(ready, 'goal:\n  metric: "[주 지표]"\n  threshold: "[임계값]"')
    got = L._goal(ready)
    assert got["metric"] == L.DEFAULT_METRIC == "loss"
    assert got["threshold"] is None
    assert any("goal.metric" in n for n in got["notes"])
    assert any("threshold" in n for n in got["notes"])


def test_방향을_안_적으면_lower(ready):
    write_goal(ready, 'goal:\n  metric: loss\n  threshold: "1.5"')
    assert L._goal(ready)["direction"] == "lower"


@pytest.mark.parametrize("word", ["lower", "min", "minimize", "작을수록", "LOWER"])
def test_lower_를_여러_말로_받는다(ready, word):
    write_goal(ready, f'goal:\n  metric: loss\n  threshold: "1.5"\n  direction: {word}')
    assert L._goal(ready)["direction"] == "lower"


@pytest.mark.parametrize("word", ["higher", "max", "maximize", "클수록"])
def test_higher_를_여러_말로_받는다(ready, word):
    write_goal(ready, f'goal:\n  metric: acc\n  threshold: "0.9"\n  direction: {word}')
    assert L._goal(ready)["direction"] == "higher"


def test_모르는_방향은_추측하지_않는다(ready):
    """틀린 방향으로 비교하면 **실패를 성공으로 읽는다** — 아무 판정도 안
    하는 것보다 나쁘다."""
    write_goal(ready, 'goal:\n  metric: loss\n  threshold: "1.5"\n  direction: 적당히')
    got = L._goal(ready)
    assert got["direction"] == ""
    assert any("goal.direction" in n for n in got["notes"])


def test_숫자가_아닌_임계값을_말한다(ready):
    write_goal(ready, 'goal:\n  metric: loss\n  threshold: "낮게"')
    got = L._goal(ready)
    assert got["threshold"] is None
    assert any("숫자가 아니에요" in n for n in got["notes"])


# --- 성공 판정 -------------------------------------------------------------------


def test_작을수록_좋은_지표(ready):
    write_goal(ready, 'goal:\n  metric: loss\n  threshold: "1.5"\n  direction: lower')
    write_result(ready, "EXP-001", [("loss", 1.2)])
    got = L._numbers(ready, "EXP-001")
    assert got["metric"] == "loss"
    assert got["value"] == pytest.approx(1.2)
    assert got["success"] is True

    write_result(ready, "EXP-002", [("loss", 1.9)])
    assert L._numbers(ready, "EXP-002")["success"] is False


def test_클수록_좋은_지표(ready):
    """**이게 뒤집혀 있었다.** accuracy 0.95 를 "임계값 0.9 미달" 로 읽었다."""
    write_goal(ready, 'goal:\n  metric: accuracy\n  threshold: "0.9"\n  direction: higher')
    write_result(ready, "EXP-001", [("accuracy", 0.95)])
    got = L._numbers(ready, "EXP-001")
    assert got["metric"] == "accuracy"
    assert got["value"] == pytest.approx(0.95)
    assert got["success"] is True

    write_result(ready, "EXP-002", [("accuracy", 0.80)])
    assert L._numbers(ready, "EXP-002")["success"] is False


def test_goal_의_지표를_result_csv_에서_찾는다(ready):
    """전에는 `loss` 만 찾아서, accuracy 만 있는 result.csv 에서 값이 `None`
    이었다 — 그러면 대조가 아예 안 돌고 아무도 모른다."""
    write_goal(ready, 'goal:\n  metric: accuracy\n  threshold: "0.9"\n  direction: higher')
    write_result(ready, "EXP-001", [("accuracy", 0.95), ("loss", 99.0)])
    got = L._numbers(ready, "EXP-001")
    assert got["metric"] == "accuracy"
    assert got["value"] == pytest.approx(0.95)


def test_방향을_모르면_성공_판정을_접는다(ready):
    write_goal(ready, 'goal:\n  metric: loss\n  threshold: "1.5"\n  direction: 적당히')
    write_result(ready, "EXP-001", [("loss", 1.2)])
    got = L._numbers(ready, "EXP-001")
    assert got["value"] == pytest.approx(1.2)
    assert got["success"] is None
    assert got["notes"]


def test_임계값이_없으면_성공_판정을_접는다(ready):
    write_goal(ready, 'goal:\n  metric: loss\n  threshold: "[임계값]"')
    write_result(ready, "EXP-001", [("loss", 1.2)])
    got = L._numbers(ready, "EXP-001")
    assert got["value"] == pytest.approx(1.2)
    assert got["success"] is None


# --- 템플릿 ----------------------------------------------------------------------


def test_템플릿에_direction_이_있다():
    """템플릿에 없으면 새 프로젝트는 방향을 적을 자리를 모른다."""
    path = os.path.join(
        os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
        "app", "templates", "project", "specifications", "Config.yaml.tmpl",
    )
    body = open(path, encoding="utf-8").read()
    assert "direction:" in body
    assert "lower" in body and "higher" in body
