"""`labremote doctor` 점검 항목 시험.

훅은 **조용히 안 뜨는 게 제일 위험하다.** 그래서 "안 걸려 있다"·"설정이
어긋난다" 를 눈에 보이게 하는 게 doctor 의 일이고, 그걸 여기서 지킨다.
"""

import json
import os

import pytest

from app import doctor, policy
from app import policy_defaults as D
from app.hooks import check as hooks_check
from app.hooks import install


@pytest.fixture()
def fake_settings(tmp_path, monkeypatch):
    """사용자 설정(`~/.claude/settings.json`)을 임시 파일로."""
    path = tmp_path / "claude" / "settings.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({"effortLevel": "high"}), encoding="utf-8")
    monkeypatch.setenv("LAB_CLAUDE_SETTINGS", str(path))
    return path


def check(report, title_part):
    for item in report["checks"]:
        if title_part in item["title"]:
            return item
    raise AssertionError(f"그런 점검이 없어요: {title_part} · {[c['title'] for c in report['checks']]}")


# --- 훅 이벤트 집합 ---------------------------------------------------------


def test_이벤트가_빠지면_알려_준다(project, project_root, fake_settings, monkeypatch):
    """설치한 뒤에 이벤트가 늘어나면 재설치 전까지 조용히 빠진다."""
    install.install(mode="enforce")
    data = json.loads(fake_settings.read_text(encoding="utf-8"))
    del data["hooks"]["UserPromptSubmit"]
    fake_settings.write_text(json.dumps(data), encoding="utf-8")

    item = check(doctor.run(), "훅 이벤트")
    assert item["ok"] is False
    assert "UserPromptSubmit" in item["detail"]


def test_전부_걸려_있으면_초록(project, project_root, fake_settings):
    install.install(mode="enforce")
    assert check(doctor.run(), "훅 이벤트")["ok"] is True


# --- extraWritableRoots 겹침 -------------------------------------------------


def test_보호_경로와_겹치면_알려_준다(project, project_root, fake_settings):
    pol = policy.load("hook-sandbox")
    pol.data["paths"]["extraWritableRoots"] = [D.hard_protected_roots()[0]]
    # save() 는 거부하므로 파일을 직접 쓴다 (손으로 고친 상황을 흉내 낸다)
    from app import registry

    registry.write_json(pol.path, pol.data)

    item = check(doctor.run(), "쓰기 예외")
    assert item["ok"] is False
    assert "겹쳐요" in item["detail"]


def test_겹치는_예외는_저장을_거부한다(project):
    pol = policy.load("hook-sandbox")
    pol.data["paths"]["extraWritableRoots"] = [os.path.expanduser("~/.claude")]
    with pytest.raises(policy.PolicyError) as exc:
        policy.save(pol)
    assert "보호 경로" in str(exc.value)


def test_안_겹치면_저장된다(project, tmp_path):
    pol = policy.load("hook-sandbox")
    pol.data["paths"]["extraWritableRoots"] = [str(tmp_path / "datasets")]
    policy.save(pol)  # 던지지 않아야 한다
    assert policy.load("hook-sandbox").paths["extraWritableRoots"]


# --- 권한 기본 모드 ---------------------------------------------------------


def test_프로젝트_설정에_있으면_초록(project, project_root, fake_settings):
    policy.ensure_permission_mode(project_root)
    item = doctor.permission_mode_check(project_root, "hook-sandbox")
    assert item["ok"] is True
    assert "프로젝트 설정" in item["detail"]


def test_둘_다_없으면_빨강(project, project_root, fake_settings):
    """2.1.317 은 사용자 설정에 defaultMode 가 없으면 auto 로 뜬다."""
    item = doctor.permission_mode_check(project_root, "hook-sandbox")
    assert item["ok"] is False
    assert "auto" in item["hint"]


