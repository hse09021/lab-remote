"""③의 웹 UI 가 읽을 상태 파일.

**키 집합이 목업 JSON 과 같아야 한다.** `web/src/api/mock/*.json` 을 직접
읽어 대조한다 — `tests/test_policy.py` 가 `permissions.json` 에 하는 방식
그대로다. 어긋나면 ③에서 화면이 비는데, 그때는 원인을 찾기 어렵다.
"""

import json
import os

import pytest

from app import db, registry
from app.monitor import snapshot as S
from app.store import events as E
from app.store import experiments as X
from app.store import jobs as J
from app.store import loops as L
from tests.conftest import REPO_ROOT

MOCK = REPO_ROOT / "web" / "src" / "api" / "mock"


def mock_json(name):
    with open(MOCK / name, encoding="utf-8") as fh:
        return json.load(fh)


@pytest.fixture()
def ready(project, project_root, conn):
    registry.register(project_root, "hook-sandbox")
    L.ensure(conn, "hook-sandbox")
    return conn


def snap(conn, root="", **kw):
    return S.build(conn, "hook-sandbox", root=root, **kw)


# --- 목업 계약과 키 대조 --------------------------------------------------------


def test_dashboard_키가_목업과_같다(ready, project_root):
    got = snap(ready, project_root)["dashboard"]
    assert set(got) == set(mock_json("dashboard.json"))


def test_metric_타일_키가_목업과_같다(ready, project_root):
    """목업 타일은 선택 키를 다 쓴다. 우리 쪽이 더 적으면 안 된다."""
    want = set(mock_json("dashboard.json")["metrics"][0])
    for tile in snap(ready, project_root)["dashboard"]["metrics"]:
        assert want <= set(tile), sorted(want - set(tile))


def test_자원_바_키가_목업과_같다(ready, project_root):
    want = set(mock_json("dashboard.json")["resources"][0])
    for meter in snap(ready, project_root)["dashboard"]["resources"]:
        assert set(meter) == want


def test_학습_곡선_키가_목업과_같다(ready, project_root):
    want = set(mock_json("dashboard.json")["learningCurve"])
    assert set(snap(ready, project_root)["dashboard"]["learningCurve"]) == want


def test_승인_배너_키가_목업과_같다(ready, project_root):
    want = set(mock_json("dashboard.json")["approval"])
    pending = [{"actions": [{"action": "pkg", "name": "패키지 설치"}]}]
    got = snap(ready, project_root, pending=pending)["dashboard"]["approval"]
    assert set(got) == want
    assert got["count"] == 1
    assert "패키지 설치" in got["text"]


def test_승인이_없으면_null(ready, project_root):
    assert snap(ready, project_root)["dashboard"]["approval"] is None


def test_실험_키가_목업과_같다(ready, project_root):
    X.upsert(ready, "hook-sandbox", "EXP-001", knob="rank 32", state="done", best_metric=0.79)
    want = set(mock_json("experiments.json")[0])
    for item in snap(ready, project_root)["experiments"]:
        assert set(item) == want


def test_사건_키가_목업과_같다(ready, project_root):
    E.add(ready, "hook-sandbox", "결정", "EXP-001 을 시작했어요", tone="good")
    want = set(mock_json("events.json")[0])
    for item in snap(ready, project_root)["events"]:
        assert set(item) == want


def test_사건_tone_은_목업_어휘뿐(ready, project_root):
    """`EventEntry.tone` 은 warn·success·neutral 셋뿐이다."""
    for tone in ("info", "good", "attention", "bad"):
        E.add(ready, "hook-sandbox", "k", "t", tone=tone)
    tones = {e["tone"] for e in snap(ready, project_root)["events"]}
    assert tones <= {"warn", "success", "neutral"}


def test_실험_상태는_목업_어휘뿐(ready, project_root):
    for state in ("planned", "running", "done", "failed", "stopped"):
        X.upsert(ready, "hook-sandbox", f"EXP-{state[:3]}", state=state)
    states = {e["state"] for e in snap(ready, project_root)["experiments"]}
    assert states <= {"queued", "running", "done", "failed", "stopped"}


# --- 아무것도 안 돌았을 때도 화면이 찬다 -----------------------------------------


def test_빈_프로젝트도_타일이_있다(ready, project_root):
    got = snap(ready, project_root)["dashboard"]
    assert len(got["metrics"]) >= 3
    assert all(tile["label"] for tile in got["metrics"])
    assert got["learningCurve"]["epochs"] == []


def test_권한_프리셋_이름을_보여_준다(ready, project_root):
    assert snap(ready, project_root)["dashboard"]["modeLabel"] == "수동제어"


def test_루프_문구를_만든다(ready, project_root):
    L.set_state(ready, "hook-sandbox", "running")
    L.bump_loop(ready, "hook-sandbox")
    label = snap(ready, project_root)["dashboard"]["loopLabel"]
    assert label == "루프 1회차 · 실행 중"


def test_멈춤_상태가_실린다(ready, project_root):
    L.pause(ready, "hook-sandbox", reason="한도를 기다려요")
    assert snap(ready, project_root)["dashboard"]["loopPaused"] is True


# --- GPU 조회 실패가 정상 경로 ---------------------------------------------------


