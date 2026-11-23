"""에이전트 세션 — 가짜 연결 부품으로 manager · 승인 흐름 · API 를 시험한다.

진짜 Claude 는 부르지 않는다(사용량을 쓰지 않게). 진짜 연결은 단계 보고 때
손으로 한 번 확인했다.
"""

import asyncio
import json
import os
import subprocess

import pytest
from fastapi.testclient import TestClient

from app import inbox, main
from app.agents import base, claude
from app.agents import manager as mgr_mod
from app.agents.manager import AgentError, Manager
from app.events import bus
from app.git import worktree


class FakeBackend(base.AgentBackend):
    """메시지를 받으면 (원하면) 도구 승인을 한 번 묻고 답에 따라 글을 낸다."""

    kind = "fake"
    script: list = []  # 보낼 때마다 꺼내 쓰는 동작
    instances: list = []

    def __init__(self, config, emit, ask):
        super().__init__(config, emit, ask)
        self._idle = asyncio.Event()
        self._idle.set()
        self.decisions = []
        self.closed = False
        FakeBackend.instances.append(self)

    async def connect(self):
        self.agent_session_id = self.agent_session_id or "agent-1"

    async def send(self, text):
        self._idle.clear()
        asyncio.get_running_loop().create_task(self._turn(text))

    async def _turn(self, text):
        action = FakeBackend.script.pop(0) if FakeBackend.script else None
        if action:
            tool, data = action
            self.emit({"type": "tool", "toolId": "t1", "name": tool, "summary": claude.summarize(tool, data), "input": data})
            d = await self.ask(base.ApprovalRequest(tool=tool, input=data))
            self.decisions.append(d)
            self.emit({"type": "tool_result", "toolId": "t1", "ok": d.allow, "output": "ok" if d.allow else d.message})
        self.emit({"type": "text", "text": f"답: {text}"})
        self.emit({"type": "result", "ok": True, "durationMs": 1, "turns": 1})
        self._idle.set()

    async def wait_idle(self):
        await self._idle.wait()

    async def interrupt(self):
        pass

    async def set_mode(self, mode):
        self.config.mode = mode

    async def set_model(self, model):
        self.config.model = model

    async def close(self):
        self.closed = True

    @property
    def busy(self):
        return not self._idle.is_set()


@pytest.fixture()
def fake(monkeypatch):
    monkeypatch.setitem(mgr_mod.BACKENDS, "claude", FakeBackend)
    FakeBackend.script = []
    FakeBackend.instances = []
    yield FakeBackend


def run(coro):
    return asyncio.run(coro)


async def settle(m, sid):
    for _ in range(100):
        await asyncio.sleep(0.01)
        live = m.live.get(sid)
        if (not live or not live.backend.busy) and not any(p.session == sid for p in m.pending.values()):
            await asyncio.sleep(0.02)
            return
    raise AssertionError("차례가 안 끝났어요")


async def wait_pending(m, n=1):
    for _ in range(200):
        if len(m.pending) >= n:
            return list(m.pending.values())
        await asyncio.sleep(0.01)
    raise AssertionError("승인 요청이 안 왔어요")


def test_세션을_만들고_이벤트를_저장한다(fake, project):
    async def go():
        bus.bind(asyncio.get_running_loop())
        m = Manager()
        s = await m.create("demo", text="안녕", mode="plan", effort="low")
        await settle(m, s["id"])
        got = m.get(s["id"])
        assert [e["type"] for e in got["events"]] == ["user", "text", "result"]
        assert got["state"] == "idle" and got["agentSessionId"] == "agent-1"
        assert got["mode"] == "plan" and fake.instances[0].config.effort == "low"
        assert os.path.exists(os.path.join(project, ".labremote", "sessions", f"{s['id']}.jsonl"))
        # 서버가 다시 떠도(새 manager) 목록이 남고 이어 간다
        m2 = Manager()
        assert [x["id"] for x in m2.list("demo")] == [s["id"]]
        await m2.send(s["id"], "이어서")
        await settle(m2, s["id"])
        assert fake.instances[-1].config.resume == "agent-1"

    run(go())


