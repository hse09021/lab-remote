"""프로젝트 생성기 시험."""

import json
import os
import subprocess

import pytest

from app import loop_layout as L
from app import policy, registry, runstate
from app.generator import plan as plan_mod
from app.generator import scaffold, tree
from app.generator.spec import ProjectSpec


@pytest.fixture()
def spec():
    return ProjectSpec("hook-sandbox", goal="훅·생성기 검증용")


@pytest.fixture()
def made(spec):
    return scaffold.create_project(spec)


# --- 계획과 실제가 같은가 ----------------------------------------------------


def test_만든_파일이_계획과_같다(spec, made):
    planned = sorted(item.path for item in plan_mod.build_plan(spec))
    on_disk = []
    for base, dirs, files in os.walk(made["target"]):
        dirs[:] = [d for d in dirs if d != ".git"]
        for name in files:
            on_disk.append(os.path.relpath(os.path.join(base, name), made["target"]))
    assert sorted(on_disk) == planned


def test_dry_run_이_같은_목록을_내놓는다(spec):
    report = scaffold.dry_run(spec)
    assert report["count"] == len(plan_mod.build_plan(spec))
    assert [f["path"] for f in report["files"]] == [i.path for i in plan_mod.build_plan(spec)]


def test_PDF_7쪽_구조대로_만든다(made):
    for rel in (
        L.LOOP_LAYOUT["state"],
        L.LOOP_LAYOUT["experiment_log"],
        L.LOOP_LAYOUT["decision_log"],
        L.LOOP_LAYOUT["failures"],
        L.LOOP_LAYOUT["experiment_spec"],
        L.LOOP_LAYOUT["background"],
        L.LOOP_LAYOUT["process"],
        L.LOOP_LAYOUT["results_example"],
    ):
        assert os.path.exists(os.path.join(made["target"], rel)), rel


def test_File_directory_의_트리가_실제와_같다(spec, made):
    body = open(os.path.join(made["target"], L.LOOP_LAYOUT["file_directory"]), encoding="utf-8").read()
    assert tree.render_tree(spec.name, plan_mod.build_plan(spec)) in body


def test_첫_실험_폴더는_옵션(spec):
    assert not any("EXP-001" in i.path for i in plan_mod.build_plan(spec))
    spec.first_exp = "EXP-001"
    assert any(i.path == "experiments/EXP-001/config.yaml" for i in plan_mod.build_plan(spec))


# --- 템플릿 내용 ------------------------------------------------------------


def test_자리표시가_그대로_새지_않는다(made):
    """string.Template.substitute 라 빠진 키는 예외가 난다."""
    for base, dirs, files in os.walk(made["target"]):
        dirs[:] = [d for d in dirs if d != ".git"]
        for name in files:
            body = open(os.path.join(base, name), encoding="utf-8").read()
            assert "$project_name" not in body
            assert "$goal" not in body


def test_CLAUDE_md_에_필요한_규칙이_다_있다(made):
    body = open(os.path.join(made["target"], "CLAUDE.md"), encoding="utf-8").read()
    from app.hooks.install import SHELL_LIMITATION_NOTE

    assert "항상 이 폴더 안에서 켜" in body  # 래퍼의 한계
    assert "프로젝트 폴더 밖 쓰기·삭제" in body
    assert "이전 실험 폴더" in body
    assert "실패한 실험도 폴더를 남기고" in body
    assert "[대괄호 자리표시]" in body
    assert "다른 도구나 명령으로 돌아가지 말고" in body
    assert SHELL_LIMITATION_NOTE.split(".")[0][:12] in body or "항상 이 폴더 안에서" in body


def test_Config_와_Evaluation_의_값은_자리표시(made):
    config = open(os.path.join(made["target"], L.LOOP_LAYOUT["config"]), encoding="utf-8").read()
    for key in ("[주 지표]", "[임계값]", "[최대 실행 횟수]", "[GPU 시간]", "[마감]"):
        assert key in config, key
    assert "usage_limit: wait" in config  # 자동으로 더 사지 않는다


def test_environment_yml(made, spec):
    body = open(os.path.join(made["target"], L.LOOP_LAYOUT["environment"]), encoding="utf-8").read()
    assert f"name: {spec.env_name}" in body
    assert "python=3.11" in body


def test_승인_로그에_헤더가_들어_있다(made):
    from app import approval_log

    path = os.path.join(made["target"], L.LOOP_LAYOUT["approval_log"])
    assert open(path, encoding="utf-8").read().strip() == ",".join(approval_log.COLUMNS)