def test_사용자_설정만_있어도_초록(project, project_root, fake_settings):
    fake_settings.write_text(
        json.dumps({"permissions": {"defaultMode": "default"}}), encoding="utf-8"
    )
    item = doctor.permission_mode_check(project_root, "hook-sandbox")
    assert item["ok"] is True
    assert "사용자 설정" in item["detail"]


def test_프로젝트_설정이_우회_모드면_빨강(project, project_root, fake_settings):
    os.makedirs(os.path.join(project_root, ".claude"), exist_ok=True)
    with open(policy.claude_settings_path(project_root), "w", encoding="utf-8") as fh:
        json.dump({"permissions": {"defaultMode": "bypassPermissions"}}, fh)
    assert doctor.permission_mode_check(project_root, "hook-sandbox")["ok"] is False


def test_이미_있는_defaultMode_는_안_바꾼다(project, project_root):
    """사람이 고른 모드를 되돌리지 않는다. 다른 키도 그대로 둔다."""
    os.makedirs(os.path.join(project_root, ".claude"), exist_ok=True)
    with open(policy.claude_settings_path(project_root), "w", encoding="utf-8") as fh:
        json.dump({"permissions": {"defaultMode": "plan"}, "나의키": 1}, fh)
    info = policy.ensure_permission_mode(project_root)
    assert info["mode"] == "plan"
    with open(info["path"], encoding="utf-8") as fh:
        data = json.load(fh)
    assert data["나의키"] == 1
    # ②에서 더하는 키는 새로 들어간다
    assert data["permissions"]["blockReadsOutsideWorkingDirectories"] is True


def test_두_번_불러도_안_바뀐다(project, project_root):
    os.makedirs(os.path.join(project_root, ".claude"), exist_ok=True)
    policy.ensure_permission_mode(project_root)
    again = policy.ensure_permission_mode(project_root)
    assert again["changed"] is False


def test_프로젝트_밖_읽기_쓰기를_막는_설정을_박는다(project, project_root):
    """홈의 자격 증명을 경로 하나하나 적지 않고 통째로 막는다 (실측 확인)."""
    os.makedirs(os.path.join(project_root, ".claude"), exist_ok=True)
    info = policy.ensure_permission_mode(project_root)
    with open(info["path"], encoding="utf-8") as fh:
        perms = json.load(fh)["permissions"]
    assert perms["blockReadsOutsideWorkingDirectories"] is True
    assert perms["blockWritesOutsideWorkingDirectories"] is True
    assert perms["blockReadsExemptPaths"] == []


def test_사람이_끈_설정은_되살리지_않는다(project, project_root):
    """읽어야 할 바깥 경로가 있어서 끈 것일 수 있다. 되돌리면 싸움이 된다."""
    os.makedirs(os.path.join(project_root, ".claude"), exist_ok=True)
    with open(policy.claude_settings_path(project_root), "w", encoding="utf-8") as fh:
        json.dump({"permissions": {"defaultMode": "default",
                                   "blockReadsOutsideWorkingDirectories": False}}, fh)
    info = policy.ensure_permission_mode(project_root)
    with open(info["path"], encoding="utf-8") as fh:
        assert json.load(fh)["permissions"]["blockReadsOutsideWorkingDirectories"] is False


def test_다른_키는_그대로_둔다(project, project_root):
    os.makedirs(os.path.join(project_root, ".claude"), exist_ok=True)
    with open(policy.claude_settings_path(project_root), "w", encoding="utf-8") as fh:
        json.dump({"env": {"X": "1"}}, fh)
    policy.ensure_permission_mode(project_root)
    with open(policy.claude_settings_path(project_root), encoding="utf-8") as fh:
        data = json.load(fh)
    assert data["env"] == {"X": "1"}
    assert data["permissions"]["defaultMode"] == "default"


# --- 프로젝트 안 비밀 파일 ---------------------------------------------------


