"""학습 프로세스 샌드박스 — `bubblewrap`.

학습 스크립트는 **AI 가 쓴 코드**다. 훅은 도구 호출만 보므로
`train.py` 안의 `open(os.path.expanduser("~/.claude/settings.json"), "w")` 는
훅을 **한 번도 거치지 않는다.** 정책·자격 증명·허가 서명 키·`lab.db` 가
그대로 사정권이다. 막는 수단은 샌드박스뿐이다.

0단계 실측 15번(2026-11-04)에서 `bwrap` 으로 확정했다. `systemd-run --user` 의
`InaccessiblePaths`·`ProtectHome`·`PrivateUsers` 는 사용자 매니저에서 **전부
무효**였다 — 값은 `systemctl show` 에 보이는데 실제로는 아무것도 막히지 않았다.

측정한 명령 꼴:

    bwrap --ro-bind / / --dev-bind /dev /dev --proc /proc --tmpfs /tmp \\
          --bind   <프로젝트 루트>  <프로젝트 루트> \\
          --tmpfs  ~/.claude  --tmpfs ~/.config/labremote \\
          --tmpfs  <저장소>/server  --tmpfs <다른 프로젝트들> \\
          --die-with-parent -- <명령>

결과: 비밀 내용 안 보임 · 보호 경로 쓰기가 **실제 파일에 안 남음** ·
프로젝트 읽기·쓰기 됨 · GPU(RTX 5080)·`nvidia-smi`·conda·네트워크 전부 정상.

> ⚠ `--tmpfs` 는 내용을 가리고 쓰기를 **버린다.** 샌드박스 안에서 보호 경로
> 쓰기는 **성공한 것처럼 보이지만** 실제 파일에는 안 남는다. 학습이
> "저장했다" 고 믿고 조용히 오동작할 수 있어서 `runner/spec.py` 가 미리 경고한다.

전제: `/etc/apparmor.d/` 에 `bwrap` 용 프로파일이 있어야 한다(`userns,`).
없으면 `bwrap: setting up uid map: Permission denied` 다. `available()` 이
**실제로 띄워 보고** 판정한다 — 설정만 보고 믿지 않는다.
"""

from __future__ import annotations

import os
import shutil
import subprocess

from .. import paths, policy_defaults as D, registry

__all__ = [
    "BWRAP_CANDIDATES",
    "SandboxError",
    "bwrap_path",
    "secret_paths",
    "other_project_paths",
    "hidden_paths",
    "command",
    "available",
    "describe",
]

#: 설정으로 바꿀 수 있지만 기본은 `PATH` 에서 찾는다.
BWRAP_CANDIDATES = ("/usr/bin/bwrap", "/bin/bwrap")

#: 띄워 보는 데 기다릴 시간
PROBE_TIMEOUT_SEC = 10


class SandboxError(RuntimeError):
    """샌드박스를 쓸 수 없을 때. **학습을 띄우지 않는다.**"""


def bwrap_path() -> str:
    """`bwrap` 실행 파일. 없으면 빈 문자열."""
    override = os.environ.get("LAB_BWRAP")
    if override:
        return override if os.path.exists(override) else ""
    found = shutil.which("bwrap")
    if found:
        return found
    for candidate in BWRAP_CANDIDATES:
        if os.path.exists(candidate):
            return candidate
    return ""


def secret_paths(project_root: str = "") -> list[str]:
    """**읽기까지 막아야 하는** 곳. 있는 것만 돌려준다.

    | 가리는 것 | 왜 |
    |---|---|
    | `~/.claude`·`~/.claude.json*` | 훅 등록·자격 증명 |
    | `~/.config/labremote` | 웹훅 주소, **허가 서명 키** |
    | `<저장소>/server` | 정책·허가·`lab.db`·래퍼 — ②와 ①의 상태 전부 |

    `run.dataPaths` 로도 **다시 열 수 없는** 목록이다. 다른 실험 프로젝트는
    여기 없다 — 그건 교차 오염 방지라서, 사람이 `dataPaths` 로 명시하면
    읽기로 열어 준다.
    """
    root = paths.real(project_root) if project_root else ""
    out: list[str] = []
    for pattern in D.hard_protected_roots():
        target = paths.real(pattern)
        if target and os.path.isdir(target) and not (root and paths.is_inside(target, root)):
            out.append(target)
    home = os.path.expanduser("~")
    for rel in (".claude", ".config/labremote"):
        target = os.path.join(home, rel)
        if os.path.isdir(target) and target not in out:
            out.append(target)
    return sorted(dict.fromkeys(out))


