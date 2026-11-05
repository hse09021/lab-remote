"""🚪 돌릴 수 있는 스크립트가 없을 때 — **설계 세션을 버리지 않는다.**

9단계를 시작하려는데 `hook-sandbox` 의 `specifications/Config.yaml` 에 `run:`
절이 통째로 없었다. `run:` 이 생기기 전 템플릿으로 만든 프로젝트다.

그대로였으면 루프는 A(설계)를 **정상으로 끝내고** B(실행)에서
`run.json 을 믿을 수 없어요` 로 죽는다 — Claude 호출 하나를 버린 뒤다.
"""

import os

import pytest

from app import doctor
from app.orchestrator import guards
from app.runner import spec as spec_mod

from test_orchestrator_loop import (  # noqa: F401
    ctx_for,
    fake,
    healthy_gpu,
    ready,
    write_config,
)

TEMPLATE = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    "app", "templates", "project", "specifications", "Config.yaml.tmpl",
)


def config_path(root):
    return os.path.join(root, "specifications", "Config.yaml")


def drop_run_section(root):
    """`run:` 절이 없는 옛 Config.yaml 로 되돌린다."""
    path = config_path(root)
    with open(path, encoding="utf-8") as fh:
        body = fh.read()
    head = body.split("\nrun:", 1)[0].rstrip() + "\n"
    with open(path, "w", encoding="utf-8") as fh:
        fh.write(head)
    return path


# --- 사유 문구 -------------------------------------------------------------------


def test_run_절이_없으면_옛_템플릿이라고_말한다(ready):
    drop_run_section(ready)
    gap = guards.entrypoint_gap(ready)
    assert "run: 절이 없어요" in gap
    assert "옛 템플릿" in gap


def test_갓_만든_프로젝트는_doctor_가_경고로_둔다(ready):
    """`init-project` 직후다 — 사람이 아직 학습 스크립트를 안 썼을 뿐이고
    설치가 깨진 게 아니다. ✘ 면 "고칠 수 없는 ✘" 가 된다."""
    path = config_path(ready)
    with open(path, encoding="utf-8") as fh:
        body = fh.read()
    with open(path, "w", encoding="utf-8") as fh:
        fh.write(body.replace("entrypoints: [src/train.py]", "entrypoints: []"))
    got = doctor.entrypoint_check(ready, "hook-sandbox")
    assert got["level"] == "warn"
    assert got["ok"] is False


def test_run_절이_없으면_doctor_가_막는다(ready):
    """옛 템플릿은 **어긋남**이다 — 경고로 두면 모르고 지나간다."""
    drop_run_section(ready)
    assert doctor.entrypoint_check(ready, "hook-sandbox")["level"] == "bad"


def test_적힌_파일이_없으면_doctor_가_막는다(ready):
    os.remove(os.path.join(ready, "src", "train.py"))
    assert doctor.entrypoint_check(ready, "hook-sandbox")["level"] == "bad"


def test_목록만_비어_있으면_다르게_말한다(ready):
    path = config_path(ready)
    with open(path, encoding="utf-8") as fh:
        body = fh.read()
    with open(path, "w", encoding="utf-8") as fh:
        fh.write(body.replace("entrypoints: [src/train.py]", "entrypoints: []"))
    gap = guards.entrypoint_gap(ready)
    assert "돌릴 수 있는 스크립트가 없어요" in gap
    assert "옛 템플릿" not in gap


def test_적힌_파일이_없으면_그_이름을_말한다(ready):
    os.remove(os.path.join(ready, "src", "train.py"))
    gap = guards.entrypoint_gap(ready)
    assert "src/train.py" in gap


def test_제대로_적혀_있으면_빈_문자열(ready):
    assert guards.entrypoint_gap(ready) == ""


# --- 루프가 Claude 를 띄우기 전에 멈추나 ------------------------------------------


def test_Claude_를_띄우지_않고_멈춘다(conn, ready, fake):
    """이게 이 시험의 요점이다. 설계 세션을 **쓰지 않는다.**"""
    from app.orchestrator.__main__ import once

    drop_run_section(ready)
    got = once(conn, "hook-sandbox", ready, **ctx_for(ready, fake))
    assert got["ok"] is False
    assert fake.calls == [], "Claude 를 띄웠어요 — 설계 세션을 버렸어요"
    assert "run: 절이 없어요" in str(got)


def test_멈춘_사유가_stop_이다(conn, ready):
    """기다리면 풀리는 게 아니다 — 사람이 파일을 고쳐야 한다."""
    drop_run_section(ready)
    verdict = guards.check_loop(conn, "hook-sandbox", ready)
    assert verdict.ok is False
    assert verdict["stop"] is True


# --- doctor 가 붙여 넣을 내용을 준다 ----------------------------------------------


def test_doctor_가_막고_붙여_넣을_내용을_준다(ready):
    drop_run_section(ready)
    got = doctor.entrypoint_check(ready, "hook-sandbox")
    assert got["ok"] is False
    assert got["level"] == "bad"
    assert "run:" in got["hint"]
    assert "entrypoints:" in got["hint"]


def test_doctor_가_제대로_적혀_있으면_통과(ready):
    got = doctor.entrypoint_check(ready, "hook-sandbox")
    assert got["ok"] is True
    assert "src/train.py" in got["detail"]


def test_안내_문구의_키가_템플릿과_같다():
    """`doctor` 가 알려 주는 `run:` 절이 **생성기 템플릿과 어긋나면** 사람이
    붙여 넣은 뒤에도 모르는 키로 거부될 수 있다."""
    import yaml

    with open(TEMPLATE, encoding="utf-8") as fh:
        template = fh.read()
    # 템플릿의 `$env_name` 자리표시를 지우고 YAML 로 읽는다
    template = template.replace("$env_name", "x").replace("$python_version", "3.11")
    want = set((yaml.safe_load(template) or {}).get("run") or {})

    body = doctor.RUN_BLOCK_HINT.split("\n", 1)[1]
    got = set((yaml.safe_load(body) or {}).get("run") or {})
    assert got == want, f"템플릿과 안내 문구의 키가 달라요: {got ^ want}"


def test_안내_문구가_그대로_붙여_넣어_통과한다(ready):
    """사람이 그대로 붙여 넣으면 정말 통과해야 한다."""
    path = drop_run_section(ready)
    body = doctor.RUN_BLOCK_HINT.split("\n", 1)[1]
    with open(path, "a", encoding="utf-8") as fh:
        fh.write("\n" + body.strip() + "\n")

    # 안내 문구의 예시 스크립트를 두면
    import shutil
    from test_orchestrator_loop import FAKE

    shutil.copy(FAKE, os.path.join(ready, "src", "fake_train.py"))
    assert guards.entrypoint_gap(ready) == ""
    assert spec_mod.entrypoints_of(guards.read_config(ready)) == ["src/fake_train.py"]
