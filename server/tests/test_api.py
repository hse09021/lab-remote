"""FastAPI — 🔑 로컬 전용 검사, 그리고 화면이 쓰는 흐름 한 바퀴."""

import os

import pytest
from fastapi.testclient import TestClient

from app import main, system

H = {"X-Lab-Remote": "1"}


@pytest.fixture()
def client(tmp_path, monkeypatch):
    dist = tmp_path / "dist"
    (dist / "assets").mkdir(parents=True)
    (dist / "index.html").write_text("<!doctype html><title>lab.remote</title>")
    (dist / "assets" / "app.js").write_text("console.log(1)")
    monkeypatch.setattr(system.gpu_mod, "probe", lambda: {"available": False, "reason": "없음", "devices": []})
    return TestClient(main.create_app(web_dist=str(dist), port=8000), base_url="http://127.0.0.1:8000")


def test_health(client):
    assert client.get("/api/health").json()["ok"] is True


@pytest.mark.parametrize("host", ["evil.example", "127.0.0.1.evil.example", "192.168.0.5:8000"])
def test_다른_Host_는_거절(client, host):
    assert client.get("/api/health", headers={"Host": host}).status_code == 403
    assert client.get("/", headers={"Host": host}).status_code == 403


@pytest.mark.parametrize("host", ["localhost:5173", "127.0.0.1", "[::1]:8000"])
def test_로컬_Host_는_통과(client, host):
    assert client.get("/api/health", headers={"Host": host}).status_code == 200


def test_허용_Host_를_환경변수로_더한다(client, monkeypatch):
    monkeypatch.setenv("LAB_ALLOWED_HOSTS", "box-8000.tunnel.example")
    assert client.get("/api/health", headers={"Host": "box-8000.tunnel.example"}).status_code == 200


def test_바꾸는_요청은_헤더가_있어야(client, project_root):
    r = client.post("/api/projects", json={"path": project_root, "name": "demo"})
    assert r.status_code == 403
    assert not os.path.exists(os.path.join(project_root, ".labremote"))


def test_다른_사이트의_Origin_은_거절(client, project_root):
    r = client.post(
        "/api/projects",
        json={"path": project_root, "name": "demo"},
        headers={**H, "Origin": "https://evil.example"},
    )
    assert r.status_code == 403
    r = client.post(
        "/api/projects",
        json={"path": project_root, "name": "demo"},
        headers={**H, "Origin": "http://localhost:5173"},
    )
    assert r.status_code == 200


def test_프로젝트와_파일_한_바퀴(client, project_root):
    r = client.post("/api/projects", json={"path": project_root, "name": "demo"}, headers=H)
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["name"] == "demo" and body["labremote"] is True and body["git"]["state"] == "none"

    assert [p["name"] for p in client.get("/api/projects").json()["projects"]] == ["demo"]

    assert client.post("/api/projects/demo/files", json={"path": "notes", "kind": "dir"}, headers=H).status_code == 200
    r = client.put("/api/projects/demo/files/upload?path=notes/a.txt", content=b"hello", headers=H)
    assert r.json() == {"path": "notes/a.txt", "size": 5}
    assert client.put("/api/projects/demo/files/upload?path=notes/a.txt", content=b"x", headers=H).status_code == 400

    names = [e["name"] for e in client.get("/api/projects/demo/files", params={"path": "notes"}).json()["entries"]]
    assert names == ["a.txt"]
    assert client.get("/api/projects/demo/files/content", params={"path": "notes/a.txt"}).json()["text"] == "hello"
    r = client.get("/api/projects/demo/files/download", params={"path": "notes/a.txt"})
    assert r.content == b"hello" and "attachment" in r.headers["content-disposition"]

    r = client.post("/api/projects/demo/files/move", json={"from": "notes/a.txt", "to": "notes/b.txt"}, headers=H)
    assert r.json() == {"from": "notes/a.txt", "to": "notes/b.txt"}
    r = client.post("/api/projects/demo/files/delete", json={"path": "notes", "confirm": "notes"}, headers=H)
    assert r.status_code == 200

    assert client.get("/api/projects/demo/files", params={"path": "../"}).status_code == 400
    assert client.get("/api/projects/demo/files", params={"path": "nope"}).status_code == 404
    assert client.get("/api/projects/nope/files").status_code == 400

    r = client.put("/api/projects/demo/settings", json={"condaEnv": "lora-env", "share": True}, headers=H)
    assert r.json()["share"] is True
    assert client.put("/api/projects/demo/pin", json={"pinned": True}, headers=H).json() == {"pins": ["demo"]}

    r = client.delete("/api/projects/demo", headers=H)
    assert r.json()["removedLabremote"] is False
    assert os.path.isdir(os.path.join(project_root, ".labremote"))


def test_시스템(client, project):
    body = client.get("/api/system").json()
    assert body["server"]["host"] == "127.0.0.1" and body["server"]["port"] == 8000
    assert body["gpu"]["label"] == "GPU 조회 불가"
    assert body["tunnel"]["state"] == "unknown"
    whats = [row["what"] for row in body["changes"]]
    assert whats[:3] == ["conda 환경 labremote", "사용자 서비스 labremote-session", "linger (로그아웃해도 서비스 유지)"]
    assert "demo 의 .labremote/" in whats


def test_웹_빌드를_내준다(client):
    assert "lab.remote" in client.get("/projects/demo?tab=files").text  # SPA 폴백
    assert client.get("/assets/app.js").text == "console.log(1)"
    assert "lab.remote" in client.get("/../../etc/passwd").text  # 밖은 index 로
    assert client.get("/api/nope").status_code == 404


def test_GPU_한_줄():
    raw = {"available": True, "devices": [{"utilPct": 94.0, "memUsedMb": 13414.0, "memTotalMb": 16303.0}]}
    assert system.gpu_summary(probe=lambda: raw)["label"] == "GPU 94% · 13.1/16G"
