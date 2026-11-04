"""`claude -p` 출력 읽기와 Final Report 파싱.

출력 앞에 쓰레기가 붙는 건 0단계에서 실제로 당한 일이다 —
`json.load` 가 `Expecting value: line 1 column 1` 로 깨졌고, 출력이
`Warning: no stdin data received in 3s...` 로 시작했다.
"""

import pytest

from app.agent import report as R
from app.agent import result as RES

OK_JSON = (
    '{"type":"result","subtype":"success","is_error":false,'
    '"result":"했어요","stop_reason":"end_turn","session_id":"0f0c",'
    '"num_turns":3,"permission_denials":[],"total_cost_usd":0.12,'
    '"usage":{"input_tokens":10},"model":"claude-opus-5"}'
)


# --- 출력 읽기 -------------------------------------------------------------------


def test_정상_출력(tmp_path):
    got = RES.parse(OK_JSON, exit_code=0)
    assert got.ok is True
    assert got.text == "했어요"
    assert got["sessionId"] == "0f0c"
    assert got["model"] == "claude-opus-5"
    assert got["costUsd"] == 0.12


def test_앞에_붙은_경고를_건너뛴다():
    """실측에서 json.load 가 깨진 그 꼴."""
    raw = "Warning: no stdin data received in 3s...\n" + OK_JSON
    got = RES.parse(raw, exit_code=0)
    assert got.ok is True and got.text == "했어요"


def test_뒤에_붙은_쓰레기도_건너뛴다():
    got = RES.parse(OK_JSON + "\n(끝)\n", exit_code=0)
    assert got.ok is True


def test_JSON_이_아예_없으면_원문을_남긴다():
    got = RES.parse("무슨 일인지 모를 출력", exit_code=1)
    assert got.ok is False
    assert got["parseError"]
    assert got["raw"] == "무슨 일인지 모를 출력"  # 한도 문구를 뽑을 유일한 재료
    assert got["exitCode"] == 1


def test_깨진_JSON_도_원문을_남긴다():
    got = RES.parse("{이건 JSON 이 아니에요}", exit_code=0)
    assert got.ok is False and got["raw"]


def test_종료코드가_0이_아니면_실패():
    assert RES.parse(OK_JSON, exit_code=1).ok is False


def test_is_error_면_실패():
    assert RES.parse('{"is_error":true,"result":"x"}', exit_code=0).ok is False


def test_정지는_성공이_아니다():
    """헤드리스에서 훅의 defer 가 이렇게 끝난다. 아무것도 못 했다."""
    got = RES.parse('{"stop_reason":"tool_deferred","result":"","is_error":false}', exit_code=0)
    assert got.stalled is True
    assert got.ok is False


def test_거절_목록을_읽는다():
    got = RES.parse('{"permission_denials":[{"tool":"Read"}],"result":"x","is_error":false}')
    assert len(got["denials"]) == 1


def test_모델을_여러_자리에서_찾는다():
    assert RES.parse('{"modelInfo":{"id":"claude-sonnet-5-5"},"result":""}')["model"] == "claude-sonnet-5-5"
    assert RES.parse('{"usage":{"model":"claude-haiku-5-5"},"result":""}')["model"] == "claude-haiku-5-5"
    assert RES.parse('{"result":""}')["model"] is None


# --- 한도 추정 -------------------------------------------------------------------


def test_패턴이_비어_있으면_아무것도_한도로_안_본다():
    """틀린 패턴은 인증 만료를 한도로 오인해 **영원히 기다리게** 만든다."""
    got = RES.parse("Claude usage limit reached", exit_code=1)
    assert RES.looks_like_usage_limit(got, []) == ""
    assert RES.looks_like_usage_limit(got, None) == ""


def test_패턴이_맞으면_그_문구를_돌려준다():
    got = RES.parse("Claude usage limit reached. Try again later.", exit_code=1)
    assert RES.looks_like_usage_limit(got, ["usage limit reached"]) == "usage limit reached"


