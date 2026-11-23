"""/api/projects/{name}/runs — 실행 (CLI `labremote run`과 같은 함수)."""

from __future__ import annotations

from fastapi import APIRouter
from pydantic import BaseModel

from .. import runs

router = APIRouter()


class StartBody(BaseModel):
    command: str
    env: str = ""
    cwd: str = ""
    name: str = ""


class StopBody(BaseModel):
    force: bool = False


@router.get("/projects/{name}/runs")
def list_runs(name: str):
    return {"runs": runs.list_runs(name)}


@router.post("/projects/{name}/runs")
def start(name: str, body: StartBody):
    return runs.start(name, body.command, env=body.env, cwd=body.cwd, name=body.name)


@router.get("/projects/{name}/runs/{run_id}")
def get(name: str, run_id: str):
    return runs.get(name, run_id)


@router.post("/projects/{name}/runs/{run_id}/stop")
def stop(name: str, run_id: str, body: StopBody):
    return runs.stop(name, run_id, force=body.force)


@router.post("/projects/{name}/runs/{run_id}/ack")
def ack(name: str, run_id: str):
    return runs.ack(name, run_id)


@router.get("/projects/{name}/runs/{run_id}/log")
def log(name: str, run_id: str, lines: int = 400):
    return runs.log_tail(name, run_id, lines=lines)


@router.get("/projects/{name}/runs/{run_id}/metrics")
def metrics(name: str, run_id: str):
    return runs.metrics_summary(name, run_id)
