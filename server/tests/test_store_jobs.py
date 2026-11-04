"""작업 큐.

두 가지를 못박는다.
  - **동시 실행은 0건 또는 1건.** GPU 가 1개다. 코드가 세는 게 아니라
    `ux_jobs_running` UNIQUE 인덱스가 막는다.
  - **상태 전이표.** `done` 인 작업이 다시 `running` 이 되면 기록이 거짓이 된다.
"""

import os
import subprocess
import sys

import pytest

from app.store import jobs as J


def test_넣고_읽는다(conn):
    job_id = J.add(conn, "hook-sandbox", "train", experiment_id="EXP-001", payload={"a": 1})
    job = J.get(conn, job_id)
    assert job["state"] == "queued"
    assert job["payload"] == {"a": 1}  # JSON 으로 왕복한다
    assert job["attempt"] == 0


def test_모르는_종류는_거절한다(conn):
    with pytest.raises(J.StateError):
        J.add(conn, "hook-sandbox", "학습해줘")


def test_우선순위가_높은_것부터_집어간다(conn):
    low = J.add(conn, "p", "plan")
    high = J.add(conn, "p", "plan", priority=5)
    assert J.lease(conn)["id"] == high
    assert J.lease(conn)["id"] == low
    assert J.lease(conn) is None


def test_lease_는_시도_횟수를_올린다(conn):
    job_id = J.add(conn, "p", "plan")
    assert J.lease(conn)["attempt"] == 1
    J.requeue(conn, job_id)
    assert J.lease(conn)["attempt"] == 2


def test_프로젝트와_종류로_걸러_집어간다(conn):
    J.add(conn, "가", "plan")
    train = J.add(conn, "나", "train")
    assert J.lease(conn, project="나")["id"] == train
    J.requeue(conn, train)
    assert J.lease(conn, kinds=("train",))["id"] == train


# --- 단일 슬롯 ---------------------------------------------------------------


def test_돌고_있는_작업은_한_건뿐(conn):
    first = J.add(conn, "p", "train")
    second = J.add(conn, "p", "train")
    J.lease(conn)
    J.start(conn, first, pid=111)
    J.lease(conn)
    with pytest.raises(J.SlotBusy) as exc:
        J.start(conn, second, pid=222)
    assert "GPU 가 1개라" in str(exc.value)
    assert J.running(conn)["id"] == first


def test_끝나면_슬롯을_놓는다(conn):
    first = J.add(conn, "p", "train")
    second = J.add(conn, "p", "train")
    J.lease(conn)
    J.start(conn, first)
    J.finish(conn, first, "done", exit_code=0)
    assert J.running(conn) is None
    J.lease(conn)
    assert J.start(conn, second)["state"] == "running"


def test_승인_대기도_슬롯을_놓는다(conn):
    """사람을 기다리는 동안 GPU 를 잡고 있으면 아무것도 못 나간다."""
    job_id = J.add(conn, "p", "plan")
    J.lease(conn)
    J.start(conn, job_id)
    J.wait_approval(conn, job_id, error="승인 대기")
    assert J.running(conn) is None
    assert J.get(conn, job_id)["state"] == "waiting_approval"


def test_다른_프로세스가_떠도_두_건이_안_된다(conn, isolated_data):
    first = J.add(conn, "p", "train")
    J.lease(conn)
    J.start(conn, first)
    second = J.add(conn, "p", "train")
    J.lease(conn)
    code = (
        "import sys\n"
        "from app import db\n"
        "from app.store import jobs as J\n"
        "with db.open_db() as c:\n"
        "    try:\n"
        "        J.start(c, int(sys.argv[1]))\n"
        "        print('시작됨')\n"
        "    except J.SlotBusy:\n"
        "        print('막힘')\n"
    )
    out = subprocess.run(
        [sys.executable, "-c", code, str(second)],
        capture_output=True,
        text=True,
        env={**os.environ, "PYTHONPATH": os.getcwd()},
        cwd=os.getcwd(),
    )
    assert out.stdout.strip() == "막힘", out.stderr


