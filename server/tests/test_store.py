"""`lab.db`의 나머지 표.

가장 중요한 두 가지:
  - **NaN은 숫자 칸에 넣지 않는다.** REAL에 NaN을 넣으면 왕복이 깨지고
    비교가 전부 거짓이 되는데, NaN 자체가 "즉시 중단" 신호다.
  - **중복 제거는 코드가 세는 게 아니라 UNIQUE 제약이다.** 프로세스가
    둘이어도 재시작해도 같은 답이 나온다.
"""

import math

import pytest

from app.store import (
    events as E,
    metrics as M,
    notifications as N,
    resources as R,
)


# --- metrics -----------------------------------------------------------------


def test_지표를_넣고_읽는다(conn):
    for step, value in enumerate([2.0, 1.5, 1.2]):
        M.add(conn, "p", "EXP-001", "loss", value, step=step)
    series = M.series(conn, "p", "EXP-001", "loss")
    assert [r["value"] for r in series] == [2.0, 1.5, 1.2]
    assert M.last(conn, "p", "EXP-001", "loss")["value"] == 1.2


@pytest.mark.parametrize(
    "value,flag",
    [
        (float("nan"), "nan"),
        (float("inf"), "inf"),
        (float("-inf"), "-inf"),
        ("숫자가아님", "nan"),
    ],
)
def test_숫자가_아니면_깃발로_남는다(conn, value, flag):
    M.add(conn, "p", "EXP-001", "loss", value)
    row = M.last(conn, "p", "EXP-001", "loss")
    assert row["value"] is None
    assert row["flag"] == flag


def test_NaN_은_왕복이_깨지지_않는다(conn):
    """REAL에 그대로 넣었다면 여기서 비교가 전부 거짓이 된다."""
    M.add(conn, "p", "EXP-001", "loss", float("nan"))
    flagged = M.has_flag(conn, "p", "EXP-001")
    assert len(flagged) == 1
    assert flagged[0]["flag"] == "nan"
    assert not any(
        r["value"] is not None and math.isnan(r["value"])
        for r in M.series(conn, "p", "EXP-001", "loss")
    )


def test_None_은_깃발도_없다(conn):
    M.add(conn, "p", "EXP-001", "loss", None)
    assert M.has_flag(conn, "p", "EXP-001") == []


# --- events ------------------------------------------------------------------


def test_사건을_최근부터_읽는다(conn):
    E.add(conn, "p", "loop", "루프를 시작했어요")
    E.add(conn, "p", "train", "EXP-001을 시작했어요", tone="good", ref="EXP-001")
    recent = E.recent(conn, "p")
    assert [e["text"] for e in recent] == ["EXP-001을 시작했어요", "루프를 시작했어요"]
    assert recent[0]["tone"] == "good"


def test_모르는_tone_은_거절한다(conn):
    with pytest.raises(ValueError):
        E.add(conn, "p", "loop", "x", tone="무지개")


# --- notifications -----------------------------------------------------------


def test_중복_제거_열쇠는_쿨다운_구간을_담는다():
    first = N.dedupe_key("p", "failure", "EXP-001", 300, now_ts=900.0)
    same = N.dedupe_key("p", "failure", "EXP-001", 300, now_ts=1100.0)
    later = N.dedupe_key("p", "failure", "EXP-001", 300, now_ts=1200.0)
    assert first == same  # 같은 5분 구간 (900~1199)
    assert first != later  # 구간이 넘어가면 다시 보낸다


def test_구간_경계에서는_연달아_갈_수_있다():
    """고정 구간 방식의 알려진 한계. 1초 차이로 경계를 넘으면 두 번 간다.
    쿨다운을 "마지막 전송으로부터"로 바꾸면 없어지지만, 그러면 상태를
    읽고 쓰는 경쟁이 생겨 프로세스가 둘일 때 답이 흔들린다."""
    before = N.dedupe_key("p", "failure", "x", 300, now_ts=1199.0)
    after = N.dedupe_key("p", "failure", "x", 300, now_ts=1200.0)
    assert before != after


def test_쿨다운이_0_이면_안_묵힌다():
    first = N.dedupe_key("p", "approval", "x", 0, now_ts=1000.0)
    second = N.dedupe_key("p", "approval", "x", 0, now_ts=1000.001)
    assert first != second


def test_같은_열쇠는_두_번_못_넣는다(conn):
    key = N.dedupe_key("p", "failure", "EXP-001", 300, now_ts=1000.0)
    assert N.claim(conn, key, project="p", kind="failure") is not None
    assert N.claim(conn, key, project="p", kind="failure") is None


def test_보냈는지_실패했는지_적는다(conn):
    first = N.claim(conn, "키1", project="p", kind="failure")
    N.mark_sent(conn, first["id"], 204)
    assert N.get(conn, first["id"])["state"] == "sent"
    second = N.claim(conn, "키2", project="p", kind="failure")
    N.mark_failed(conn, second["id"], error="그물이 없어요", status=500)
    failed = N.get(conn, second["id"])
    assert failed["state"] == "failed" and failed["error"] == "그물이 없어요"


# --- resources ---------------------------------------------------------------


def test_GPU_조회_실패도_표본으로_남는다(conn):
    """드라이버 불일치로 nvidia-smi가 죽어 있어도 "언제부터"가 남아야 한다."""
    R.add(conn, gpu_available=False, note="Driver/library version mismatch")
    latest = R.latest(conn)
    assert latest["gpu_available"] == 0
    assert "mismatch" in latest["note"]


def test_최근_표본부터_읽는다(conn):
    R.add(conn, gpu_available=True, gpu_util=10.0)
    R.add(conn, gpu_available=True, gpu_util=20.0)
    assert [r["gpu_util"] for r in R.recent(conn)] == [20.0, 10.0]


def test_오래된_표본은_버린다(conn):
    for index in range(10):
        R.add(conn, gpu_available=True, gpu_util=float(index))
    assert R.prune(conn, keep=3) == 7
    assert len(R.recent(conn)) == 3
