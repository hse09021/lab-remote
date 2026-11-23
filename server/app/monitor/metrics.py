"""`result.csv`를 읽고 **이상을 감지**한다.

지표의 출처는 `experiments/EXP-NNN/result.csv` 다 (W&B는 ② 범위 밖).
열 규약은 생성기가 AI에게 주는 `templates/result_example.csv` 다.

    step,split,metric,value

긴 형식이다. 넓은 형식(`epoch,train_loss,val_loss`)도 읽어 주지만 **경고를
남긴다** — 조용히 둘 다 받아 주면 규약이 흐려지고, 어느 쪽인지 모른 채
그래프가 비어 보이는 게 제일 나쁘다.

### 이상 감지 (spec III-4)

| 이상 | 기본 규칙 | 행동 |
|---|---|---|
| NaN / Inf | 한 번이라도 | **즉시 중단** |
| 발산 | 최근 5개가 연속으로 초기값 × 3 초과 | 중단 |
| OOM 반복 | 로그에 `CUDA out of memory`가 2회 | 중단 |
| 진전 없음 | 로그 mtime이 900초 동안 그대로 | 알림만 |
| 디스크 부족 | 여유 < 10GB | 큐 정지 |

`Config.yaml`의 `monitor:`로 덮어쓴다.
"""

from __future__ import annotations

import csv
import math
import os
import re

__all__ = [
    "DEFAULTS",
    "OOM_RE",
    "read_result",
    "series_of",
    "find_anomalies",
    "scan_log",
]

#: 기본 임계값. `Config.yaml`의 `monitor:`가 이긴다.
DEFAULTS = {
    "divergeFactor": 3.0,
    "divergeWindow": 5,
    "oomRepeat": 2,
    "stalledSec": 900,
    "diskFreeGb": 10.0,
}

#: 로그에서 찾는 말
OOM_RE = re.compile(r"CUDA out of memory|out of memory|CUBLAS_STATUS_ALLOC_FAILED", re.I)
NAN_RE = re.compile(r"\b(nan|inf|-inf)\b", re.I)

#: 넓은 형식에서 split을 가르는 접두사
WIDE_SPLITS = (("train_", "train"), ("val_", "val"), ("valid_", "val"), ("test_", "test"))

LONG_HEADER = ("step", "split", "metric", "value")


def _to_float(text):
    text = str(text if text is not None else "").strip()
    if not text:
        return None, None
    try:
        number = float(text)
    except ValueError:
        return None, "nan" if NAN_RE.search(text) else None
    if math.isnan(number):
        return None, "nan"
    if math.isinf(number):
        return None, "inf" if number > 0 else "-inf"
    return number, None


def read_result(path: str) -> dict:
    """`result.csv`를 읽는다. 없거나 깨졌으면 정상 반환 (던지지 않는다).

    `{"ok", "format", "rows", "warnings", "reason"}`. `rows`는
    `{"step", "split", "metric", "value", "flag"}`로 **정규화**한 것이다.
    """
    try:
        with open(path, encoding="utf-8", newline="") as fh:
            table = list(csv.reader(fh))
    except OSError as exc:
        return {"ok": False, "reason": str(exc), "format": "none", "rows": [], "warnings": []}
    if not table:
        return {"ok": True, "reason": "", "format": "none", "rows": [], "warnings": []}

    header = [c.strip() for c in table[0]]
    lower = [c.lower() for c in header]
    warnings: list[str] = []

    if tuple(lower[:4]) == LONG_HEADER:
        rows = _read_long(table[1:], warnings)
        return {"ok": True, "reason": "", "format": "long", "rows": rows, "warnings": warnings}

    if lower and lower[0] in ("step", "epoch", "iter", "iteration"):
        warnings.append(
            "result.csv가 넓은 형식이에요(열마다 지표). 규약은 "
            "templates/result_example.csv의 step,split,metric,value예요."
        )
        rows = _read_wide(header, table[1:], warnings)
        return {"ok": True, "reason": "", "format": "wide", "rows": rows, "warnings": warnings}

    return {
        "ok": False,
        "reason": f"result.csv의 열을 읽지 못했어요: {header}",
        "format": "unknown",
        "rows": [],
        "warnings": warnings,
    }


