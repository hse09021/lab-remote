"""정책 파일과 권한 판정 시험.

`test_web_목업과_modes_actions_가_같다` 가 ①단계에서 가장 값이 높은 시험이다.
프런트가 먼저 확정한 권한 모델과 백엔드가 갈라지는 걸 막는다.
"""

import json
import os

import pytest

from app import paths, policy, registry
from app import policy_defaults as D
from tests.conftest import REPO_ROOT

WEB_PERMISSIONS = REPO_ROOT / "web" / "src" / "api" / "mock" / "permissions.json"


@pytest.fixture()
def pol(project_root):
    registry.register(project_root, "hook-sandbox")
    return policy.ensure("hook-sandbox", project_root)


# --- 프런트와의 드리프트 방지 ------------------------------------------------


def test_web_목업과_modes_actions_가_같다():
    web = json.loads(WEB_PERMISSIONS.read_text(encoding="utf-8"))
    assert web["modes"] == D.MODES
    assert web["actions"] == D.ACTIONS
    assert web["labels"] == D.LABELS


def test_web_목업의_경로_상수와_같다():
    web = json.loads(WEB_PERMISSIONS.read_text(encoding="utf-8"))
    template = policy.render_template()
    assert web["configPath"] == template["paths"]["stopLockedFiles"][0]
    assert web["logPath"] == template["logPath"]
    assert web["saved"] is None and template["saved"] is None


def test_커밋된_템플릿이_코드와_일치한다():
    """`policy_defaults` 가 단일 출처. 어긋나면 템플릿을 다시 만들어야 한다."""
    with open(policy.template_path(), encoding="utf-8") as fh:
        on_disk = json.load(fh)
    assert on_disk == policy.render_template()


# --- resolve ---------------------------------------------------------------

EXPECTED = {
    #          manual    error    full
    "code": ("ask", "allow", "allow"),
    "hparam": ("ask", "ask", "allow"),
    "pkg": ("ask", "ask", "ask"),
    "del": ("ask", "ask", "ask"),
    "newexp": ("ask", "ask", "allow"),
    "net": ("ask", "ask", "ask"),
    "outside": ("block", "block", "block"),
    "stop": ("block", "block", "block"),
    "prev": ("block", "block", "block"),
}


def test_모든_모드_모든_행동의_기본_판정(pol):
    assert set(EXPECTED) == set(D.ACTION_KEYS)
    for key, expected in EXPECTED.items():
        for mode, want in zip(D.MODE_IDS, expected):
            pol.set_saved(mode)
            assert pol.resolve(key) == want, (key, mode)


def test_saved_가_없으면_기본_프리셋(pol):
    assert pol.saved is None
    assert pol.effective_mode() == D.DEFAULT_MODE == "manual"
    assert pol.resolve("code") == "ask"


def test_saved_가_있으면_그걸_쓴다(pol):
    pol.set_saved("full")
    policy.save(pol)
    again = policy.load("hook-sandbox")
    assert again.effective_mode() == "full"
    assert again.resolve("code") == "allow"


def test_override_가_기본값을_덮는다(pol):
    pol.set_saved("manual", {"pkg": "allow"})
    assert pol.resolve("pkg") == "allow"
    assert pol.resolve("del") == "ask"  # 다른 행동은 그대로


def test_잠긴_항목은_override_로_뚫리지_않는다(pol):
    for key in D.LOCKED_KEYS:
        with pytest.raises(policy.PolicyError):
            pol.set_saved("full", {key: "allow"})
        assert pol.resolve(key) == "block"


def test_정책_파일을_직접_고쳐도_잠금은_유지된다(pol):
    """정책 파일이 손상·조작됐을 때도 잠긴 항목이 열리지 않아야 한다."""
    pol.data["saved"] = {"mode": "full", "overrides": {"outside": "allow"}}
    policy.save(pol)
    again = policy.load("hook-sandbox")
    assert again.resolve("outside") == "block"


def test_모르는_행동_유형은_예외(pol):
    with pytest.raises(policy.PolicyError):
        pol.resolve("없는행동")


def test_행동_이름은_한국어(pol):
    assert pol.action_name("pkg") == "패키지 설치"
    assert pol.action_name("outside") == "프로젝트 폴더 밖 쓰기·삭제"


# --- fail-closed -----------------------------------------------------------


def test_정책_파일이_없으면_예외():
    with pytest.raises(policy.PolicyError) as err:
        policy.load("hook-sandbox")
    assert "정책 파일이 없어요" in str(err.value)


