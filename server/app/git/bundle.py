"""🎒 `git bundle` 백업 — **앵커가 위조를 잡았을 때 되살릴 정본.**

## 왜 필요한가

T5 의 앵커는 위조를 **잡습니다**. 그런데 잡은 다음이 문제입니다 — `.git` 이
이미 오염됐고, `git reflog` 는 AI 도 지울 수 있어서 근거가 못 됩니다. 사람이
`blocked` 알림을 받고 들여다봐도 **되살릴 정본이 없습니다.**

그래서 기록 커밋마다 `git bundle` 로 저장소를 통째로 떠서
`server/data/backups/<프로젝트>/` 에 남깁니다. 그 폴더는 샌드박스 안에서
쓰기가 실패하므로(M1b) AI 가 쓴 코드가 **백업을 지울 수도 고칠 수도 없습니다.**

`git bundle` 을 고른 이유: **파일 하나**이고, `git clone <파일>` 로 그대로
되살아나며, `git bundle verify` 로 온전한지 확인할 수 있고, git 말고 아무것도
필요하지 않습니다.

## 복구 (사람이 합니다)

```bash
labremote git-backups <프로젝트>              # 어떤 백업이 있나
cd ~/projects/<프로젝트>
git bundle verify <백업>.bundle               # 온전한가
git clone <백업>.bundle /tmp/recovered        # 되살리기
# 또는 지금 저장소에 가져오기
git fetch <백업>.bundle 'refs/heads/*:refs/heads/백업-*'
```

자세한 절차는 `docs/operations.md` 의 "git 기록 복구" 절에 있습니다.
"""

from __future__ import annotations

import os
import subprocess
from datetime import datetime

from .. import paths, registry
from . import ops

__all__ = [
    "KEEP",
    "backup_dir",
    "create",
    "listing",
    "verify",
    "prune",
]

#: 몇 개를 남기나. 저장소가 작아서(기록만 추적) 넉넉하게 둔다.
KEEP = 10

#: 큰 저장소에서 느릴 수 있다
TIMEOUT_SEC = 120


class BundleError(RuntimeError):
    """백업을 못 떴을 때. **루프를 멈추지는 않는다** — 부르는 쪽이 삼킨다."""


def backup_dir(project: str) -> str:
    """`<data>/backups/<프로젝트>/`. 샌드박스 안에서 못 쓴다(M1b)."""
    return os.path.join(registry.data_dir(), "backups", registry.valid_name(project))


def _run(root: str, args: list[str], *, timeout: int = TIMEOUT_SEC):
    return subprocess.run(
        ["git", "--no-pager", *ops.safe_config(), "-C", paths.real(root), *args],
        capture_output=True, text=True, timeout=timeout, env=ops.safe_env(),
    )


def create(root: str, project: str, *, note: str = "", keep: int = KEEP) -> dict:
    """저장소를 통째로 떠서 백업 폴더에 남긴다. **던지지 않는다.**

    `--all` 로 모든 브랜치를 담는다 — `main` 과 `exp-NNN` 전부. 커밋이 하나도
    없으면 뜰 것이 없으므로 그냥 알린다.
    """
    root = paths.real(root)
    folder = backup_dir(project)
    # 마이크로초까지 넣는다 — 같은 초에 두 번 뜨면 이름이 겹쳐서 백업이 줄어든다.
    stamp = datetime.now().astimezone().strftime("%Y%m%d-%H%M%S-%f")
    try:
        os.makedirs(folder, exist_ok=True)
    except OSError as exc:
        return {"ok": False, "path": "", "reason": f"백업 폴더를 못 만들었어요: {exc}"}

    # 같은 초에 두 번 뜨면 이름이 겹친다 (덮어쓰면 백업이 하나 줄어든다).
    path = os.path.join(folder, f"{stamp}.bundle")
    serial = 1
    while os.path.exists(path):
        serial += 1
        path = os.path.join(folder, f"{stamp}-{serial}.bundle")

    try:
        done = _run(root, ["bundle", "create", path, "--all"])
    except (OSError, subprocess.SubprocessError) as exc:
        return {"ok": False, "path": "", "reason": f"git bundle 을 못 돌렸어요: {exc}"}
    if done.returncode != 0:
        text = (done.stderr or done.stdout or "").strip()
        # 커밋이 없으면 담을 ref 가 없다 — 실패가 아니라 "아직 없다" 다.
        if os.path.exists(path):
            try:
                os.unlink(path)
            except OSError:
                pass
        return {"ok": False, "path": "", "reason": text[:300]}

    if note:
        try:
            with open(path + ".note", "w", encoding="utf-8") as fh:
                fh.write(note + "\n")
        except OSError:
            pass
    pruned = prune(project, keep=keep)
    return {
        "ok": True,
        "path": path,
        "bytes": os.path.getsize(path) if os.path.exists(path) else 0,
        "pruned": pruned,
        "reason": "",
    }