# --- git -------------------------------------------------------------------


def test_첫_커밋_하나(made):
    out = subprocess.run(["git", "log", "--oneline"], cwd=made["target"], capture_output=True, text=True)
    assert len(out.stdout.strip().splitlines()) == 1


def test_커밋_뒤_작업_트리가_깨끗하다(made):
    out = subprocess.run(["git", "status", "--porcelain"], cwd=made["target"], capture_output=True, text=True)
    assert out.stdout.strip() == ""


def test_비밀_값과_데이터는_추적하지_않는다(made):
    from app.generator import gitops

    tracked = gitops.tracked_files(made["target"])
    assert ".env" not in tracked
    assert not any(t.startswith("data/") for t in tracked)
    assert ".env.example" in tracked


def test_승인_로그는_반드시_추적한다(made):
    """logs/ 를 통째로 무시하면 여기서 걸린다."""
    from app.generator import gitops

    assert L.LOOP_LAYOUT["approval_log"] in gitops.tracked_files(made["target"])


# --- 등록 ------------------------------------------------------------------


def test_레지스트리와_정책과_실행_상태가_준비된다(made, spec):
    assert registry.root_of(spec.name) == made["target"]
    pol = policy.load(spec.name)
    assert pol.root == made["target"]
    assert runstate.load(spec.name).running is False


def test_프리셋을_고를_수_있다():
    spec = ProjectSpec("hook-sandbox", mode="full")
    scaffold.create_project(spec)
    assert policy.load("hook-sandbox").effective_mode() == "full"


def test_정책은_프로젝트_밖에_있다(made, spec):
    from app import paths

    assert paths.rel_or_none(made["target"], paths.real(policy.load(spec.name).path)) is None


# --- 막는 것 ---------------------------------------------------------------


def test_두_번째는_거절(spec, made):
    with pytest.raises(scaffold.ScaffoldError) as err:
        scaffold.create_project(spec)
    assert "이미" in str(err.value)


def test_저장소_안에는_못_만든다(monkeypatch, spec):
    monkeypatch.setenv("LAB_PROJECTS_DIR", os.path.join(scaffold.repo_root(), "lab-remote"))
    with pytest.raises(scaffold.ScaffoldError) as err:
        scaffold.preflight(spec)
    assert "저장소 밖" in str(err.value)


def test_이미_git_저장소_안이면_거절(monkeypatch, tmp_path, spec):
    parent = tmp_path / "어떤저장소"
    parent.mkdir()
    subprocess.run(["git", "init", "-q"], cwd=parent, check=True)
    monkeypatch.setenv("LAB_PROJECTS_DIR", str(parent))
    with pytest.raises(scaffold.ScaffoldError) as err:
        scaffold.preflight(spec)
    assert "git 저장소" in str(err.value)


def test_부모_폴더가_없으면_거절(monkeypatch, tmp_path, spec):
    monkeypatch.setenv("LAB_PROJECTS_DIR", str(tmp_path / "없는폴더"))
    with pytest.raises(scaffold.ScaffoldError):
        scaffold.preflight(spec)


def test_나쁜_이름은_거절():
    with pytest.raises(registry.InvalidName):
        scaffold.preflight(ProjectSpec("../../etc"))


def test_실패하면_흔적이_안_남는다(monkeypatch, spec):
    from app.generator import gitops

    monkeypatch.setattr(gitops, "init_and_commit", lambda root: (_ for _ in ()).throw(gitops.GitError("일부러")))
    with pytest.raises(gitops.GitError):
        scaffold.create_project(spec)
    target = scaffold.target_path(spec.name)
    assert not os.path.exists(target)
    assert os.listdir(os.path.dirname(target)) == []  # 임시 폴더도 없다


# --- update ----------------------------------------------------------------


def test_update_는_사용자_파일을_안_건드린다(spec, made):
    claude_md = os.path.join(made["target"], "CLAUDE.md")
    with open(claude_md, "a", encoding="utf-8") as fh:
        fh.write("\n내가 고친 줄\n")
    before = open(claude_md, encoding="utf-8").read()

    result = scaffold.create_project(spec, if_exists="update")
    assert open(claude_md, encoding="utf-8").read() == before
    assert L.LOOP_LAYOUT["file_directory"] in result["refreshed"]
    assert result["backup"]


def test_update_는_없는_파일만_채운다(spec, made):
    missing = os.path.join(made["target"], L.LOOP_LAYOUT["failures"])
    os.remove(missing)
    result = scaffold.create_project(spec, if_exists="update")
    assert L.LOOP_LAYOUT["failures"] in result["added"]
    assert os.path.exists(missing)


