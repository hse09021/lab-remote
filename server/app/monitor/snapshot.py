"""③의 웹 UI 가 읽을 상태 파일.

두 층이다. **SQLite 가 단일 출처**(`server/data/lab.db`)이고, 모니터가
`server/data/status/<프로젝트>.json` 을 원자적으로 쓴다. ③의 FastAPI 가
없어도 화면 데이터가 완성되고, ②가 죽어도 마지막 상태가 남는다.

### 화면 문구를 **서버가 만든다**

목업 계약이 그렇다 — `MetricTileData` 는 `label`·`value`·`sub` 처럼 **문장**을
담는다. 그래서 여기서 한국어 해요체로 채운다 (`CLAUDE.md` 규칙).
키 집합은 `web/src/api/types.ts` 와 `web/src/api/mock/*.json` 이 기준이고,
시험이 그 JSON 을 직접 읽어 대조한다.

### 모르는 값은 지어내지 않는다

`[대괄호 자리표시]` 로 남긴다 (`CLAUDE.md` 규칙). GPU 가 안 보이면
"조회 불가" 이고, W&B 링크는 아직 `[W&B 링크 — 미연결]` 이다.
"""

from __future__ import annotations

import os
from datetime import datetime

from .. import registry
from ..store import events as E
from ..store import experiments as X
from ..store import jobs as J
from ..store import loops as L
from . import gpu as gpu_mod
from . import host as host_mod
from . import metrics as metrics_mod

__all__ = [
    "VERSION",
    "WANDB_PLACEHOLDER",
    "status_path",
    "build",
    "write",
    "read",
]

VERSION = 1

#: 아직 확인 못 한 값 (`CLAUDE.md` 의 자리표시 규칙)
WANDB_PLACEHOLDER = "[W&B 링크 — 미연결]"
CLAUDE_LINK_PLACEHOLDER = "[Claude 앱 딥링크 — 미확인]"

#: 루프 상태 -> 화면 문구
LOOP_LABELS = {
    "idle": "멈춰 있어요",
    "planning": "다음 실험을 설계하는 중",
    "running": "실행 중",
    "reviewing": "결과를 보는 중",
    "waiting_approval": "승인을 기다리는 중",
    "usage_limited": "응답이 막혀 기다리는 중",
    "paused": "멈춤",
    "blocked": "사람 확인이 필요해요",
    "stopped": "종료 조건에 닿아 멈췄어요",
    "done": "끝났어요",
}

#: 사건 tone -> 화면 tone (`EventEntry.tone` 은 셋뿐이다)
EVENT_TONES = {"info": "neutral", "good": "success", "attention": "warn", "bad": "warn"}


def status_path(project: str) -> str:
    return os.path.join(registry.data_dir(), "status", f"{registry.valid_name(project)}.json")


def _tone_for(pct: float | None, *, warn: float = 85.0) -> str:
    if pct is None:
        return "neutral"
    if pct >= warn:
        return "attention"
    if pct >= 60.0:
        return "accent"
    return "neutral"


