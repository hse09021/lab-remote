"""사유 문구 — 조사와 새 잠금 문구.

실측에서 "패키지 설치 은 승인이 필요해요" 가 나왔다. 이름이 정책 파일에서,
경로가 도구에서 오니 문구를 쓰는 쪽에서 미리 고를 수 없다.
"""

import pytest

from app.hooks import messages as M


@pytest.mark.parametrize(
    "word,expected",
    [
        ("패키지 설치", "는"),  # 치 — 받침 없음
        ("코드 수정", "은"),  # 정 — 받침 있음
        ("파일 삭제", "는"),
        ("새 실험 시작", "은"),
        ("외부 네트워크 접근", "은"),
        ("하이퍼파라미터 변경", "은"),
        # 라틴 문자·기호로 끝나면 받침 없는 쪽으로
        ("docs/Evaluation.md", "는"),
        ("experiments/EXP-001/analysis.md", "는"),
        (".env", "는"),
        # 숫자는 발음으로
        ("EXP-001", "은"),  # 일
        ("loop-2", "는"),  # 이
        ("rank-3", "은"),  # 삼
        ("lr-5", "는"),  # 오
        ("step-6", "은"),  # 육
        ("gpu-9", "는"),  # 구
        ("", "는"),  # 빈 값에서 터지지 않는다
    ],
)
def test_조사를_받침으로_고른다(word, expected):
    assert M.josa(word) == expected


def test_다른_조사_짝도_된다():
    assert M.josa("코드 수정", "이/가") == "이"
    assert M.josa("패키지 설치", "이/가") == "가"
    assert M.josa("코드 수정", "을/를") == "을"


def test_ask_문구에_조사가_붙는다():
    assert M.ask_action("패키지 설치", "pip install peft") == "패키지 설치는 승인이 필요해요: pip install peft"
    assert M.block_action("코드 수정", "src/a.py").startswith("코드 수정은 ")


def test_경로_문구에_조사가_붙는다():
    assert "docs/Evaluation.md는" in M.stop_idle("docs/Evaluation.md")
    # 라틴 문자로 끝나면 받침 없는 쪽. "…은" 이 붙던 자리다.
    assert ".claude/settings.json는" in M.self_protect(".claude/settings.json")


# --- 새 잠금 문구 -----------------------------------------------------------


def test_보호_목록_문구():
    text = M.with_guard(M.hard_protect("/home/u/.claude.json"))
    assert "어떤 권한 설정에서도" in text
    assert M.NO_WORKAROUND in text


def test_비밀_파일_문구는_환경_변수로_안내():
    text = M.secret("/home/u/p/.env")
    assert "환경 변수 이름만" in text
    assert "~/.config/labremote" in text


def test_산출물_문구에_실험_ID_와_동작이_들어간다():
    text = M.output_protect("experiments/EXP-002/output/train.log", "EXP-002", "지우거나 비울")
    assert "EXP-002" in text and "지우거나 비울 수 없어요" in text


def test_헤드리스_문구는_실측_문장():
    text = M.with_guard(M.headless_ask("패키지 설치", "패키지 설치는 승인이 필요해요: pip install peft"))
    assert "화면 없이 실행 중이라 지금은 승인받을 수 없어요" in text
    assert "승인 요청을 남겨 두었어요" in text
    assert M.NO_WORKAROUND in text


def test_새_분류에_이름표가_있다():
    """승인 로그 action 칸이 비면 무엇이 막혔는지 알 수 없다."""
    for key in ("hardProtect", "secret", "outputProtect"):
        assert M.LABELS[key]
