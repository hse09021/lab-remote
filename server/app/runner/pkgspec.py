"""📦 설치할 패키지 목록 검증 — **이름과 버전만** 받는다.

Conda 화면(7단계)에서 사람이 고른 패키지를 lab.remote 가 사용자 권한으로
설치한다. 그래서 입력 칸에 들어간 글자가 명령에 섞이지 않게 여기서 막는다.

```json
{ "version": 1,
  "packages": [ {"name": "peft", "spec": "==0.13.2"}, {"name": "accelerate"} ],
  "reason": "LoRA 어댑터를 쓰려고요" }
```

받지 않는 것: 명령 문자열 · URL · 저장소 주소 · 로컬 경로 · 인덱스 옵션 ·
`-e` · 파일 이름. 하나라도 섞이면 **전체를 거부**한다 — 일부만 걸러서
"고쳐 준" 목록을 설치하면 사람이 본 것과 다른 게 설치된다.

## 왜 `--only-binary=:all:` 이 기본인가

소스 배포(sdist)는 설치할 때 `setup.py` 를 **실행**한다. 휠은 풀어 넣기만
한다. 그래서 기본은 휠만이고, 소스가 필요하면 `allowSource: true` 를 따로
켜야 한다.
"""

from __future__ import annotations

import hashlib
import json
import re

__all__ = [
    "SpecError",
    "MAX_PACKAGES",
    "NAME_RE",
    "SPEC_RE",
    "FORBIDDEN_NAMES",
    "BAD_SUBSTRINGS",
    "parse",
    "requirements",
    "fingerprint",
    "summary",
]


class SpecError(ValueError):
    """요청이 규칙에 안 맞는다. **아무것도 설치하지 않는다.**"""


#: 한 번에 받을 수 있는 개수. 많으면 사람이 눈으로 못 본다.
MAX_PACKAGES = 20

#: PyPI 이름 규칙(PEP 508)보다 **좁게** 둔다. 좁혀서 생기는 불편은 사람이
#: 직접 설치하면 되고, 넓혀서 생기는 구멍은 되돌릴 수 없다.
NAME_RE = re.compile(r"^[A-Za-z][A-Za-z0-9._-]{0,63}$")

#: 버전 지정. 비어 있으면 최신을 받는다.
SPEC_RE = re.compile(r"^(==|>=|<=|~=|!=|<|>)[0-9][0-9A-Za-z.*+!-]{0,31}$")

#: 추가 기능(extras). `peft[torch]` 꼴.
EXTRAS_RE = re.compile(r"^[a-z0-9][a-z0-9,_-]{0,63}$")

#: 설치하면 안 되는 것.
#:
#: `pip`·`setuptools`·`wheel` 은 **설치 도구 자신**이다 — 바꿔치기하면 다음
#: 설치가 임의 코드가 된다. `conda` 는 환경 자체를 고친다. `claude`·
#: `anthropic` 은 사용자가 설치해 둔 Claude Code 를 바꿔치기하지 않으려는 것이다.
FORBIDDEN_NAMES = frozenset(
    {"pip", "setuptools", "wheel", "pkg-resources", "conda", "mamba", "micromamba",
     "claude", "claude-code", "anthropic"}
)

#: 이름·버전에 들어 있으면 거부. 셸·URL·경로·옵션의 흔적이다.
#:
#: `<`·`>` 는 **일부러 빼 뒀다** — `>=0.13` 같은 정상 버전 지정에 들어간다.
#: 리다이렉트로 쓰일 걱정은 `NAME_RE`·`SPEC_RE`·`EXTRAS_RE` 가 **앵커된
#: 화이트리스트**라 없다 (그 셋을 지나가지 못한다). 여기 목록은 그 위의 한 겹이다.
BAD_SUBSTRINGS = (
    "/", "\\", ":", "@", ";", "&", "|", "$", "`", "(", ")", "'", '"',
    "..", "--", "git+", "http", "file:", ".whl", ".tar.gz", ".zip", "%", "\n", "\t",
    " ",
)


def _clean(label: str, value: str, *, allow_empty: bool = False) -> str:
    text = str(value or "").strip()
    if not text:
        if allow_empty:
            return ""
        raise SpecError(f"{label} 이 비어 있어요")
    if text != str(value):
        # 앞뒤 공백을 말없이 지우지 않는다 — 요청과 승인 내용이 달라진다.
        raise SpecError(f"{label} 앞뒤에 공백이 있어요: {value!r}")
    if any(bad in text for bad in BAD_SUBSTRINGS):
        raise SpecError(
            f"{label}에 쓸 수 없는 글자가 있어요: {text!r} · "
            "이름과 버전만 받아요 (URL·경로·옵션은 안 돼요)"
        )
    return text


