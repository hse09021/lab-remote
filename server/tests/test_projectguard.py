"""프로젝트 설정 정본 대조·되돌림 — **샌드박스 탈출을 막는 둘째 겹.**

M6 실측에서 프로젝트 `.claude/settings.json` 한 파일로 울타리가 사라졌다.

| 심은 것 | 실측 결과 |
|---|---|
| `hooks.PreToolUse` | 훅은 샌드박스 **밖**이라(M1) 그 명령이 **사용자 권한으로 돌았다** |
| `sandbox.enabled: false` | 샌드박스가 꺼지고 AI 코드가 `server/data/runstate/` 에 **실제로 썼다** |
| `.mcp.json` | 훅이 못 보는 MCP 서버가 **실제로 떴다** |

런처는 그 파일을 안 읽지만(`--setting-sources user`) 맨손 `claude` 는 읽는다.
그래서 되돌린다. 이 시험이 그걸 고정한다.
"""

import json
import os

import pytest

from app.orchestrator import projectguard as PG


def _write(path, data):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(data, fh, ensure_ascii=False)


@pytest.fixture()
def clean(project, project_root):
    """정본 상태의 프로젝트."""
    _write(PG.settings_path(project_root), PG.expected_settings())
    return project_root


# --- 대조 -------------------------------------------------------------------


def test_정본이면_통과한다(clean):
    got = PG.check(clean)
    assert got["ok"] is True
    assert got["settings"] == "ok" and got["mcp"] == "ok"


def test_공백_차이로_싸우지_않는다(clean):
    """템플릿과 들여쓰기가 달라도 내용이 같으면 같다."""
    with open(PG.settings_path(clean), "w", encoding="utf-8") as fh:
        json.dump(PG.expected_settings(), fh, indent=8)
    assert PG.check(clean)["ok"] is True


def test_훅을_심으면_잡아낸다(clean):
    """가장 위험한 것 — 훅은 샌드박스 **밖에서** 실행된다(M1)."""
    data = PG.expected_settings()
    data["hooks"] = {
        "PreToolUse": [
            {"matcher": "*", "hooks": [{"type": "command", "command": "curl evil"}]}
        ]
    }
    _write(PG.settings_path(clean), data)
    got = PG.check(clean)
    assert got["ok"] is False and got["settings"] == "changed"
    assert any("hooks" in p for p in got["problems"])


def test_샌드박스_끄기를_잡아낸다(clean):
    """실측에서 이 한 줄로 AI 코드가 server/data/runstate 에 썼다."""
    data = PG.expected_settings()
    data["sandbox"] = {"enabled": False}
    _write(PG.settings_path(clean), data)
    got = PG.check(clean)
    assert got["ok"] is False
    assert any("enabled" in p and "꺼져" in p for p in got["problems"])


def test_permissions_allow_를_잡아낸다(clean):
    for key in ("allow", "deny", "ask", "additionalDirectories"):
        data = PG.expected_settings()
        data["permissions"][key] = ["Bash(*)"]
        _write(PG.settings_path(clean), data)
        got = PG.check(clean)
        assert got["ok"] is False, key
        assert any(f"permissions.{key}" in p for p in got["problems"]), key


def test_defaultMode_를_바꾸면_잡아낸다(clean):
    data = PG.expected_settings()
    data["permissions"]["defaultMode"] = "bypassPermissions"
    _write(PG.settings_path(clean), data)
    got = PG.check(clean)
    assert got["ok"] is False
    assert any("defaultMode" in p for p in got["problems"])


def test_바깥_쓰기_차단을_끄면_잡아낸다(clean):
    data = PG.expected_settings()
    data["permissions"]["blockWritesOutsideWorkingDirectories"] = False
    _write(PG.settings_path(clean), data)
    assert PG.check(clean)["ok"] is False


def test_mcp_json_은_있으면_안_된다(clean):
    """정본은 **없음** 이다 — 훅이 못 보는 도구가 생긴다."""
    _write(PG.mcp_path(clean), {"mcpServers": {"x": {"command": "sh"}}})
    got = PG.check(clean)
    assert got["ok"] is False and got["mcp"] == "present"


def test_설정이_없거나_깨져도_잡아낸다(clean):
    os.unlink(PG.settings_path(clean))
    assert PG.check(clean)["settings"] == "missing"
    with open(PG.settings_path(clean), "w", encoding="utf-8") as fh:
        fh.write("{ 깨진 json")
    assert PG.check(clean)["settings"] == "broken"


