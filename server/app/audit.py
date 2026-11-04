"""📒 승인 기록의 **진본** — `server/data/audit/<프로젝트>.jsonl`.

## 왜 여기인가

프로젝트 안의 `logs/Approval_log.csv` 는 **AI 가 쓴 코드가 고칠 수
있습니다.** 샌드박스는 작업 디렉터리 쓰기를 못 막고(**M4**) 좁힐 수도
없습니다(`denyWrite` 키가 없습니다). 훅은 도구 호출만 보므로
`python x.py` 안의 `open(..., "w")` 를 못 막습니다.

반대로 `server/data/` 는

| | 샌드박스 | `server/data/audit/` 쓰기 |
|---|---|---|
| **훅** | **밖** (M1) | **된다** — `allowWrite` 에 아무것도 안 열어도 됩니다 |
| AI 가 쓴 코드 | 안 | **안 된다** (M1b · 조용히 버려집니다) |
| 학습 프로세스 | bwrap | **안 된다** (`--tmpfs <server>`) |

그래서 훅이 **여기에 진본을 쓰고**, 프로젝트의 CSV 는 사람이 보고 git 에
남는 **사본**으로 둡니다.

## 왜 해시 체인 + 앵커가 아닌가

원래 계획은 CSV 를 진본으로 두고 줄마다 앞 줄 해시를 넣는 **체인**과
`lab.db` **앵커**로 변조를 탐지하는 방식이었습니다. 비교하면:

| | 체인 + 앵커 | 서버 쪽 진본 (이것) |
|---|---|---|
| 위조 **탐지** | 가능 | 가능 |
| 위조 **복원** | **불가** — 원본 내용을 모릅니다 | **가능** — 진본에서 CSV 를 다시 만듭니다 |
| 필요한 것 | 체인 계산 · 앵커 · CSV 헤더 판 올림 · 대조 | append 한 곳 · 대조 |

체인의 유일한 장점은 "CSV 가 자기 검증적이라 다른 기계로 옮겨도 검사
가능" 인데, 개인 서버 한 대에서는 값이 없습니다.

## 무결성의 근거는 M1b 하나입니다

줄마다 HMAC 서명을 넣는 것도 생각했지만 **막는 것이 없습니다.** AI 는 이
폴더에 못 씁니다. 사용자 권한으로 임의 코드를 돌릴 수 있는 상대라면
`lab.db` 와 서명 키도 함께 고칠 수 있어서 어떤 설계도 막지 못합니다.
`grants/`·`anchors` 가 이미 같은 근거 위에 서 있으므로 그 하나를 더 쓰는 것이
맞습니다 — 보호막을 겹쳐 보이게 만들지 않습니다.

## 훅 경로다

**표준 라이브러리만** 씁니다. `sqlite3`·`yaml` 을 import 하지 않습니다
(`tests/test_stdlib_only.py` 가 강제합니다).
"""

from __future__ import annotations

import fcntl
import json
import os

from . import paths, registry

__all__ = [
    "FIELDS",
    "audit_dir",
    "audit_path",
    "append",
    "read",
    "csv_rows",
    "compare",
    "describe",
    "seed",
    "rebuild",
]

#: 진본 한 줄의 칸. `approval_log.COLUMNS` 와 **같은 순서**로 맞춘다 —
#: CSV 를 다시 만들 수 있어야 한다.
FIELDS = ("time", "action", "request", "result", "resultPending", "handledBy", "toolUseId")


def audit_dir() -> str:
    return os.path.join(registry.data_dir(), "audit")


def audit_path(project: str) -> str:
    """`<data>/audit/<프로젝트>.jsonl`."""
    return os.path.join(audit_dir(), registry.valid_name(project) + ".jsonl")