def test_없는_프로젝트는_update_못_한다(spec):
    with pytest.raises(scaffold.ScaffoldError):
        scaffold.create_project(spec, if_exists="update")


# --- conda -----------------------------------------------------------------


def test_기본은_환경을_만들지_않는다(made):
    assert made["env"]["skipped"] is True


# --- 비밀 값은 프로젝트 밖 (판 2) --------------------------------------------


def test_env_는_만들지_않는다(made):
    """훅은 `cat .env` 는 막지만 `grep -r` 은 못 막는다. 위치가 1차 방어다."""
    assert not os.path.exists(os.path.join(made["target"], ".env"))
    assert ".env" not in made["files"]


def test_env_example_은_남아_있고_밖을_가리킨다(made):
    path = os.path.join(made["target"], ".env.example")
    body = open(path, encoding="utf-8").read()
    assert "~/.config/labremote/hook-sandbox.env" in body
    assert "WANDB_API_KEY=" in body


def test_doctor_가_이_프로젝트에서_비밀_파일을_못_찾는다(made):
    from app import doctor

    assert doctor.project_secrets(made["target"]) == []


# --- 권한 기본 모드 고정 (판 2) ----------------------------------------------


def test_claude_설정에_기본_모드가_박혀_있다(made):
    """2.1.317 은 사용자 설정에 defaultMode 가 없으면 auto 로 뜬다."""
    path = os.path.join(made["target"], ".claude", "settings.json")
    with open(path, encoding="utf-8") as fh:
        data = json.load(fh)
    assert data["permissions"]["defaultMode"] == "default"


def test_claude_설정도_추적한다(made):
    from app.generator import gitops

    assert ".claude/settings.json" in gitops.tracked_files(made["target"])


def test_update_가_기본_모드를_채운다(made):
    """이미 만든 프로젝트에도 소급 적용된다."""
    spec = ProjectSpec(name="hook-sandbox", goal="시험")
    target = made["target"]
    os.remove(os.path.join(target, ".claude", "settings.json"))

    result = scaffold.create_project(spec, if_exists="update")
    assert result["settings"]["mode"] == "default"
    assert os.path.exists(os.path.join(target, ".claude", "settings.json"))


def test_gitignore_가_판_올림_백업을_무시한다(made):
    """`policy migrate` 가 logs/Approval_log.csv.v1.bak 을 남겨요."""
    from app.generator import gitops

    body = open(os.path.join(made["target"], ".gitignore"), encoding="utf-8").read()
    assert "logs/*.bak" in body

    with open(os.path.join(made["target"], "logs", "Approval_log.csv.v1.bak"), "w") as fh:
        fh.write("백업\n")
    tracked = gitops.tracked_files(made["target"])
    assert not any(t.endswith(".bak") for t in tracked)


def test_gitignore_가_Current_yaml_을_무시한다(made):
    """오케스트레이터가 실험 중에 계속 쓰는 파일이다. 추적하면 루프 앞뒤의
    `git switch` 가 막힌다. `State.yaml` 은 기록 의무라 추적한다."""
    from app import loop_layout as L
    from app.generator import gitops

    body = open(os.path.join(made["target"], ".gitignore"), encoding="utf-8").read()
    assert L.LOOP_LAYOUT["current"] in body

    os.makedirs(os.path.join(made["target"], "state"), exist_ok=True)
    for key in ("current", "state"):
        with open(os.path.join(made["target"], L.LOOP_LAYOUT[key]), "w", encoding="utf-8") as fh:
            fh.write("loop_no: 0\n")
    tracked = gitops.tracked_files(made["target"])
    assert L.LOOP_LAYOUT["current"] not in tracked
    assert L.LOOP_LAYOUT["state"] in tracked


def test_CLAUDE_md_가_루프_규약을_적는다(made):
    """프롬프트만으로는 부족하다 — 고정 지침에도 있어야 매 세션에서 읽힌다."""
    from app import loop_layout as L

    body = open(os.path.join(made["target"], "CLAUDE.md"), encoding="utf-8").read()
    # "현재 실험" 의 근거를 맨 앞에서 읽게 한다
    assert L.LOOP_LAYOUT["current"] in body
    # 4번(실험 실행)은 AI 가 하지 않는다
    assert "4번(실험 실행)은 당신이 하지 않아요" in body
    assert "run.json" in body and "문자열 배열" in body
    assert "$" not in body  # 자리표시가 새어 나가지 않았다
