"""Final Report 읽기 — PDF 9쪽의 9항목.

PDF 9쪽 `AGENTS.md 예시` 의 `## Final Report` 절이 계약이다.

    - 실험 ID
    - 검증한 가설
    - 변경한 조작변인
    - 실행 상태
    - 주요 결과
    - 성공 기준 충족 여부
    - 생성·수정한 파일
    - 다음 행동
    - 사람의 검토 필요 여부

### 왜 파싱하나

오케스트레이터가 **AI 의 말을 믿지 않고** 따로 판정하기 때문이다
(spec III-4). `result.csv` 에서 직접 읽은 값과 AI 가 적은 "성공 기준 충족
여부" 가 **어긋나면 자동 진행을 멈추고** 사람에게 알린다. 그러려면 AI 가 뭐라
했는지를 구조로 알아야 한다.

### 너그럽게 읽는다

문구가 조금 달라도(`- 실험 ID:` vs `**실험 ID**:`) 읽는다. 대신 **없는 항목은
없다고** 말한다 — 지어내지 않는다.
"""

from __future__ import annotations

import re

__all__ = ["FIELDS", "YES_WORDS", "NO_WORDS", "parse", "missing_fields", "success_of"]

#: (키, 보고서에 적히는 이름, 같은 뜻으로 받아 줄 말들)
FIELDS: tuple[tuple[str, str, tuple[str, ...]], ...] = (
    ("experimentId", "실험 ID", ("실험ID", "실험 아이디", "experiment id")),
    ("hypothesis", "검증한 가설", ("가설", "hypothesis")),
    ("knob", "변경한 조작변인", ("조작변인", "변경한 변인", "knob")),
    ("state", "실행 상태", ("상태", "실행상태", "state")),
    ("result", "주요 결과", ("결과", "주요결과", "result")),
    ("success", "성공 기준 충족 여부", ("성공 여부", "성공기준", "success")),
    ("files", "생성·수정한 파일", ("생성/수정한 파일", "수정한 파일", "files")),
    ("next", "다음 행동", ("다음행동", "next")),
    ("needsReview", "사람의 검토 필요 여부", ("검토 필요", "사람 검토", "needs review")),
)

#: "충족했다" 로 읽는 말
YES_WORDS = ("충족", "달성", "성공", "yes", "true", "o", "예", "넘었", "통과")
#: "아니다" 로 읽는 말
NO_WORDS = ("미충족", "불충족", "미달", "실패", "no", "false", "x", "아니", "못 넘", "못넘")

#: 머리말. 없으면 본문 전체에서 찾는다.
_HEADING_RE = re.compile(r"^#{1,6}\s*final\s*report\s*$", re.I | re.M)

#: `- 이름: 값` · `* **이름**: 값` · `이름: 값`
_LINE_RE = re.compile(
    r"^\s*(?:[-*+]\s*)?(?:\*\*|__)?\s*(?P<name>[^:\n*_]{1,40}?)\s*(?:\*\*|__)?\s*[:：]\s*(?P<value>.*)$"
)


def _norm(text: str) -> str:
    return re.sub(r"[\s·/|]+", "", str(text or "")).lower()


def _body(text: str) -> str:
    """`## Final Report` 아래만. 없으면 전체."""
    found = _HEADING_RE.search(text or "")
    if not found:
        return text or ""
    rest = text[found.end():]
    # 다음 같은 수준 머리말 전까지
    nxt = re.search(r"^#{1,6}\s+\S", rest, re.M)
    return rest[: nxt.start()] if nxt else rest


def parse(text: str) -> dict:
    """Final Report 를 dict 로. 못 찾은 항목은 **없는 채로** 둔다.

    `{"fields": {...}, "found": [...], "missing": [...], "hasHeading": bool}`
    """
    body = _body(text or "")
    wanted = {}
    for key, label, aliases in FIELDS:
        wanted[_norm(label)] = key
        for alias in aliases:
            wanted.setdefault(_norm(alias), key)

    fields: dict[str, str] = {}
    for line in body.splitlines():
        found = _LINE_RE.match(line)
        if not found:
            continue
        key = wanted.get(_norm(found.group("name")))
        if not key or key in fields:
            continue  # 처음 나온 값을 믿는다
        value = found.group("value").strip().strip("*_` ")
        if value:
            fields[key] = value

    keys = [key for key, _, _ in FIELDS]
    return {
        "fields": fields,
        "found": [k for k in keys if k in fields],
        "missing": [k for k in keys if k not in fields],
        "hasHeading": bool(_HEADING_RE.search(text or "")),
    }


def missing_fields(text: str) -> list[str]:
    """빠진 항목의 **사람이 읽는 이름**. 다시 물을 때 그대로 쓴다."""
    names = {key: label for key, label, _ in FIELDS}
    return [names[key] for key in parse(text)["missing"]]


def success_of(report: dict) -> bool | None:
    """"성공 기준 충족 여부" 를 참·거짓으로. 못 읽으면 `None`.

    **`None` 을 참으로 바꾸지 않는다.** 모르면 모른다고 해야 오케스트레이터가
    `result.csv` 쪽 판정과 대조해서 어긋남을 찾아낼 수 있다.
    """
    value = (report.get("fields") or {}).get("success")
    if not value:
        return None
    text = str(value).lower()
    # 부정이 먼저다 — "미충족" 안에 "충족" 이 들어 있다.
    if any(word in text for word in NO_WORDS):
        return False
    if any(word in text for word in YES_WORDS):
        return True
    return None
