"""바깥 주소 · 터널 상태 · 알림 링크 (9단계)."""

import json

import pytest
from fastapi.testclient import TestClient

from app import main, remote, tunnel

H = {"X-Lab-Remote": "1"}


def test_주소_검사():
    for bad in ("", "http://a.example", "https://", "https://u:p@a.example", "https://a.example/?x=1", "https://localhost:8000"):
        with pytest.raises(remote.RemoteError):
            remote.set_url(bad)
    got = remote.set_url("https://Abc-8000.Example.ms/lab/")
    assert got["publicUrl"] == "https://abc-8000.example.ms/lab"
    assert "abc-8000.example.ms" in remote.extra_hosts()
    remote.clear()
    assert remote.public_url() == "" and remote.extra_hosts() == set()


def test_환경_변수도_먹는다(monkeypatch):
    monkeypatch.setenv("LAB_ALLOWED_HOSTS", "a.example, B.example")
    assert remote.extra_hosts() == {"a.example", "b.example"}


def test_링크():
    assert remote.link_for({"project": "p", "session": "s1"}) == ""
    remote.set_url("https://h.example")
    assert remote.link_for({"project": "my p", "session": "s1"}) == "https://h.example/projects/my%20p/ade?session=s1"
    assert remote.link_for({"project": "p", "run": "EXP-001"}) == "https://h.example/projects/p?tab=work&run=EXP-001"
    assert remote.link_for(None) == ""


def test_바깥_주소의_Host_만_받는다(tmp_path, monkeypatch):
    monkeypatch.setattr(tunnel, "status", lambda **k: {"state": "off"})
    app = main.create_app(web_dist=str(tmp_path))
    outside = TestClient(app, base_url="https://h.example")
    r = outside.get("/api/health")
    assert r.status_code == 403 and "labremote remote set" in r.json()["detail"]
    local = TestClient(app, base_url="http://127.0.0.1:8000")
    assert local.put("/api/system/remote", json={"url": "https://h.example"}, headers=H).status_code == 200
    assert outside.get("/api/health").json() == {"ok": True, "version": outside.get("/api/health").json()["version"], "tunnel": "off"}
    # 바깥 주소로 온 바꾸는 요청도 헤더 규칙은 그대로
    assert outside.put("/api/system/remote", json={"url": ""}).status_code == 403
    assert local.put("/api/system/remote", json={"url": "nope"}, headers=H).status_code == 400
    assert local.put("/api/system/remote", json={"url": ""}, headers=H).json()["publicUrl"] == ""


def test_자동_시작_API(tmp_path, monkeypatch):
    from app.service import autostart, units

    monkeypatch.setattr(tunnel, "status", lambda **k: {"state": "off"})
    client = TestClient(main.create_app(web_dist=str(tmp_path)), base_url="http://127.0.0.1:8000")
    assert client.post("/api/system/autostart/uninstall", json={"confirm": "x"}, headers=H).status_code == 400
    called = {}
    monkeypatch.setattr(autostart, "uninstall", lambda stop=True: called.setdefault("stop", stop) and [] or [])
    monkeypatch.setattr(units, "inside", lambda: False)
    r = client.post("/api/system/autostart/uninstall", json={"confirm": "끄기"}, headers=H)
    assert r.status_code == 200 and r.json()["stopsSelf"] is False and called["stop"] is True


# --- 터널 상태 ------------------------------------------------------------------


def _runner(status, user="not logged in"):
    def run(argv):
        if argv[1:] == ["tunnel", "status"]:
            return 0, status
        if argv[1:] == ["tunnel", "user", "show"]:
            return (1 if "not logged" in user else 0), user
        raise AssertionError(argv)

    return run


def test_터널_꺼짐(monkeypatch):
    monkeypatch.setattr(tunnel, "cli_path", lambda: "/x/code")
    got = tunnel.status(run=_runner('{"tunnel":null,"service_installed":false}'))
    assert got["state"] == "off" and got["loggedIn"] is False and got["service"] is False


def test_터널_켜짐_이름은_있으면_쓴다(monkeypatch):
    monkeypatch.setattr(tunnel, "cli_path", lambda: "/x/code")
    body = json.dumps({"tunnel": {"name": "desk", "tunnel": "Connected"}, "service_installed": True})
    got = tunnel.status(run=_runner(body, "logged in with GitHub as someone"))
    assert got["state"] == "up" and got["url"] == "https://vscode.dev/tunnel/desk"
    assert got["loggedIn"] is True and got["service"] is True
    # 계정 이름은 내보내지 않는다
    assert "someone" not in json.dumps(got)


def test_터널_CLI_가_없거나_못_읽으면(monkeypatch):
    monkeypatch.setattr(tunnel, "cli_path", lambda: "")
    assert tunnel.status(run=lambda a: (0, ""))["state"] == "absent"
    monkeypatch.setattr(tunnel, "cli_path", lambda: "/x/code")
    assert tunnel.status(run=lambda a: (1, "boom"))["state"] == "unknown"


def test_원격_창의_code_는_건너뛴다(monkeypatch):
    import shutil

    monkeypatch.setattr(tunnel, "_CANDIDATES", ())
    monkeypatch.setattr(shutil, "which", lambda name: "/h/.vscode-server/bin/remote-cli/code" if name == "code" else None)
    assert tunnel.cli_path() == ""


# --- 알림 링크 ------------------------------------------------------------------


def test_Discord_알림에_답하기_링크(conn, monkeypatch):
    from app import alerts, notifier

    sent = {}
    monkeypatch.setattr(alerts.config, "discord_webhook", lambda *a: "https://discord.example/hook")
    monkeypatch.setattr(notifier, "send", lambda conn, kind, **k: sent.update(k) or {"sent": True})
    remote.set_url("https://h.example")
    alerts.post(conn, "ask", "ask", "질문", where="p · main", project="p", ref={"project": "p", "session": "s9"})
    assert ("답하기", "https://h.example/projects/p/ade?session=s9") in sent["fields"]