def _resources(gpu: dict, host: dict) -> list[dict]:
    """`ResourceMeter[]`. **조회 실패도 한 줄로 보여 준다.**"""
    out: list[dict] = []
    device = (gpu.get("devices") or [{}])[0] if gpu.get("available") else {}
    if gpu.get("available") and device:
        util = device.get("utilPct")
        out.append(
            {
                "label": "GPU",
                "pct": int(util or 0),
                "value": f"{int(util or 0)}%",
                "tone": _tone_for(util, warn=95.0),
            }
        )
        used, total = device.get("memUsedMb"), device.get("memTotalMb")
        mem_pct = device.get("memPct")
        out.append(
            {
                "label": "VRAM",
                "pct": int(mem_pct or 0),
                "value": (
                    f"{used / 1024:.1f}/{total / 1024:.0f}G" if used is not None and total else "조회 불가"
                ),
                "tone": _tone_for(mem_pct),
            }
        )
        temp = device.get("tempC")
        if temp is not None:
            out.append(
                {
                    "label": "온도",
                    "pct": int(min(100.0, temp)),
                    "value": f"{int(temp)}°C",
                    "tone": "attention" if temp >= 85 else "neutral",
                }
            )
    else:
        # 실패가 정상 경로다. 화면에 "왜" 가 보여야 한다.
        out.append({"label": "GPU", "pct": 0, "value": "조회 불가", "tone": "attention"})

    cpu = host.get("cpuPct")
    out.append(
        {
            "label": "CPU",
            "pct": int(cpu or 0),
            "value": f"{int(cpu)}%" if cpu is not None else "조회 중",
            "tone": _tone_for(cpu),
        }
    )
    memory = host.get("memory") or {}
    if memory.get("ok"):
        out.append(
            {
                "label": "RAM",
                "pct": int(memory["pct"]),
                "value": f"{memory['usedGb']:.0f}/{memory['totalGb']:.0f}G",
                "tone": _tone_for(memory["pct"]),
            }
        )
    disk = host.get("disk") or {}
    if disk.get("ok"):
        out.append(
            {
                "label": "디스크",
                "pct": int(disk["pct"]),
                "value": f"{disk['freeGb']:.0f}G 여유",
                "tone": "attention" if disk["freeGb"] < metrics_mod.DEFAULTS["diskFreeGb"] else "neutral",
            }
        )
    return out


def _metric_tiles(conn, project: str, running: dict | None, rows: list[dict]) -> list[dict]:
    """`MetricTileData[]`. 아직 아무것도 안 돈 프로젝트도 **빈 화면이 아니게**."""
    out: list[dict] = []
    exp_id = (running or {}).get("experiment_id")
    experiment = X.get(conn, project, exp_id) if exp_id else None

    if experiment:
        progress = experiment.get("progress") or 0
        out.append(
            {
                "label": f"{exp_id} 학습 중",
                "value": str(progress),
                "valueSuffix": " / 100",
                "valueTone": "default",
                "valueVariant": "numeric",
                "sub": "남은 시간은 [예상 시간 — 미구현]",
                "subTone": "muted",
                "progress": progress,
            }
        )
    else:
        counts = J.counts(conn, project)
        waiting = counts.get("queued", 0) + counts.get("leased", 0)
        out.append(
            {
                "label": "지금 돌고 있는 실험",
                "value": "없어요",
                "valueSuffix": None,
                "valueTone": "default",
                "valueVariant": "text",
                "sub": f"대기 {waiting}건" if waiting else "대기 중인 작업도 없어요",
                "subTone": "muted",
                "progress": None,
            }
        )

    latest = metrics_mod.series_of(rows, "loss", "val")
    value = next((r["value"] for r in reversed(latest) if r["value"] is not None), None)
    out.append(
        {
            "label": "최근 val loss",
            "value": f"{value:.4g}" if value is not None else "아직 없어요",
            "valueSuffix": None,
            "valueTone": "default",
            "valueVariant": "numeric" if value is not None else "text",
            "sub": f"{len(latest)}개 기록" if latest else "result.csv 가 아직 비어 있어요",
            "subTone": "muted",
            "progress": None,
        }
    )

    best = max(
        (e for e in X.listing(conn, project) if e.get("best_metric") is not None),
        key=lambda e: e["best_metric"],
        default=None,
    )
    out.append(
        {
            "label": "이번 연구 최고",
            "value": f"{best['best_metric']:.4g}" if best else "아직 없어요",
            "valueSuffix": None,
            "valueTone": "accent" if best else "default",
            "valueVariant": "numeric" if best else "text",
            "sub": f"{best['exp_id']}" if best else "실험이 끝나면 채워져요",
            "subTone": "accent" if best else "muted",
            "progress": None,
        }
    )
    return out


