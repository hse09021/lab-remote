"""에이전트 세션 관리 — 저장 · 이어 가기 · 동시 세션 상한 · 승인 흐름.

저장: `<프로젝트>/.labremote/sessions/<id>.json`(기록)과 `<id>.jsonl`(이벤트).
서버가 다시 떠도 목록과 에이전트 쪽 세션 id 가 남아 **이어 갈 수 있다**
(PLAN 4.1). 대화 원문은 에이전트(Claude Code)도 따로 갖고 있다.

승인: 연결 부품이 도구를 쓰기 전에 묻으면 "대기 중 승인" 으로 올리고
(화면 SSE · Inbox · Discord), **먼저 온 답**을 돌려준다. 어느 화면에서 답해도
같다. "이 세션에서 계속 허용" 은 lab.remote 가 이 세션 안에서만 기억한다 —
Claude Code 설정 파일에 쓰지 않는다.

모든 함수는 서버의 이벤트 루프에서 돈다.
"""

from __future__ import annotations

import asyncio
import json
import os
import re
import secrets
import time
from dataclasses import dataclass, field

from .. import alerts, db, inbox, paths, projects, registry
from ..events import bus
from ..git import ops as git_ops
from ..git import worktree as worktree_mod
from .base import MODES, AgentBackend, ApprovalRequest, Decision, SessionConfig

__all__ = ["AgentError", "Manager", "manager", "MAX_LIVE", "STATE_LABELS"]

MAX_LIVE = 4
ID_RE = re.compile(r"\As-[0-9a-f]{10}\Z")
STATE_LABELS = {"ask": "답 필요", "working": "작업 중", "idle": "끝남", "error": "오류"}
EFFORTS = ("", "low", "medium", "high", "xhigh", "max")
#: 파일을 다루는 도구 — "이 세션에서 이 파일은 계속 허용" 의 열쇠가 파일 경로다
FILE_TOOLS = ("Edit", "Write", "MultiEdit", "NotebookEdit")


class AgentError(ValueError):
    """사람에게 그대로 보여 줄 수 있는 거절 사유."""


#: 연결 부품. Codex 를 붙이면 여기에 한 줄 더한다(시험은 가짜를 끼운다).
BACKENDS: dict[str, object] = {}


def _backend_class(kind: str):
    if kind in BACKENDS:
        return BACKENDS[kind]
    if kind == "claude":
        from .claude import ClaudeBackend

        return ClaudeBackend
    raise AgentError(f"모르는 에이전트예요: {kind}")


@dataclass
class Pending:
    id: str
    session: str
    project: str
    request: ApprovalRequest
    future: asyncio.Future
    created: float
    inbox_id: int | None = None
    #: 승인 카드에 띄울 경고 (학습이 쓰는 환경에 설치 등)
    warning: str = ""


@dataclass
class Live:
    backend: AgentBackend
    lock: asyncio.Lock = field(default_factory=asyncio.Lock)
    allow_keys: set = field(default_factory=set)
    last_used: float = field(default_factory=time.time)


#: 패키지를 바꾸는 명령처럼 보이나 — **경고용 짐작**이다. 막는 데 쓰지 않는다
#: (명령 글자로는 빠짐없이 가를 수 없다 — v1에서 62가지 중 52가지가 빠져나갔다).
INSTALL_RE = re.compile(
    r"\b(?:pip3?|python[0-9.]*\s+-m\s+pip|conda|mamba|micromamba|uv)\b[^;&|]*?\b"
    r"(?:install|add|update|upgrade|remove|uninstall)\b"
)
ENV_NAME_RE = re.compile(r"(?:-n|--name)\s+([A-Za-z0-9][A-Za-z0-9._-]*)")


