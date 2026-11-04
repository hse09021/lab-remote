"""📒 승인 기록의 **진본** — S7.

프로젝트의 `logs/Approval_log.csv` 는 **AI 가 쓴 코드가 고칠 수 있다.**
샌드박스는 작업 디렉터리 쓰기를 못 막고(M4) `denyWrite` 키도 없다. 훅은 도구
호출만 보므로 `python x.py` 안의 `open(..., "w")` 를 못 막는다.

진본은 `server/data/audit/<프로젝트>.jsonl` 이다.

| | 샌드박스 | `server/data/audit/` 쓰기 |
|---|---|---|
| **훅** | **밖** (M1) | **된다** |
| AI 가 쓴 코드 | 안 | **안 된다** (M1b) |
| 학습 프로세스 | bwrap | **안 된다** (`--tmpfs <server>`) |

## 왜 해시 체인 + 앵커가 아닌가

체인은 위조를 **탐지**만 한다 — 원본 내용을 모르니 **되살릴 수 없다.**
서버 쪽 진본은 되살린다. 그리고 체인 계산·앵커·CSV 헤더 판 올림이 전부
필요 없다.
"""

import json
import os

import pytest

from app import approval_log as A
from app import audit


@pytest.fixture()
def csv_path(project, project_root):
    return A.log_path(project_root, project)


def _rows(path):
    import csv as csv_mod

    with open(path, encoding="utf-8", newline="") as fh:
        rows = list(csv_mod.reader(fh))
    return rows[1:]  # 헤더 제외


# --- 훅이 쓸 때 진본에도 남나 -------------------------------------------------


def test_append_row_가_진본에도_남긴다(project_root, csv_path):
    A.append_row(
        csv_path, project="hook-sandbox",
        action="패키지 설치", request="pip install peft",
        result="차단", handled_by="Hooks · 잠금", tool_use_id="toolu_1",
    )
    truth = audit.read("hook-sandbox")
    assert len(truth) == 1
    assert truth[0]["action"] == "패키지 설치"
    assert truth[0]["result"] == "차단"
    assert truth[0]["toolUseId"] == "toolu_1"
    # 사본과 같은 순서·같은 값
    assert audit.csv_rows("hook-sandbox") == _rows(csv_path)
    assert audit.compare("hook-sandbox", csv_path)["ok"] is True


def test_project_를_안_주면_진본에_안_남는다(project_root, csv_path):
    """진본에 남기는 것은 **명시적**이다 — 실수로 안 남는 자리는 테스트가 잡는다."""
    A.append_row(csv_path, action="x", request="y", result="허용")
    assert audit.read("hook-sandbox") == []


def test_모든_append_row_호출이_project_를_준다():
    """🔑 하나라도 빠지면 그 줄은 진본에 안 남고, 대조가 거짓 경보를 낸다."""
    import pathlib
    import re

    root = pathlib.Path(A.__file__).resolve().parent
    missing = []
    for path in sorted(root.rglob("*.py")):
        body = path.read_text(encoding="utf-8")
        for m in re.finditer(r"append_row\(\n((?:.*\n){0,12}?)\s*\)", body):
            if "project=" not in m.group(1):
                line = body[: m.start()].count("\n") + 1
                missing.append(f"{path.name}:{line}")
    # `approval_log.py` 의 **정의**는 제외한다 (`def append_row(`)
    missing = [m for m in missing if not m.startswith("approval_log.py:1")]
    assert missing == [], missing


def test_진본_쓰기가_실패해도_사본은_쓴다(project_root, csv_path, monkeypatch):
    """막는 것과 기록이 먼저다. 어긋난 것은 `compare` 가 잡는다."""
    monkeypatch.setattr(audit, "audit_path", lambda project: "/proc/못쓰는곳")
    A.append_row(csv_path, project="hook-sandbox", action="x", request="y", result="허용")
    assert len(_rows(csv_path)) == 1


# --- 🔑 위조를 잡고 되살린다 ---------------------------------------------------


def _three(csv_path):
    for n in range(3):
        A.append_row(
            csv_path, project="hook-sandbox",
            action=f"행동{n}", request=f"요청{n}",
            result="차단" if n == 1 else "허용", tool_use_id=f"toolu_{n}",
        )


def test_줄_내용을_바꾸면_잡는다(project_root, csv_path):
    """승인 기록에서 가장 위험한 위조 — `차단` 을 `허용` 으로."""
    _three(csv_path)
    body = open(csv_path, encoding="utf-8").read().replace(",차단,", ",허용,")
    open(csv_path, "w", encoding="utf-8").write(body)

    report = audit.compare("hook-sandbox", csv_path)
    assert report["ok"] is False
    assert len(report["changed"]) == 1
    number, truth, copy = report["changed"][0]
    assert number == 2 and truth[3] == "차단" and copy[3] == "허용"
    assert "2번째 줄이 달라요" in audit.describe(report)


def test_줄을_지우면_잡는다(project_root, csv_path):
    _three(csv_path)
    lines = open(csv_path, encoding="utf-8").read().splitlines()
    open(csv_path, "w", encoding="utf-8").write("\n".join(lines[:-1]) + "\n")

    report = audit.compare("hook-sandbox", csv_path)
    assert report["ok"] is False and len(report["missing"]) == 1
    assert "지워졌어요" in audit.describe(report)