def test_승인은_먼저_온_답만_먹는다(fake, project, conn):
    async def go():
        bus.bind(asyncio.get_running_loop())
        m = Manager()
        fake.script = [("Edit", {"file_path": "src/a.py", "old_string": "a", "new_string": "b"})]
        s = await m.create("demo", text="고쳐 줘")
        [p] = await wait_pending(m)
        assert m.get(s["id"])["state"] == "ask"
        assert inbox.badge(conn) == 1  # 답 필요는 처리할 것
        assert m.answer(p.id, "allow", via="dashboard")["state"] == "allowed"
        with pytest.raises(AgentError, match="이미 답했"):
            m.answer(p.id, "deny", via="inbox")
        await settle(m, s["id"])
        assert fake.instances[0].decisions[0].allow is True
        assert inbox.badge(conn) == 0  # 답하면 Inbox 에서 읽음
        states = [e.get("state") for e in m.get(s["id"])["events"] if e["type"] == "approval"]
        assert states == ["pending", "allowed"]

    run(go())


def test_거부하면_이유가_간다(fake, project):
    async def go():
        bus.bind(asyncio.get_running_loop())
        m = Manager()
        fake.script = [("Bash", {"command": "rm -rf data"})]
        s = await m.create("demo", text="지워")
        [p] = await wait_pending(m)
        m.answer(p.id, "deny", reason="데이터는 지우지 마")
        await settle(m, s["id"])
        d = fake.instances[0].decisions[0]
        assert d.allow is False and "데이터는 지우지 마" in d.message

    run(go())


def test_이_세션에서_계속_허용(fake, project):
    async def go():
        bus.bind(asyncio.get_running_loop())
        m = Manager()
        edit = ("Edit", {"file_path": "src/a.py", "old_string": "a", "new_string": "b"})
        fake.script = [edit]
        s = await m.create("demo", text="1")
        [p] = await wait_pending(m)
        m.answer(p.id, "allowSession")
        await settle(m, s["id"])
        # 같은 파일은 묻지 않는다
        fake.script = [("Edit", {"file_path": "src/a.py", "old_string": "b", "new_string": "c"})]
        await m.send(s["id"], "2")
        await settle(m, s["id"])
        assert not m.pending and fake.instances[0].decisions[1].allow is True
        # 다른 파일은 다시 묻는다
        fake.script = [("Edit", {"file_path": "src/b.py", "old_string": "x", "new_string": "y"})]
        await m.send(s["id"], "3")
        [p] = await wait_pending(m)
        m.answer(p.id, "deny")
        await settle(m, s["id"])

    run(go())


def test_동시_세션은_4개까지(fake, project, monkeypatch):
    async def go():
        bus.bind(asyncio.get_running_loop())
        m = Manager()
        ids = []
        for i in range(4):
            s = await m.create("demo", text=f"{i}")
            await settle(m, s["id"])
            ids.append(s["id"])
        s5 = await m.create("demo", text="5")  # 가장 오래 쉰 세션을 닫고 연다
        await settle(m, s5["id"])
        assert len(m.live) == 4 and ids[0] not in m.live
        assert fake.instances[0].closed is True
        # 모두 바쁘면 거절
        for sid in list(m.live):
            m.live[sid].backend._idle.clear()
        with pytest.raises(AgentError, match="4개"):
            await m.send(ids[0], "다시")

    run(go())