def install_warning(project: str, req: ApprovalRequest) -> str:
    """학습이 쓰고 있는 conda 환경에 설치하려는 것 같으면 경고 한 줄. 아니면 "".

    명령에 `-n 환경` 이 있으면 그 환경을 쓰는 학습(모든 프로젝트)을, 없으면 이 프로젝트에서
    도는 학습을 본다. 사람이 승인 카드에서 판단하도록 알려 주기만 한다(사람이 고름, 2026-11-23).
    """
    if req.tool != "Bash":
        return ""
    command = str(req.input.get("command") or "")
    if not INSTALL_RE.search(command):
        return ""
    from .. import runs

    named = ENV_NAME_RE.search(command)
    busy = []
    for _root, name in registry.load().items():
        if not named and name != project:
            continue
        try:
            items = runs.list_runs(name, refresh_running=False)
        except Exception:
            continue
        for r in items:
            if r["state"] != "running":
                continue
            if named and r.get("env") != named.group(1):
                continue
            busy.append(f"{r.get('name') or r['id']} 이 {r.get('env') or 'conda 없이'}")
    if not busy:
        return ""
    return f"{', '.join(busy[:3])} 로 학습 중이에요. 지금 패키지를 바꾸면 학습이 깨질 수 있어요."


def _allow_key(req: ApprovalRequest) -> tuple:
    if req.tool in FILE_TOOLS:
        return (req.tool if req.tool != "MultiEdit" else "Edit", str(req.input.get("file_path") or req.input.get("notebook_path") or ""))
    if req.tool == "Bash":
        return ("Bash", str(req.input.get("command") or ""))
    return (req.tool, json.dumps(req.input, sort_keys=True, ensure_ascii=False)[:2000])