def test_GPU_가_안_보이면_조회_불가로_보여_준다(ready, project_root, monkeypatch):
    from app.monitor import gpu as G

    monkeypatch.setattr(
        G, "probe", lambda: {"available": False, "reason": "mismatch", "devices": [], "driver": {"ok": False}}
    )
    got = snap(ready, project_root)["dashboard"]
    gpu_row = [r for r in got["resources"] if r["label"] == "GPU"][0]
    assert gpu_row["value"] == "조회 불가"
    assert gpu_row["tone"] == "attention"


def test_드라이버_상태가_raw_에_남는다(ready, project_root):
    raw = snap(ready, project_root)["raw"]
    assert "driver" in raw
    assert set(raw["driver"]) >= {"ok", "mismatch", "kernel", "userland"}


# --- 학습 곡선 ----------------------------------------------------------------


def test_학습_곡선은_loss_값을_담는다(ready, project_root):
    """좌표가 아니라 값이다 — 그리는 쪽이 스케일을 계산한다 (목업 계약)."""
    exp = os.path.join(project_root, "experiments", "EXP-001")
    os.makedirs(exp, exist_ok=True)
    with open(os.path.join(exp, "result.csv"), "w", encoding="utf-8") as fh:
        fh.write("step,split,metric,value\n1,train,loss,2.0\n1,val,loss,2.2\n2,train,loss,1.0\n2,val,loss,1.1\n")
    job = J.add(ready, "hook-sandbox", "train", experiment_id="EXP-001")
    J.lease(ready)
    J.start(ready, job)

    curve = snap(ready, project_root)["dashboard"]["learningCurve"]
    assert curve["epochs"] == [1, 2]
    assert curve["train"] == [2.0, 1.0]
    assert curve["val"] == [2.2, 1.1]
    assert curve["currentEpoch"] == 2
    assert curve["yMax"] == 2.2
    assert curve["title"] == "학습 곡선 · EXP-001"


def test_val_이_빠진_step_은_None_으로_둔다(ready, project_root):
    """0 으로 메우면 그래프가 바닥을 찍는다. 끊어진 선이 사실이다."""
    exp = os.path.join(project_root, "experiments", "EXP-001")
    os.makedirs(exp, exist_ok=True)
    with open(os.path.join(exp, "result.csv"), "w", encoding="utf-8") as fh:
        fh.write("step,split,metric,value\n1,train,loss,2.0\n2,train,loss,1.0\n2,val,loss,1.1\n")
    job = J.add(ready, "hook-sandbox", "train", experiment_id="EXP-001")
    J.lease(ready)
    J.start(ready, job)
    curve = snap(ready, project_root)["dashboard"]["learningCurve"]
    assert curve["val"] == [None, 1.1]


def test_W_B_링크는_자리표시다(ready, project_root):
    """없는 링크를 지어내지 않는다 (`CLAUDE.md` 규칙)."""
    assert snap(ready, project_root)["dashboard"]["learningCurve"]["wandbHref"] == S.WANDB_PLACEHOLDER


def test_result_csv_형식이_틀리면_raw_에_경고(ready, project_root):
    exp = os.path.join(project_root, "experiments", "EXP-001")
    os.makedirs(exp, exist_ok=True)
    with open(os.path.join(exp, "result.csv"), "w", encoding="utf-8") as fh:
        fh.write("epoch,train_loss\n1,2.0\n")
    job = J.add(ready, "hook-sandbox", "train", experiment_id="EXP-001")
    J.lease(ready)
    J.start(ready, job)
    assert any("넓은 형식" in w for w in snap(ready, project_root)["raw"]["resultWarnings"])


# --- 쓰기 ---------------------------------------------------------------------


def test_상태_파일을_원자적으로_쓴다(ready, project_root, isolated_data):
    path = S.write(ready, "hook-sandbox", root=project_root)
    assert path == os.path.join(str(isolated_data), "status", "hook-sandbox.json")
    data = S.read("hook-sandbox")
    assert data["project"] == "hook-sandbox"
    assert data["version"] == S.VERSION
    assert set(data) == {"version", "project", "generatedAt", "dashboard", "experiments", "events", "raw"}


def test_없는_상태_파일은_빈_dict(isolated_data):
    assert S.read("처음보는프로젝트") == {}


def test_다른_프로젝트의_실행_작업은_안_섞인다(ready, project_root, tmp_path):
    other = tmp_path / "projects" / "다른프로젝트"
    other.mkdir(parents=True)
    registry.register(str(other), "other-proj")
    job = J.add(ready, "other-proj", "train", experiment_id="EXP-900")
    J.lease(ready)
    J.start(ready, job)
    got = snap(ready, project_root)
    assert got["raw"]["job"] is None
    assert got["dashboard"]["metrics"][0]["value"] == "없어요"


def test_GPU_조회가_터져도_스냅샷은_나온다(ready, project_root, monkeypatch):
    """`probe()` 가 예상 밖으로 터지면 화면이 통째로 안 갱신된다.
    "조회 실패가 정상 경로" 는 예외에도 성립해야 한다."""
    from app.monitor import gpu as G

    monkeypatch.setattr(G, "probe", lambda: (_ for _ in ()).throw(RuntimeError("GPU 폭발")))
    got = snap(ready, project_root)
    gpu_row = [r for r in got["dashboard"]["resources"] if r["label"] == "GPU"][0]
    assert gpu_row["value"] == "조회 불가"
    assert "GPU 폭발" in got["raw"]["gpu"]["reason"]
    # 나머지는 그대로 채워진다
    assert got["dashboard"]["metrics"]
    assert any(r["label"] == "디스크" for r in got["dashboard"]["resources"])
