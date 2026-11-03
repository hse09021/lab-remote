"""대기 건 마감 — 거부로 턴이 끊긴 경우.

실측(2026-11-04): PC 터미널에서 승인을 거부하면 턴이 "Interrupted" 로 끊겨
**Stop 훅이 안 돈다.** Stop 은 `prompt_id` 로 그 응답 것만 닫으므로 다음 턴의
Stop 도 이전 턴 대기 건을 지나치고, `SessionEnd` 가 세션을 닫을 때까지
"대기 중" 으로 남았다 (`Approval_log.csv` 13·15·25·28행 -> 34~37행, 25분).
"""

import csv
import json
import os

from app import approval_log as A
from app.hooks import posttooluse, pretooluse, userprompt


def rows(project_root):
    with open(A.log_path(project_root), encoding="utf-8", newline="") as fh:
        return list(csv.DictReader(fh))


def run_pre(event):
    return pretooluse.handle(event)


def open_ask(prompt_id="p1", tool_use_id="t1", session_id="sess-테스트", action="패키지 설치"):
    A.open_pending(
        "hook-sandbox",
        tool_use_id,
        {
            "promptId": prompt_id,
            "sessionId": session_id,
            "tool": "Bash",
            "action": action,
            "request": f"pip install {tool_use_id}",
        },
    )


# --- UserPromptSubmit -------------------------------------------------------


def test_새_프롬프트가_이전_턴_대기_건을_닫는다(project, project_root):
    open_ask()
    closed = userprompt.handle({"cwd": project_root, "session_id": "sess-테스트"})
    assert len(closed) == 1
    assert A.list_pending("hook-sandbox") == []
    assert rows(project_root)[-1]["result"] == A.RESULT_NO_ANSWER


def test_마감_행에_toolUseId_가_들어간다(project, project_root):
    """같은 호출의 여러 행을 묶는 키다. 없으면 화면이 마지막 행을 못 고른다."""
    open_ask(tool_use_id="toolu_abc")
    userprompt.handle({"cwd": project_root, "session_id": "sess-테스트"})
    assert rows(project_root)[-1]["toolUseId"] == "toolu_abc"


def test_다른_세션_대기_건은_안_닫는다(project, project_root):
    open_ask(session_id="다른-세션")
    assert userprompt.handle({"cwd": project_root, "session_id": "sess-테스트"}) == []
    assert len(A.list_pending("hook-sandbox")) == 1


def test_prompt_id_가_와도_세션_전체를_닫는다(project, project_root):
    """이 시점에 열려 있는 건 전부 이전 턴 것이다 — 이 턴의 도구는 아직 안 돌았다."""
    open_ask(prompt_id="p1", tool_use_id="t1")
    open_ask(prompt_id="p2", tool_use_id="t2")
    closed = userprompt.handle(
        {"cwd": project_root, "session_id": "sess-테스트", "prompt_id": "p3"}
    )
    assert len(closed) == 2


def test_등록_안_된_폴더는_아무것도_안_한다(tmp_path):
    assert userprompt.handle({"cwd": str(tmp_path), "session_id": "s"}) == []


def test_입력이_깨져도_조용히_끝난다(monkeypatch):
    import io

    monkeypatch.setattr("sys.stdin", io.StringIO("{ 깨진"))
    assert userprompt.main() == 0


def test_자가_점검_기록은_따로_표시된다(project, project_root):
    """`labremote hooks check` 가 남긴 것은 사용자 거부가 아니다."""
    open_ask(session_id=A.SELF_CHECK_SESSION)
    closed = A.close_stale("hook-sandbox", project_root, project, session_id="")
    assert closed[0]["result"] == "정리됨 · 자가 점검"
    assert rows(project_root)[-1]["result"] == "정리됨 · 자가 점검"


# --- PreToolUse 안전망 ------------------------------------------------------


def test_PreToolUse_가_이전_응답_대기_건을_닫는다(project, project_root, hook_event):
    """UserPromptSubmit 이 아직 설치 안 된 경우에도 뱃지가 거짓으로 켜지지 않게."""
    open_ask(prompt_id="예전-응답", tool_use_id="예전")
    event = hook_event("Bash", {"command": "pip install b"}, cwd=project_root,
                       prompt_id="지금-응답", tool_use_id="지금")
    run_pre(event)
    left = [item["promptId"] for item in A.list_pending("hook-sandbox")]
    assert left == ["지금-응답"]