def test_대소문자를_안_가린다():
    got = RES.parse("CLAUDE USAGE LIMIT REACHED", exit_code=1)
    assert RES.looks_like_usage_limit(got, ["usage limit"]) == "usage limit"


def test_결과_본문에서도_찾는다():
    got = RES.parse('{"result":"5-hour limit reached","is_error":true}', exit_code=0)
    assert RES.looks_like_usage_limit(got, ["5-hour limit"]) == "5-hour limit"


# --- Final Report ----------------------------------------------------------------

FULL = """분석을 마쳤어요.

## Final Report
- 실험 ID: EXP-007
- 검증한 가설: rank 를 올리면 정확도가 오른다
- 변경한 조작변인: lora rank 16 → 32
- 실행 상태: 정상 종료
- 주요 결과: val acc 78.4%
- 성공 기준 충족 여부: 미충족 (목표 82.0%)
- 생성·수정한 파일: result.csv, analysis.md
- 다음 행동: rank 64 로 한 번 더
- 사람의 검토 필요 여부: 아니요
"""


def test_아홉_항목을_전부_읽는다():
    """PDF 9쪽의 9항목이 계약이다."""
    got = R.parse(FULL)
    assert got["missing"] == []
    assert len(R.FIELDS) == 9
    assert got["fields"]["experimentId"] == "EXP-007"
    assert got["fields"]["files"] == "result.csv, analysis.md"
    assert got["hasHeading"] is True


def test_빠진_항목을_이름으로_알려_준다():
    text = "## Final Report\n- 실험 ID: EXP-007\n- 주요 결과: 78%\n"
    missing = R.missing_fields(text)
    assert "검증한 가설" in missing
    assert "실험 ID" not in missing


def test_머리말이_없어도_읽는다():
    """문구가 조금 달라도 읽되, 없는 건 없다고 한다."""
    got = R.parse("- 실험 ID: EXP-001\n- 주요 결과: loss 0.4\n")
    assert got["hasHeading"] is False
    assert got["fields"]["experimentId"] == "EXP-001"


def test_굵은_글씨와_다른_기호도_읽는다():
    text = "## Final Report\n* **실험 ID**: EXP-002\n+ __주요 결과__: 좋아요\n"
    got = R.parse(text)
    assert got["fields"]["experimentId"] == "EXP-002"
    assert got["fields"]["result"] == "좋아요"


def test_다음_머리말_뒤는_안_읽는다():
    text = FULL + "\n## 덧붙임\n- 실험 ID: 거짓말\n"
    assert R.parse(text)["fields"]["experimentId"] == "EXP-007"


def test_같은_항목이_여러_번이면_처음_것(tmp_path):
    text = "## Final Report\n- 주요 결과: 처음\n- 주요 결과: 나중\n"
    assert R.parse(text)["fields"]["result"] == "처음"


@pytest.mark.parametrize(
    "value,expect",
    [
        ("충족", True),
        ("성공 기준을 충족했어요", True),
        ("달성", True),
        ("Yes", True),
        ("미충족", False),
        ("미충족 (목표 82%)", False),
        ("불충족", False),
        ("실패", False),
        ("No", False),
        ("목표를 못 넘었어요", False),
        ("판단 보류", None),
        ("", None),
    ],
)
def test_성공_판정을_읽는다(value, expect):
    """**부정이 먼저다** — "미충족" 안에 "충족" 이 들어 있다."""
    text = f"## Final Report\n- 성공 기준 충족 여부: {value}\n"
    assert R.success_of(R.parse(text)) is expect


def test_성공_여부를_모르면_None_이다():
    """`None` 을 참으로 바꾸지 않는다. 모르면 모른다고 해야 대조할 수 있다."""
    assert R.success_of(R.parse("## Final Report\n- 실험 ID: EXP-001\n")) is None


def test_빈_입력도_안_터진다():
    for bad in ("", None):
        got = R.parse(bad)
        assert got["fields"] == {}
        assert len(got["missing"]) == 9