def _learning_curve(rows: list[dict], exp_id: str | None) -> dict:
    """`LearningCurve`. 좌표가 아니라 **loss 값**으로 담는다 (목업 계약)."""
    train = metrics_mod.series_of(rows, "loss", "train")
    val = metrics_mod.series_of(rows, "loss", "val")
    steps = [r["step"] for r in train if r["step"] is not None and r["value"] is not None]
    values = [r["value"] for r in train if r["step"] is not None and r["value"] is not None]
    val_by_step = {r["step"]: r["value"] for r in val if r["value"] is not None}
    val_values = [val_by_step.get(step) for step in steps]
    everything = [v for v in [*values, *[v for v in val_values if v is not None]] if v is not None]
    return {
        "title": f"학습 곡선 · {exp_id}" if exp_id else "학습 곡선",
        "epochs": steps,
        "train": values,
        # 빠진 값은 0 으로 메우지 않는다 — 그리는 쪽이 끊어진 선을 보여야 한다
        "val": [v if v is not None else None for v in val_values],
        "totalEpochs": max(steps) if steps else 0,
        "currentEpoch": steps[-1] if steps else 0,
        "yMax": round(max(everything), 4) if everything else 1.0,
        "wandbHref": WANDB_PLACEHOLDER,
    }


def _approval(pending: list[dict]) -> dict | None:
    """`ApprovalNotice`. 없으면 `null` (목업 계약)."""
    if not pending:
        return None
    first = pending[0]
    actions = first.get("actions") or []
    names = " · ".join(a.get("name") or a.get("action") or "?" for a in actions)
    what = names or first.get("action") or "승인"
    text = f"{what} 을 허용할까요?"
    if len(pending) > 1:
        text += f" 대기 중인 요청이 {len(pending)}건이에요."
    return {
        "count": len(pending),
        "text": text,
        "ctaLabel": "터미널에서 승인하기",
        "ctaHref": CLAUDE_LINK_PLACEHOLDER,
    }


def _experiments(conn, project: str) -> list[dict]:
    """`Experiment[]`. DB 의 실험과 큐를 합쳐 화면 모양으로."""
    queued = [j for j in J.listing(conn, project, states=("queued", "leased")) if j["kind"] == "train"]
    order = {j["experiment_id"]: index + 1 for index, j in enumerate(reversed(queued))}
    out: list[dict] = []
    for row in X.listing(conn, project):
        state = row["state"] if row["state"] in ("running", "done", "failed", "stopped") else "queued"
        out.append(
            {
                "id": row["exp_id"],
                "knob": row.get("knob") or "[조작변인 — 미기록]",
                "knobNote": None,
                "state": state,
                "stateNote": row.get("report") if state == "failed" else None,
                "queuePosition": order.get(row["exp_id"]) if state == "queued" else None,
                "progress": row.get("progress") if state == "running" else None,
                "bestAcc": f"{row['best_metric']:.4g}" if row.get("best_metric") is not None else None,
                "branch": row.get("branch"),
                "commit": (row.get("commit_sha") or "")[:7] or None,
                "report": "analysis.md" if state in ("done", "failed") else None,
                "detail": None,
            }
        )
    return out


def _events(conn, project: str, limit: int = 50) -> list[dict]:
    """`EventEntry[]`. 시각은 화면 표기(`HH:MM`)로 줄인다."""
    out = []
    for row in E.recent(conn, project, limit):
        stamp = str(row.get("at") or "")
        try:
            shown = datetime.fromisoformat(stamp).strftime("%H:%M")
        except ValueError:
            shown = stamp[:5]
        out.append(
            {
                "time": shown,
                "kind": row.get("kind") or "기록",
                "tone": EVENT_TONES.get(row.get("tone") or "info", "neutral"),
                "text": row.get("text") or "",
            }
        )
    return out


