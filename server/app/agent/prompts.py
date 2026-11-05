"""루프 프롬프트 렌더.

`app/templates/prompts/loop/*.md` 를 `string.Template` 로 채운다.
**`safe_substitute` 는 쓰지 않는다** — 빠진 키에서 예외가 나야 `$next_exp` 가
그대로 Claude 에게 새어 나가지 않는다 (생성기의 `render.py` 와 같은 원칙).

`app/templates/prompts/*.md`(한 단계 위)는 **사람이 읽는 참고 프롬프트**다.
거기는 `{중괄호}` 를 쓰고 코드가 읽지 않는다. 섞이지 않게 폴더를 나눴다.
"""

from __future__ import annotations

import os
from string import Template

__all__ = ["PROMPTS", "COMMON_RULES", "prompts_dir", "read", "render"]

#: 루프가 쓰는 프롬프트. 이름이 곧 파일 이름이다.
PROMPTS = ("loop_plan", "loop_review", "resume_after_approval", "fill_missing_journal")


#: 네 프롬프트 **전부**에 붙는 꼬리. 한 군데만 고치면 되게 모아 둔다.
#:
#: 왜 필요한가 (9단계 1번 실측, 2026-11-05): 첫 설계 세션이 참고 문서를
#: 한 번에 읽으려고 셸 `for f in …; do cat "$f"; done` 을 썼다. `bashparse`
#: 는 `for` 를 모르므로 `unclassified` → `ask` → **헤드리스에서 거부**다.
#: 읽기만 하는 명령 하나 때문에 루프가 첫 걸음에서 멈추고 사람의 승인을
#: 기다렸다. 그리고 다음 루프에서도 똑같이 멈춘다.
#:
#: 판정 쪽을 넓히지 않고 **프롬프트로** 푼다 — `Read` 도구는 이미 허용이고
#: 읽기 전용이라 게이트를 약하게 만들 이유가 없다.
COMMON_RULES = """

## 도구를 쓰는 방식 (이걸 지키면 안 멈춰요)

- **파일은 `Read` 도구로 읽어 주세요.** 셸로 `cat` 을 여러 번 묶지 마세요 —
  특히 `for f in …; do cat "$$f"; done` 은 제가 무엇을 건드리는지 알 수 없어서
  **승인 대기로 멈춰요.** 여러 파일은 `Read` 를 여러 번 부르면 돼요.
- 파일을 찾을 때도 셸 반복문 대신 도구를 쓰세요.
- `$$(…)`·백틱·`for`·`while` 이 들어간 Bash 는 분류가 안 돼서 멈춰요.
- 막혔으면 **다른 명령으로 돌아가지 말고** 그대로 멈추고 보고해 주세요.
  사람이 승인하면 제가 같은 자리에서 이어 가요.
"""

def prompts_dir() -> str:
    here = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    return os.path.join(here, "templates", "prompts", "loop")


def read(name: str) -> str:
    if name not in PROMPTS:
        raise KeyError(f"모르는 프롬프트예요: {name!r} · 있는 것: {', '.join(PROMPTS)}")
    with open(os.path.join(prompts_dir(), f"{name}.md"), encoding="utf-8") as fh:
        return fh.read()


def render(name: str, values: dict) -> str:
    """빠진 키가 있으면 `KeyError` 다. 자리표시가 새어 나가지 않게.

    `COMMON_RULES` 를 **꼬리에 붙인다** — 네 프롬프트가 같은 규칙을 쓰고,
    한 군데만 고치면 된다.
    """
    body = read(name) + COMMON_RULES
    return Template(body).substitute({k: str(v) for k, v in values.items()})
