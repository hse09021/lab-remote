"""GPU 상태와 드라이버 불일치.

**조회 실패가 정상 경로다.** ①의 실측 중에 실제로 당했다 — 우분투 자동
업데이트가 드라이버를 올리고 재부팅을 안 해서 `nvidia-smi`가 통째로 죽었고,
그 상태로 며칠 지났다.
"""

import pytest

from app.monitor import gpu as G

OK_LINE = "0, NVIDIA GeForce RTX 5080, 94, 21300, 16303, 71, 595.99.02\n"


@pytest.fixture()
def fake_run(monkeypatch):
    """`nvidia-smi`를 가짜로 바꿔 끼운다."""
    calls = []

    def install(answers):
        def run(args):
            calls.append(args)
            key = "driver" if "--query-gpu=driver_version" in " ".join(args) else "full"
            return answers.get(key, answers.get("full", (0, "", "")))

        monkeypatch.setattr(G, "_run", run)
        return calls

    return install


# --- 파싱 ---------------------------------------------------------------------


def test_한_줄을_장치로_읽는다():
    devices = G.parse_csv(OK_LINE)
    assert len(devices) == 1
    device = devices[0]
    assert device["name"] == "NVIDIA GeForce RTX 5080"
    assert device["utilPct"] == 94.0
    assert device["memUsedMb"] == 21300.0
    assert device["memPct"] == 130.7  # 값 그대로 — 꾸미지 않는다
    assert device["tempC"] == 71.0
    assert device["driver"] == "595.99.02"


def test_여러_장치도_읽는다():
    assert len(G.parse_csv(OK_LINE + OK_LINE.replace("0,", "1,", 1))) == 2


def test_모르는_값은_None():
    line = "0, GPU, [N/A], [Not Supported], 16303, N/A, 595.99.02\n"
    device = G.parse_csv(line)[0]
    assert device["utilPct"] is None
    assert device["memUsedMb"] is None
    assert device["memPct"] is None
    assert device["tempC"] is None


def test_칸이_모자란_줄은_건너뛴다():
    assert G.parse_csv("0, GPU\n" + OK_LINE) == G.parse_csv(OK_LINE)


def test_빈_출력은_빈_목록():
    assert G.parse_csv("") == []
    assert G.parse_csv("\n\n") == []


# --- 조회 실패가 정상 경로 ------------------------------------------------------


def test_nvidia_smi_가_없으면_정상_반환(fake_run):
    fake_run({"full": (127, "", "nvidia-smi가 없어요")})
    got = G.probe()
    assert got["available"] is False
    assert "없어요" in got["reason"]
    assert got["devices"] == []


def test_드라이버가_깨졌으면_사유를_싣는다(fake_run):
    fake_run({"full": (9, "", "Failed to initialize NVML: Driver/library version mismatch\n")})
    got = G.probe()
    assert got["available"] is False
    assert "Failed to initialize NVML" in got["reason"]
    assert got["driver"]["mismatch"] is True


def test_출력이_비어_있으면_실패로_본다(fake_run):
    fake_run({"full": (0, "\n", "")})
    assert G.probe()["available"] is False


def test_정상이면_장치가_나온다(fake_run):
    fake_run({"full": (0, OK_LINE, ""), "driver": (0, "595.99.02\n", "")})
    got = G.probe()
    assert got["available"] is True
    assert got["reason"] == ""
    assert got["devices"][0]["index"] == 0


@pytest.mark.parametrize(
    "error,expect",
    [
        (FileNotFoundError(), "nvidia-smi가 없어요"),
        (OSError("프로세스를 못 띄웠어요"), "못 띄웠어요"),
        (G.subprocess.TimeoutExpired("nvidia-smi", 10), "nvidia-smi"),
    ],
)
def test_프로세스를_못_띄워도_안_터진다(monkeypatch, error, expect):
    """모니터가 던지면 오케스트레이터가 멈춘다."""

    def boom(*args, **kwargs):
        raise error

    monkeypatch.setattr(G.subprocess, "run", boom)
    code, out, err = G._run(["nvidia-smi"])
    assert code != 0
    assert expect in err
    assert G.probe()["available"] is False


