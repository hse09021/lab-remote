"""실행 — 진짜 tmux 로 띄운다 (scope 는 conftest 가 끈다)."""

import os
import shutil
import subprocess
import time

import pytest

from app import files, inbox, runs, watch

pytestmark = pytest.mark.skipif(not runs.tmux_bin(), reason="tmux 가 없어요")


@pytest.fixture()
def proj(project):
    yield "demo"
    # 남은 tmux 서버를 정리한다
    folder = runs.runs_dir(project)
    if os.path.isdir(folder):
        for run_id in os.listdir(folder):
            if runs.ID_RE.match(run_id):
                sock, _ = runs._session(run_id, "demo")
                subprocess.run([runs.tmux_bin(), "-L", sock, "kill-server"], capture_output=True)


def wait_state(project, run_id, want, timeout=8.0):
    end = time.time() + timeout
    while time.time() < end:
        got = runs.get(project, run_id)
        if got["state"] in want:
            return got
        time.sleep(0.1)
    raise AssertionError(f"{run_id} 가 {want} 가 안 됐어요: {runs.get(project, run_id)['state']}")


def test_끝까지_돌고_로그와_종료코드를_남긴다(proj, project):
    r = runs.start(proj, "echo hi; pwd", name="hello")
    assert r["id"] == "EXP-001" and r["state"] == "running"
    assert r["attach"].startswith("tmux -L labremote-demo-EXP-001 attach")
    done = wait_state(proj, "EXP-001", {"done"})
    assert done["exitCode"] == 0
    text = runs.log_tail(proj, "EXP-001")["text"]
    assert "hi" in text and project in text and "종료코드 0" in text
    assert runs.start(proj, "true")["id"] == "EXP-002"


def test_실패(proj):
    runs.start(proj, "exit 3")
    got = wait_state(proj, "EXP-001", {"failed"})
    assert got["exitCode"] == 3 and got["stateLabel"] == "실패"


def test_중지는_프로그램이_정리할_시간을_준다(proj):
    script = 'trap "echo saving; sleep 0.3; echo saved; exit 130" INT; while true; do sleep 0.1; done'
    runs.start(proj, script)
    time.sleep(0.5)
    runs.stop(proj, "EXP-001")
    got = wait_state(proj, "EXP-001", {"stopped"})
    assert got["exitCode"] == 130
    assert "saved" in runs.log_tail(proj, "EXP-001")["text"]  # tee 가 같이 죽지 않았다


def test_프로세스가_사라지면_끊김(proj):
    runs.start(proj, "sleep 30")
    time.sleep(0.3)
    sock, _ = runs._session("EXP-001", "demo")
    subprocess.run([runs.tmux_bin(), "-L", sock, "kill-server"], capture_output=True)
    got = wait_state(proj, "EXP-001", {"cut"})
    assert "종료코드 없이" in got["reason"]


def test_재부팅이면_그렇게_적는다(proj, project, monkeypatch):
    runs.start(proj, "sleep 30")
    time.sleep(0.3)
    sock, _ = runs._session("EXP-001", "demo")
    subprocess.run([runs.tmux_bin(), "-L", sock, "kill-server"], capture_output=True)
    monkeypatch.setattr(runs, "boot_id", lambda: "다른-부팅")
    got = wait_state(proj, "EXP-001", {"cut"})
    assert "다시 켜지면서" in got["reason"]


def test_거절(proj, project):
    with pytest.raises(runs.RunError, match="명령"):
        runs.start(proj, "  ")
    with pytest.raises(runs.RunError, match="위치"):
        runs.start(proj, "true", cwd="../")
    with pytest.raises(runs.RunError, match="보호"):
        runs.start(proj, "true", env="base")
    with pytest.raises(runs.RunError):
        runs.get(proj, "../../etc")
    assert not os.path.exists(runs.runs_dir(project)) or os.listdir(runs.runs_dir(project)) in ([], [".lock"])


def test_실행_중이면_실행_위치를_못_지운다(proj, project):
    runs.start(proj, "sleep 30", cwd="src")
    time.sleep(0.2)
    with pytest.raises(files.FileRefused, match="실행 중"):
        files.delete(project, project, "src", confirm="src")
    runs.stop(proj, "EXP-001", force=True)
    wait_state(proj, "EXP-001", {"stopped"})
    files.delete(project, project, "src", confirm="src")


def test_지표_파일의_마지막_값(proj, project):
    runs.start(proj, "true")
    wait_state(proj, "EXP-001", {"done"})
    os.makedirs(os.path.join(project, "runs", "a"))
    with open(os.path.join(project, "runs", "a", "metrics.csv"), "w") as fh:
        fh.write("epoch,loss,val_acc\n1,0.9,0.5\n2,0.7,0.61\n")
    got = runs.metrics_summary(proj, "EXP-001")
    assert got["file"] == "runs/a/metrics.csv" and got["format"] == "wide"
    assert got["last"] == {"epoch": 2, "loss": 0.7, "val_acc": 0.61}


def test_긴_형식_지표(proj, project):
    runs.start(proj, "true")
    wait_state(proj, "EXP-001", {"done"})
    with open(os.path.join(project, "metrics.csv"), "w") as fh:
        fh.write("step,split,metric,value\n1,train,loss,0.9\n1,val,acc,0.5\n2,train,loss,0.8\n")
    got = runs.metrics_summary(proj, "EXP-001")
    assert got["format"] == "long"
    assert got["last"] == {"train/loss": 0.8, "val/acc": 0.5, "step": 2}


def test_감시가_끝남과_실패를_Inbox_에_넣는다(proj, conn):
    runs.start(proj, "true")
    runs.start(proj, "exit 1")
    time.sleep(1.5)
    changed = watch.tick(conn)
    assert {r["state"] for r in changed} == {"done", "failed"}
    items = inbox.items(conn)
    titles = sorted(i["title"] for i in items)
    assert titles == ["EXP-001 끝남", "EXP-002 실패"]
    assert inbox.badge(conn) == 1  # 실패만 "처리할 것"
    assert watch.tick(conn) == []  # 두 번 알리지 않는다


@pytest.mark.skipif(not shutil.which("bash"), reason="bash 가 없어요")
def test_실행_스크립트는_명령을_한_덩어리로_넘긴다(proj, project):
    runs.start(proj, "printf '%s\\n' \"$(echo 'a b')\" ; echo $((1+2))")
    wait_state(proj, "EXP-001", {"done"})
    text = runs.log_tail(proj, "EXP-001")["text"]
    assert "a b" in text and "\n3\n" in text


def test_화면이_먼저_알아채도_감시가_한_번_알린다(proj, conn):
    runs.start(proj, "exit 2")
    wait_state(proj, "EXP-001", {"failed"})  # 화면(get)이 먼저 상태를 적었다
    assert [r["id"] for r in watch.tick(conn)] == ["EXP-001"]
    assert watch.tick(conn) == []
    assert [i["title"] for i in inbox.items(conn)] == ["EXP-001 실패"]


def test_옛_기록은_한꺼번에_알리지_않는다(proj, project, conn):
    runs.start(proj, "true")
    wait_state(proj, "EXP-001", {"done"})
    record = runs._load(project, "EXP-001")
    record.pop("announced")
    runs._save(project, record)
    assert watch.tick(conn) == []
