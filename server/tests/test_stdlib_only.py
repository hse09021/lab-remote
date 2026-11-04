"""훅 경로가 표준 라이브러리만 쓰는지, 그 중에서도 안 쓰기로 한 것까지.

훅은 도구 호출마다 새 프로세스로 뜬다. import 가 무거우면 체감이 나빠지고,
conda 환경이 깨지면 안전장치까지 같이 죽는다.

`sqlite3` 는 **표준 라이브러리지만 금지**다. ②의 상태는 `lab.db` 에 있는데,
훅이 그걸 열면 모니터·오케스트레이터와 잠금을 다투게 되고 그 지연이 곧
판정 지연이다. 훅이 보는 것은 `runstate` JSON 미러뿐이다.
"""

import json
import pathlib
import subprocess
import sys

HOOK_MODULES = [
    "app.hooks.pretooluse",
    "app.hooks.posttooluse",
    "app.hooks.stop",
    "app.hooks.sessionend",
    "app.hooks.debug",
    # ②에서 훅이 새로 import 하는 것 — 1회용 허가
    "app.grants",
]

#: 외부 패키지 + 훅 경로에서 쓰지 않기로 한 표준 모듈
FORBIDDEN = {
    "yaml",
    "fastapi",
    "pydantic",
    "uvicorn",
    "starlette",
    "numpy",
    "requests",
    "sqlite3",
}

APP = pathlib.Path(__file__).resolve().parents[1] / "app"

#: 훅이 직접·간접으로 import 하는 모듈. 여기엔 yaml·sqlite3 가 없어야 한다.
HOOK_PATH_FILES = sorted(APP.glob("hooks/*.py")) + [
    APP / "paths.py",
    APP / "policy.py",
    APP / "policy_defaults.py",
    APP / "registry.py",
    APP / "runstate.py",
    APP / "approval_log.py",
    APP / "audit.py",
    APP / "loop_layout.py",
    APP / "notify.py",
    # ②에서 추가된 훅 경로
    APP / "grants.py",
    APP / "config.py",
]


def _loaded(modules):
    code = (
        "import importlib, sys, json\n"
        f"for m in {modules!r}: importlib.import_module(m)\n"
        "print(json.dumps(sorted({k.split('.')[0] for k in sys.modules})))\n"
    )
    out = subprocess.run(
        [sys.executable, "-c", code], capture_output=True, text=True, check=True
    )
    return set(json.loads(out.stdout))


def test_훅_경로에_금지된_모듈이_없다():
    loaded = _loaded(HOOK_MODULES)
    assert not (loaded & FORBIDDEN), sorted(loaded & FORBIDDEN)


def test_훅이_sqlite3_를_안_쓴다():
    """②의 lab.db 는 훅의 일이 아니다. 잠금 경쟁이 판정 지연이 된다."""
    loaded = _loaded(HOOK_MODULES)
    assert "sqlite3" not in loaded


def test_훅_경로_파일에_금지_import_가_없다():
    """간접 import 까지 잡으려고 소스도 본다."""
    for path in HOOK_PATH_FILES:
        body = path.read_text(encoding="utf-8")
        assert "import yaml" not in body, path.name
        assert "import sqlite3" not in body, path.name
        # db·store 를 import 하면 그 안에서 sqlite3 가 딸려 온다.
        assert "from . import db" not in body, path.name
        assert "from .store" not in body, path.name


def test_db_와_store_는_훅_경로가_아니다():
    """반대 방향도 고정한다 — 여기는 sqlite3 를 써야 한다."""
    assert "import sqlite3" in (APP / "db.py").read_text(encoding="utf-8")
