"""GPU 상태와 **드라이버 불일치**.

`nvidia-smi` 한 줄 파싱이다. 외부 패키지를 쓰지 않는다.

### 조회 실패가 정상 경로다

예외를 던지지 않고 `{"available": false, "reason": ...}`를 돌려준다.
①의 실측 중에 실제로 당했다 — 우분투 자동 업데이트가 드라이버를 올리고
재부팅을 안 해서 `nvidia-smi`가 통째로 죽었고, 그 상태로 며칠 지났다.

### 드라이버 불일치

| 신호 | 읽는 곳 |
|---|---|
| 커널 모듈 | `/proc/driver/nvidia/version`의 `NVRM version:` |
| 유저랜드 | `nvidia-smi --query-gpu=driver_version` |
| 재부팅 대기 | `/var/run/reboot-required.pkgs`에 `nvidia`가 있나 |
| 이미 깨짐 | `nvidia-smi` stderr의 `version mismatch` |

앞 두 자리가 다르면 **불일치**다. 재부팅 대기만 있으면 아직 안 깨졌지만
곧 깨질 상태라 미리 알린다. 불일치면 `guards`가 학습을 **시작하지 않는다**
(어차피 실패할 학습으로 GPU 시간과 사용량을 버리지 않게).
"""

from __future__ import annotations

import os
import re
import subprocess

__all__ = [
    "QUERY_FIELDS",
    "NVRM_PATH",
    "REBOOT_REQUIRED_PKGS",
    "probe",
    "driver_state",
    "parse_csv",
    "nvrm_version",
    "reboot_pending",
]

#: 한 줄로 받아 오는 칸. 순서가 파싱 순서다.
QUERY_FIELDS = (
    "index",
    "name",
    "utilization.gpu",
    "memory.used",
    "memory.total",
    "temperature.gpu",
    "driver_version",
)

NVRM_PATH = "/proc/driver/nvidia/version"
REBOOT_REQUIRED = "/var/run/reboot-required"
REBOOT_REQUIRED_PKGS = "/var/run/reboot-required.pkgs"

TIMEOUT_SEC = 10

#: 드라이버가 깨졌을 때 나오는 말
MISMATCH_HINTS = ("version mismatch", "Failed to initialize NVML")


def _run(args: list[str]) -> tuple[int, str, str]:
    try:
        done = subprocess.run(args, capture_output=True, text=True, timeout=TIMEOUT_SEC)
    except FileNotFoundError:
        return 127, "", "nvidia-smi가 없어요"
    except (OSError, subprocess.SubprocessError) as exc:
        return 1, "", str(exc)
    return done.returncode, done.stdout, done.stderr


def _number(text: str):
    text = (text or "").strip()
    if not text or text in ("[N/A]", "N/A", "[Not Supported]"):
        return None
    try:
        return float(text)
    except ValueError:
        return None


def parse_csv(stdout: str) -> list[dict]:
    """`--format=csv,noheader,nounits` 출력을 장치 목록으로."""
    devices: list[dict] = []
    for line in (stdout or "").splitlines():
        parts = [p.strip() for p in line.split(",")]
        if len(parts) < len(QUERY_FIELDS):
            continue
        row = dict(zip(QUERY_FIELDS, parts))
        used = _number(row["memory.used"])
        total = _number(row["memory.total"])
        devices.append(
            {
                "index": int(_number(row["index"]) or 0),
                "name": row["name"],
                "utilPct": _number(row["utilization.gpu"]),
                "memUsedMb": used,
                "memTotalMb": total,
                "memPct": round(100 * used / total, 1) if used is not None and total else None,
                "tempC": _number(row["temperature.gpu"]),
                "driver": row["driver_version"],
            }
        )
    return devices


def nvrm_version() -> str:
    """커널 모듈이 보고하는 드라이버 판. 못 읽으면 빈 문자열."""
    try:
        with open(NVRM_PATH, encoding="utf-8", errors="replace") as fh:
            raw = fh.read()
    except OSError:
        return ""
    found = re.search(r"NVRM version:.*?Kernel Module\s+([0-9][0-9.]*)", raw)
    if found:
        return found.group(1)
    found = re.search(r"([0-9]+\.[0-9]+(?:\.[0-9]+)?)", raw)
    return found.group(1) if found else ""


def reboot_pending() -> dict:
    """재부팅 대기 상태와, 그 이유가 nvidia 인가.

    아직 안 깨졌지만 **곧 깨질** 상태다. 미리 알려서 실험을 시작하지 않게 한다.
    """
    pending = os.path.exists(REBOOT_REQUIRED)
    packages: list[str] = []
    try:
        with open(REBOOT_REQUIRED_PKGS, encoding="utf-8", errors="replace") as fh:
            packages = [line.strip() for line in fh if line.strip()]
    except OSError:
        pass
    nvidia = [p for p in packages if "nvidia" in p.lower() or "cuda" in p.lower()]
    return {"pending": pending or bool(packages), "packages": packages, "nvidia": nvidia}


def driver_state() -> dict:
    """커널 모듈과 유저랜드가 같은 판인가.

    `{"ok", "kernel", "userland", "mismatch", "rebootPending", "reason"}`.
    **던지지 않는다.**
    """
    kernel = nvrm_version()
    code, stdout, stderr = _run(
        ["nvidia-smi", "--query-gpu=driver_version", "--format=csv,noheader"]
    )
    userland = (stdout or "").strip().splitlines()[0].strip() if stdout.strip() else ""
    boot = reboot_pending()
    text = f"{stdout}\n{stderr}"
    broken = any(hint in text for hint in MISMATCH_HINTS)

    mismatch = bool(kernel and userland and kernel != userland) or broken
    reason = ""
    if broken:
        reason = next(
            (line.strip() for line in stderr.splitlines() if line.strip()), "드라이버에 문제가 있어요"
        )
    elif mismatch:
        reason = f"커널 모듈 {kernel} vs 유저랜드 {userland}"
    elif boot["nvidia"]:
        reason = "nvidia 패키지가 업데이트됐는데 아직 재부팅을 안 했어요: " + ", ".join(boot["nvidia"])

    return {
        "ok": not mismatch and not boot["nvidia"],
        "kernel": kernel,
        "userland": userland,
        "mismatch": mismatch,
        "rebootPending": boot["pending"],
        "rebootPackages": boot["nvidia"],
        "reason": reason,
        "exitCode": code,
    }


def probe() -> dict:
    """GPU 상태 한 덩어리. **실패해도 정상 반환한다.**

    `{"available", "reason", "devices", "driver"}`.
    """
    driver = driver_state()
    code, stdout, stderr = _run(
        [
            "nvidia-smi",
            "--query-gpu=" + ",".join(QUERY_FIELDS),
            "--format=csv,noheader,nounits",
        ]
    )
    if code != 0 or not stdout.strip():
        detail = [line.strip() for line in (stderr or "").splitlines() if line.strip()]
        reason = detail[0] if detail else f"nvidia-smi가 실패했어요 (종료 코드 {code})"
        return {"available": False, "reason": reason, "devices": [], "driver": driver}
    devices = parse_csv(stdout)
    if not devices:
        return {
            "available": False,
            "reason": "nvidia-smi 출력을 읽지 못했어요",
            "devices": [],
            "driver": driver,
        }
    return {"available": True, "reason": "", "devices": devices, "driver": driver}
