"""설치 승인 → 재개 — **연결**을 고정한다.

실측 2026-11-05: `installs.pending()` 은 있었지만 `once()` 가 **한 번도 안
봤고**, 설치 결과를 프롬프트에 싣는 자리도 없었다. 그래서

* 승인을 안 한 동안에도 설계 세션을 띄웠다 — Claude 는 같은 요청을 또 쓸
  뿐이고 사용량만 쓴다.
* 사람이 승인해서 설치가 끝나도 막혔던 세션을 안 이어 가고 **다음 바퀴가
  설계부터 다시** 했다. 세션 하나와 그때까지 읽은 맥락이 통째로 버려진다.
  Claude 는 `Install_result.json` 이 있는 줄도 모른다.

`resume_after_approval` 프롬프트는 이미 그 파일을 읽으라고 적어 뒀다.
부르는 쪽만 없었다.
"""

import json
import os
import subprocess
import sys

import pytest

sys.path.insert(0, os.path.dirname(__file__))

from test_orchestrator_loop import (  # noqa: E402
    FakeClaude,
    ctx_for,
    plan_writes_run_json,
    ready,  # noqa: F401
    review_writes_journal,
)

from app.orchestrator import installs as installs_mod  # noqa: E402
from app.orchestrator.__main__ import once, stop_reason  # noqa: E402
from app.store import approvals as AP  # noqa: E402


@pytest.fixture(autouse=True)
def env_made(monkeypatch, project_root):
    """conda 환경 존재·이름 검사는 이 시험의 대상이 아니다 (별도 시험이 있다)."""
    from app.orchestrator import installs as I
    from app.runner import condaenv

    monkeypatch.setattr(condaenv, "require_made", lambda name: None)
    monkeypatch.setattr(I, "_conda_env", lambda root: "hook-sandbox")


@pytest.fixture()
def fake(ready):  # noqa: F811
    got = FakeClaude(ready)
    got.on_plan = plan_writes_run_json
    got.on_review = review_writes_journal
    return got


def _ok_runner(argv, **kw):
    return subprocess.CompletedProcess(argv, 0, "Successfully installed peft-0.13.2", "")


def _bad_runner(argv, **kw):
    return subprocess.CompletedProcess(argv, 1, "", "ERROR: No matching distribution")


def write_install_request(root, name="peft", spec="==0.13.2"):
    path = os.path.join(root, "state", "Install_request.json")
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(
            {"version": 1, "packages": [{"name": name, "spec": spec}], "reason": "필요해요"},
            fh,
            ensure_ascii=False,
        )
    return path


def test_설치_승인을_기다리는_동안_설계를_안_띄운다(conn, ready, fake):  # noqa: F811
    def ask_install(root, prompt):
        write_install_request(root)
        return "설치가 필요해서 요청만 적고 멈췄어요"

    fake.on_plan = ask_install
    first = once(conn, "hook-sandbox", ready, **ctx_for(ready, fake))
    assert installs_mod.pending(conn, "hook-sandbox"), "설치 승인이 안 열렸어요"

    before = len(fake.calls)
    second = once(conn, "hook-sandbox", ready, **ctx_for(ready, fake))
    assert second["stoppedAt"] == "install", second
    assert "설치 승인을 기다려요" in stop_reason(second)
    assert len(fake.calls) == before, "승인도 안 났는데 또 띄웠어요"


def test_설치가_끝나면_그_세션을_이어_간다(conn, ready, fake):  # noqa: F811
    def ask_install(root, prompt):
        write_install_request(root)
        return "설치가 필요해서 요청만 적고 멈췄어요"

    fake.on_plan = ask_install
    first = once(conn, "hook-sandbox", ready, **ctx_for(ready, fake))
    exp_id = first["steps"][0]["experimentId"]
    asked_session = fake.calls[0]["argv"][
        fake.calls[0]["argv"].index("--session-id") + 1
    ]

    row = installs_mod.pending(conn, "hook-sandbox")[0]
    got = installs_mod.approve(
        conn, "hook-sandbox", row["id"],
        runner=_ok_runner,
    )
    conn.commit()
    assert got["ok"] is True, got

    # 끝났고 아직 안 이어 갔다
    assert [r["id"] for r in installs_mod.resumable(conn, "hook-sandbox")] == [row["id"]]

    # 이어 가면서 설계를 마치게 한다
    fake.on_resume = lambda root, prompt: plan_writes_run_json(root, f"experiments/{exp_id}/")
    second = once(conn, "hook-sandbox", ready, **ctx_for(ready, fake))

    resumed = [c for c in fake.calls if "승인이 났어요" in c["prompt"]]
    assert resumed, [c["prompt"][:30] for c in fake.calls]
    assert "--resume" in resumed[0]["argv"]
    assert asked_session in resumed[0]["argv"], "다른 세션을 이어 갔어요"
    # 프롬프트가 결과 파일을 가리킨다
    assert "Install_result.json" in resumed[0]["prompt"]

    # 새 실험을 또 만들지 않았다
    assert second["experimentId"] == exp_id, second
    # 두 번은 이어 가지 않는다
    assert installs_mod.resumable(conn, "hook-sandbox") == []


def test_설치가_실패해도_알려_주러_이어_간다(conn, ready, fake):  # noqa: F811
    """실패를 모르면 같은 요청을 또 써요."""
    fake.on_plan = lambda root, prompt: (
        write_install_request(root) and "" or "요청만 적었어요"
    )
    once(conn, "hook-sandbox", ready, **ctx_for(ready, fake))

    row = installs_mod.pending(conn, "hook-sandbox")[0]
    installs_mod.approve(
        conn, "hook-sandbox", row["id"],
        runner=_bad_runner,
    )
    conn.commit()
    assert AP.get(conn, row["id"])["state"] == "blocked"
    assert [r["id"] for r in installs_mod.resumable(conn, "hook-sandbox")] == [row["id"]]

    fake.on_resume = lambda root, prompt: "실패를 봤어요. 다른 방법을 찾을게요"
    once(conn, "hook-sandbox", ready, **ctx_for(ready, fake))
    assert [c for c in fake.calls if "승인이 났어요" in c["prompt"]]
    assert installs_mod.resumable(conn, "hook-sandbox") == []


def test_거절한_설치는_이어_가지_않는다(conn, ready, fake):  # noqa: F811
    """사람이 거절했으면 그 세션을 되살릴 이유가 없어요."""
    fake.on_plan = lambda root, prompt: (
        write_install_request(root) and "" or "요청만 적었어요"
    )
    once(conn, "hook-sandbox", ready, **ctx_for(ready, fake))
    row = installs_mod.pending(conn, "hook-sandbox")[0]
    installs_mod.deny(conn, "hook-sandbox", row["id"], reason="안 쓸 거예요")
    conn.commit()
    assert installs_mod.resumable(conn, "hook-sandbox") == []
    assert installs_mod.pending(conn, "hook-sandbox") == []