def append(project: str, row: dict) -> bool:
    """한 줄을 덧붙인다. **한 번의 `write()`** 라 동시에 써도 섞이지 않는다.

    어떤 이유로도 예외를 올리지 않는다 — 진본을 못 써도 판정은 계속해야
    한다(막는 것이 먼저다). 못 쓴 것은 `compare` 가 "CSV 에만 있는 줄" 로
    잡아낸다.
    """
    try:
        path = audit_path(project)
        os.makedirs(os.path.dirname(path), exist_ok=True)
        body = {key: row.get(key) for key in FIELDS}
        line = (json.dumps(body, ensure_ascii=False, sort_keys=True) + "\n").encode("utf-8")
        fd = os.open(path, os.O_WRONLY | os.O_APPEND | os.O_CREAT, 0o644)
        try:
            fcntl.flock(fd, fcntl.LOCK_EX)
            os.write(fd, line)
        finally:
            fcntl.flock(fd, fcntl.LOCK_UN)
            os.close(fd)
        return True
    except Exception:
        return False


def read(project: str) -> list[dict]:
    """진본 전체. 깨진 줄은 건너뛰고 `None` 대신 빈 문자열로 맞춘다."""
    out: list[dict] = []
    try:
        with open(audit_path(project), encoding="utf-8") as fh:
            lines = fh.read().splitlines()
    except (OSError, ValueError):
        return out
    for line in lines:
        text = line.strip()
        if not text:
            continue
        try:
            got = json.loads(text)
        except ValueError:
            continue
        if isinstance(got, dict):
            out.append({key: "" if got.get(key) is None else str(got.get(key)) for key in FIELDS})
    return out


def csv_rows(project: str) -> list[list[str]]:
    """진본을 CSV 행 모양으로. `approval_log` 가 이걸로 사본을 다시 만든다."""
    return [[row[key] for key in FIELDS] for row in read(project)]


def _read_csv(path: str) -> list[list[str]]:
    import csv as csv_mod

    try:
        with open(path, encoding="utf-8", newline="") as fh:
            rows = list(csv_mod.reader(fh))
    except (OSError, ValueError):
        return []
    # 헤더를 걷어낸다
    if rows and rows[0] and rows[0][0] == FIELDS[0]:
        rows = rows[1:]
    return [[str(c) for c in row] for row in rows if any(str(c).strip() for c in row)]


def compare(project: str, csv_path: str) -> dict:
    """진본과 사본을 **줄 단위로** 맞춰 본다. 아무것도 고치지 않는다.

    돌려주는 것:
        ok          같은가
        truth       진본 줄 수
        copy        사본 줄 수
        changed     내용이 다른 줄 (`[(번호, 진본, 사본), …]`)
        missing     진본에만 있는 줄 (사본에서 **지워졌다**)
        extra       사본에만 있는 줄 (사본에 **끼워 넣었다**)
    """
    truth = csv_rows(project)
    copy = _read_csv(csv_path)
    out = {
        "ok": False,
        "project": project,
        "csv": csv_path,
        # 진본 파일이 **아예 없다** = 이 기능이 생기기 전의 프로젝트다.
        # 지난 기록을 되짚어 검증할 방법이 없으므로 사람이 한 번
        # `labremote audit <프로젝트> --seed` 로 지금 사본을 출발점으로 삼는다.
        "missingTruth": not os.path.exists(audit_path(project)),
        "truth": len(truth),
        "copy": len(copy),
        "changed": [],
        "missing": [],
        "extra": [],
    }
    for index in range(min(len(truth), len(copy))):
        if truth[index] != copy[index]:
            out["changed"].append((index + 1, truth[index], copy[index]))
    if len(truth) > len(copy):
        out["missing"] = truth[len(copy):]
    elif len(copy) > len(truth):
        out["extra"] = copy[len(truth):]
    # 진본이 없고 사본도 비어 있으면 **대조할 것이 없다** — 아직 승인 기록이
    # 하나도 없는 새 프로젝트다. 막을 이유가 없다.
    if out["missingTruth"] and not copy:
        out["missingTruth"] = False
    out["ok"] = not (
        out["missingTruth"] or out["changed"] or out["missing"] or out["extra"]
    )
    return out


