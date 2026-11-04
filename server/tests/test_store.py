"""`lab.db` 의 나머지 표.

가장 중요한 두 가지:
  - **NaN 은 숫자 칸에 넣지 않는다.** REAL 에 NaN 을 넣으면 왕복이 깨지고
    비교가 전부 거짓이 되는데, NaN 자체가 "즉시 중단" 신호다.
  - **중복 제거는 코드가 세는 게 아니라 UNIQUE 제약이다.** 프로세스가
    둘이어도 재시작해도 같은 답이 나온다.
"""

import math

import pytest

from app.store import (
    approvals as A,
    commands as C,
    events as E,
    experiments as X,
    loops as L,
    metrics as M,
    notifications as N,
    resources as R,
    usage as U,
)


# --- experiments -------------------------------------------------------------


def test_실험을_넣고_고친다(conn):
    X.upsert(conn, "p", "EXP-001", knob="lr=1e-4")
    X.upsert(conn, "p", "EXP-001", state="running", branch="exp-001")
    found = X.get(conn, "p", "EXP-001")
    assert found["knob"] == "lr=1e-4"  # 준 칸만 고친다
    assert found["state"] == "running"


def test_없는_칸은_거절한다(conn):
    with pytest.raises(ValueError):
        X.upsert(conn, "p", "EXP-001", 비밀="x")


def test_모르는_실험_상태는_거절한다(conn):
    with pytest.raises(ValueError):
        X.set_state(conn, "p", "EXP-001", "돌고있음")


def test_끝난_실험에_끝낸_시각이_적힌다(conn):
    X.set_state(conn, "p", "EXP-001", "running")
    assert X.get(conn, "p", "EXP-001")["started_at"]
    X.set_state(conn, "p", "EXP-001", "done")
    assert X.get(conn, "p", "EXP-001")["ended_at"]


def test_best_는_방향을_따른다(conn):
    X.record_result(conn, "p", "EXP-001", metric_name="loss", metric_value=0.5)
    X.record_result(conn, "p", "EXP-001", metric_name="loss", metric_value=0.9)
    assert X.get(conn, "p", "EXP-001")["best_metric"] == 0.5
    X.record_result(conn, "p", "EXP-002", metric_name="acc", metric_value=0.5, better="higher")
    X.record_result(conn, "p", "EXP-002", metric_name="acc", metric_value=0.9, better="higher")
    assert X.get(conn, "p", "EXP-002")["best_metric"] == 0.9


def test_목록은_실험_번호_역순(conn):
    for exp in ("EXP-001", "EXP-002"):
        X.upsert(conn, "p", exp)
    assert [e["exp_id"] for e in X.listing(conn, "p")] == ["EXP-002", "EXP-001"]


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
    """REAL 에 그대로 넣었다면 여기서 비교가 전부 거짓이 된다."""
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
    E.add(conn, "p", "train", "EXP-001 을 시작했어요", tone="good", ref="EXP-001")
    recent = E.recent(conn, "p")
    assert [e["text"] for e in recent] == ["EXP-001 을 시작했어요", "루프를 시작했어요"]
    assert recent[0]["tone"] == "good"


def test_모르는_tone_은_거절한다(conn):
    with pytest.raises(ValueError):
        E.add(conn, "p", "loop", "x", tone="무지개")


# --- approvals ---------------------------------------------------------------


def test_승인_요청을_올리고_결정한다(conn):
    A.open_request(conn, "p", "toolu_1", tool="Bash", action_key="pkg", request="pip install peft")
    assert [a["request_id"] for a in A.pending(conn, "p")] == ["toolu_1"]
    decided = A.decide(conn, "p", "toolu_1", "approved", grant_id="g-1")
    assert decided["state"] == "approved" and decided["grant_id"] == "g-1"
    assert A.pending(conn, "p") == []


def test_거울을_또_불러도_횟수가_안_올라간다(conn):
    """⚠ 전에는 올라갔다. 그래서 `sync` 를 부를 때마다 횟수가 늘어 **한 번의
    거절이 3회**가 됐다(S9 e2e 가 잡았다). 상한이 2라 정상 요청이 막혔다.

    진짜 재시도는 `bump()` 로 센다.
    """
    A.open_request(conn, "p", "toolu_1", tool="Bash", action_key="pkg")
    again = A.open_request(conn, "p", "toolu_1", tool="Bash", action_key="pkg")
    assert again["attempts"] == 1
    assert len(A.pending(conn, "p")) == 1