def test_깨진_JSON_은_예외(pol):
    with open(pol.path, "w", encoding="utf-8") as fh:
        fh.write("{ 이건 JSON 이 아니에요")
    with pytest.raises(policy.PolicyError):
        policy.load("hook-sandbox")


def test_판이_다르면_예외(pol):
    pol.data["version"] = D.POLICY_VERSION + 1
    policy.save(pol)
    with pytest.raises(policy.PolicyError) as err:
        policy.load("hook-sandbox")
    assert "판이 맞지 않아요" in str(err.value)


def test_행동_유형이_빠지면_예외(pol):
    pol.data["actions"] = [a for a in pol.data["actions"] if a["key"] != "pkg"]
    policy.save(pol)
    with pytest.raises(policy.PolicyError):
        policy.load("hook-sandbox")


def test_잠금이_풀려_있으면_예외(pol):
    for action in pol.data["actions"]:
        if action["key"] == "outside":
            action["locked"] = False
    policy.save(pol)
    with pytest.raises(policy.PolicyError) as err:
        policy.load("hook-sandbox")
    assert "잠긴 항목이 풀려 있어요" in str(err.value)


def test_프리셋_값이_이상하면_예외(pol):
    pol.data["saved"] = {"mode": "아무거나", "overrides": {}}
    policy.save(pol)
    with pytest.raises(policy.PolicyError):
        policy.load("hook-sandbox")


def test_사유_문구는_해요체(pol):
    with pytest.raises(policy.PolicyError) as err:
        policy.load("other-project")
    assert "어요" in str(err.value)


def test_이름이_규칙에_안_맞아도_PolicyError(pol):
    """훅은 한 종류의 예외만 잡고 deny 로 끝낼 수 있어야 한다."""
    with pytest.raises(policy.PolicyError):
        policy.load("../../etc/passwd")


# --- 위치 -----------------------------------------------------------------


def test_정책_파일은_프로젝트_밖에_있다(pol, project_root):
    """그래서 AI 가 고치려 들면 잠긴 항목 ①(폴더 밖)에 자동으로 걸린다."""
    assert paths.rel_or_none(project_root, paths.real(pol.path)) is None


def test_ensure_는_두_번_불러도_덮어쓰지_않는다(project_root):
    first = policy.ensure("hook-sandbox", project_root)
    first.set_saved("full", {"pkg": "allow"})
    policy.save(first)
    second = policy.ensure("hook-sandbox", project_root)
    assert second.effective_mode() == "full"
    assert second.overrides() == {"pkg": "allow"}


def test_ensure_가_프로젝트_이름과_루트를_채운다(project_root):
    pol = policy.ensure("hook-sandbox", project_root)
    assert pol.data["project"] == {"name": "hook-sandbox", "root": project_root}
    assert pol.root == project_root


def test_ensure_가_기본_템플릿을_씨뿌린다(project_root):
    seeded = registry.data_dir() + "/policy.default.json"
    policy.ensure("hook-sandbox", project_root)
    with open(seeded, encoding="utf-8") as fh:
        assert json.load(fh) == policy.render_template()


# --- 판 올림 (1 -> 2) --------------------------------------------------------
# 판 2 에서 보호 목록·비밀 파일·산출물 보존이 생기고 headless 기본값이
# deny-with-reason 으로 바뀌었다. 옛 파일은 fail-closed 로 거절된다.


def old_policy(project, version=1):
    """판 1 짜리 정책 파일을 만든다 (프리셋·예외는 사람이 고른 값)."""
    from app import registry

    data = dict(project.data)
    data["version"] = version
    data["saved"] = {"mode": "error", "overrides": {"pkg": "allow"}}
    data["headless"] = {"onAsk": "ask", "notifyDiscord": True}
    registry.write_json(project.path, data)
    return data


def test_낡은_판은_거절된다(project):
    old_policy(project)
    with pytest.raises(policy.PolicyError) as exc:
        policy.load("hook-sandbox")
    assert "판이 맞지 않아요" in str(exc.value)


def test_migrate_가_프리셋과_예외를_보존한다(project, project_root):
    old_policy(project)
    info = policy.migrate("hook-sandbox")
    assert info["from"] == 1 and info["to"] == D.POLICY_VERSION
    pol = policy.load("hook-sandbox")
    assert pol.effective_mode() == "error"
    assert pol.overrides() == {"pkg": "allow"}