def _safe_gpu() -> dict:
    """GPU 조회. `probe()` 가 예상 밖으로 터져도 **스냅샷 전체를 죽이지 않는다.**

    "조회 실패가 정상 경로" 는 예외에도 성립해야 한다. 여기서 터지면 화면이
    통째로 안 갱신되고, 그러면 사람이 아무것도 못 본다.
    """
    try:
        return gpu_mod.probe()
    except Exception as exc:
        return {
            "available": False,
            "reason": f"GPU 조회가 실패했어요: {type(exc).__name__}: {exc}",
            "devices": [],
            "driver": {"ok": False, "mismatch": False, "kernel": "", "userland": "", "reason": str(exc)},
        }


def _safe_host(path: str, before) -> dict:
    try:
        return host_mod.probe(path or ".", before=before)
    except Exception as exc:  # pragma: no cover - /proc 이 없는 환경
        return {
            "cpuPct": None,
            "cpuSample": None,
            "memory": {"ok": False, "reason": str(exc)},
            "disk": {"ok": False, "reason": str(exc)},
            "load": None,
        }


def _mode_label(project: str) -> str:
    """권한 프리셋의 사람 이름. 정책을 못 읽으면 그 사실을 보여 준다."""
    from .. import policy as policy_mod
    from .. import policy_defaults as D

    try:
        mode = policy_mod.load(project).effective_mode()
    except Exception as exc:
        return f"권한 설정을 읽을 수 없어요 ({type(exc).__name__})"
    for item in D.MODES:
        if item["id"] == mode:
            return item["name"]
    return mode


def build(conn, project: str, *, root: str = "", host_before=None, pending=None) -> dict:
    """스냅샷 한 덩어리. **던지지 않는다** — 모니터가 멈추면 안 된다."""
    project_root = root or (registry.root_of(project) or "")
    loop = L.ensure(conn, project)
    running = J.running(conn)
    if running and running.get("project") != project:
        running = None

    gpu = _safe_gpu()
    host = _safe_host(project_root, host_before)

    rows: list[dict] = []
    result_warnings: list[str] = []
    exp_id = (running or {}).get("experiment_id")
    if project_root and exp_id:
        from .. import loop_layout as LY

        result_path = os.path.join(project_root, LY.experiments_dir(), exp_id, "result.csv")
        got = metrics_mod.read_result(result_path)
        rows = got["rows"]
        result_warnings = got["warnings"] + ([got["reason"]] if not got["ok"] else [])

    state = loop.get("state") or "idle"
    loop_label = f"루프 {loop.get('loop_no') or 0}회차 · {LOOP_LABELS.get(state, state)}"
    pending = list(pending or [])

    return {
        "version": VERSION,
        "project": project,
        "generatedAt": datetime.now().astimezone().isoformat(timespec="seconds"),
        "dashboard": {
            "project": project,
            "modeLabel": _mode_label(project),
            "loopLabel": loop_label,
            "approval": _approval(pending),
            "metrics": _metric_tiles(conn, project, running, rows),
            "learningCurve": _learning_curve(rows, exp_id),
            "resources": _resources(gpu, host),
            "queueCaption": "GPU 1개 · 순차 실행",
            "loopPaused": bool(loop.get("paused")),
            "eventsCaption": "Decision_log.md · Discord 알림",
        },
        "experiments": _experiments(conn, project),
        "events": _events(conn, project),
        "raw": {
            "gpu": {k: v for k, v in gpu.items() if k != "driver"},
            "driver": gpu.get("driver") or {},
            "host": {k: v for k, v in host.items() if k != "cpuSample"},
            "job": running,
            "loop": dict(loop),
            "resultWarnings": result_warnings,
            "pendingApprovals": len(pending),
        },
    }


def write(conn, project: str, **kw) -> str:
    """스냅샷을 원자적으로 쓴다. ②가 죽어도 마지막 상태가 남는다."""
    data = build(conn, project, **kw)
    path = status_path(project)
    registry.write_json(path, data)
    return path


def read(project: str) -> dict:
    try:
        import json

        with open(status_path(project), encoding="utf-8") as fh:
            return json.load(fh)
    except (OSError, ValueError):
        return {}
