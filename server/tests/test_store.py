"""`lab.db`의 알림 표.

**중복 제거는 코드가 세는 게 아니라 UNIQUE 제약이다.** 프로세스가
둘이어도 재시작해도 같은 답이 나온다.
"""

import math

import pytest

from app.store import notifications as N


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