def test_Effort_를_바꾸면_다음_연결부터(fake, project):
    async def go():
        bus.bind(asyncio.get_running_loop())
        m = Manager()
        s = await m.create("demo", text="1", effort="low")
        await settle(m, s["id"])
        await m.configure(s["id"], effort="high", mode="edit")
        assert s["id"] not in m.live  # 쉬고 있었으니 끊었다
        await m.send(s["id"], "2")
        await settle(m, s["id"])
        assert fake.instances[-1].config.effort == "high" and fake.instances[-1].config.mode == "edit"
        with pytest.raises(AgentError):
            await m.configure(s["id"], mode="bypass")

    run(go())


def test_서버가_다시_뜨면_작업_중은_끊김으로(fake, project):
    async def go():
        bus.bind(asyncio.get_running_loop())
        m = Manager()
        fake.script = [("Bash", {"command": "make"})]
        s = await m.create("demo", text="1")
        await wait_pending(m)
        assert Manager().recover() == 1
        assert "끊겼어요" in Manager().get(s["id"])["note"]
        from app import db

        with db.open_db() as c:
            assert inbox.badge(c) == 0  # 답할 수 없게 된 승인은 배지에서 빠진다
        await m.shutdown()

    run(go())


def test_worktree_를_만든다(project):
    subprocess.run(["git", "-C", project, "init", "-q", "-b", "main"], check=True)
    subprocess.run(["git", "-C", project, "-c", "user.name=t", "-c", "user.email=t@t", "commit", "-q", "--allow-empty", "-m", "i"], check=True)
    made = worktree.add(project, "exp/early-stop")
    assert made["rel"] == ".labremote/worktrees/early-stop" and os.path.isdir(made["path"])
    # 같은 브랜치를 두 worktree 가 쓸 수는 없다 — git 이 거절하고 그 문구를 그대로 보여 준다
    with pytest.raises(worktree.WorktreeError, match="already used"):
        worktree.add(project, "exp/early-stop")
    with pytest.raises(worktree.WorktreeError):
        worktree.add(project, "../evil")


def test_정보에서_계정을_뺀다():
    got = claude._public_info({"account": {"email": "a@b"}, "models": [{"value": "opus"}], "commands": [{"name": "review", "description": "d"}]})
    assert "account" not in got and "a@b" not in json.dumps(got)
    assert got["commands"] == [{"name": "review", "description": "d", "argumentHint": ""}]
    assert claude.MODE_MAP == {"manual": "default", "edit": "acceptEdits", "plan": "plan", "auto": "auto"}


def test_API(fake, project, tmp_path):
    with TestClient(main.create_app(web_dist=str(tmp_path)), base_url="http://127.0.0.1:8000") as client:
        H = {"X-Lab-Remote": "1"}
        r = client.post("/api/agents/sessions", json={"project": "demo", "text": "안녕"}, headers=H)
        assert r.status_code == 200, r.text
        sid = r.json()["id"]
        assert client.post("/api/agents/sessions", json={"project": "demo", "text": " "}, headers=H).status_code == 400
        assert client.post("/api/approvals/a-0000000000", json={"choice": "allow"}, headers=H).status_code == 409
        body = client.get("/api/agents/sessions", params={"project": "demo"}).json()
        assert [s["id"] for s in body["sessions"]] == [sid]
        assert client.get("/api/agents/sessions/s-zzz").status_code == 404


def test_할_일은_TaskCreate_TaskUpdate_로_만든다():
    got = []
    b = claude.ClaudeBackend(base.SessionConfig(cwd="."), emit=got.append, ask=None)
    b._track_task_call("t1", "TaskCreate", {"subject": "파일 읽기", "description": "d"})
    b._track_task_result("t1", {"task": {"id": "1", "subject": "파일 읽기"}}, "")
    b._track_task_call("t2", "TaskCreate", {"subject": "고치기", "description": "d"})
    b._track_task_result("t2", None, "Task #2 created successfully")
    b._track_task_call("t3", "TaskUpdate", {"taskId": "1", "status": "completed"})
    b._track_task_call("t4", "TaskUpdate", {"taskId": "2", "status": "in_progress"})
    assert got[-1] == {"type": "todos", "items": [
        {"content": "파일 읽기", "status": "completed"},
        {"content": "고치기", "status": "in_progress"},
    ]}