def other_project_paths(project_root: str) -> list[str]:
    """다른 실험 프로젝트. **교차 오염**을 막으려고 가린다.

    비밀이라서가 아니다. 그래서 `run.dataPaths` 로 그 안의 데이터셋을
    읽기로 다시 열 수 있다 (`Config.yaml` 은 프로젝트 안이지만 실험이 도는
    중에는 잠겨 있고, 열어 주는 건 **읽기**뿐이다).
    """
    root = paths.real(project_root)
    out = []
    for other_root in registry.load():
        other = paths.real(other_root)
        if other and other != root and os.path.isdir(other):
            out.append(other)
    return sorted(dict.fromkeys(out))


def hidden_paths(project_root: str) -> list[str]:
    """샌드박스가 가릴 경로 전부 (`--tmpfs` 는 없는 경로에 실패한다)."""
    return sorted(
        dict.fromkeys(secret_paths(project_root) + other_project_paths(project_root))
    )


def command(
    argv: list[str],
    *,
    project_root: str,
    hide: list[str] | None = None,
    extra_ro: list[str] | None = None,
    cache_dir: str = "",
    bwrap: str = "",
    die_with_parent: bool = False,
) -> list[str]:
    """`bwrap` 으로 감싼 전체 명령을 돌려준다.

    `hide` 를 주면 그 목록만 가린다(시험용). 안 주면 `hidden_paths()`.

    ### 인자 순서가 의미를 바꾼다

    `bwrap` 은 **뒤에 온 것이 이긴다.** 그래서

      1. `--ro-bind / /` 로 전부 읽기 전용
      2. `--bind <프로젝트>` · `--bind <캐시>` 로 쓸 수 있는 곳 둘
      3. `--tmpfs <보호 경로>` 로 가리기
      4. `--ro-bind <데이터셋>` 으로 **가림을 다시 뚫기**

    4번이 3번 **뒤**에 와야 한다. 데이터셋이 가려진 경로 안에 있을 때
    (다른 프로젝트의 `data/` 를 공유하는 경우 등) 읽을 수 있게 하려는 것이다.
    루트 전체가 이미 읽기 전용으로 보이니, 가려지지 않은 데이터셋은 이 항목
    없이도 읽힌다.

    ### `--die-with-parent` 는 기본으로 **끈다**

    측정할 때 쓴 명령에는 있었지만, 그건 격리를 재려고 띄운 것이었다. 실제
    운영에서는 **오케스트레이터가 재시작돼도 학습이 살아 있어야** 한다 —
    복구가 `pid` + `/proc/<pid>/stat` 의 starttime + `output/exit_code` 로
    이어받는 설계이고(9단계 수동 검증 9·10번), systemd 유닛도 `KillMode=mixed`
    로 학습을 안 죽인다. `--die-with-parent` 를 켜면 오케스트레이터를 재시작할
    때마다 **몇 시간 돌던 학습이 같이 죽는다.**

    대가로 고아 프로세스가 생길 수 있다. 그건 복구가 이어받거나
    `labremote queue cancel` 로 정리한다 — 되돌릴 수 있는 쪽을 고른다.
    터미널에서 디버깅할 때(`labremote up --foreground`)는 켜면 편하다.
    """
    binary = bwrap or bwrap_path()
    if not binary:
        raise SandboxError(
            "bwrap 을 찾을 수 없어요. `sudo apt install bubblewrap` 으로 깔아 주세요."
        )
    root = paths.real(project_root)
    if not os.path.isdir(root):
        raise SandboxError(f"프로젝트 폴더가 없어요: {root}")

    out = [
        binary,
        # 루트 전체는 **읽기 전용**으로 보인다. conda·CUDA·데이터셋을 읽어야 한다.
        "--ro-bind", "/", "/",
        # GPU 장치가 보여야 한다 (`/dev/nvidia*`·`/dev/nvidiactl`·`/dev/nvidia-uvm`)
        "--dev-bind", "/dev", "/dev",
        "--proc", "/proc",
        # 임시 폴더는 버려지는 것으로. 밖에 흔적을 남기지 않는다.
        "--tmpfs", "/tmp",
        # 쓸 수 있는 곳은 프로젝트와 (있으면) 공용 캐시뿐이다.
        "--bind", root, root,
    ]
    cache_real = paths.real(cache_dir) if cache_dir else ""
    if cache_real:
        if not os.path.isdir(cache_real):
            raise SandboxError(
                f"캐시 폴더가 없어요: {cache_real} · runner/cache.ensure 를 먼저 불러 주세요."
            )
        if paths.is_inside(root, cache_real):
            # 프로젝트 안이면 이미 쓸 수 있다. 같은 곳을 두 번 바인드하지 않는다.
            cache_real = ""
        else:
            out += ["--bind", cache_real, cache_real]
    for item in hidden_paths(root) if hide is None else hide:
        target = paths.real(item)
        if not os.path.exists(target):
            continue
        if cache_real and paths.is_inside(target, cache_real):
            # 여기까지 오면 cache.check 가 놓친 것이다. 가리는 쪽을 포기하면
            # 보호가 뚫리니, 띄우지 않는다.
            raise SandboxError(
                f"캐시 폴더가 보호 경로 안이에요: {cache_real} ⊂ {target}"
            )
        out += ["--tmpfs", target]
    # 가림 **뒤에** 와야 뚫린다 (위 주석).
    for item in extra_ro or []:
        target = paths.real(item)
        if os.path.exists(target):
            out += ["--ro-bind", target, target]
    if die_with_parent:
        out.append("--die-with-parent")
    out.append("--")
    return out + list(argv)


