"""가짜 학습. 진짜 GPU 없이 루프 전체를 돌려 보는 데 쓴다.

계획의 결정: **가짜 학습으로 루프부터.** 진짜 학습은 10단계다.

학습 스크립트 규약을 흉내 낸다.
  - `--epochs N` 만큼 `result.csv` 에 줄을 쌓는다
  - `--resume-from <경로>` 로 이어 돌린다
  - 체크포인트를 `output/epoch_*.ckpt` 와 `output/best.ckpt` 로 남긴다
  - 로그를 stdout 으로 흘린다 (오케스트레이터가 파일로 받는다)

시험용 장치도 있다.
  - `--sleep SEC`        한 에폭마다 쉰다 (타임아웃 시험)
  - `--children N`       자식을 N 개 띄운다 (손자까지 정리되는지)
  - `--nan-at N`         N 에폭에서 loss 를 NaN 으로 (이상 감지)
  - `--probe-write 경로`  그 경로에 쓰려고 **시도**한다 (샌드박스 시험)
  - `--probe-read 경로`   그 경로를 읽으려고 **시도**한다
  - `--crash-at N`       N 에폭에서 0이 아닌 코드로 죽는다

표준 라이브러리만 쓴다 — conda 환경이 없어도 돌아야 한다.
"""

from __future__ import annotations

import argparse
import csv
import json
import os
import subprocess
import sys
import time


def log(message: str) -> None:
    print(message, flush=True)


def probe_write(path: str) -> dict:
    """그 경로에 쓰려고 **시도**한다. 결과를 적어 돌려준다."""
    target = os.path.expanduser(path)
    try:
        os.makedirs(os.path.dirname(target) or ".", exist_ok=True)
        with open(target, "w", encoding="utf-8") as fh:
            fh.write("SBX-MARK\n")
        return {"path": target, "result": "MADE"}
    except OSError as exc:
        return {"path": target, "result": "BLOCKED", "error": f"{type(exc).__name__}: {exc}"}


def probe_read(path: str) -> dict:
    target = os.path.expanduser(path)
    try:
        with open(target, encoding="utf-8", errors="replace") as fh:
            head = fh.read(64)
        return {"path": target, "result": "READ", "head": head[:32]}
    except OSError as exc:
        return {"path": target, "result": "BLOCKED", "error": f"{type(exc).__name__}: {exc}"}


def probe_env(name: str) -> dict:
    """환경 변수가 가리키는 곳에 **실제로 쓸 수 있는지** 본다.

    캐시 폴더(HF_HOME 등)가 샌드박스 안에서 쓰기 가능한지 보는 장치다.
    """
    value = os.environ.get(name, "")
    if not value:
        return {"path": f"${name}", "result": "UNSET"}
    target = os.path.join(value, f"{name.lower()}-probe.txt")
    got = probe_write(target)
    return {**got, "env": name, "value": value}


def probe_tempfile() -> dict:
    """`tempfile` 이 쓰는 곳. `TMPDIR` 을 따라간다.

    샌드박스의 `/tmp` 는 tmpfs(메모리)라 큰 임시 파일이면 메모리가 터진다.
    그래서 `TMPDIR` 이 **진짜 디스크**를 가리켜야 한다.
    """
    import tempfile

    try:
        handle, path = tempfile.mkstemp(prefix="labremote-tmp-")
        with os.fdopen(handle, "w", encoding="utf-8") as fh:
            fh.write("SBX-MARK\n")
        return {"path": path, "result": "MADE", "env": "TMPDIR", "value": tempfile.gettempdir()}
    except OSError as exc:
        return {"path": "", "result": "BLOCKED", "env": "TMPDIR", "error": str(exc)}