def test_migrate_가_코드_기본값을_가져온다(project, project_root):
    old_policy(project)
    policy.migrate("hook-sandbox")
    pol = policy.load("hook-sandbox")
    assert pol.headless["onAsk"] == "deny-with-reason"
    assert pol.paths["outputDirs"]
    assert pol.paths["secretFilesExtra"] == []


def test_migrate_가_권한_기본_모드를_넣는다(project, project_root):
    old_policy(project)
    info = policy.migrate("hook-sandbox")
    assert info["settings"]["changed"] is True
    with open(policy.claude_settings_path(project_root), encoding="utf-8") as fh:
        assert json.load(fh)["permissions"]["defaultMode"] == "default"


def test_migrate_가_승인_로그_헤더를_올린다(project, project_root):
    from app import approval_log

    path = approval_log.log_path(project_root)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8", newline="") as fh:
        fh.write("time,action,request,result,resultPending,handledBy\n")
        fh.write("2026-11-04T00:00:00+09:00,패키지 설치,pip install x,차단,false,Hooks · 잠금\n")

    old_policy(project)
    info = policy.migrate("hook-sandbox")
    assert info["log"]["changed"] is True
    assert os.path.exists(info["log"]["backup"])
    with open(path, encoding="utf-8") as fh:
        assert fh.readline().strip() == ",".join(approval_log.COLUMNS)


def test_migrate_는_루트를_모르면_거절한다():
    """등록도 안 됐고 정책 파일도 없으면 어디를 고칠지 알 수 없다."""
    with pytest.raises(policy.PolicyError) as exc:
        policy.migrate("ghost-project")
    assert "프로젝트 루트를 알 수 없어요" in str(exc.value)


def test_migrate_는_이상한_이름을_거절한다():
    with pytest.raises(policy.PolicyError) as exc:
        policy.migrate("../탈출")
    assert "이름이 규칙에 안 맞아요" in str(exc.value)


def test_migrate_뒤에도_잠금은_잠겨_있다(project):
    old_policy(project)
    policy.migrate("hook-sandbox")
    pol = policy.load("hook-sandbox")
    for key in D.LOCKED_KEYS:
        assert pol.resolve(key) == "block"


def test_migrate_기록이_JSONL_에_남는다(project, project_root):
    from app import approval_log

    old_policy(project)
    policy.migrate("hook-sandbox")
    path = approval_log.event_path(project_root)
    lines = [json.loads(line) for line in open(path, encoding="utf-8") if line.strip()]
    assert any(item["event"] == "policy-migrate" for item in lines)


# --- 판 3: ②가 들어오면서 늘어난 것 -------------------------------------------


def test_판_3_이다():
    assert D.POLICY_VERSION == 3


def test_Current_yaml_이_selfProtect_에_있다(project):
    """AI 가 고칠 수 있으면 "현재 실험" 의 근거가 되지 못한다."""
    from app import loop_layout as L

    protected = project.paths["selfProtectedFiles"]
    assert L.LOOP_LAYOUT["current"] in protected
    assert L.LOOP_LAYOUT["state"] not in protected  # State.yaml 은 AI 소유


@pytest.mark.parametrize(
    "command",
    [
        # 자기 승인·자기 조작
        "labremote",
        "sqlite3",
        "systemctl",
        "systemd-run",
        "loginctl",
        "kill",
        "pkill",
        "killall",
        # 격리를 깨는 것
        "bwrap",
        "unshare",
        "nsenter",
        "chroot",
        "setarch",
        # 프로세스에 붙는 것
        "strace",
        "ltrace",
        "gdb",
        # 컨테이너
        "docker",
        "podman",
        # 훅 밖에서 나중에 실행되는 것
        "at",
        "batch",
        "crontab",
        # ① 에서부터 막던 것
        "claude",
        "shred",
        "mkfs",
    ],
)
def test_금지_명령_목록(project, command):
    assert command in project.bash["denyCommands"], command


def test_허용_목록은_추가만_하는_칸이_있다(project):
    """기본 목록은 코드에 둔다 — AI 가 정책으로 목록을 넓히지 못하게."""
    assert project.bash["allowExtra"] == []


def test_migrate_가_판_3_으로_올린다(project, project_root):
    from app import policy, registry

    data = dict(project.data)
    data["version"] = 2
    registry.write_json(project.path, data)
    info = policy.migrate("hook-sandbox")
    assert info["from"] == 2 and info["to"] == 3
    after = policy.load("hook-sandbox")
    assert "labremote" in after.bash["denyCommands"]
    from app import loop_layout as L

    assert L.LOOP_LAYOUT["current"] in after.paths["selfProtectedFiles"]
