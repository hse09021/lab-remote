"""지표 파일(`result.csv`) 읽기와 이상 감지.

긴 형식 `step,split,metric,value`와 넓은 형식을 읽는다(넓은 형식은 경고를
남긴다). 어느 파일을 읽을지(설정 규칙 → 흔한 위치 자동 탐색)는 2단계에서
정한다 (PLAN 4.1 runs).
"""

import os

import pytest

from app.monitor import metrics as M

LONG = "step,split,metric,value\n1,train,loss,2.0\n1,val,loss,2.2\n2,train,loss,1.0\n2,val,loss,1.1\n"
WIDE = "epoch,train_loss,val_loss,val_acc\n1,2.0,2.2,0.6\n2,1.0,1.1,0.7\n"


def write(tmp_path, body, name="result.csv"):
    path = tmp_path / name
    path.write_text(body, encoding="utf-8")
    return str(path)








# --- 긴 형식 ------------------------------------------------------------------


def test_긴_형식을_읽는다(tmp_path):
    got = M.read_result(write(tmp_path, LONG))
    assert got["ok"] is True and got["format"] == "long"
    assert len(got["rows"]) == 4
    assert [r["value"] for r in M.series_of(got["rows"], "loss", "train")] == [2.0, 1.0]


def test_split_으로_걸러_낸다(tmp_path):
    rows = M.read_result(write(tmp_path, LONG))["rows"]
    assert len(M.series_of(rows, "loss")) == 4  # split 안 주면 전부
    assert len(M.series_of(rows, "loss", "val")) == 2
    assert M.series_of(rows, "없는지표") == []


def test_칸이_모자란_줄은_경고로_건너뛴다(tmp_path):
    got = M.read_result(write(tmp_path, LONG + "3,train\n"))
    assert len(got["rows"]) == 4
    assert any("칸이 모자라요" in w for w in got["warnings"])


# --- 넓은 형식 ----------------------------------------------------------------


def test_넓은_형식도_읽지만_경고한다(tmp_path):
    got = M.read_result(write(tmp_path, WIDE))
    assert got["format"] == "wide"
    assert any("넓은 형식" in w for w in got["warnings"])
    assert [r["value"] for r in M.series_of(got["rows"], "loss", "train")] == [2.0, 1.0]
    assert [r["value"] for r in M.series_of(got["rows"], "acc", "val")] == [0.6, 0.7]


def test_모르는_헤더는_정상_실패(tmp_path):
    got = M.read_result(write(tmp_path, "뭐가,뭔지,모를,열\n1,2,3,4\n"))
    assert got["ok"] is False
    assert "열을 읽지 못했어요" in got["reason"]


def test_없는_파일은_정상_실패(tmp_path):
    got = M.read_result(str(tmp_path / "없음.csv"))
    assert got["ok"] is False and got["rows"] == []


def test_빈_파일은_빈_결과(tmp_path):
    got = M.read_result(write(tmp_path, ""))
    assert got["ok"] is True and got["format"] == "none"


# --- NaN·Inf ------------------------------------------------------------------


@pytest.mark.parametrize("text,flag", [("nan", "nan"), ("NaN", "nan"), ("inf", "inf"), ("-inf", "-inf")])
def test_숫자가_아닌_값은_깃발로(tmp_path, text, flag):
    got = M.read_result(write(tmp_path, f"step,split,metric,value\n1,train,loss,{text}\n"))
    row = got["rows"][0]
    assert row["value"] is None and row["flag"] == flag


def test_NaN_은_즉시_중단(tmp_path):
    rows = M.read_result(write(tmp_path, "step,split,metric,value\n1,train,loss,nan\n"))["rows"]
    found = M.find_anomalies(rows)
    assert [a["kind"] for a in found] == ["nan"]
    assert found[0]["action"] == "stop"
    assert "train/loss" in found[0]["text"]


def test_정상_값에는_이상이_없다(tmp_path):
    rows = M.read_result(write(tmp_path, LONG))["rows"]
    assert M.find_anomalies(rows) == []


# --- 발산 ---------------------------------------------------------------------


def test_발산을_잡는다():
    rows = [{"step": i, "split": "train", "metric": "loss", "value": v, "flag": None}
            for i, v in enumerate([1.0, 2.0, 5.0, 10.0, 20.0, 40.0, 80.0], start=1)]
    found = M.find_anomalies(rows)
    assert [a["kind"] for a in found] == ["diverge"]
    assert found[0]["action"] == "stop"


def test_줄어드는_loss_는_발산이_아니다():
    rows = [{"step": i, "split": "train", "metric": "loss", "value": v, "flag": None}
            for i, v in enumerate([2.0, 1.5, 1.2, 1.0, 0.8, 0.6, 0.5], start=1)]
    assert M.find_anomalies(rows) == []


def test_한_번_튀는_것은_발산이_아니다():
    """최근 5개가 **연속으로** 넘어야 한다."""
    rows = [{"step": i, "split": "train", "metric": "loss", "value": v, "flag": None}
            for i, v in enumerate([1.0, 0.9, 50.0, 0.8, 0.7, 0.6, 0.5], start=1)]
    assert M.find_anomalies(rows) == []


def test_기록이_적으면_발산_판정을_안_한다():
    rows = [{"step": 1, "split": "train", "metric": "loss", "value": 1.0, "flag": None},
            {"step": 2, "split": "train", "metric": "loss", "value": 99.0, "flag": None}]
    assert M.find_anomalies(rows) == []


def test_발산_임계를_덮어쓸_수_있다():
    rows = [{"step": i, "split": "train", "metric": "loss", "value": v, "flag": None}
            for i, v in enumerate([1.0, 1.1, 1.2, 1.3, 1.4, 1.5, 1.6], start=1)]
    assert M.find_anomalies(rows) == []
    found = M.find_anomalies(rows, config={"divergeFactor": 1.05, "divergeWindow": 3})
    assert [a["kind"] for a in found] == ["diverge"]


# --- OOM · 디스크 · 진전 없음 ---------------------------------------------------


def test_로그에서_OOM_을_센다():
    lines = [
        "epoch 1 loss=2.0",
        "RuntimeError: CUDA out of memory. Tried to allocate 2.00 GiB",
        "epoch 2 loss=1.0",
        "torch.cuda.OutOfMemoryError: CUDA out of memory",
    ]
    got = M.scan_log(lines)
    assert got["oom"] == 2
    assert len(got["oomLines"]) == 2


def test_OOM_이_반복되면_중단():
    assert [a["kind"] for a in M.find_anomalies([], oom_count=2)] == ["oom"]
    assert M.find_anomalies([], oom_count=1) == []


def test_디스크가_부족하면_큐_정지():
    found = M.find_anomalies([], disk_free_gb=3.0)
    assert found[0]["kind"] == "disk" and found[0]["action"] == "pause"
    assert M.find_anomalies([], disk_free_gb=100.0) == []


def test_진전이_없으면_알림만():
    found = M.find_anomalies([], stalled_sec=1000)
    assert found[0]["kind"] == "stalled" and found[0]["action"] == "notify"
    assert M.find_anomalies([], stalled_sec=10) == []


def test_여러_이상이_같이_나온다(tmp_path):
    rows = M.read_result(write(tmp_path, "step,split,metric,value\n1,train,loss,nan\n"))["rows"]
    found = M.find_anomalies(rows, oom_count=5, disk_free_gb=1.0, stalled_sec=9999)
    assert sorted(a["kind"] for a in found) == ["disk", "nan", "oom", "stalled"]
    assert {a["action"] for a in found} == {"stop", "pause", "notify"}