def spawn_children(count: int, sleep_sec: float) -> list[int]:
    """오래 자는 자식들. 학습을 끝낼 때 **손자까지** 정리되는지 보는 장치다."""
    pids = []
    for _ in range(count):
        child = subprocess.Popen(
            [sys.executable, "-c", f"import time; time.sleep({sleep_sec})"],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        pids.append(child.pid)
    return pids


def main() -> int:
    parser = argparse.ArgumentParser(description="가짜 학습")
    parser.add_argument("--epochs", type=int, default=3)
    parser.add_argument("--lr", default="1e-4")
    parser.add_argument("--sleep", type=float, default=0.0)
    parser.add_argument("--out", default="")
    parser.add_argument("--resume-from", default="")
    parser.add_argument("--children", type=int, default=0)
    parser.add_argument("--child-sleep", type=float, default=600.0)
    parser.add_argument("--nan-at", type=int, default=0)
    parser.add_argument("--diverge-at", type=int, default=0)
    parser.add_argument("--oom-at", type=int, default=0)
    parser.add_argument("--crash-at", type=int, default=0)
    parser.add_argument("--probe-write", action="append", default=[])
    parser.add_argument("--probe-read", action="append", default=[])
    parser.add_argument("--probe-env", action="append", default=[])
    parser.add_argument("--probe-tempfile", action="store_true")
    args = parser.parse_args()

    exp_dir = args.out or os.environ.get("LAB_EXP_DIR") or os.getcwd()
    output = os.path.join(exp_dir, "output")
    os.makedirs(output, exist_ok=True)

    probes = [probe_write(p) for p in args.probe_write]
    probes += [probe_read(p) for p in args.probe_read]
    probes += [probe_env(name) for name in args.probe_env]
    if args.probe_tempfile:
        probes.append(probe_tempfile())
    for item in probes:
        log(f"[probe] {item['result']:8} {item['path']}" + (f"  {item.get('error','')}" if item.get("error") else ""))
    if probes:
        with open(os.path.join(output, "probes.json"), "w", encoding="utf-8") as fh:
            json.dump(probes, fh, ensure_ascii=False, indent=2)

    if args.children:
        pids = spawn_children(args.children, args.child_sleep)
        log(f"[설정] 자식 {len(pids)}개를 띄웠어요: {pids}")
        with open(os.path.join(output, "children.json"), "w", encoding="utf-8") as fh:
            json.dump(pids, fh)

    start_epoch = 0
    if args.resume_from:
        try:
            with open(args.resume_from, encoding="utf-8") as fh:
                start_epoch = int(json.load(fh).get("epoch", 0))
            log(f"[재개] {args.resume_from} 에서 {start_epoch} 에폭까지 돌렸어요")
        except (OSError, ValueError, json.JSONDecodeError) as exc:
            log(f"[재개] 체크포인트를 못 읽었어요: {exc}")

    result_path = os.path.join(exp_dir, "result.csv")
    fresh = start_epoch == 0 or not os.path.exists(result_path)
    with open(result_path, "a" if not fresh else "w", encoding="utf-8", newline="") as fh:
        writer = csv.writer(fh)
        # 열 규약은 templates/result_example.csv 와 같다 (긴 형식).
        if fresh:
            writer.writerow(["step", "split", "metric", "value"])
        for epoch in range(start_epoch + 1, args.epochs + 1):
            if args.sleep:
                time.sleep(args.sleep)
            loss = round(2.0 / epoch, 4)
            if args.nan_at and epoch >= args.nan_at:
                loss = float("nan")
            if args.diverge_at and epoch >= args.diverge_at:
                loss = round(2.0 * 10 * epoch, 4)
            accuracy = round(min(0.99, 0.5 + 0.1 * epoch), 4)
            writer.writerow([epoch, "train", "loss", loss])
            writer.writerow([epoch, "val", "loss", round(loss * 1.1, 4)])
            writer.writerow([epoch, "val", "accuracy", accuracy])
            fh.flush()
            if args.oom_at and epoch >= args.oom_at:
                log("RuntimeError: CUDA out of memory. Tried to allocate 2.00 GiB")
            log(f"epoch {epoch}/{args.epochs}  loss={loss}  val_acc={accuracy}  lr={args.lr}")

            checkpoint = os.path.join(output, f"epoch_{epoch:03d}.ckpt")
            with open(checkpoint, "w", encoding="utf-8") as ck:
                json.dump({"epoch": epoch, "loss": None if loss != loss else loss}, ck)
            if args.crash_at and epoch >= args.crash_at:
                log(f"[실패] {epoch} 에폭에서 일부러 죽어요")
                return 3

    with open(os.path.join(output, "best.ckpt"), "w", encoding="utf-8") as fh:
        json.dump({"epoch": args.epochs, "note": "가짜 best"}, fh)
    with open(os.path.join(output, "final.ckpt"), "w", encoding="utf-8") as fh:
        json.dump({"epoch": args.epochs, "note": "가짜 final"}, fh)
    log("[완료] 가짜 학습이 끝났어요")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