def test_할_일_도구를_켜고_위험한_도구는_허용_목록에_없다():
    b = claude.ClaudeBackend(base.SessionConfig(cwd="."), emit=lambda e: None, ask=None)
    opts = b._options()
    assert opts.allowed_tools == ["TodoWrite", "TaskCreate", "TaskUpdate", "TaskGet", "TaskList"]
    assert not {"Bash", "Edit", "Write"} & set(opts.allowed_tools)
    assert "AskUserQuestion" not in opts.disallowed_tools  # 질문 카드로 답한다
    assert opts.settings is None  # Ultracode 는 켤 때만
    on = claude.ClaudeBackend(base.SessionConfig(cwd=".", extra={"ultracode": True}), emit=lambda e: None, ask=None)._options()
    assert json.loads(on.settings) == {"ultracode": True}
    assert opts.permission_mode == "default" and opts.setting_sources == ["user", "project", "local"]


Q = {"questions": [
    {"question": "어느 형식으로 쓸까요?", "header": "형식", "options": [{"label": "CSV", "description": ""}, {"label": "JSON", "description": ""}], "multiSelect": False},
    {"question": "무엇을 넣을까요?", "header": "항목", "options": [{"label": "loss", "description": ""}, {"label": "acc", "description": ""}], "multiSelect": True},
]}


def test_질문에_답하면_answers_로_돌려준다(fake, project, conn):
    async def go():
        bus.bind(asyncio.get_running_loop())
        m = Manager()
        fake.script = [("AskUserQuestion", Q)]
        s = await m.create("demo", text="정리해 줘")
        [p] = await wait_pending(m)
        assert m.pending_list()[0]["summary"] == "어느 형식으로 쓸까요? 외 1개"
        assert "질문" in inbox.items(conn)[0]["title"]
        with pytest.raises(AgentError, match="계속 허용"):
            m.answer(p.id, "allowSession")
        with pytest.raises(AgentError, match="없는 질문"):
            m.answer(p.id, "answer", answers={"엉뚱한 질문": "CSV"})
        with pytest.raises(AgentError, match="고르거나"):
            m.answer(p.id, "answer", answers={})
        m.answer(p.id, "answer", answers={"어느 형식으로 쓸까요?": "CSV", "무엇을 넣을까요?": ["loss", "acc"]}, via="ADE")
        await settle(m, s["id"])
        d = fake.instances[0].decisions[0]
        assert d.allow is True
        assert d.updated_input == {"questions": Q["questions"], "answers": {"어느 형식으로 쓸까요?": "CSV", "무엇을 넣을까요?": ["loss", "acc"]}}
        assert inbox.badge(conn) == 0

    run(go())


def test_보기_대신_직접_쓴_답(fake, project):
    async def go():
        bus.bind(asyncio.get_running_loop())
        m = Manager()
        fake.script = [("AskUserQuestion", Q)]
        s = await m.create("demo", text="정리해 줘")
        [p] = await wait_pending(m)
        m.answer(p.id, "answer", response="둘 다 말고 마크다운 표로 해 줘")
        await settle(m, s["id"])
        assert fake.instances[0].decisions[0].updated_input["response"] == "둘 다 말고 마크다운 표로 해 줘"

    run(go())


def test_Ultracode_는_다음_연결부터(fake, project):
    async def go():
        bus.bind(asyncio.get_running_loop())
        m = Manager()
        s = await m.create("demo", text="1")
        await settle(m, s["id"])
        await m.configure(s["id"], ultracode=True)
        assert s["id"] not in m.live
        await m.send(s["id"], "2")
        await settle(m, s["id"])
        assert fake.instances[-1].config.extra == {"ultracode": True}

    run(go())
