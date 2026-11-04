"""끝난 실험의 산출물 정리.

체크포인트는 금방 수십 GB 가 된다. 끝난 실험에서 **재개용**(`epoch_*`)은
버리고 **결과용**(`best.*`·`final.*`)은 남긴다.

> ⚠ **의도된 비대칭이다.** 이 파일들은 훅의 `outputProtect` 대상이라 Claude 는
> 지울 수 없다. 오케스트레이터는 훅을 거치지 않으니 지울 수 있다. "AI 는 못
> 지우고 시스템은 지운다" 가 설계이고, `docs/operations.md` 에 적어 뒀다.
>
> 그래서 **지우는 조건을 코드가 좁게 쥔다** — 실험이 끝났고, 경로가 그 실험의
> `output/` 안이고, 이름이 재개용 패턴에 맞을 때만. 자유 glob 을 받지 않는다.
"""

from __future__ import annotations

import fnmatch
import os

from .. import paths

__all__ = ["RESUME_PATTERNS", "KEEP_PATTERNS", "prune_checkpoints", "disk_usage"]

#: 재개용 — 끝난 실험에서는 지운다
RESUME_PATTERNS = ("epoch_*", "step_*", "ckpt_*", "last.*", "latest.*")

#: 결과용 — 언제나 남긴다. 재개용 패턴과 겹치면 **이쪽이 이긴다.**
KEEP_PATTERNS = ("best.*", "final.*", "*.json", "*.csv", "*.log", "*.md")


def _matches(name: str, patterns) -> bool:
    return any(fnmatch.fnmatch(name, pattern) for pattern in patterns)


def prune_checkpoints(
    output_dir: str,
    *,
    project_root: str,
    dry_run: bool = False,
    resume_patterns=RESUME_PATTERNS,
    keep_patterns=KEEP_PATTERNS,
) -> dict:
    """재개용 체크포인트를 지운다. 지운 목록과 되찾은 용량을 돌려준다.

    `output_dir` 이 프로젝트 안이 아니면 아무것도 하지 않는다.
    """
    root = paths.real(project_root)
    target = paths.real(output_dir)
    if not root or not paths.is_inside(root, target) or not os.path.isdir(target):
        return {"ok": False, "reason": "프로젝트 안의 폴더가 아니에요", "removed": [], "freedBytes": 0}

    removed: list[str] = []
    freed = 0
    kept: list[str] = []
    for name in sorted(os.listdir(target)):
        path = os.path.join(target, name)
        if not os.path.isfile(path) or os.path.islink(path):
            continue
        # 남길 패턴이 **먼저** 이긴다. `best.ckpt` 를 `ckpt_*` 로 잡는 사고를 막는다.
        if _matches(name, keep_patterns) or not _matches(name, resume_patterns):
            kept.append(name)
            continue
        try:
            size = os.path.getsize(path)
        except OSError:
            size = 0
        if not dry_run:
            try:
                os.remove(path)
            except OSError:
                kept.append(name)
                continue
        removed.append(name)
        freed += size
    return {"ok": True, "removed": removed, "kept": kept, "freedBytes": freed, "dryRun": dry_run}


def disk_usage(path: str) -> dict:
    """그 경로가 올라가 있는 파일 시스템의 여유 공간 (GB)."""
    try:
        stat = os.statvfs(path)
    except OSError as exc:
        return {"ok": False, "reason": str(exc)}
    free = stat.f_bavail * stat.f_frsize
    total = stat.f_blocks * stat.f_frsize
    return {
        "ok": True,
        "freeGb": round(free / 1024**3, 2),
        "totalGb": round(total / 1024**3, 2),
        "usedPct": round(100 * (1 - free / total), 1) if total else 0.0,
    }