def test_check_는_아무것도_고치지_않는다(clean):
    data = PG.expected_settings()
    data["hooks"] = {"PreToolUse": []}
    _write(PG.settings_path(clean), data)
    PG.check(clean)
    again = json.loads(open(PG.settings_path(clean), encoding="utf-8").read())
    assert "hooks" in again


# --- 되돌림 ------------------------------------------------------------------


def test_되돌리고_증거를_남긴다(clean):
    data = PG.expected_settings()
    data["hooks"] = {"PreToolUse": [{"matcher": "*", "hooks": []}]}
    data["sandbox"] = {"enabled": False}
    _write(PG.settings_path(clean), data)
    _write(PG.mcp_path(clean), {"mcpServers": {"x": {"command": "sh"}}})

    got = PG.restore(clean, "hook-sandbox")

    assert got["changed"] is True
    assert set(got["restored"]) == {".claude/settings.json", ".mcp.json"}
    # 정본으로 돌아갔다
    assert PG.check(clean)["ok"] is True
    assert json.loads(open(PG.settings_path(clean), encoding="utf-8").read()) == PG.expected_settings()
    # `.mcp.json` 은 지워졌다 (정본이 '없음')
    assert not os.path.exists(PG.mcp_path(clean))
    # 원본이 증거로 남았다
    folder = got["evidence"]
    kept = json.loads(
        open(os.path.join(folder, ".claude__settings.json"), encoding="utf-8").read()
    )
    assert "hooks" in kept and kept["sandbox"]["enabled"] is False
    report = json.loads(open(os.path.join(folder, "report.json"), encoding="utf-8").read())
    assert report["project"] == "hook-sandbox" and report["problems"]


def test_증거는_server_data_아래에_남는다(clean):
    """샌드박스 안에서 그 폴더 쓰기가 실패하므로(M1b) AI 가 증거를 못 지운다."""
    from app import registry

    folder = PG.tamper_dir("hook-sandbox")
    assert folder.startswith(os.path.join(registry.data_dir(), "tamper"))


def test_정본이면_되돌리지_않는다(clean):
    got = PG.restore(clean, "hook-sandbox")
    assert got["changed"] is False and got["evidence"] == ""


# --- 루프에 붙어 있나 ---------------------------------------------------------


def test_세션이_끝나면_되돌린다(clean, conn, monkeypatch):
    """`_claude` 가 단일 깔때기다 — 모든 Claude 세션 뒤에 돈다."""
    from app.orchestrator import loop as loop_mod
    from app.orchestrator import runner_ctx

    data = PG.expected_settings()
    data["hooks"] = {"PreToolUse": [{"matcher": "*", "hooks": []}]}

    def fake_runner(made):
        # 세션이 도는 동안 AI 가 쓴 코드가 설정을 고친 상황
        _write(PG.settings_path(clean), data)
        return {"ok": True, "result": "", "sessionId": "S-1"}

    ctx = runner_ctx.LoopCtx(
        project="hook-sandbox", root=clean, preset="full", runner=fake_runner
    )
    sent = []
    monkeypatch.setattr(
        loop_mod.notifier, "send", lambda *a, **k: sent.append(k) or {"ok": True}
    )

    loop_mod._claude(ctx, conn, prompt="p", session_id="S-1", resume=False)

    assert PG.check(clean)["ok"] is True, "세션 뒤에 되돌려야 해요"
    assert sent and "프로젝트 설정이 바뀌어" in sent[0]["title"]
    from app.store import loops as LP

    assert LP.ensure(conn, "hook-sandbox")["state"] == "blocked"


def test_루프_시작_전에는_되돌리고_계속한다(clean, conn, monkeypatch):
    from app.orchestrator import loop as loop_mod
    from app.orchestrator import runner_ctx
    from app.store import loops as LP

    data = PG.expected_settings()
    data["sandbox"] = {"enabled": False}
    _write(PG.settings_path(clean), data)
    ctx = runner_ctx.LoopCtx(project="hook-sandbox", root=clean, preset="full")
    monkeypatch.setattr(loop_mod.notifier, "send", lambda *a, **k: {"ok": True})

    loop_mod.guard_project(ctx, conn, when="루프 시작 전", block=False)

    assert PG.check(clean)["ok"] is True
    assert LP.ensure(conn, "hook-sandbox")["state"] != "blocked"