def available(project_root: str = "") -> dict:
    """**실제로 띄워 보고** 판정한다. 설정만 보고 믿지 않는다.

    `{"ok": bool, "bwrap": 경로, "reason": 사유}` 를 돌려준다. 던지지 않는다 —
    `doctor` 와 런처가 같은 함수를 쓴다.
    """
    binary = bwrap_path()
    if not binary:
        return {"ok": False, "bwrap": "", "reason": "bwrap 이 설치돼 있지 않아요"}
    try:
        result = subprocess.run(
            [binary, "--ro-bind", "/", "/", "--proc", "/proc", "--", "/bin/true"],
            capture_output=True,
            text=True,
            timeout=PROBE_TIMEOUT_SEC,
        )
    except (OSError, subprocess.SubprocessError) as exc:
        return {"ok": False, "bwrap": binary, "reason": f"띄워 보지 못했어요: {exc}"}
    if result.returncode != 0:
        detail = (result.stderr or result.stdout or "").strip().splitlines()
        reason = detail[-1] if detail else f"종료코드 {result.returncode}"
        if "uid map" in reason or "Permission denied" in reason:
            reason += (
                " · 우분투 24.04 는 비특권 user namespace 를 막아요. "
                "/etc/apparmor.d/ 에 bwrap 프로파일(userns,)을 넣어 주세요."
            )
        return {"ok": False, "bwrap": binary, "reason": reason}
    return {"ok": True, "bwrap": binary, "reason": ""}


def describe(project_root: str) -> dict:
    """`doctor` 가 보여 줄 요약."""
    state = available(project_root)
    return {**state, "hidden": hidden_paths(project_root) if project_root else []}