def test_줄을_끼워_넣으면_잡는다(project_root, csv_path):
    _three(csv_path)
    with open(csv_path, "a", encoding="utf-8") as fh:
        fh.write("2026-01-01T00:00:00+09:00,가짜,가짜,허용,false,,\n")

    report = audit.compare("hook-sandbox", csv_path)
    assert report["ok"] is False and len(report["extra"]) == 1
    assert "끼워져 있어요" in audit.describe(report)


def test_사본을_통째로_지워도_잡는다(project_root, csv_path):
    _three(csv_path)
    os.unlink(csv_path)
    report = audit.compare("hook-sandbox", csv_path)
    assert report["ok"] is False and len(report["missing"]) == 3


def test_진본으로_사본을_되살린다(project_root, csv_path):
    """🔑 체인+앵커로는 **못 하는 것**. 원본 내용을 모르기 때문이다."""
    _three(csv_path)
    before = open(csv_path, "rb").read()
    open(csv_path, "w", encoding="utf-8").write("time,action\n엉망,엉망\n")

    got = audit.rebuild("hook-sandbox", csv_path)

    assert got["ok"] is True and got["rows"] == 3
    assert open(csv_path, "rb").read() == before, "바이트까지 같아야 해요"
    assert audit.compare("hook-sandbox", csv_path)["ok"] is True


# --- 이행 (--seed) -----------------------------------------------------------


def test_진본이_없으면_출발점을_삼으라고_한다(project_root, csv_path):
    """이 기능이 생기기 전의 프로젝트. 지난 줄은 되짚어 검증할 수 없다."""
    A.append_row(csv_path, action="옛 기록", request="x", result="허용")
    report = audit.compare("hook-sandbox", csv_path)
    assert report["missingTruth"] is True and report["ok"] is False
    assert "--seed" in audit.describe(report)

    got = audit.seed("hook-sandbox", csv_path)
    assert got["ok"] is True and got["rows"] == 1
    assert audit.compare("hook-sandbox", csv_path)["ok"] is True


def test_진본이_있으면_seed_를_거절한다(project_root, csv_path):
    """덮어쓰게 두면 "진본을 지우고 위조된 사본으로 다시 만드는" 길이 생긴다."""
    _three(csv_path)
    got = audit.seed("hook-sandbox", csv_path)
    assert got["ok"] is False and "이미 있어요" in got["reason"]


def test_빈_사본으로도_진본_파일이_생긴다(project_root, csv_path):
    A.ensure_log(csv_path)
    got = audit.seed("hook-sandbox", csv_path)
    assert got["ok"] is True and got["rows"] == 0
    assert audit.compare("hook-sandbox", csv_path)["missingTruth"] is False


# --- 진본이 AI 가 못 쓰는 곳에 있나 ------------------------------------------


def test_진본은_server_data_아래다():
    from app import registry

    assert audit.audit_path("hook-sandbox").startswith(
        os.path.join(registry.data_dir(), "audit")
    )


def test_깨진_줄은_건너뛴다(project_root, csv_path):
    A.append_row(csv_path, project="hook-sandbox", action="좋은줄", request="x", result="허용")
    with open(audit.audit_path("hook-sandbox"), "a", encoding="utf-8") as fh:
        fh.write("{반쯤 쓰인 JSON\n\n")
    assert [r["action"] for r in audit.read("hook-sandbox")] == ["좋은줄"]


# --- 루프·doctor 에 붙어 있나 -------------------------------------------------


def test_루프_시작_전에_막는다(project, project_root, conn, csv_path):
    from app.orchestrator import guards

    _three(csv_path)
    assert guards.check_loop(conn, "hook-sandbox", project_root).ok is True

    body = open(csv_path, encoding="utf-8").read().replace(",차단,", ",허용,")
    open(csv_path, "w", encoding="utf-8").write(body)

    verdict = guards.check_loop(conn, "hook-sandbox", project_root)
    assert verdict.ok is False
    assert "진본과 달라요" in verdict["reason"]
    # 종료 조건이 아니다 — 되살리면 풀린다
    assert verdict["stop"] is False


def test_커밋_전에_멈추고_사람을_부른다(project, project_root, conn, csv_path, monkeypatch):
    from app.orchestrator import loop as loop_mod
    from app.orchestrator import runner_ctx
    from app.store import loops as LP

    _three(csv_path)
    body = open(csv_path, encoding="utf-8").read().replace(",차단,", ",허용,")
    open(csv_path, "w", encoding="utf-8").write(body)

    ctx = runner_ctx.LoopCtx(project="hook-sandbox", root=project_root, preset="full")
    sent = []
    monkeypatch.setattr(
        loop_mod.notifier, "send", lambda *a, **k: sent.append(k) or {"ok": True}
    )
    assert loop_mod.guard_audit(ctx, conn, when="기록 커밋 전") is False
    assert LP.ensure(conn, "hook-sandbox")["state"] == "blocked"
    assert sent and "승인 기록이 바뀌었어요" in sent[0]["title"]
    # 되돌리지 않는다 — 사람이 보고 --rebuild 한다
    assert ",허용," in open(csv_path, encoding="utf-8").read()


def test_doctor_가_잡는다(project, project_root, csv_path):
    from app import doctor

    _three(csv_path)
    assert doctor.audit_check(project_root, "hook-sandbox", project)["ok"] is True

    body = open(csv_path, encoding="utf-8").read().replace(",차단,", ",허용,")
    open(csv_path, "w", encoding="utf-8").write(body)
    got = doctor.audit_check(project_root, "hook-sandbox", project)
    assert got["ok"] is False and got["level"] == "bad"
    assert "--rebuild" in got["hint"]