def describe(report: dict) -> str:
    """알림·CLI 에 쓸 한 덩어리 글."""
    if report.get("ok"):
        return f"승인 기록이 진본과 같아요 ({report.get('truth', 0)}줄)."
    if report.get("missingTruth"):
        return (
            f"승인 기록의 진본이 아직 없어요 (사본 {report.get('copy')}줄) — "
            "이 기능이 생기기 전의 프로젝트예요. 지난 기록은 되짚어 검증할 수 "
            "없으니, 지금 사본을 출발점으로 삼아 주세요: "
            f"labremote audit {report.get('project')} --seed"
        )
    lines = [
        "승인 기록이 진본과 달라요 — "
        f"진본 {report.get('truth')}줄 · 사본 {report.get('copy')}줄:"
    ]
    for number, truth, copy in (report.get("changed") or [])[:5]:
        lines.append(f"  · {number}번째 줄이 달라요")
        lines.append(f"      진본: {truth}")
        lines.append(f"      사본: {copy}")
    if report.get("missing"):
        lines.append(f"  · 사본에서 {len(report['missing'])}줄이 지워졌어요")
    if report.get("extra"):
        lines.append(f"  · 사본에 {len(report['extra'])}줄이 끼워져 있어요")
    lines.append(
        "진본은 server/data/audit/ 에 있고 AI 가 쓴 코드는 거기에 못 써요(M1b). "
        "labremote audit <프로젝트> --rebuild 로 사본을 다시 만들 수 있어요."
    )
    return "\n".join(lines)


def seed(project: str, csv_path: str) -> dict:
    """사본을 **출발점으로** 삼아 진본을 만든다. 사람이 한 번만 부른다.

    이 기능이 생기기 전의 프로젝트에는 CSV 기록만 있다. 지난 줄들을 되짚어
    검증할 방법이 없으므로 "지금 이것이 진본이다" 를 사람이 선언한다 —
    `labremote tools --accept` 와 같은 성질이다.

    **진본이 이미 있으면 거절한다.** 덮어쓰게 두면 "진본을 지우고 위조된
    사본으로 다시 만드는" 길이 생긴다 (AI 는 `server/data` 에 못 쓰지만,
    사람이 실수로 부르는 것도 막는다).
    """
    path = audit_path(project)
    if os.path.exists(path):
        return {
            "ok": False, "rows": 0,
            "reason": f"진본이 이미 있어요: {path} · 덮어쓰지 않아요",
        }
    rows = _read_csv(csv_path)
    for row in rows:
        if not append(project, dict(zip(FIELDS, row))):
            return {"ok": False, "rows": 0, "reason": "진본을 쓰지 못했어요"}
    if not rows:
        # 빈 사본이어도 진본 파일은 만들어 둔다 (다음부터 `missingTruth` 가 거짓)
        try:
            os.makedirs(os.path.dirname(path), exist_ok=True)
            open(path, "a", encoding="utf-8").close()
        except OSError as exc:
            return {"ok": False, "rows": 0, "reason": str(exc)}
    return {"ok": True, "rows": len(rows), "reason": ""}


def rebuild(project: str, csv_path: str) -> dict:
    """진본으로 사본을 **다시 만든다.** 사람·오케스트레이터만 부른다.

    훅은 이걸 부르지 않는다 — 훅이 프로젝트 파일을 통째로 덮어쓰는 길을
    만들지 않는다.
    """
    import csv as csv_mod
    import io

    truth = csv_rows(project)
    target = paths.real(csv_path)

    # ⚠ 줄 끝이 섞여 있다 — `approval_log.ensure_log` 는 헤더를 csv
    # 기본값(`\r\n`)으로 쓰고 `append_row` 는 줄을 `\n` 으로 쓴다. 그 모양이
    # 지금 파일의 모양이므로 **그대로 다시 만든다.** 바꾸면 바이트가 달라져
    # 대조가 영원히 어긋난다.
    #
    # 있던 헤더를 그대로 쓰지 **않는다** — 위조된 파일의 헤더를 보존하게 된다.
    head = io.StringIO()
    csv_mod.writer(head).writerow(list(FIELDS))
    header = head.getvalue().encode("utf-8")

    body = io.StringIO()
    csv_mod.writer(body, lineterminator="\n").writerows(truth)

    try:
        os.makedirs(os.path.dirname(target) or ".", exist_ok=True)
        tmp = target + ".rebuild"
        with open(tmp, "wb") as fh:
            fh.write(header)
            fh.write(body.getvalue().encode("utf-8"))
        os.replace(tmp, target)
    except OSError as exc:
        return {"ok": False, "rows": 0, "reason": str(exc)}
    return {"ok": True, "rows": len(truth), "reason": ""}
