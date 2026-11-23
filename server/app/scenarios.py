"""Scenario — 프로젝트가 어떤 순서로 돌아가는지(데이터 준비 → 학습 → 평가 …)를 **보기 전용**으로.

PLAN 4.1 scenarios:
- **사람이 요청할 때만** 그린다. 에이전트를 계획 모드로, 도구는 읽기만(`Read` · `Glob` ·
  `Grep`) 열어서 파일을 읽고, 정해진 JSON 모양(`output_format`)으로 답하게 한다.
  명령을 돌리거나 파일을 고치지 못한다.
- `<프로젝트>/.labremote/scenarios/main.json`에 단계와 **분석한 파일들의 해시**를 저장한다.
  열 때마다 해시를 다시 재서 바뀐 파일을 알려 준다 — **저절로 다시 그리지 않는다.**
- 단계를 이어서 자동으로 돌리지 않는다(AI 자동화 없음). "실행 탭에 채우기" 는 명령만 채운다.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import os
import time

from . import files, paths, projects, registry
from .events import bus

__all__ = ["ScenarioError", "SCHEMA", "path_of", "load", "draw", "status", "file_hashes"]

#: 에이전트가 맞춰 답할 JSON 모양
SCHEMA = {
    "type": "object",
    "properties": {
        "summary": {"type": "string", "description": "이 프로젝트가 하는 일 한두 문장 (한국어)"},
        "steps": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "name": {"type": "string", "description": "단계 이름 (한국어, 짧게)"},
                    "command": {"type": "string", "description": "이 단계를 돌리는 셸 명령. 프로젝트 루트 기준. 없으면 빈 문자열"},
                    "inputs": {"type": "array", "items": {"type": "string"}, "description": "받는 파일·폴더"},
                    "outputs": {"type": "array", "items": {"type": "string"}, "description": "내는 파일·폴더"},
                    "env": {"type": "string", "description": "필요한 환경(conda 환경·GPU 등). 모르면 빈 문자열"},
                    "code": {"type": "array", "items": {"type": "string"}, "description": "이 단계의 코드 파일(프로젝트 루트 기준 상대 경로)"},
                    "note": {"type": "string", "description": "설정 여러 개 · 주의할 점 (한국어, 짧게)"},
                },
                "required": ["name", "command", "inputs", "outputs", "env", "code", "note"],
            },
        },
        "files": {"type": "array", "items": {"type": "string"}, "description": "분석하면서 읽은 파일(프로젝트 루트 기준 상대 경로)"},
    },
    "required": ["summary", "steps", "files"],
}

PROMPT = """이 프로젝트의 실행 순서(시나리오)를 그려 주세요.