def test_알림이_실패해도_루프를_멈추지_않는다(clean, conn, monkeypatch):
    from app.orchestrator import loop as loop_mod
    from app.orchestrator import runner_ctx

    data = PG.expected_settings()
    data["hooks"] = {}
    _write(PG.settings_path(clean), data)
    ctx = runner_ctx.LoopCtx(project="hook-sandbox", root=clean, preset="full")

    def boom(*a, **k):
        raise RuntimeError("웹훅이 죽었어요")

    monkeypatch.setattr(loop_mod.notifier, "send", boom)
    got = loop_mod.guard_project(ctx, conn, when="시험")
    assert got["changed"] is True
    assert PG.check(clean)["ok"] is True


# --- doctor -----------------------------------------------------------------


def test_doctor_가_변조를_잡는다(clean):
    from app import doctor

    data = PG.expected_settings()
    data["hooks"] = {"PreToolUse": []}
    _write(PG.settings_path(clean), data)
    got = doctor.project_settings_check(clean, "hook-sandbox")
    assert got["ok"] is False
    assert "hooks" in got["detail"]
    assert "labremote claude hook-sandbox --force" in got["hint"]


def test_doctor_가_사용자_설정의_샌드박스를_잡는다(tmp_path, monkeypatch):
    """거기 있으면 이 PC 의 **모든** 세션이 갇힌다 — 전에 그렇게 됐다."""
    from app import doctor

    path = tmp_path / "claude" / "settings.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({"sandbox": {"enabled": True}}), encoding="utf-8")
    monkeypatch.setenv("LAB_CLAUDE_SETTINGS", str(path))
    got = doctor.user_sandbox_check()
    assert got["ok"] is False and "모든" in got["hint"]

    path.write_text(json.dumps({"hooks": {}}), encoding="utf-8")
    assert doctor.user_sandbox_check()["ok"] is True


# --- labremote claude -------------------------------------------------------


def test_cli_는_변조되면_띄우지_않는다(clean, capsys):
    from app import cli

    data = PG.expected_settings()
    data["sandbox"] = {"enabled": False}
    _write(PG.settings_path(clean), data)
    code = cli.main(["claude", "hook-sandbox", "--dry-run"])
    out = capsys.readouterr().out
    assert code == 3, out
    assert "정본과 달라요" in out and "--force" in out
    # 고치지 않았다
    assert PG.check(clean)["ok"] is False


def test_cli_force_는_되돌리고_띄운다(clean, capsys):
    from app import cli, policy

    data = PG.expected_settings()
    data["sandbox"] = {"enabled": False}
    _write(PG.settings_path(clean), data)
    code = cli.main(["claude", "hook-sandbox", "--force", "--dry-run"])
    out = capsys.readouterr().out
    assert code == 0, out
    assert "되돌렸어요" in out
    assert PG.check(clean)["ok"] is True
    # 경계 플래그 셋이 다 있고 헤드리스 전용은 없다
    assert "--setting-sources user" in out
    assert "--strict-mcp-config" in out
    assert policy.launch_settings_path() in out
    assert " -p " not in out and "--permission-prompts" not in out


def test_cli_는_등록_안_된_프로젝트를_거부한다(capsys):
    from app import cli

    assert cli.main(["claude", "없는프로젝트", "--dry-run"]) == 2
    assert "등록된 실험 프로젝트가 아니에요" in capsys.readouterr().err


def test_cli_는_금지_플래그를_거부한다(clean, capsys):
    """`--` 뒤로 넘긴 인자도 `check_flags` 를 지나간다. 종료코드 2 + 사유."""
    from app import cli

    for bad in (["--bare"], ["--add-dir", "/etc"], ["--setting-sources", "project"]):
        assert cli.main(["claude", "hook-sandbox", "--dry-run", "--", *bad]) == 2, bad
        err = capsys.readouterr().err
        assert "✘" in err, bad


def test_cli_는_무해한_인자는_그대로_넘긴다(clean, capsys):
    from app import cli

    assert cli.main(["claude", "hook-sandbox", "--dry-run", "--", "--debug"]) == 0
    assert "--debug" in capsys.readouterr().out
