"""Discord 임베드 조립 — **표준 라이브러리만.**

`app/notifier.py` 와 훅이 같은 모양을 쓰게 하려고 따로 뺐다. notifier 는
SQLite 를 보지만 훅은 못 본다(`tests/test_stdlib_only.py`). 그래서 모양을
만드는 부분만 여기 둔다.

임베드로 보내는 이유는 하나다 — **훅이 쓴 사유를 자르지 않으려고.** 평문
`content` 는 2000자 제한이라 ①에서 사유가 잘렸다. 임베드 필드는 1024자씩
나눠 담을 수 있다.
"""

from __future__ import annotations

__all__ = ["COLORS", "build"]

#: 임베드 왼쪽 띠 색. 목업의 tone 과 뜻을 맞춘다.
COLORS = {
    "approval": 0xF0B429,
    "start": 0x4C6EF5,
    "done": 0x37B24D,
    "failure": 0xE03131,
    "usage_limit": 0xF0B429,
    "driver": 0xE03131,
    "gpu": 0xF0B429,
    "recovery": 0x37B24D,
    "blocked": 0xE03131,
    "test": 0x868E96,
}

DESC_MAX = 4000
FIELD_MAX = 1024
FIELDS_MAX = 25
FOOTER_MAX = 2048


#: 잘렸다는 표시. **조용히 자르지 않는다** — 사람이 끝을 봤다고 믿으면
#: 못 본 뒷부분까지 승인하게 된다 (9단계 1번).
TRUNC_MARK = " … (잘렸어요)"
TRUNC_FIELD = "⚠ 여기서 잘렸어요"


def _trunc_note(dropped: int) -> str:
    return (
        f"길어서 {dropped}칸이 안 들어갔어요. **전문을 보고 승인해 주세요**:\n"
        "`labremote approvals show <프로젝트> <요청ID>`"
    )


def _chunk(text: str, limit: int) -> list[str]:
    """긴 값을 여러 필드로 나눈다. **자르지 않는다.**"""
    text = text or ""
    return [text[i : i + limit] for i in range(0, len(text), limit)] or [""]


def build(
    kind: str,
    *,
    project: str = "",
    title: str,
    body: str = "",
    fields=None,
    footer: str = "",
    at: str = "",
) -> dict:
    """Discord 웹훅에 보낼 payload 한 덩어리."""
    embed: dict = {
        "title": f"{title} · {project}" if project else title,
        "color": COLORS.get(kind, 0x868E96),
    }
    if body:
        # 잘렸으면 **잘렸다고 말한다.** 조용히 자르면 사람이 끝을 봤다고
        # 믿는다 (9단계 1번에서 승인 화면이 그랬다).
        embed["description"] = (
            body if len(body) <= DESC_MAX else body[: DESC_MAX - len(TRUNC_MARK)] + TRUNC_MARK
        )
    out: list[dict] = []
    for name, value in fields or []:
        parts = _chunk(str(value), FIELD_MAX)
        for index, part in enumerate(parts):
            out.append(
                {
                    "name": name if index == 0 else f"{name} ({index + 1})",
                    "value": part or "—",
                    "inline": False,
                }
            )
    if out:
        # 🔑 필드 수 상한에서 **조용히 사라지는 것**이 있었다. 승인 알림이면
        # 그 사라진 조각에 위험한 꼬리가 들어 있을 수 있다. 마지막 칸을 비워
        # "잘렸다 + 전문은 어디서 보나" 를 싣는다.
        if len(out) > FIELDS_MAX:
            dropped = len(out) - (FIELDS_MAX - 1)
            out = out[: FIELDS_MAX - 1]
            out.append({"name": TRUNC_FIELD, "value": _trunc_note(dropped), "inline": False})
        embed["fields"] = out
    if footer:
        embed["footer"] = {"text": footer[:FOOTER_MAX]}
    if at:
        embed["timestamp"] = at
    return {"embeds": [embed]}
