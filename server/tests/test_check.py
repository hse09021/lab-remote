"""`labremote hooks check` — **실제 프로젝트에 아무것도 남기지 않는다.**

1차 실측에서 이 명령이 `logs/Approval_log.csv` 에 시험 기록 네 줄과 영원히
안 닫히는 대기 건(`data/pending/hook-sandbox/labremote-check.json`)을 남겼다.
자가진단이 진짜 기록을 더럽히면 로그를 믿을 수 없게 된다.
"""

import json
import os

import pytest

from app import approval_log as A
from app import registry
from app.hooks import check as hooks_check
from app.hooks import install


@pytest.fixture()
def installed(project, project_root, tmp_path, monkeypatch):
    """enforce 로 설치까지 끝난 상태. 래퍼에는 임시 프로젝트 루트가 박힌다."""
    settings = tmp_path / "claude" / "settings.json"
    settings.parent.mkdir(parents=True, exist_ok=True)
    settings.write_text("{}", encoding="utf-8")
    monkeypatch.setenv("LAB_CLAUDE_SETTINGS", str(settings))
    install.install(mode="enforce", roots=registry.projects_root())
    return project_root


def snapshot(root):
    """프로젝트와 런타임 폴더의 상태를 한 덩어리로."""
    log = A.log_path(root)
    return {
        "rows": len(A.read_rows(log)),
        "pending": sorted(A.list_pending("hook-sandbox")),
        "files": sorted(os.listdir(root)),
        "data": sorted(os.listdir(registry.data_dir())),
    }


def test_자가_점검이_기록을_남기지_않는다(installed, project_root):
    A.append_row(A.log_path(project_root), action="미리", request="기존 행", result="허용")
    before = snapshot(project_root)

    report = hooks_check.run_check("hook-sandbox")

    assert report["ok"] is True, report["rows"]
    assert report["scratch"] is True
    assert snapshot(project_root) == before


def test_대기_건도_안_남는다(installed):
    hooks_check.run_check("hook-sandbox")
    assert A.list_pending("hook-sandbox") == []
    assert not os.path.isdir(os.path.join(registry.data_dir(), "pending", "hook-sandbox"))


def test_스크래치_폴더를_지우고_끝낸다(installed):
    hooks_check.run_check("hook-sandbox")
    assert hooks_check.scratch_leftovers() == []


def test_죽은_실행의_잔해를_먼저_지운다(installed):
    leftover = os.path.join(registry.projects_root(), hooks_check.SCRATCH_PREFIX + "0")
    os.makedirs(leftover, exist_ok=True)
    hooks_check.run_check("hook-sandbox")
    assert not os.path.exists(leftover)


def test_실제_정책을_그대로_시험한다(installed):
    """프리셋을 "연구 전체 자동화" 로 올리면 코드 수정은 승인이 필요 없다."""
    from app import policy

    pol = policy.load("hook-sandbox")
    pol.set_saved("full")
    policy.save(pol)

    report = hooks_check.run_check("hook-sandbox")
    labels = {row["label"]: row for row in report["rows"]}
    # 잠긴 항목은 프리셋과 무관하게 그대로 막힌다
    assert labels["폴더 밖 쓰기"]["got"] == "deny"
    assert labels["비밀 파일 읽기"]["got"] == "deny"
    assert labels["서버 보호 파일"]["got"] == "deny"


def test_등록_안_된_프로젝트는_1(installed):
    report = hooks_check.run_check("없는-프로젝트")
    assert report["ok"] is False and "등록되지 않은" in report["reason"]


def test_프로브가_새_잠금을_덮는다(installed):
    """판 2 에서 늘어난 보호가 프로브에 들어 있어야 한다."""
    labels = {label for label, _, _ in hooks_check.PROBES("/tmp/x")}
    assert {"서버 보호 파일", "MCP 설정", "비밀 파일 읽기", "버린 출력", "산출물 삭제"} <= labels


def test_덤프_모드에서는_판정을_안_한다(project, project_root, tmp_path, monkeypatch):
    settings = tmp_path / "claude" / "settings.json"
    settings.parent.mkdir(parents=True, exist_ok=True)
    settings.write_text("{}", encoding="utf-8")
    monkeypatch.setenv("LAB_CLAUDE_SETTINGS", str(settings))
    install.install(mode="dump")
    report = hooks_check.run_check("hook-sandbox")
    assert report["ok"] is False and "dump 모드" in report["reason"]


def test_환경_변수를_되돌린다(installed, monkeypatch):
    """임시 데이터 폴더로 돌린 뒤 원래 값으로 돌아와야 한다."""
    before = (os.environ["LAB_DATA_DIR"], os.environ["LAB_PROJECTS_DIR"])
    hooks_check.run_check("hook-sandbox")
    assert (os.environ["LAB_DATA_DIR"], os.environ["LAB_PROJECTS_DIR"]) == before


def test_정책이_깨져_있으면_돌리지_않는다(installed):
    with open(registry.policy_path("hook-sandbox"), "w", encoding="utf-8") as fh:
        fh.write("{ 깨진")
    report = hooks_check.run_check("hook-sandbox")
    assert report["ok"] is False and "정책" in report["reason"]


def test_보고서가_JSON_으로_나간다(installed):
    report = hooks_check.run_check("hook-sandbox")
    json.dumps(report, ensure_ascii=False)  # 던지지 않아야 한다
    assert report["project"] == "hook-sandbox"
