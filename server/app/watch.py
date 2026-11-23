"""서버 안의 가벼운 감시 — 실행이 끝났나·끊겼나, 그리고 실행 중일 때만 자원 경고.

**AI 자동화가 아니다**(PLAN 1.4): 보고 알리기만 한다. 다시 돌리거나 이어서
돌리지 않는다.

- 10초마다 "실행 중" 으로 적힌 기록만 본다(종료코드 파일·tmux 세션 확인).
  실행이 없으면 거의 아무것도 안 한다.
- 서버가 뜰 때 한 번 훑어서 **재부팅으로 끊긴 실행**을 알아챈다.
- 자원 경고(VRAM · 디스크 · 드라이버)는 실행이 돌고 있을 때 5분마다만 본다
  — 화면을 안 볼 때 서버가 혼자 자원을 폴링하지 않는다는 원칙(PLAN 1.3)을
  지키면서, 학습이 위험할 때는 알려 주려고.
"""

from __future__ import annotations

import os
import shutil
import threading
import time

from . import alerts, db, projects, registry, runs
from .monitor import gpu as gpu_mod

__all__ = ["Watcher", "tick", "check_resources", "VRAM_WARN_PCT", "DISK_WARN_GB"]

INTERVAL_SEC = 10
RESOURCE_EVERY_SEC = 300
VRAM_WARN_PCT = 90.0
DISK_WARN_GB = 10.0
#: 같은 시스템 경고를 다시 Inbox 에 넣기까지
SYS_COOLDOWN_SEC = 6 * 3600


def _run_where(record: dict) -> str:
    parts = [record.get("project") or ""]
    if record.get("cwd") and record["cwd"] != ".":
        parts.append(record["cwd"])
    if record.get("exitCode") is not None:
        parts.append(f"종료코드 {record['exitCode']}")
    return " · ".join(p for p in parts if p)


def _run_title(record: dict) -> str:
    return record.get("name") or record["id"]


def announce(conn, record: dict, *, poster=None) -> dict | None:
    """끝난 실행 하나를 Inbox(+Discord) 에 알린다."""
    state = record.get("state")
    title = _run_title(record)
    ref = {"project": record.get("project"), "run": record["id"]}
    common = dict(where=_run_where(record), project=record.get("project"), ref=ref, poster=poster,
                  subject=f"run:{record.get('project')}:{record['id']}:{state}")
    mins = round(max(0, (record.get("endedAt") or 0) - (record.get("startedAt") or 0)) / 60)
    if state == "done":
        return alerts.post(conn, "run", "done", f"{title} 끝남", body=f"{mins}분 걸렸어요. · {record.get('command')}", **common)
    if state == "failed":
        return alerts.post(conn, "run", "fail", f"{title} 실패", act=True,
                           body=f"종료코드 {record.get('exitCode')} · {record.get('command')}", **common)
    if state == "cut":
        return alerts.post(conn, "run", "fail", f"{title} 중간에 끊김", act=True,
                           body=f"{record.get('reason')}. 자동으로 다시 돌리지 않아요.", **common)
    if state == "stopped":
        # 사람이 직접 멈춘 것 — 기록만, 보내지 않는다
        return alerts.post(conn, "run", None, f"{title} 중지함", body=record.get("command") or "", read=True, **common)
    return None


def tick(conn, *, poster=None) -> list[dict]:
    """실행 기록을 한 번 훑는다. 끝났는데 아직 안 알린 것을 알리고 돌려준다.

    `announced` 가 없는 옛 기록은 알린 것으로 본다(처음 띄울 때 과거 실행을
    한꺼번에 알리지 않으려고).
    """
    changed = []
    for root, name in registry.load().items():
        folder = runs.runs_dir(root)
        if not os.path.isdir(folder):
            continue
        for run_id in sorted(os.listdir(folder)):
            if not runs.ID_RE.match(run_id):
                continue
            try:
                record = runs._load(root, run_id)
            except runs.RunError:
                continue
            if record.get("state") == "running":
                record, _ = runs.refresh(root, record)
            if record.get("state") == "running" or record.get("announced", True):
                continue
            record.setdefault("project", name)
            # 먼저 적고 알린다 — 알리다 죽어도 같은 알림이 두 번 가지 않게
            record["announced"] = True
            runs._save(root, record)
            announce(conn, record, poster=poster)
            changed.append(record)
    return changed


_sys_last: dict[str, float] = {}


def _sys_once(conn, key: str, title: str, where: str, body: str, *, poster=None) -> None:
    now = time.time()
    if now - _sys_last.get(key, 0) < SYS_COOLDOWN_SEC:
        return
    _sys_last[key] = now
    alerts.post(conn, "sys", "sys", title, where=where, body=body, subject=f"sys:{key}", poster=poster)


def check_resources(conn, *, probe=None, poster=None) -> None:
    """VRAM · 디스크 · 드라이버. 실행이 돌 때만 부른다."""
    raw = (probe or gpu_mod.probe)()
    driver = raw.get("driver") or {}
    if driver.get("mismatch"):
        _sys_once(conn, "driver", "GPU 드라이버가 맞지 않아요", "커널 · 유저랜드",
                  "재부팅이 필요해요. 이대로면 새 학습이 실패해요.", poster=poster)
    for d in raw.get("devices") or []:
        used, total = d.get("memUsedMb"), d.get("memTotalMb")
        if isinstance(used, (int, float)) and isinstance(total, (int, float)) and total:
            pct = 100.0 * used / total
            if pct >= VRAM_WARN_PCT:
                _sys_once(conn, f"vram:{d.get('index', 0)}", "VRAM 이 거의 찼어요",
                          f"{d.get('name', 'GPU')} · {used / 1024:.1f}/{total / 1024:.0f}G",
                          "새 실행은 메모리가 모자랄 수 있어요.", poster=poster)
    seen = set()
    for root in registry.load():
        try:
            usage = shutil.disk_usage(root)
            dev = os.stat(root).st_dev
        except OSError:
            continue
        if dev in seen:
            continue
        seen.add(dev)
        free_gb = usage.free / 1024**3
        if free_gb < DISK_WARN_GB:
            _sys_once(conn, f"disk:{dev}", "디스크 여유가 적어요", f"{projects.display_path(root)} · {free_gb:.1f}G 여유",
                      "체크포인트를 못 남길 수 있어요.", poster=poster)


def _any_running() -> bool:
    for root in registry.load():
        folder = runs.runs_dir(root)
        if not os.path.isdir(folder):
            continue
        for run_id in os.listdir(folder):
            if runs.ID_RE.match(run_id):
                try:
                    if runs._load(root, run_id).get("state") == "running":
                        return True
                except runs.RunError:
                    continue
    return False


class Watcher(threading.Thread):
    """서버와 같이 뜨고 같이 진다(daemon)."""

    def __init__(self, interval: float = INTERVAL_SEC):
        super().__init__(name="labremote-watch", daemon=True)
        self.interval = interval
        self.stop_event = threading.Event()
        self._last_resources = 0.0

    def run(self) -> None:  # pragma: no cover - 실제 스레드는 시험에서 안 띄운다
        while not self.stop_event.is_set():
            try:
                with db.open_db() as conn:
                    tick(conn)
                    now = time.monotonic()
                    if _any_running() and now - self._last_resources >= RESOURCE_EVERY_SEC:
                        self._last_resources = now
                        check_resources(conn)
            except Exception:  # 감시가 죽으면 서버 전체가 멈춘 것처럼 보인다
                pass
            self.stop_event.wait(self.interval)

    def stop(self) -> None:
        self.stop_event.set()