class Manager:
    def __init__(self) -> None:
        self.live: dict[str, Live] = {}
        self.pending: dict[str, Pending] = {}
        self._info: tuple[float, dict] | None = None

    # --- 저장 ----------------------------------------------------------------

    @staticmethod
    def _dir(root: str) -> str:
        return os.path.join(projects.labremote_dir(root), "sessions")

    def _paths(self, root: str, sid: str) -> tuple[str, str]:
        if not ID_RE.match(sid or ""):
            raise AgentError(f"세션 id 가 올바르지 않아요: {sid!r}")
        d = self._dir(root)
        return os.path.join(d, f"{sid}.json"), os.path.join(d, f"{sid}.jsonl")

    def _find(self, sid: str) -> tuple[str, dict]:
        for root, _name in registry.load().items():
            path, _ = self._paths(root, sid)
            if os.path.exists(path):
                with open(path, encoding="utf-8") as fh:
                    return root, json.load(fh)
        raise AgentError(f"없는 세션이에요: {sid}")

    def _save(self, root: str, rec: dict) -> None:
        rec["updatedAt"] = time.time()
        registry.write_json(self._paths(root, rec["id"])[0], rec)

    def _append(self, root: str, sid: str, event: dict) -> dict:
        event = {"at": time.time(), **event}
        _, log = self._paths(root, sid)
        os.makedirs(os.path.dirname(log), exist_ok=True)
        with open(log, "a", encoding="utf-8") as fh:
            fh.write(json.dumps(event, ensure_ascii=False) + "\n")
        bus.publish("session.event", {"session": sid, "event": event})
        return event

    def events(self, sid: str, limit: int = 3000) -> list[dict]:
        root, _ = self._find(sid)
        _, log = self._paths(root, sid)
        try:
            with open(log, encoding="utf-8") as fh:
                lines = fh.readlines()[-limit:]
        except FileNotFoundError:
            return []
        out = []
        for line in lines:
            try:
                out.append(json.loads(line))
            except json.JSONDecodeError:
                continue
        return out

    def _view(self, rec: dict) -> dict:
        out = dict(rec)
        sid = rec["id"]
        out["connected"] = sid in self.live
        out["busy"] = bool(sid in self.live and self.live[sid].backend.busy)
        out["stateLabel"] = STATE_LABELS.get(rec.get("state", ""), rec.get("state", ""))
        out["pending"] = [self._pending_view(p) for p in self.pending.values() if p.session == sid]
        out.pop("allowKeys", None)
        return out

    @staticmethod
    def _pending_view(p: Pending) -> dict:
        from .claude import summarize

        r = p.request
        return {
            "id": p.id,
            "session": p.session,
            "project": p.project,
            "tool": r.tool,
            "summary": summarize(r.tool, r.input),
            "input": r.input,
            "title": r.title,
            "reason": r.reason,
            "createdAt": p.created,
            "warning": p.warning,
        }

    def list(self, project: str = "") -> list[dict]:
        out = []
        for root, name in registry.load().items():
            if project and name != project:
                continue
            d = self._dir(root)
            if not os.path.isdir(d):
                continue
            for fname in os.listdir(d):
                if not fname.endswith(".json"):
                    continue
                try:
                    with open(os.path.join(d, fname), encoding="utf-8") as fh:
                        out.append(self._view(json.load(fh)))
                except (OSError, json.JSONDecodeError):
                    continue
        out.sort(key=lambda r: -(r.get("updatedAt") or 0))
        return out

    def get(self, sid: str) -> dict:
        _, rec = self._find(sid)
        return {**self._view(rec), "events": self.events(sid)}

    # --- 시작 · 복구 ------------------------------------------------------------

    def recover(self) -> int:
        """서버가 뜰 때 — 작업 중이던 세션은 연결이 끊긴 것으로 적는다.

        기다리던 승인 요청은 프로세스와 함께 사라졌으니, Inbox 의 안 읽은
        "답 필요" 도 읽음으로 돌린다(배지가 답할 수 없는 걸 세지 않게).
        """
        try:
            with db.open_db() as conn:
                conn.execute(
                    "UPDATE inbox SET read_at = ?, sent = CASE WHEN sent = '' THEN '서버가 다시 떠서 사라졌어요' "
                    "ELSE sent || ' · 서버가 다시 떠서 사라졌어요' END WHERE kind = 'ask' AND read_at IS NULL",
                    (db.now(),),
                )
        except Exception:
            pass
        n = 0
        for rec in self.list():
            if rec.get("state") in ("working", "ask"):
                root, raw = self._find(rec["id"])
                raw["state"] = "idle"
                raw["note"] = "서버가 다시 떠서 연결이 끊겼어요. 메시지를 보내면 이어서 해요."
                self._save(root, raw)
                n += 1
        return n

    async def info(self) -> dict:
        """모델 목록·슬래시 명령 (10분 캐시). 연결된 세션이 있으면 그걸 쓴다."""
        now = time.time()
        if self._info and now - self._info[0] < 600:
            return self._info[1]
        for live in self.live.values():
            got = getattr(live.backend, "info", None)
            if got:
                self._info = (now, got)
                return got
        from .claude import probe_info

        got = await probe_info(registry.data_dir())
        self._info = (now, got)
        return got

    async def create(
        self,
        project: str,
        *,
        text: str,
        title: str = "",
        tree: str = "",
        new_branch: str = "",
        mode: str = "manual",
        model: str = "",
        effort: str = "",
        ultracode: bool = False,
        kind: str = "claude",
    ) -> dict:
        root = projects.require(project)
        text = (text or "").strip()
        if not text:
            raise AgentError("첫 메시지를 적어 주세요.")
        if mode not in MODES:
            raise AgentError(f"모르는 Mode 예요: {mode}")
        if effort not in EFFORTS:
            raise AgentError(f"모르는 Effort 예요: {effort}")
        _backend_class(kind)
        if new_branch:
            made = await asyncio.to_thread(worktree_mod.add, root, new_branch)
            tree = made["rel"] or ""
        from .. import files

        cwd = files.base_of(root, tree)
        branch = ""
        try:
            branch = await asyncio.to_thread(git_ops.current_branch, cwd)
        except Exception:
            branch = ""
        sid = "s-" + secrets.token_hex(5)
        rec = {
            "version": 1,
            "id": sid,
            "kind": kind,
            "project": project,
            "title": (title or text.splitlines()[0])[:80],
            "tree": paths.rel_or_none(root, cwd) or ".",
            "branch": branch,
            "mode": mode,
            "model": model,
            "effort": effort,
            "ultracode": bool(ultracode),
            "agentSessionId": "",
            "createdAt": time.time(),
            "state": "idle",
            "lastText": "",
            "todos": None,
            "note": "",
            "allowKeys": [],
        }
        os.makedirs(self._dir(root), exist_ok=True)
        self._save(root, rec)
        bus.publish("session.created", {"session": sid, "project": project})
        await self.send(sid, text)
        return self.get(sid)

    async def _ensure_live(self, sid: str, root: str, rec: dict) -> Live:
        live = self.live.get(sid)
        if live:
            return live
        if len(self.live) >= MAX_LIVE:
            idle = sorted(
                ((s, l) for s, l in self.live.items() if not l.backend.busy and not any(p.session == s for p in self.pending.values())),
                key=lambda x: x[1].last_used,
            )
            if not idle:
                raise AgentError(f"동시에 돌 수 있는 세션은 {MAX_LIVE}개예요. 다른 세션이 끝나면 다시 보내 주세요.")
            await self.disconnect(idle[0][0])
        from .. import files

        cfg = SessionConfig(
            cwd=files.base_of(root, "" if rec.get("tree") in (".", "") else rec["tree"]),
            mode=rec.get("mode") or "manual",
            model=rec.get("model") or "",
            effort=rec.get("effort") or "",
            resume=rec.get("agentSessionId") or "",
            extra={"ultracode": bool(rec.get("ultracode"))},
        )
        cls = _backend_class(rec.get("kind") or "claude")
        backend = cls(cfg, emit=lambda ev: self._on_event(sid, ev), ask=lambda req: self._on_ask(sid, req))
        try:
            await backend.connect()
        except Exception as exc:
            raise AgentError(f"에이전트를 띄우지 못했어요: {exc}") from None
        live = Live(backend=backend, allow_keys={tuple(k) for k in rec.get("allowKeys") or []})
        self.live[sid] = live
        bus.publish("session.state", {"session": sid})
        return live

    # --- 메시지 ---------------------------------------------------------------

    async def send(self, sid: str, text: str) -> dict:
        root, rec = self._find(sid)
        text = (text or "").strip()
        if not text:
            raise AgentError("메시지를 적어 주세요.")
        live = await self._ensure_live(sid, root, rec)
        if live.backend.busy:
            raise AgentError("아직 앞 차례가 끝나지 않았어요. 멈추거나 끝나길 기다려 주세요.")
        live.last_used = time.time()
        self._append(root, sid, {"type": "user", "text": text})
        rec["state"] = "working"
        rec["note"] = ""
        self._save(root, rec)
        bus.publish("session.state", {"session": sid})
        await live.backend.send(text)
        asyncio.create_task(self._after_turn(sid), name=f"turn-{sid}")
        return self._view(rec)

    async def _after_turn(self, sid: str) -> None:
        live = self.live.get(sid)
        if not live:
            return
        await live.backend.wait_idle()
        try:
            root, rec = self._find(sid)
        except AgentError:
            return
        rec["state"] = "idle"
        if live.backend.agent_session_id:
            rec["agentSessionId"] = live.backend.agent_session_id
        self._save(root, rec)
        bus.publish("session.state", {"session": sid})

    def _on_event(self, sid: str, event: dict) -> None:
        try:
            root, rec = self._find(sid)
        except AgentError:
            return
        self._append(root, sid, event)
        changed = False
        if event.get("type") == "text" and not event.get("parent"):
            rec["lastText"] = event["text"][:400]
            changed = True
        elif event.get("type") == "todos":
            items = event.get("items") or []
            now = next((t["content"] for t in items if t.get("status") == "in_progress"), "")
            rec["todos"] = {"done": sum(1 for t in items if t.get("status") == "completed"), "total": len(items), "current": now}
            changed = True
        elif event.get("type") == "subagent":
            # Agents 그래프에 쓸 하위 에이전트 (최근 10개)
            subs = [x for x in rec.get("subagents") or [] if x.get("taskId") != event.get("taskId")]
            subs.append({"taskId": event.get("taskId"), "description": str(event.get("description") or "")[:120], "status": event.get("status"), "at": time.time()})
            rec["subagents"] = subs[-10:]
            changed = True
        elif event.get("type") == "result":
            if event.get("error"):
                rec["note"] = event["error"][:300]
            changed = True
        live = self.live.get(sid)
        if live and live.backend.agent_session_id and rec.get("agentSessionId") != live.backend.agent_session_id:
            rec["agentSessionId"] = live.backend.agent_session_id
            changed = True
        if changed:
            self._save(root, rec)
            bus.publish("session.state", {"session": sid})

    # --- 승인 ----------------------------------------------------------------

    async def _on_ask(self, sid: str, req: ApprovalRequest) -> Decision:
        root, rec = self._find(sid)
        live = self.live.get(sid)
        if live and _allow_key(req) in live.allow_keys:
            self._append(root, sid, {"type": "approval", "approvalId": "", "state": "allowed", "tool": req.tool, "via": "이 세션에서 계속 허용"})
            return Decision(allow=True)
        aid = "a-" + secrets.token_hex(5)
        loop = asyncio.get_running_loop()
        pending = Pending(id=aid, session=sid, project=rec["project"], request=req, future=loop.create_future(), created=time.time())
        try:
            pending.warning = await asyncio.to_thread(install_warning, rec["project"], req)
        except Exception:
            pending.warning = ""
        self.pending[aid] = pending
        view = self._pending_view(pending)
        self._append(root, sid, {"type": "approval", "approvalId": aid, "state": "pending", **{k: view[k] for k in ("tool", "summary", "input", "title", "reason")}})
        rec["state"] = "ask"
        self._save(root, rec)
        def _notify() -> int | None:
            # Discord 재시도가 sleep 을 쓰므로 이벤트 루프 밖(스레드)에서 돈다
            with db.open_db() as conn:
                return alerts.post(
                    conn, "ask", "ask",
                    f"{rec['title']} · " + ("질문" if req.tool == "AskUserQuestion" else f"{req.tool} 승인"),
                    where=f"{rec['project']} · {rec.get('branch') or ('프로젝트 루트' if rec.get('tree') in ('.', '') else rec.get('tree'))}",
                    body=req.title or view["summary"],
                    project=rec["project"],
                    ref={"project": rec["project"], "session": sid, "approval": aid},
                    act=True,
                    subject=f"ask:{aid}",
                )["id"]

        try:
            pending.inbox_id = await asyncio.to_thread(_notify)
        except Exception:
            pass
        bus.publish("approval.new", view)
        bus.publish("session.state", {"session": sid})
        try:
            return await pending.future
        finally:
            self.pending.pop(aid, None)

    def answer(
        self,
        aid: str,
        choice: str,
        *,
        reason: str = "",
        via: str = "",
        answers: dict | None = None,
        response: str = "",
    ) -> dict:
        """`choice`: allow · allowSession · deny · answer(질문에 답). 먼저 온 답만 먹는다."""
        p = self.pending.get(aid)
        if not p or p.future.done():
            raise AgentError("이미 답했거나 사라진 승인 요청이에요.")
        if choice not in ("allow", "allowSession", "deny", "answer"):
            raise AgentError(f"모르는 답이에요: {choice}")
        if choice == "answer":
            return self._answer_questions(p, answers or {}, response, via)
        root, rec = self._find(p.session)
        if choice == "allowSession" and p.request.tool == "AskUserQuestion":
            raise AgentError("질문에는 '계속 허용' 이 없어요. 답을 골라 주세요.")
        if choice == "allowSession":
            key = _allow_key(p.request)
            live = self.live.get(p.session)
            if live:
                live.allow_keys.add(key)
            rec["allowKeys"] = sorted({tuple(k) for k in rec.get("allowKeys") or []} | {key})
        decision = (
            Decision(allow=True)
            if choice != "deny"
            else Decision(allow=False, message=(f"사람이 거부했어요: {reason}" if reason else "사람이 거부했어요."))
        )
        p.future.set_result(decision)
        state = {"allow": "allowed", "allowSession": "allowed", "deny": "denied"}[choice]
        self._append(root, p.session, {"type": "approval", "approvalId": aid, "state": state, "tool": p.request.tool, "reason": reason, "via": via, "always": choice == "allowSession"})
        if not any(x.session == p.session and x.id != aid for x in self.pending.values()):
            rec["state"] = "working"
        self._save(root, rec)
        if p.inbox_id:
            try:
                with db.open_db() as conn:
                    inbox.mark_read(conn, [p.inbox_id])
            except Exception:
                pass
        bus.publish("approval.done", {"id": aid, "session": p.session, "state": state})
        bus.publish("session.state", {"session": p.session})
        return {"id": aid, "state": state}

    def _answer_questions(self, p: Pending, answers: dict, response: str, via: str) -> dict:
        """AskUserQuestion — 답은 질문 글을 열쇠로, 고른 label(여러 개면 목록)을 값으로.

        `response` 는 보기 대신 자유롭게 쓴 답이다(문서의 top-level `response`).
        """
        questions = p.request.input.get("questions")
        if not isinstance(questions, list):
            raise AgentError("질문 요청이 아니에요.")
        texts = {str(q.get("question", "")) for q in questions if isinstance(q, dict)}
        clean: dict = {}
        for key, value in (answers or {}).items():
            if key not in texts:
                raise AgentError(f"없는 질문이에요: {key[:60]}")
            if isinstance(value, list):
                items = [str(v).strip() for v in value if str(v).strip()]
                if items:
                    clean[key] = items
            elif str(value).strip():
                clean[key] = str(value).strip()
        response = (response or "").strip()
        if not clean and not response:
            raise AgentError("답을 고르거나 적어 주세요.")
        updated = {"questions": questions, "answers": clean}
        if response:
            updated["response"] = response
        root, rec = self._find(p.session)
        p.future.set_result(Decision(allow=True, updated_input=updated))
        self._append(root, p.session, {"type": "approval", "approvalId": p.id, "state": "answered", "tool": p.request.tool, "answers": clean, "response": response, "via": via})
        if not any(x.session == p.session and x.id != p.id for x in self.pending.values()):
            rec["state"] = "working"
        self._save(root, rec)
        if p.inbox_id:
            try:
                with db.open_db() as conn:
                    inbox.mark_read(conn, [p.inbox_id])
            except Exception:
                pass
        bus.publish("approval.done", {"id": p.id, "session": p.session, "state": "answered"})
        bus.publish("session.state", {"session": p.session})
        return {"id": p.id, "state": "answered"}

    def pending_list(self) -> list[dict]:
        return [self._pending_view(p) for p in sorted(self.pending.values(), key=lambda p: p.created)]

    # --- 조작 ----------------------------------------------------------------

    async def interrupt(self, sid: str) -> dict:
        root, rec = self._find(sid)
        live = self.live.get(sid)
        if live:
            for p in [p for p in self.pending.values() if p.session == sid]:
                if not p.future.done():
                    p.future.set_result(Decision(allow=False, message="사람이 멈췄어요.", interrupt=True))
            await live.backend.interrupt()
            self._append(root, sid, {"type": "system", "text": "멈췄어요."})
        return self._view(rec)

    async def configure(
        self,
        sid: str,
        *,
        mode: str | None = None,
        model: str | None = None,
        effort: str | None = None,
        ultracode: bool | None = None,
    ) -> dict:
        """Mode·Model 은 바로, Effort·Ultracode 는 다음 연결부터(쉬고 있으면 끊었다가 이어 간다)."""
        root, rec = self._find(sid)
        live = self.live.get(sid)
        if ultracode is not None and bool(ultracode) != bool(rec.get("ultracode")):
            rec["ultracode"] = bool(ultracode)
            if live and not live.backend.busy:
                await self.disconnect(sid)
                live = None
        if mode is not None:
            if mode not in MODES:
                raise AgentError(f"모르는 Mode 예요: {mode}")
            rec["mode"] = mode
            if live:
                await live.backend.set_mode(mode)
        if model is not None:
            rec["model"] = model
            if live:
                await live.backend.set_model(model)
        if effort is not None:
            if effort not in EFFORTS:
                raise AgentError(f"모르는 Effort 예요: {effort}")
            if effort != rec.get("effort") and live and not live.backend.busy:
                await self.disconnect(sid)
            rec["effort"] = effort
        self._save(root, rec)
        bus.publish("session.state", {"session": sid})
        return self._view(rec)

    async def disconnect(self, sid: str) -> None:
        live = self.live.pop(sid, None)
        if not live:
            return
        for p in [p for p in self.pending.values() if p.session == sid]:
            if not p.future.done():
                p.future.set_result(Decision(allow=False, message="세션이 닫혔어요.", interrupt=True))
        if live.backend.agent_session_id:
            try:
                root, rec = self._find(sid)
                rec["agentSessionId"] = live.backend.agent_session_id
                if rec.get("state") != "idle":
                    rec["state"] = "idle"
                self._save(root, rec)
            except AgentError:
                pass
        await live.backend.close()
        bus.publish("session.state", {"session": sid})

    async def shutdown(self) -> None:
        for sid in list(self.live):
            await self.disconnect(sid)


manager = Manager()