# --- 드라이버 불일치 -----------------------------------------------------------


def test_판이_다르면_불일치(fake_run, monkeypatch):
    monkeypatch.setattr(G, "nvrm_version", lambda: "595.84")
    fake_run({"driver": (0, "595.99.02\n", "")})
    state = G.driver_state()
    assert state["mismatch"] is True
    assert state["ok"] is False
    assert "595.84" in state["reason"] and "595.99.02" in state["reason"]


def test_판이_같으면_정상(fake_run, monkeypatch):
    monkeypatch.setattr(G, "nvrm_version", lambda: "595.99.02")
    monkeypatch.setattr(G, "reboot_pending", lambda: {"pending": False, "packages": [], "nvidia": []})
    fake_run({"driver": (0, "595.99.02\n", "")})
    state = G.driver_state()
    assert state["ok"] is True and state["mismatch"] is False


def test_재부팅_대기만_있으면_곧_깨질_상태(fake_run, monkeypatch):
    """아직 안 깨졌지만 미리 알린다."""
    monkeypatch.setattr(G, "nvrm_version", lambda: "595.99.02")
    monkeypatch.setattr(
        G, "reboot_pending", lambda: {"pending": True, "packages": ["nvidia-driver-595"], "nvidia": ["nvidia-driver-595"]}
    )
    fake_run({"driver": (0, "595.99.02\n", "")})
    state = G.driver_state()
    assert state["mismatch"] is False
    assert state["ok"] is False  # 실험을 시작하면 안 되는 상태
    assert "재부팅하지 않았어요" in state["reason"]


def test_NVRM_판을_못_읽어도_안_터진다(monkeypatch):
    monkeypatch.setattr(G, "NVRM_PATH", "/없는경로/version")
    assert G.nvrm_version() == ""


def test_NVRM_형식을_읽는다(tmp_path, monkeypatch):
    path = tmp_path / "version"
    path.write_text(
        "NVRM version: NVIDIA UNIX x86_64 Kernel Module  595.99.02  Thu Oct 2 2026\n"
        "GCC version:  gcc version 13.3.0\n",
        encoding="utf-8",
    )
    monkeypatch.setattr(G, "NVRM_PATH", str(path))
    assert G.nvrm_version() == "595.99.02"


def test_재부팅_대기_파일을_읽는다(tmp_path, monkeypatch):
    pkgs = tmp_path / "reboot-required.pkgs"
    pkgs.write_text("nvidia-driver-595\nlinux-image-7.0.0-42\n", encoding="utf-8")
    monkeypatch.setattr(G, "REBOOT_REQUIRED_PKGS", str(pkgs))
    monkeypatch.setattr(G, "REBOOT_REQUIRED", str(tmp_path / "reboot-required"))
    got = G.reboot_pending()
    assert got["pending"] is True
    assert got["nvidia"] == ["nvidia-driver-595"]


def test_재부팅_대기_파일이_없으면_조용하다(monkeypatch, tmp_path):
    monkeypatch.setattr(G, "REBOOT_REQUIRED_PKGS", str(tmp_path / "없음.pkgs"))
    monkeypatch.setattr(G, "REBOOT_REQUIRED", str(tmp_path / "없음"))
    got = G.reboot_pending()
    assert got["pending"] is False and got["nvidia"] == []


# --- 이 머신에서 실제로 -------------------------------------------------------


def test_실제_조회가_던지지_않는다():
    """GPU가 있든 없든 예외 없이 상태를 돌려줘야 한다."""
    got = G.probe()
    assert set(got) == {"available", "reason", "devices", "driver"}
    assert isinstance(got["available"], bool)