def _one(item, index: int) -> dict:
    if not isinstance(item, dict):
        raise SpecError(f"{index + 1}번째 항목이 객체가 아니에요: {item!r}")
    unknown = sorted(set(item) - {"name", "spec", "extras"})
    if unknown:
        raise SpecError(f"{index + 1}번째 항목에 모르는 칸이 있어요: {', '.join(unknown)}")

    name = _clean(f"{index + 1}번째 이름", item.get("name"))
    if not NAME_RE.match(name):
        raise SpecError(
            f"패키지 이름 규칙에 안 맞아요: {name!r} · 영문으로 시작하고 "
            "영문·숫자·`.`·`_`·`-` 만 쓸 수 있어요"
        )
    if name.lower() in FORBIDDEN_NAMES:
        raise SpecError(
            f"{name} 은 설치하지 않아요 — 설치 도구나 환경 자체를 바꿔요"
        )

    spec = _clean(f"{index + 1}번째 버전", item.get("spec"), allow_empty=True)
    if spec and not SPEC_RE.match(spec):
        raise SpecError(
            f"버전 지정 규칙에 안 맞아요: {spec!r} · `==1.2.3`처럼 비교 연산자와 "
            "숫자로 시작해야 해요"
        )

    extras = _clean(f"{index + 1}번째 extras", item.get("extras"), allow_empty=True)
    if extras and not EXTRAS_RE.match(extras):
        raise SpecError(f"extras 규칙에 안 맞아요: {extras!r}")

    return {"name": name, "spec": spec, "extras": extras}


def parse(data) -> dict:
    """요청을 검증해 **정규화된 dict**로. 하나라도 어긋나면 `SpecError`.

    돌려주는 것: `{"packages": [...], "reason": str, "allowSource": bool}`
    """
    if not isinstance(data, dict):
        raise SpecError("요청이 JSON 객체가 아니에요")
    unknown = sorted(set(data) - {"version", "packages", "reason", "allowSource"})
    if unknown:
        raise SpecError(f"모르는 칸이 있어요: {', '.join(unknown)}")

    version = data.get("version", 1)
    if version not in (1, "1"):
        raise SpecError(f"모르는 판이에요: {version!r} (아는 건 1 이에요)")

    items = data.get("packages")
    if not isinstance(items, list) or not items:
        raise SpecError("packages 가 비어 있어요")
    if len(items) > MAX_PACKAGES:
        raise SpecError(
            f"한 번에 {MAX_PACKAGES}개까지만 받아요 (받은 것 {len(items)}개) · "
            "사람이 눈으로 볼 수 있는 양이어야 해요"
        )

    seen: dict[str, dict] = {}
    for index, item in enumerate(items):
        got = _one(item, index)
        key = got["name"].lower().replace("_", "-")
        if key in seen and seen[key] != got:
            raise SpecError(
                f"같은 패키지를 다르게 두 번 적었어요: {got['name']} · "
                f"{seen[key]['spec']!r} vs {got['spec']!r}"
            )
        seen[key] = got

    reason = str(data.get("reason") or "").strip()
    if len(reason) > 500:
        reason = reason[:500] + "…"

    allow_source = data.get("allowSource", False)
    if not isinstance(allow_source, bool):
        raise SpecError("allowSource 는 true/false 여야 해요")

    return {
        "packages": [seen[k] for k in sorted(seen)],
        "reason": reason,
        "allowSource": allow_source,
    }


def requirements(parsed: dict) -> list[str]:
    """`pip`에 넘길 인자. **셸을 거치지 않는다** (`shell=False`)."""
    out = []
    for item in parsed["packages"]:
        extras = f"[{item['extras']}]" if item.get("extras") else ""
        out.append(f"{item['name']}{extras}{item.get('spec') or ''}")
    return out


def fingerprint(parsed: dict) -> str:
    """같은 요청인지 가르는 지문. 승인·중복 판정에 쓴다.

    `reason` 은 **넣지 않는다** — 사유를 고쳐 같은 설치를 다시 승인받게
    만드는 길을 막는다.
    """
    body = json.dumps(
        {"packages": parsed["packages"], "allowSource": parsed["allowSource"]},
        sort_keys=True, ensure_ascii=False, separators=(",", ":"),
    )
    return "sha256:" + hashlib.sha256(body.encode("utf-8")).hexdigest()[:32]


def summary(parsed: dict) -> str:
    """사람이 승인할 때 보는 한 줄."""
    names = ", ".join(requirements(parsed))
    tail = " · 소스 배포 허용 요청" if parsed["allowSource"] else ""
    return f"{len(parsed['packages'])}개: {names}{tail}"