- 코드를 읽어서 데이터 준비 → 학습 → 추론 → 평가 → 정리 같은 단계를 실제 파일에 맞게 나눠 주세요.
- 각 단계마다 돌리는 명령(프로젝트 루트 기준), 받는 파일, 내는 파일, 필요한 환경, 그 단계의 코드 파일을 적어 주세요.
- 명령은 README · 스크립트 · argparse 기본값에서 확인한 것만 적고, 모르면 빈 문자열로 두세요. 지어내지 마세요.
- 파일을 고치거나 명령을 돌리지 말고 읽기만 하세요. 읽은 파일 목록을 files에 적어 주세요.
- 이름 · 설명은 한국어로 짧게 써 주세요.
"""

READ_TOOLS = ["Read", "Glob", "Grep"]
MAX_TURNS = 40
MAX_HASH_FILES = 200

_jobs: dict[str, dict] = {}  # 프로젝트 → {"state", "startedAt", "error"}


class ScenarioError(ValueError):
    """사람에게 그대로 보여 줄 수 있는 거절 사유."""


def path_of(root: str) -> str:
    return os.path.join(projects.labremote_dir(root), "scenarios", "main.json")


def _hash(path: str) -> str | None:
    try:
        h = hashlib.sha256()
        with open(path, "rb") as fh:
            for chunk in iter(lambda: fh.read(1 << 20), b""):
                h.update(chunk)
        return h.hexdigest()
    except OSError:
        return None


def file_hashes(root: str, rels: list[str]) -> dict[str, str | None]:
    """프로젝트 안 파일만. 밖을 가리키거나 없는 건 None."""
    out: dict[str, str | None] = {}
    root_real = paths.real(root)
    for raw in rels[:MAX_HASH_FILES]:
        rel = str(raw).strip()
        if os.path.isabs(rel):  # 에이전트가 절대 경로로 적었으면 프로젝트 기준으로
            rel = paths.rel_or_none(root_real, paths.real(rel)) or ""
        while rel.startswith("./"):
            rel = rel[2:]
        if not rel or rel == "." or rel in out:
            continue
        try:
            target = files.resolve(root, rel)
        except files.FileRefused:
            out[rel] = None
            continue
        out[rel] = _hash(target) if os.path.isfile(target) else None
    return out


def load(project: str) -> dict:
    """저장된 시나리오 + 지금 바뀐 파일. 없으면 `{"scenario": None}`."""
    root = projects.require(project)
    job = _jobs.get(project) or {"state": "idle"}
    try:
        with open(path_of(root), encoding="utf-8") as fh:
            data = json.load(fh)
    except FileNotFoundError:
        return {"scenario": None, "job": job, "path": ".labremote/scenarios/main.json"}
    except (OSError, json.JSONDecodeError) as exc:
        return {"scenario": None, "job": job, "error": f"시나리오 파일을 읽지 못했어요 ({type(exc).__name__})"}
    saved = data.get("hashes") or {}
    now = file_hashes(root, list(saved))
    changed = sorted(p for p, h in saved.items() if now.get(p) != h)
    for step in data.get("steps") or []:
        step["changed"] = sorted(set(step.get("code") or []) & set(changed))
    return {"scenario": data, "changed": changed, "job": job, "path": ".labremote/scenarios/main.json"}


def status(project: str) -> dict:
    return _jobs.get(project) or {"state": "idle"}


async def _ask_agent(root: str, model: str, *, query_fn=None) -> tuple[dict, list[str], str]:
    """에이전트에게 읽기만 시켜 JSON 을 받는다. `(답, 실제로 읽은 파일, 모델)`."""
    from claude_agent_sdk import AssistantMessage, ClaudeAgentOptions, PermissionResultAllow, PermissionResultDeny, ResultMessage, ToolUseBlock

    from .agents.claude import SETTING_SOURCES, _scrub_env, cli_path

    async def read_only(tool_name, tool_input, _ctx):
        # tools로 이미 읽기만 열었지만 한 겹 더 — 읽기 도구가 아니면 거부
        if tool_name in READ_TOOLS:
            return PermissionResultAllow()
        return PermissionResultDeny(message="시나리오는 읽기만 해요.")

    _scrub_env()
    if not cli_path():
        raise ScenarioError("Claude Code(claude)를 찾지 못했어요.")
    options = ClaudeAgentOptions(
        # PDF · 이미지를 읽으면 메시지 하나가 SDK 기본 상한(1MB)을 넘어요 (실측 2026-11-24)
        max_buffer_size=32 * 1024 * 1024,
        cli_path=cli_path(),
        cwd=root,
        setting_sources=SETTING_SOURCES,
        permission_mode="plan",
        tools=list(READ_TOOLS),
        can_use_tool=read_only,
        model=model or None,
        max_turns=MAX_TURNS,
        output_format={"type": "json_schema", "schema": SCHEMA},
    )
    read: list[str] = []
    result = None
    used_model = ""
    run = query_fn
    if run is None:
        from claude_agent_sdk import ClaudeSDKClient

        async def run(opts, prompt):
            async with ClaudeSDKClient(options=opts) as client:
                await client.query(prompt)
                async for msg in client.receive_response():
                    yield msg

    async for msg in run(options, PROMPT):
        if isinstance(msg, AssistantMessage):
            used_model = msg.model or used_model
            for block in msg.content:
                if isinstance(block, ToolUseBlock) and block.name == "Read":
                    fp = str((block.input or {}).get("file_path") or "")
                    rel = paths.rel_or_none(root, paths.real(fp)) if fp else None
                    if rel and rel != ".":
                        read.append(rel)
        elif isinstance(msg, ResultMessage):
            result = msg
    if result is None or result.is_error:
        raise ScenarioError("에이전트가 답을 끝내지 못했어요: " + "; ".join((result.errors or []) if result else [])[:300])
    data = result.structured_output
    if isinstance(data, str):
        try:
            data = json.loads(data)
        except json.JSONDecodeError:
            data = None
    if not isinstance(data, dict) or not isinstance(data.get("steps"), list):
        raise ScenarioError("정해진 모양(JSON)으로 답을 받지 못했어요.")
    return data, read, used_model


def _clean_steps(steps: list) -> list[dict]:
    out = []
    for s in steps[:30]:
        if not isinstance(s, dict):
            continue
        lst = lambda k: [str(x)[:300] for x in (s.get(k) or []) if str(x).strip()][:30]  # noqa: E731
        out.append({
            "name": str(s.get("name") or "")[:80],
            "command": str(s.get("command") or "")[:1000],
            "inputs": lst("inputs"),
            "outputs": lst("outputs"),
            "env": str(s.get("env") or "")[:120],
            "code": lst("code"),
            "note": str(s.get("note") or "")[:300],
        })
    return out


async def draw(project: str, *, model: str = "", query_fn=None) -> dict:
    """그린다(사람이 눌렀을 때만). 이미 그리는 중이면 거절."""
    root = projects.require(project)
    if (_jobs.get(project) or {}).get("state") == "running":
        raise ScenarioError("이미 그리는 중이에요.")
    _jobs[project] = {"state": "running", "startedAt": time.time(), "error": ""}
    bus.publish("scenario.updated", {"project": project})
    try:
        data, read, used_model = await _ask_agent(root, model, query_fn=query_fn)
        steps = _clean_steps(data["steps"])
        listed = [str(x) for x in data.get("files") or []]
        code = [c for st in steps for c in st["code"]]
        # 해시는 실제로 읽은 파일 + 답에 적힌 파일 + 단계의 코드 파일.
        # 단계가 **내는 파일**(지표 · 체크포인트)은 뺀다 — 학습할 때마다 "바뀜" 이 뜨면 안 된다
        outs = [o.rstrip("/").replace("<", "").split("*")[0] for st in steps for o in st["outputs"]]
        outs = [o for o in outs if o]
        tracked = [
            f for f in dict.fromkeys(read + listed + code)
            if not any(f == o or f.startswith(o.rstrip("/") + "/") for o in outs)
        ]
        hashes = {k: v for k, v in (await asyncio.to_thread(file_hashes, root, tracked)).items() if v}
        out = {
            "version": 1,
            "createdAt": time.time(),
            "model": used_model,
            "summary": str(data.get("summary") or "")[:500],
            "steps": steps,
            "hashes": hashes,
        }
        projects.ensure_labremote(root)
        os.makedirs(os.path.dirname(path_of(root)), exist_ok=True)
        registry.write_json(path_of(root), out)
        _jobs[project] = {"state": "idle", "finishedAt": time.time(), "error": ""}
        return out
    except Exception as exc:
        _jobs[project] = {"state": "error", "error": str(exc)[:300], "finishedAt": time.time()}
        raise
    finally:
        bus.publish("scenario.updated", {"project": project})