def test_PreToolUse_는_지금_응답_것은_안_닫는다(project, project_root, hook_event):
    open_ask(prompt_id="지금-응답", tool_use_id="먼저")
    event = hook_event("Bash", {"command": "pip install b"}, cwd=project_root,
                       prompt_id="지금-응답", tool_use_id="나중")
    run_pre(event)
    assert len(A.list_pending("hook-sandbox")) == 2


# --- 늦게 오는 PostToolUse --------------------------------------------------
# 백그라운드 서브에이전트의 승인창은 새 프롬프트 뒤까지 열려 있을 수 있다.


def test_닫힌_뒤_늦게_승인되면_허용_행이_붙는다(project, project_root, hook_event):
    open_ask(tool_use_id="toolu_늦은")
    userprompt.handle({"cwd": project_root, "session_id": "sess-테스트"})
    assert rows(project_root)[-1]["result"] == A.RESULT_NO_ANSWER

    late = hook_event("Bash", {"command": "pip install t1"}, cwd=project_root,
                      tool_use_id="toolu_늦은")
    assert posttooluse.handle(late) is not None
    last = rows(project_root)[-1]
    assert last["result"] == "허용"
    assert last["action"] == "패키지 설치"  # 닫힌 건의 이름표를 되찾는다
    assert last["toolUseId"] == "toolu_늦은"


def test_표시는_같은_호출의_마지막_행을_따른다(project, project_root, hook_event):
    open_ask(tool_use_id="toolu_늦은")
    userprompt.handle({"cwd": project_root, "session_id": "sess-테스트"})
    posttooluse.handle(
        hook_event("Bash", {"command": "pip install t1"}, cwd=project_root,
                   tool_use_id="toolu_늦은")
    )
    grouped = A.group_rows(A.read_rows(A.log_path(project_root)))
    mine = [r for r in grouped if r["toolUseId"] == "toolu_늦은"]
    assert len(mine) == 1 and mine[0]["result"] == "허용"
    # 원본은 두 행 다 남아 있다 (append-only)
    raw = [r for r in A.read_rows(A.log_path(project_root)) if r["toolUseId"] == "toolu_늦은"]
    assert [r["result"] for r in raw] == [A.RESULT_NO_ANSWER, "허용"]


def test_ask_였던_적_없는_호출엔_행을_안_남긴다(project, project_root, hook_event):
    before = len(rows(project_root)) if os.path.exists(A.log_path(project_root)) else 0
    event = hook_event("Bash", {"command": "ls"}, cwd=project_root, tool_use_id="toolu_그냥")
    assert posttooluse.handle(event) is None
    after = len(rows(project_root)) if os.path.exists(A.log_path(project_root)) else 0
    assert after == before


def test_닫은_대기_건은_목록에_안_보인다(project, project_root):
    """`.closed/` 로 옮기므로 하위 폴더가 목록에 섞이면 안 된다."""
    open_ask(tool_use_id="t1")
    A.close_pending("hook-sandbox", "t1")
    assert A.list_pending("hook-sandbox") == []
    assert A.recall_closed("hook-sandbox", "t1")["action"] == "패키지 설치"


# --- 헤드리스 승인 요청 ------------------------------------------------------


def test_헤드리스_거절은_승인_요청으로_남는다(project, project_root, hook_event, monkeypatch):
    monkeypatch.setenv(pretooluse.HEADLESS_ENV, "1")
    monkeypatch.setenv("LAB_NOTIFY_DISABLED", "1")
    event = hook_event("Bash", {"command": "pip install peft"}, cwd=project_root,
                       tool_use_id="toolu_헤드리스")
    decision = run_pre(event)
    assert decision.kind == "deny"

    requests = A.list_requests("hook-sandbox")
    assert len(requests) == 1
    assert requests[0]["action"] == "패키지 설치"
    assert "승인 요청을 남겨 두었어요" in requests[0]["reason"]
    # 대기 폴더에는 넣지 않는다 — 닫아 줄 주체가 ②의 대기열이다
    assert A.list_pending("hook-sandbox") == []
    assert rows(project_root)[-1]["result"] == "차단"


def test_승인_요청은_sweep_으로_안_닫힌다(project, project_root):
    A.open_request("hook-sandbox", "r1", {"action": "패키지 설치", "request": "pip install x"})
    A.close_stale("hook-sandbox", project_root, project, session_id="")
    assert len(A.list_requests("hook-sandbox")) == 1
    assert A.clear_request("hook-sandbox", "r1") is True
    assert A.list_requests("hook-sandbox") == []