def listing(project: str) -> list[dict]:
    """새것부터. `{"path", "at", "bytes", "note"}`."""
    folder = backup_dir(project)
    out = []
    try:
        names = os.listdir(folder)
    except OSError:
        return out
    # **이름이 아니라 mtime 으로** 정렬한다 — 이름 규칙이 바뀌어도 "새것부터" 가
    # 유지된다. 보관 개수 판정이 여기에 달려 있다.
    def _when(name):
        try:
            return os.path.getmtime(os.path.join(folder, name))
        except OSError:
            return 0.0

    for name in sorted(
        (n for n in names if n.endswith(".bundle")),
        key=lambda n: (_when(n), n),
        reverse=True,
    ):
        path = os.path.join(folder, name)
        note = ""
        try:
            with open(path + ".note", encoding="utf-8") as fh:
                note = fh.read().strip()
        except OSError:
            note = ""
        try:
            size = os.path.getsize(path)
        except OSError:
            size = 0
        out.append(
            {"path": path, "at": name[: -len(".bundle")], "bytes": size, "note": note}
        )
    return out


def prune(project: str, *, keep: int = KEEP) -> list[str]:
    """오래된 백업을 지운다. 새것 `keep` 개만 남긴다."""
    dropped = []
    for item in listing(project)[max(0, int(keep)) :]:
        for path in (item["path"], item["path"] + ".note"):
            try:
                os.unlink(path)
            except OSError:
                continue
            if path.endswith(".bundle"):
                dropped.append(path)
    return dropped


def verify(path: str, *, root: str = "", deep: bool = False) -> dict:
    """백업이 온전한가. **던지지 않는다.**

    ⚠ **실측: `git bundle verify` 는 pack 을 깊게 보지 않습니다.** 꼬리를 반
    잘라 낸 백업도 통과했습니다 — 머리와 전제(prerequisite)만 봅니다. 그리고
    저장소 안에서 돌려야 합니다("need a repository to verify a bundle").

    그래서 두 단계다.

    | | 무엇을 보나 | 비용 |
    |---|---|---|
    | 얕게 (기본) | 파일이 bundle 인가 · 전제가 맞나 | 싸다 |
    | 깊게 (`deep=True`) | **임시 폴더로 `git clone` 해 본다** — 통째로 읽는다 | 저장소 크기만큼 |

    기록만 추적하는 저장소라 깊게 봐도 싸다. 사람이 부르는
    `labremote git-backups` 는 **깊게** 본다.
    """
    import shutil
    import tempfile

    target = paths.real(path)
    if not os.path.isfile(target):
        return {"ok": False, "deep": False, "reason": "백업 파일이 없어요"}

    if deep or not root:
        # `clone` 은 저장소가 필요 없고 **통째로 읽는다.**
        folder = tempfile.mkdtemp(prefix="labremote-bundle-")
        try:
            done = subprocess.run(
                [
                    "git", "--no-pager", *ops.safe_config(),
                    # `safe_config` 는 `protocol.allow=never` 로 원격 전송을
                    # 끊는다(②는 로컬 브랜치만). bundle 을 복제하려면 `file`
                    # 전송이 필요하다 — `protocol.<이름>.allow` 가 그 하나만
                    # 여는 좁은 문이고, 대상은 우리가 쓴 백업 파일이다.
                    "-c", "protocol.file.allow=always",
                    "clone", "--bare", "--quiet", target,
                    os.path.join(folder, "probe.git"),
                ],
                capture_output=True, text=True,
                timeout=TIMEOUT_SEC, env=ops.safe_env(),
            )
        except (OSError, subprocess.SubprocessError) as exc:
            return {"ok": False, "deep": True, "reason": f"못 돌렸어요: {exc}"}
        finally:
            shutil.rmtree(folder, ignore_errors=True)
        text = ((done.stderr or "") + (done.stdout or "")).strip()
        return {
            "ok": done.returncode == 0,
            "deep": True,
            "reason": "" if done.returncode == 0 else text[:300],
        }

    try:
        done = _run(paths.real(root), ["bundle", "verify", target])
    except (OSError, subprocess.SubprocessError) as exc:
        return {"ok": False, "deep": False, "reason": f"못 돌렸어요: {exc}"}
    text = ((done.stdout or "") + (done.stderr or "")).strip()
    return {
        "ok": done.returncode == 0,
        "deep": False,
        "reason": "" if done.returncode == 0 else text[:300],
    }