def test_프로젝트_안_env_를_찾는다(project, project_root, fake_settings):
    """재귀 읽기(grep -r)는 훅이 못 막는다. 위치 규칙이 1차 방어다."""
    with open(os.path.join(project_root, ".env"), "w", encoding="utf-8") as fh:
        fh.write("KEY=비밀\n")
    item = check(doctor.run(), "비밀 파일 위치")
    assert item["ok"] is False
    assert ".env" in item["detail"]
    assert "~/.config/labremote" in item["hint"]


def test_예시_파일은_괜찮다(project, project_root, fake_settings):
    for rel in (".env.example", ".env.sample"):
        with open(os.path.join(project_root, rel), "w", encoding="utf-8") as fh:
            fh.write("KEY=\n")
    assert doctor.project_secrets(project_root) == []


# --- 정책 판 ---------------------------------------------------------------


def test_판이_낡으면_migrate_를_알려_준다(project, project_root, fake_settings):
    from app import registry

    data = dict(project.data)
    data["version"] = 1
    registry.write_json(project.path, data)

    item = check(doctor.run(), "정책 · hook-sandbox")
    assert item["ok"] is False
    assert "policy migrate hook-sandbox" in item["hint"]


# --- 자가 점검 잔해 ---------------------------------------------------------


def test_스크래치_잔해를_찾는다(project, project_root, fake_settings, monkeypatch, tmp_path):
    from app import registry

    leftover = os.path.join(registry.projects_root(), hooks_check.SCRATCH_PREFIX + "9999")
    os.makedirs(leftover, exist_ok=True)
    item = check(doctor.run(), "자가 점검 잔해")
    assert item["ok"] is False
    assert "9999" in item["detail"]

    assert hooks_check.clean_leftovers() == [leftover]
    assert not os.path.exists(leftover)
    assert check(doctor.run(), "자가 점검 잔해")["ok"] is True


def test_SubagentStop_이_빠지면_알려_준다(project, project_root, fake_settings):
    install.install(mode="enforce")
    data = json.loads(fake_settings.read_text(encoding="utf-8"))
    del data["hooks"]["SubagentStop"]
    fake_settings.write_text(json.dumps(data), encoding="utf-8")

    item = check(doctor.run(), "훅 이벤트")
    assert item["ok"] is False
    assert "SubagentStop" in item["detail"]


# --- 3단계: 샌드박스와 공용 캐시 ------------------------------------------------


def test_샌드박스_점검이_들어_있다(project, project_root):
    report = doctor.run()
    titles = [c["title"] for c in report["checks"]]
    assert "학습 샌드박스" in titles
    assert "공용 캐시" in titles


def test_캐시가_보호_경로와_겹치면_알려_준다(project, project_root, monkeypatch):
    from app import policy_defaults as D

    monkeypatch.setenv("LAB_CACHE_DIR", os.path.join(D.hard_protected_roots()[0], "캐시"))
    found = [c for c in doctor.run()["checks"] if c["title"] == "공용 캐시"]
    assert found and found[0]["ok"] is False
    assert "보호 경로" in found[0]["detail"]


def test_캐시가_프로젝트_안이면_알려_준다(project, project_root, monkeypatch):
    monkeypatch.setenv("LAB_CACHE_DIR", os.path.join(project_root, "캐시"))
    found = [c for c in doctor.run()["checks"] if c["title"] == "공용 캐시"]
    assert found and found[0]["ok"] is False
    assert "프로젝트 안이에요" in found[0]["hint"]


def test_정책을_못_읽어도_뒤_점검이_돈다(project, project_root):
    """판이 낡아 정책을 못 읽어도 샌드박스·캐시 점검은 나와야 한다."""
    from app import registry

    data = dict(project.data)
    data["version"] = 1
    registry.write_json(project.path, data)
    titles = [c["title"] for c in doctor.run()["checks"]]
    assert "학습 샌드박스" in titles and "공용 캐시" in titles