# --- 권한 모드 기록 ---------------------------------------------------------


def test_권한_우회_모드는_기록만_한다(project, project_root, hook_event):
    """판정은 permission_mode 를 읽지 않는다. 막은 게 아니라 적은 것이다."""
    event = hook_event("Bash", {"command": "pip install peft"}, cwd=project_root,
                       permission_mode="auto")
    decision = run_pre(event)
    assert decision.kind == "ask"  # auto 여도 승인창으로 간다

    mode_rows = [r for r in rows(project_root) if r["action"] == "권한 우회 모드"]
    assert len(mode_rows) == 1
    assert mode_rows[0]["result"] == "기록"
    assert "permission_mode=auto" in mode_rows[0]["request"]
    assert "ask" in mode_rows[0]["request"]


def test_기본_모드는_기록하지_않는다(project, project_root, hook_event):
    for mode in ("default", "plan", "acceptEdits"):
        run_pre(hook_event("Bash", {"command": "ls"}, cwd=project_root, permission_mode=mode))
    # 읽기 명령은 defer 라 애초에 행이 하나도 안 남는다 (소음 없음)
    got = A.read_rows(A.log_path(project_root))
    assert [r for r in got if r["action"] == "권한 우회 모드"] == []


# --- CSV 판 올림 ------------------------------------------------------------


def test_옛_6열_로그도_읽힌다(project_root):
    path = A.log_path(project_root)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8", newline="") as fh:
        fh.write("time,action,request,result,resultPending,handledBy\n")
        fh.write("2026-11-04T00:00:00+09:00,패키지 설치,pip install x,대기 중,true,Claude 앱\n")
    got = A.read_rows(path)
    assert got[0]["toolUseId"] == ""
    assert got[0]["action"] == "패키지 설치"


def test_옛_로그를_판_올리면_백업이_남는다(project_root):
    path = A.log_path(project_root)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8", newline="") as fh:
        fh.write("time,action,request,result,resultPending,handledBy\n")
        fh.write("2026-11-04T00:00:00+09:00,패키지 설치,pip install x,차단,false,Hooks · 잠금\n")

    info = A.migrate_log(path)
    assert info["changed"] and info["added"] == ["toolUseId"]
    assert os.path.exists(info["backup"])
    with open(path, encoding="utf-8", newline="") as fh:
        got = list(csv.DictReader(fh))
    assert list(got[0]) == A.COLUMNS
    assert got[0]["toolUseId"] == ""

    # 두 번 돌려도 그대로
    assert A.migrate_log(path)["changed"] is False


def test_모르는_헤더는_건드리지_않는다(project_root):
    path = A.log_path(project_root)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as fh:
        fh.write("엉뚱한,헤더\n1,2\n")
    assert A.migrate_log(path)["changed"] is False
    assert "엉뚱한" in open(path, encoding="utf-8").read()


def test_옛_행과_새_행이_섞여도_묶인다(project_root):
    """옛 행은 toolUseId 가 없으니 action+request 로 묶는다."""
    rows_in = [
        {"time": "1", "action": "패키지 설치", "request": "pip install x", "result": "대기 중",
         "resultPending": "true", "handledBy": "Claude 앱", "toolUseId": ""},
        {"time": "2", "action": "패키지 설치", "request": "pip install x", "result": "허용",
         "resultPending": "false", "handledBy": "Claude 앱", "toolUseId": ""},
        {"time": "3", "action": "코드 수정", "request": "src/a.py", "result": "대기 중",
         "resultPending": "true", "handledBy": "Claude 앱", "toolUseId": "t9"},
    ]
    got = A.group_rows(rows_in)
    assert [(r["action"], r["result"]) for r in got] == [
        ("패키지 설치", "허용"),
        ("코드 수정", "대기 중"),
    ]


def test_JSONL_에_sweep_이_남는다(project, project_root):
    open_ask()
    userprompt.handle({"cwd": project_root, "session_id": "sess-테스트"})
    path = A.event_path(project_root)
    events = [json.loads(line) for line in open(path, encoding="utf-8") if line.strip()]
    sweeps = [e for e in events if e.get("event") == "sweep"]
    assert sweeps and sweeps[-1]["by"] == "UserPromptSubmit"
