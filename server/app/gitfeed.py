"""Dashboard 의 "열린 PR" · "최근 머지" (v3 4단계에서 미뤄 둔 것).

- 머지: 등록한 프로젝트마다 main 의 첫 부모 줄기에서 **머지 커밋**만 최근 7일 (`git log`).
  빨리 감기(fast-forward)로 합친 것은 머지 커밋이 없어 안 나온다 — lab.remote 의 "main에
  합치기" 는 `--no-ff` 라 늘 나온다.
- PR: `gh` 가 깔려 있고 로그인돼 있을 때만 `gh pr list`. 없으면 없다고 말한다(지어내지 않는다).
- 느린 명령이라 60초 캐시하고, Dashboard 본문과 따로 받는다.
"""

from __future__ import annotations

import json
import re
import shutil
import subprocess
import threading
import time

from . import registry
from .git import ops, view
from .git.guard import GitRefused

__all__ = ["feed", "merges", "prs"]

CACHE_SEC = 60.0
WEEK = 7 * 24 * 3600
_lock = threading.Lock()
_cache: tuple[float, dict] | None = None
_BRANCH = re.compile(r"Merge (?:remote-tracking )?branch '([^']+)'")


def merges(now: float | None = None) -> dict:
    now = now or time.time()
    items = []
    for root, name in sorted(registry.load().items(), key=lambda kv: kv[1]):
        try:
            if not ops.inside_worktree(root):
                continue
            main = view.main_branch(root)
            if not main:
                continue
            out = ops.run(root, ["log", main, "--first-parent", "--merges", f"--since={int(now - WEEK)}", "--format=%ct%x09%s", "-n", "20"])
        except (GitRefused, ops.GitError, OSError):
            continue
        for line in out.splitlines():
            at, _, subject = line.partition("\t")
            if not at.isdigit():
                continue
            m = _BRANCH.search(subject)
            items.append({"project": name, "main": main, "branch": m.group(1) if m else "", "title": subject.strip()[:200], "at": int(at)})
    items.sort(key=lambda x: -x["at"])
    midnight = time.mktime(time.localtime(now)[:3] + (0, 0, 0, 0, 0, -1))
    return {"items": items[:10], "week": len(items), "today": sum(1 for x in items if x["at"] >= midnight)}


def _gh(root: str) -> list[dict] | None:
    gh = shutil.which("gh")
    if not gh:
        return None
    try:
        done = subprocess.run(
            [gh, "pr", "list", "--state", "open", "--limit", "10", "--json", "number,title,headRefName,isDraft,reviewDecision,statusCheckRollup,url"],
            cwd=root, capture_output=True, text=True, timeout=20,
        )
    except (OSError, subprocess.SubprocessError):
        return []
    if done.returncode != 0:
        return []
    try:
        return json.loads(done.stdout or "[]")
    except json.JSONDecodeError:
        return []


def _ci(checks) -> str:
    states = [str(c.get("conclusion") or c.get("state") or c.get("status") or "").upper() for c in checks or [] if isinstance(c, dict)]
    if not states:
        return ""
    if any(s in ("FAILURE", "ERROR", "CANCELLED", "TIMED_OUT") for s in states):
        return "CI 실패"
    if all(s in ("SUCCESS", "NEUTRAL", "SKIPPED") for s in states):
        return "CI 통과"
    return "CI 대기"


def prs() -> dict:
    if not shutil.which("gh"):
        return {"available": False, "reason": "gh(GitHub CLI)가 없어요 — 깔고 gh auth login 하면 보여요", "items": []}
    items = []
    for root, name in sorted(registry.load().items(), key=lambda kv: kv[1]):
        got = _gh(root)
        for pr in got or []:
            state = "초안" if pr.get("isDraft") else {"CHANGES_REQUESTED": "변경 요청", "APPROVED": "승인됨"}.get(str(pr.get("reviewDecision") or ""), "리뷰 기다림")
            items.append({
                "project": name,
                "number": pr.get("number"),
                "title": str(pr.get("title") or "")[:200],
                "branch": str(pr.get("headRefName") or ""),
                "state": state,
                "ci": _ci(pr.get("statusCheckRollup")),
                "url": str(pr.get("url") or ""),
            })
    return {"available": True, "reason": "", "items": items[:10]}


def feed(*, fresh: bool = False) -> dict:
    global _cache
    with _lock:
        now = time.monotonic()
        if not fresh and _cache and now - _cache[0] < CACHE_SEC:
            return _cache[1]
        got = {"merges": merges(), "prs": prs()}
        _cache = (now, got)
        return got
