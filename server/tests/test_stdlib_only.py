"""훅 경로가 표준 라이브러리만 쓰는지.

훅은 도구 호출마다 새 프로세스로 뜬다. import 가 무거우면 체감이 나빠지고,
conda 환경이 깨지면 안전장치까지 같이 죽는다.
"""

import subprocess
import sys

HOOK_MODULES = [
    "app.hooks.pretooluse",
    "app.hooks.posttooluse",
    "app.hooks.stop",
    "app.hooks.sessionend",
    "app.hooks.debug",
]

FORBIDDEN = {"yaml", "fastapi", "pydantic", "uvicorn", "starlette", "numpy", "requests"}


def test_훅_경로에_외부_의존성이_없다():
    code = (
        "import importlib, sys, json\n"
        f"for m in {HOOK_MODULES!r}: importlib.import_module(m)\n"
        "print(json.dumps(sorted({k.split('.')[0] for k in sys.modules})))\n"
    )
    out = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True, check=True)
    import json

    loaded = set(json.loads(out.stdout))
    assert not (loaded & FORBIDDEN), sorted(loaded & FORBIDDEN)


def test_생성기만_pyyaml_을_쓴다():
    """정책·판정 쪽에서 PyYAML 을 끌어다 쓰면 훅이 환경에 묶인다."""
    import pathlib

    root = pathlib.Path(__file__).resolve().parents[1] / "app"
    for path in list(root.glob("hooks/*.py")) + [
        root / "paths.py",
        root / "policy.py",
        root / "policy_defaults.py",
        root / "registry.py",
        root / "runstate.py",
        root / "approval_log.py",
        root / "loop_layout.py",
    ]:
        body = path.read_text(encoding="utf-8")
        assert "import yaml" not in body, path.name
