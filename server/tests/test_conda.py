"""Conda — 가짜 conda로 보호 · 잠금 · 미리 보기 · 삭제 백업 · 입력 검사를 시험한다."""

import json
import os
import subprocess
import time

import pytest
from fastapi.testclient import TestClient

from app import conda, main
from app.runner import condaenv

ENVS = {
    "envs": ["/c", "/c/envs/lora-env", "/c/envs/labremote"],
    "envs_details": {"/c": {"name": "base"}, "/c/envs/lora-env": {"name": "lora-env"}, "/c/envs/labremote": {"name": "labremote"}},
}
PKGS = [
    {"name": "python", "version": "3.11.9", "channel": "pkgs/main", "build_string": "h1"},
    {"name": "torch", "version": "2.6.0", "channel": "pypi", "build_string": "pypi_0"},
]


@pytest.fixture()
def fake(monkeypatch):
    calls = []

    def run(argv, timeout=120):
        calls.append(argv)
        out = ""
        if argv[1:3] == ["env", "list"]:
            out = json.dumps(ENVS)
        elif argv[1] == "list":
            out = json.dumps(PKGS)
        elif argv[1:3] == ["env", "export"]:
            out = "name: lora-env\ndependencies:\n  - python=3.11\n"
        elif "--dry-run" in argv and argv[1] == "install":
            out = json.dumps({"actions": {"LINK": [{"name": "tqdm", "version": "4.70.0"}, {"name": "openssl", "version": "3.5.9"}],
                                          "UNLINK": [{"name": "openssl", "version": "3.5.7"}]}})
        elif "--report" in argv:
            out = json.dumps({"install": [{"metadata": {"name": "torch", "version": "2.7.0"}}, {"metadata": {"name": "peft", "version": "0.13.2"}}]})
        return subprocess.CompletedProcess(argv, 0, out, "")

    monkeypatch.setattr(conda, "_run", run)
    monkeypatch.setattr(conda, "_conda", lambda: "/c/bin/conda")
    monkeypatch.setattr(conda, "_busy_envs", lambda: {})
    monkeypatch.setattr(condaenv, "check", lambda name: {"ok": name not in ("base", "labremote"),
                                                          "reason": "보호돼요" if name in ("base", "labremote") else "", "prefix": ""})
    conda._cache.clear()
    return calls


def wait(job):
    for _ in range(200):
        got = conda.job(job["id"])
        if got["state"] != "running":
            return got
        time.sleep(0.01)
    raise AssertionError("작업이 안 끝났어요")


def test_환경_목록과_보호(fake):
    envs = {e["name"]: e for e in conda.list_envs()}
    assert envs["base"]["protected"] and envs["labremote"]["protected"] and not envs["lora-env"]["protected"]
    d = conda.env_detail("lora-env")
    assert d["python"] == "3.11.9" and [p["source"] for p in d["packages"]] == ["conda", "pip"]
    assert d["lock"] == ""


def test_conda_미리_보기(fake):
    got = wait(conda.start_job("change", "lora-env", tool="conda", action="install", packages=[{"name": "tqdm"}], dry=True))
    assert got["state"] == "done"
    assert {(c["name"], c["action"]) for c in got["changes"]} == {("tqdm", "추가"), ("openssl", "바뀜")}
    assert "--dry-run" in fake[-1] and fake[-1][-1] == "tqdm"


def test_pip_미리_보기와_명령_모양(fake):
    got = wait(conda.start_job("change", "lora-env", tool="pip", action="install",
                               packages=[{"name": "torch", "spec": "==2.7.0"}, {"name": "peft"}], dry=True))
    assert {(c["name"], c["from"], c["to"]) for c in got["changes"]} == {("torch", "2.6.0", "2.7.0"), ("peft", "", "0.13.2")}
    argv = next(a for a in fake if "--report" in a)
    # 🔑 셸 없이 · 캐시 없이 · 휠만 (pkgspec 이 이름순으로 정리한다)
    assert "--no-cache-dir" in argv and "--only-binary=:all:" in argv and sorted(argv[-2:]) == ["peft", "torch==2.7.0"]


@pytest.mark.parametrize("bad", [
    [{"name": "numpy; rm -rf ~"}], [{"name": "git+https://x"}], [{"name": "pip"}], [{"name": "numpy", "spec": "-e ."}],
])
def test_이상한_패키지는_통째로_거부(fake, bad):
    with pytest.raises(conda.CondaError):
        conda.start_job("change", "lora-env", tool="pip", action="install", packages=bad, dry=True)


def test_보호된_환경과_학습이_쓰는_환경은_못_바꾼다(fake, monkeypatch):
    with pytest.raises(conda.CondaError, match="보호"):
        conda.start_job("change", "base", tool="conda", action="install", packages=[{"name": "tqdm"}])
    monkeypatch.setattr(conda, "_busy_envs", lambda: {"lora-env": ["demo · EXP-007"]})
    with pytest.raises(conda.CondaError, match="실행 중인 학습"):
        conda.start_job("change", "lora-env", tool="pip", action="install", packages=[{"name": "peft"}])
    with pytest.raises(conda.CondaError, match="실행 중인 학습"):
        conda.start_job("delete", "lora-env", confirm="lora-env")
    # 미리 보기는 잠겨 있어도 된다 (아무것도 안 바뀐다)
    assert conda.start_job("change", "lora-env", tool="pip", action="install", packages=[{"name": "peft"}], dry=True)


def test_삭제는_이름을_적어야_하고_먼저_백업한다(fake, isolated_data):
    with pytest.raises(conda.CondaError, match="똑같이"):
        conda.start_job("delete", "lora-env", confirm="lora")
    got = wait(conda.start_job("delete", "lora-env", confirm="lora-env"))
    assert got["state"] == "done" and os.path.exists(got["backup"])
    assert str(isolated_data) in got["backup"]
    assert fake[-1] == ["/c/bin/conda", "env", "remove", "-n", "lora-env", "-y"]
    with open(os.path.join(isolated_data, "conda", "history.jsonl")) as fh:
        assert json.loads(fh.readlines()[-1])["kind"] == "delete"


def test_만들기(fake):
    with pytest.raises(conda.CondaError, match="이미 있는"):
        conda.start_job("create", "lora-env")
    with pytest.raises(conda.CondaError, match="이미 있는|보호"):
        conda.start_job("create", "labremote")
    got = wait(conda.start_job("create", "vit-env", python="3.12"))
    assert fake[-1][-1] == "python=3.12" and got["state"] == "done"
    wait(conda.start_job("create", "vit-copy", clone="lora-env"))
    assert fake[-1][-2:] == ["--clone", "lora-env"]


def test_API(fake, tmp_path):
    client = TestClient(main.create_app(web_dist=str(tmp_path)), base_url="http://127.0.0.1:8000")
    H = {"X-Lab-Remote": "1"}
    assert [e["name"] for e in client.get("/api/conda/envs").json()["envs"]][:2] == ["base", "labremote"]
    r = client.post("/api/conda/envs/lora-env/changes", json={"tool": "conda", "action": "install", "packages": [{"name": "tqdm"}]}, headers=H)
    jid = r.json()["id"]
    for _ in range(100):
        got = client.get(f"/api/conda/jobs/{jid}").json()
        if got["state"] != "running":
            break
        time.sleep(0.01)
    assert got["changes"]
    assert "python=3.11" in client.get("/api/conda/envs/lora-env/export").text
    assert client.post("/api/conda/envs/base/delete", json={"confirm": "base"}, headers=H).status_code == 400