# --- 상태 전이 ---------------------------------------------------------------


def test_끝난_작업은_되돌릴_수_없다(conn):
    job_id = J.add(conn, "p", "plan")
    J.lease(conn)
    J.start(conn, job_id)
    J.finish(conn, job_id, "done")
    for target in ("running", "queued", "leased"):
        with pytest.raises(J.StateError):
            J.set_state(conn, job_id, target)


@pytest.mark.parametrize("state", ["failed", "timeout"])
def test_실패와_타임아웃은_큐로_돌아간다(conn, state):
    job_id = J.add(conn, "p", "train")
    J.lease(conn)
    J.start(conn, job_id)
    J.finish(conn, job_id, state)
    assert J.requeue(conn, job_id)["state"] == "queued"


def test_queued_에서_바로_running_은_안_된다(conn):
    """lease 를 건너뛰면 두 워커가 같은 작업을 집은 걸 못 잡는다."""
    job_id = J.add(conn, "p", "plan")
    with pytest.raises(J.StateError):
        J.start(conn, job_id)


def test_전이표에_없는_상태는_거절한다(conn):
    job_id = J.add(conn, "p", "plan")
    with pytest.raises(J.StateError):
        J.set_state(conn, job_id, "그런상태없음")


def test_없는_작업은_거절한다(conn):
    with pytest.raises(J.StateError):
        J.set_state(conn, 999, "leased")


def test_finish_로는_취소할_수_없다(conn):
    job_id = J.add(conn, "p", "plan")
    with pytest.raises(J.StateError):
        J.finish(conn, job_id, "cancelled")


def test_끝낸_시각이_적힌다(conn):
    job_id = J.add(conn, "p", "plan")
    J.lease(conn)
    J.start(conn, job_id)
    assert J.get(conn, job_id)["started_at"]
    J.finish(conn, job_id, "failed", error="그냥 실패")
    done = J.get(conn, job_id)
    assert done["ended_at"] and done["error"] == "그냥 실패"


# --- 심장 소리와 통계 --------------------------------------------------------


def test_심장이_멈추면_복구_대상이_된다(conn):
    job_id = J.add(conn, "p", "train")
    J.lease(conn)
    J.start(conn, job_id)
    assert J.stale(conn, 60) == []
    conn.execute("UPDATE jobs SET heartbeat_at='2020-01-01T00:00:00+09:00' WHERE id=?", (job_id,))
    assert [j["id"] for j in J.stale(conn, 60)] == [job_id]


def test_방금_시작한_작업은_멈춘_게_아니다(conn):
    """시간대 꼬리표(+09:00)와 'localtime' 을 섞으면 9시간만큼 다 멈춘 것으로
    보인다. 그러면 복구가 돌고 있는 학습을 가로챈다."""
    job_id = J.add(conn, "p", "train")
    J.lease(conn)
    J.start(conn, job_id)
    for window in (1, 60, 600, 3600, 86400):
        assert J.stale(conn, window) == [], window
    assert J.get(conn, job_id)["heartbeat_at"]


def test_heartbeat_이_시각을_올린다(conn):
    job_id = J.add(conn, "p", "train")
    J.lease(conn)
    conn.execute("UPDATE jobs SET heartbeat_at='2020-01-01T00:00:00+09:00' WHERE id=?", (job_id,))
    J.heartbeat(conn, job_id)
    assert J.get(conn, job_id)["heartbeat_at"] > "2021"


def test_상태별_개수(conn):
    J.add(conn, "p", "plan")
    J.add(conn, "p", "train")
    J.lease(conn)
    assert J.counts(conn, "p") == {"queued": 1, "leased": 1}


def test_목록은_최근부터(conn):
    first = J.add(conn, "p", "plan")
    second = J.add(conn, "p", "train")
    assert [j["id"] for j in J.listing(conn, "p")] == [second, first]
    assert J.listing(conn, "p", states=("queued",))
    assert J.listing(conn, "다른프로젝트") == []