def test_반복_횟수를_따로_올릴_수_있다(conn):
    A.open_request(conn, "p", "toolu_1")
    assert A.bump(conn, "p", "toolu_1") == 2


def test_모르는_승인_상태는_거절한다(conn):
    A.open_request(conn, "p", "toolu_1")
    with pytest.raises(ValueError):
        A.decide(conn, "p", "toolu_1", "그냥통과")


def test_없는_요청은_결정할_수_없다(conn):
    with pytest.raises(ValueError):
        A.decide(conn, "p", "없는요청", "approved")


# --- notifications -----------------------------------------------------------


def test_중복_제거_열쇠는_쿨다운_구간을_담는다():
    first = N.dedupe_key("p", "failure", "EXP-001", 300, now_ts=900.0)
    same = N.dedupe_key("p", "failure", "EXP-001", 300, now_ts=1100.0)
    later = N.dedupe_key("p", "failure", "EXP-001", 300, now_ts=1200.0)
    assert first == same  # 같은 5분 구간 (900~1199)
    assert first != later  # 구간이 넘어가면 다시 보낸다


def test_구간_경계에서는_연달아_갈_수_있다():
    """고정 구간 방식의 알려진 한계. 1초 차이로 경계를 넘으면 두 번 간다.
    쿨다운을 "마지막 전송으로부터" 로 바꾸면 없어지지만, 그러면 상태를
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


# --- commands ----------------------------------------------------------------


def test_웹이_보낸_명령을_하나씩_집어간다(conn):
    first = C.push(conn, "pause_loop", project="p")
    C.push(conn, "resume_loop", project="p")
    taken = C.take(conn)
    assert taken["id"] == first and taken["state"] == "taken"
    assert len(C.pending(conn)) == 1
    C.done(conn, first, result={"ok": True})
    assert C.get(conn, first)["result"] == {"ok": True}


def test_모르는_명령은_받지_않는다(conn):
    with pytest.raises(ValueError):
        C.push(conn, "rm -rf /")


def test_집어갈_게_없으면_None(conn):
    assert C.take(conn) is None


# --- resources ---------------------------------------------------------------


def test_GPU_조회_실패도_표본으로_남는다(conn):
    """드라이버 불일치로 nvidia-smi 가 죽어 있어도 "언제부터" 가 남아야 한다."""
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


# --- loop_state --------------------------------------------------------------


def test_루프_상태를_만들고_바꾼다(conn):
    assert L.ensure(conn, "p")["state"] == "idle"
    assert L.set_state(conn, "p", "running", current_job_id=3)["current_job_id"] == 3
    assert L.bump_loop(conn, "p") == 1
    assert L.bump_loop(conn, "p") == 2


def test_모르는_루프_상태는_거절한다(conn):
    with pytest.raises(ValueError):
        L.set_state(conn, "p", "열심히돌고있음")


def test_멈추고_다시_돌린다(conn):
    paused = L.pause(conn, "p", reason="사용량 한도를 기다려요", until="2026-11-04T12:00:00+09:00")
    assert paused["paused"] == 1 and "한도" in paused["paused_reason"]
    resumed = L.resume(conn, "p")
    assert resumed["paused"] == 0 and resumed["paused_reason"] is None


# --- usage_limits ------------------------------------------------------------


def test_실패_원문을_그대로_보관한다(conn):
    """패턴을 코드에 박지 않는다. 나중에 이 원문으로 한도를 구분한다."""
    raw = "Claude usage limit reached. 자세한 문구는 실측 전이에요." * 20
    usage_id = U.record(conn, project="p", raw=raw, exit_code=1)
    kept = U.latest(conn, "p")
    assert kept["raw"] == raw  # 자르지 않는다
    assert kept["exit_code"] == 1
    assert U.open_wait(conn, "p")["id"] == usage_id


def test_풀리면_대기가_닫힌다(conn):
    usage_id = U.record(conn, project="p", raw="막힘")
    U.mark_resumed(conn, usage_id)
    assert U.open_wait(conn, "p") is None


def test_대기_알림은_한_번만(conn):
    usage_id = U.record(conn, project="p", raw="막힘")
    assert U.open_wait(conn, "p")["notified_at"] is None
    U.mark_notified(conn, usage_id)
    assert U.open_wait(conn, "p")["notified_at"]
