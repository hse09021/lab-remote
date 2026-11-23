"""FastAPI 앱 — `labremote serve` 가 띄운다. 빌드된 웹(`web/dist`)도 같이 내준다.

### 🔑 127.0.0.1 에만 열지만, 그것만으로는 모자라다

브라우저에서 연 **아무 웹 페이지**나 `http://127.0.0.1:8000` 으로 요청을 보낼
수 있다. 그래서 두 겹을 더 둔다.

1. **Host 검사** — `Host` 가 `127.0.0.1`·`localhost`·`[::1]`(포트 무관)이
   아니면 거절한다. DNS rebinding(공격자 도메인을 127.0.0.1 로 돌려 응답까지
   읽는 것)을 막는다. 터널 주소는 9단계에서 `LAB_ALLOWED_HOSTS` 로 더한다.
2. **바꾸는 요청에는 `X-Lab-Remote: 1` 헤더** — 다른 출처의 페이지가 이
   헤더를 붙이려면 CORS 사전 요청이 필요한데, 이 서버는 CORS 를 허락하지
   않는다. `Origin` 이 있으면 그 호스트도 같은 규칙으로 본다.
"""

from __future__ import annotations

import os
from urllib.parse import urlsplit

from fastapi import FastAPI, Request
from fastapi.responses import FileResponse, JSONResponse

from . import files, paths, projects
from .git.guard import GitRefused

__all__ = ["create_app", "WEB_DIST", "LOCAL_HOSTS", "MUTATION_HEADER"]

_REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
WEB_DIST = os.path.join(_REPO, "web", "dist")

LOCAL_HOSTS = frozenset({"127.0.0.1", "localhost", "::1"})
MUTATION_HEADER = "x-lab-remote"
SAFE_METHODS = frozenset({"GET", "HEAD", "OPTIONS"})


def _hostname(value: str) -> str:
    """`Host` 값이나 `Origin` 의 netloc 에서 이름만."""
    value = (value or "").strip().lower()
    if value.startswith("["):  # [::1]:8000
        return value[1 : value.find("]")] if "]" in value else value
    return value.rsplit(":", 1)[0] if value.count(":") == 1 else value


def allowed_hosts() -> frozenset[str]:
    extra = {h.strip().lower() for h in (os.environ.get("LAB_ALLOWED_HOSTS") or "").split(",") if h.strip()}
    return LOCAL_HOSTS | extra


def _refuse(reason: str) -> JSONResponse:
    return JSONResponse({"detail": reason}, status_code=403)


def create_app(*, web_dist: str | None = None, port: int | None = None) -> FastAPI:
    from contextlib import asynccontextmanager

    from . import runs, watch
    from .api import agents as agents_api
    from .api import conda as conda_api
    from .api import files as files_api
    from .api import git as git_api
    from .api import ide as ide_api
    from .api import inbox as inbox_api
    from .api import projects as projects_api
    from .api import runs as runs_api
    from .api import scenarios as scenarios_api
    from .api import schedules as schedules_api
    from .api import system as system_api

    @asynccontextmanager
    async def lifespan(_app):
        import asyncio

        from .agents.manager import manager
        from .events import bus

        bus.bind(asyncio.get_running_loop())
        # 작업 중이던 에이전트 세션은 "연결 끊김" 으로 — 메시지를 보내면 이어 간다
        manager.recover()
        # 예약 시계 — 사람이 시각으로 건 예약만 (scheduler.py). 시험에서는 끈다
        from . import scheduler

        if os.environ.get("LAB_NO_WATCH") != "1":
            scheduler.start()
        # 실행 감시 — 끝남·실패·끊김을 알아채 Inbox·Discord 로 알린다 (watch.py)
        watcher = None
        if os.environ.get("LAB_NO_WATCH") != "1":
            watcher = watch.Watcher()
            watcher.start()
        try:
            yield
        finally:
            if watcher:
                watcher.stop()
            await scheduler.stop()
            await manager.shutdown()

    app = FastAPI(title="lab.remote", docs_url=None, redoc_url=None, openapi_url=None, lifespan=lifespan)
    app.state.port = port
    dist = paths.real(web_dist or WEB_DIST)

    @app.middleware("http")
    async def local_only(request: Request, call_next):
        hosts = allowed_hosts()
        if _hostname(request.headers.get("host", "")) not in hosts:
            return _refuse("이 주소로는 열 수 없어요 (Host 가 허용 목록에 없어요).")
        origin = request.headers.get("origin")
        if origin and origin != "null" and _hostname(urlsplit(origin).netloc) not in hosts:
            return _refuse("다른 사이트에서 온 요청이라 거절했어요.")
        if request.method not in SAFE_METHODS and request.url.path.startswith("/api/"):
            if request.headers.get(MUTATION_HEADER) != "1":
                return _refuse("lab.remote 화면에서 온 요청이 아니라 거절했어요.")
        return await call_next(request)

    @app.exception_handler(files.NotFound)
    async def _not_found(_request, exc):
        return JSONResponse({"detail": str(exc)}, status_code=404)

    @app.exception_handler(files.FileRefused)
    async def _file_refused(_request, exc):
        return JSONResponse({"detail": str(exc)}, status_code=400)

    @app.exception_handler(projects.ProjectError)
    async def _project_error(_request, exc):
        return JSONResponse({"detail": str(exc)}, status_code=400)

    @app.exception_handler(runs.RunError)
    async def _run_error(_request, exc):
        return JSONResponse({"detail": str(exc)}, status_code=400)

    from .git.worktree import WorktreeError

    @app.exception_handler(WorktreeError)
    async def _worktree_error(_request, exc):
        return JSONResponse({"detail": str(exc)}, status_code=400)

    @app.exception_handler(GitRefused)
    async def _git_refused(_request, exc):
        return JSONResponse({"detail": str(exc)}, status_code=409)

    @app.get("/api/health")
    def health():
        from .system import _version

        return {"ok": True, "version": _version()}

    app.include_router(projects_api.router, prefix="/api")
    app.include_router(files_api.router, prefix="/api")
    app.include_router(git_api.router, prefix="/api")
    app.include_router(system_api.router, prefix="/api")
    app.include_router(runs_api.router, prefix="/api")
    app.include_router(inbox_api.router, prefix="/api")
    app.include_router(agents_api.router, prefix="/api")
    app.include_router(ide_api.router, prefix="/api")
    app.include_router(schedules_api.router, prefix="/api")
    app.include_router(scenarios_api.router, prefix="/api")
    app.include_router(conda_api.router, prefix="/api")

    @app.get("/api/{rest:path}", include_in_schema=False)
    def api_missing(rest: str):
        return JSONResponse({"detail": f"없는 API 예요: /api/{rest}"}, status_code=404)

    @app.get("/{rest:path}", include_in_schema=False)
    def web(rest: str):
        index = os.path.join(dist, "index.html")
        if not os.path.isfile(index):
            return JSONResponse(
                {"detail": "웹이 아직 빌드되지 않았어요 — cd web && npm run build"},
                status_code=404,
            )
        if rest:
            target = os.path.realpath(os.path.join(dist, rest))
            if paths.is_inside(dist, target) and os.path.isfile(target):
                return FileResponse(target)
        return FileResponse(index)  # SPA — 화면 경로는 전부 index.html

    return app