def _read_long(body, warnings: list[str]) -> list[dict]:
    rows: list[dict] = []
    for index, raw in enumerate(body, start=2):
        if not raw or not any(c.strip() for c in raw):
            continue
        if len(raw) < 4:
            warnings.append(f"{index}번째 줄에 칸이 모자라요: {raw}")
            continue
        step, _ = _to_float(raw[0])
        value, flag = _to_float(raw[3])
        rows.append(
            {
                "step": int(step) if step is not None else None,
                "split": raw[1].strip(),
                "metric": raw[2].strip(),
                "value": value,
                "flag": flag,
            }
        )
    return rows


def _read_wide(header: list[str], body, warnings: list[str]) -> list[dict]:
    rows: list[dict] = []
    for raw in body:
        if not raw or not any(c.strip() for c in raw):
            continue
        step, _ = _to_float(raw[0])
        for column, cell in zip(header[1:], raw[1:]):
            name = column.strip()
            split = ""
            for prefix, mapped in WIDE_SPLITS:
                if name.lower().startswith(prefix):
                    split, name = mapped, name[len(prefix):]
                    break
            value, flag = _to_float(cell)
            rows.append(
                {
                    "step": int(step) if step is not None else None,
                    "split": split,
                    "metric": name,
                    "value": value,
                    "flag": flag,
                }
            )
    return rows


def series_of(rows: list[dict], metric: str, split: str = "") -> list[dict]:
    """한 지표의 시계열. 들어온 순서를 지킨다 (step이 없을 수도 있다)."""
    out = []
    for row in rows:
        if row["metric"].lower() != metric.lower():
            continue
        if split and row["split"].lower() != split.lower():
            continue
        out.append(row)
    return out


def scan_log(lines) -> dict:
    """로그 줄에서 찾을 것. OOM 횟수와 그 줄."""
    hits = [line for line in lines if OOM_RE.search(line)]
    return {"oom": len(hits), "oomLines": hits[-5:]}


def find_anomalies(
    rows: list[dict],
    *,
    metric: str = "loss",
    split: str = "train",
    oom_count: int = 0,
    stalled_sec: float = 0.0,
    disk_free_gb: float | None = None,
    config: dict | None = None,
) -> list[dict]:
    """찾은 이상들. 각각 `{"kind","action","text"}`.

    `action`은 `stop`(즉시 중단) · `pause`(큐 정지) · `notify`(알림만) 다.
    **판정만 한다** — 멈추는 건 오케스트레이터의 일이다.
    """
    cfg = {**DEFAULTS, **(config or {})}
    out: list[dict] = []

    flagged = [r for r in rows if r.get("flag")]
    if flagged:
        first = flagged[0]
        out.append(
            {
                "kind": "nan",
                "action": "stop",
                "text": (
                    f"지표가 숫자가 아니에요({first['flag']}): "
                    f"{first['split']}/{first['metric']} step {first['step']}"
                ),
            }
        )

    values = [r["value"] for r in series_of(rows, metric, split) if r["value"] is not None]
    window = int(cfg["divergeWindow"])
    factor = float(cfg["divergeFactor"])
    if len(values) > window and values[0] > 0:
        tail = values[-window:]
        if all(v > values[0] * factor for v in tail):
            out.append(
                {
                    "kind": "diverge",
                    "action": "stop",
                    "text": (
                        f"{split}/{metric}가 발산했어요: 처음 {values[0]:.4g} → "
                        f"최근 {window}개가 전부 {values[0] * factor:.4g} 초과"
                    ),
                }
            )

    if oom_count >= int(cfg["oomRepeat"]):
        out.append(
            {
                "kind": "oom",
                "action": "stop",
                "text": f"GPU 메모리가 부족해요 ({oom_count}회). 배치 크기를 줄여야 해요.",
            }
        )

    if disk_free_gb is not None and disk_free_gb < float(cfg["diskFreeGb"]):
        out.append(
            {
                "kind": "disk",
                "action": "pause",
                "text": f"디스크 여유가 {disk_free_gb}GB 뿐이에요 (임계 {cfg['diskFreeGb']}GB)",
            }
        )

    if stalled_sec >= float(cfg["stalledSec"]):
        out.append(
            {
                "kind": "stalled",
                "action": "notify",
                "text": f"로그가 {int(stalled_sec)}초 동안 안 자랐어요",
            }
        )
    return out
