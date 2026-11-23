"""`labremote` 명령 (v3).

서브커맨드는 라이브러리 함수를 얇게 감싼다. 로직은 모듈에 있고 여기는 인자
해석과 출력만 맡는다 — 서버(FastAPI)가 같은 함수를 부를 수 있게.

지금 있는 것: `doctor`, `notify test`, `service install|status`, `monitor once`.
`serve`(1단계), `run`(2단계), `autostart`(9단계)는 해당 단계에서 더한다
(docs/v3/PLAN.md 4.1 · 6장).
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time

from . import doctor, registry

__all__ = ["main", "build_parser"]


def cmd_doctor(args) -> int:
    report = doctor.run()
    if args.json:
        print(json.dumps(report, ensure_ascii=False, indent=2))
    else:
        print(doctor.render(report))
    return 0 if report["ok"] else 1


def cmd_notify(args) -> int:
    """🔔 웹훅을 한 번 쏴 본다. **주소는 찍지 않는다.**"""
    from . import db as db_mod
    from . import notifier, notify

    if not notify.webhook_url():
        print("✘ 웹훅 주소가 없어요 — Inbox 화면에서 넣어 주세요", file=sys.stderr)
        return 2
    with db_mod.open_db() as conn:
        got = notifier.send(
            conn,
            "test",
            project=args.name or "",
            subject=f"test-{int(time.time())}",
            title="알림이 닿았어요",
            body="`labremote notify test` 로 보낸 시험 알림이에요.",
            fields=[("보낸 쪽", notify.USER_AGENT)],
        )
    # `notifier.send` 는 `sent`·`status` 를 돌려준다 (`ok` 가 아니다).
    if got.get("suppressed"):
        print("· 방금 같은 알림을 보내서 이번 건은 눌렸어요 (중복 제거).")
        return 0
    if not got.get("sent"):
        print(f"✘ 못 보냈어요: {got.get('reason') or got.get('error') or '사유 없음'}",
              file=sys.stderr)
        if got.get("status") == 403:
            print("  403 이면 웹훅 주소가 틀렸거나 지워졌을 수 있어요.", file=sys.stderr)
        return 2
    print(f"✔ 보냈어요 (상태 {got.get('status')})")
    return 0


def cmd_service(args) -> int:
    """⚙️ 자동 시작 유닛을 **렌더**한다. 활성화는 사람이 한다."""
    from .service import units

    if args.action == "install":
        if args.dry_run:
            for name in sorted(units.UNITS):
                print(f"--- {units.unit_path(name)} ---")
                print(units.render(name))
            return 0
        got = units.install()
        print(f"✔ 유닛을 썼어요: {got['dir']}")
        for path in got["written"]:
            mark = "바뀜" if path in got["changed"] else "그대로"
            print(f"  {os.path.basename(path)}  ({mark})")
        print()
        print("활성화는 **사람이** 해 주세요 (sudo 는 필요 없어요):")
        for line in units.enable_commands():
            print(f"  {line}")
        return 0

    got = units.status()
    if args.json:
        print(json.dumps(got, ensure_ascii=False, indent=2))
        return 0
    if not got["systemctl"]:
        print("systemctl 이 없어요 — systemd 가 아닌 환경이에요.")
        return 1
    linger = got["linger"]
    print("linger   " + ("켜져 있어요" if linger else
                         "꺼져 있어요 — 로그아웃하면 서버가 내려가요" if linger is False
                         else "못 읽었어요"))
    for name, row in sorted(got["units"].items()):
        print(f"{name}")
        print(f"  유닛 파일  {'있어요' if row['file'] else '없어요 (labremote service install)'}")
        print(f"  enabled   {row.get('enabled')}")
        print(f"  active    {row.get('active')}")
    return 0


def cmd_monitor(args) -> int:
    """📈 GPU·호스트를 한 번 읽는다."""
    from .monitor import gpu as gpu_mod
    from .monitor import host as host_mod

    # CPU 는 **두 표본의 차분**이다 (/proc/stat). 짧게 두 번 읽는다.
    before = host_mod.cpu_times()
    time.sleep(0.2)
    gpu = gpu_mod.probe()
    host = host_mod.probe(registry.data_dir(), before=before)
    if args.json:
        print(json.dumps({"gpu": gpu, "host": host}, ensure_ascii=False, indent=2))
        return 0
    devices = gpu.get("devices") or []
    if devices:
        for d in devices:
            print(f"GPU    {d.get('name')} · {d.get('utilPct')}% · "
                  f"{d.get('memUsedMb')}/{d.get('memTotalMb')}MB · {d.get('tempC')}°C")
    else:
        print(f"GPU    조회 불가 — {gpu.get('reason') or '사유 없음'}")
    memory = host.get("memory") or {}
    disk = host.get("disk") or {}
    print(f"호스트  CPU {host.get('cpuPct')}% · RAM {memory.get('pct')}%"
          f" · 디스크 여유 {disk.get('freeGb')}GB")
    return 0


# --- 파서 -------------------------------------------------------------------


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="labremote", description="lab.remote")
    parser.add_argument("--json", action="store_true", help="JSON 으로 출력해요")
    sub = parser.add_subparsers(dest="command", required=True)

    p = sub.add_parser("doctor", help="설치와 환경 점검")
    p.set_defaults(func=cmd_doctor)

    p = sub.add_parser("notify", help="알림 시험 (주소는 안 찍어요)")
    p.add_argument("action", choices=["test"])
    p.add_argument("name", nargs="?", help="프로젝트 이름 (선택)")
    p.set_defaults(func=cmd_notify)

    p = sub.add_parser("service", help="자동 시작 유닛 렌더 (활성화는 사람이)")
    p.add_argument("action", choices=["install", "status"])
    p.add_argument("--dry-run", action="store_true", help="쓰지 않고 내용만 보여 줘요")
    p.set_defaults(func=cmd_service)

    p = sub.add_parser("monitor", help="GPU·호스트를 한 번 읽어요")
    p.add_argument("action", choices=["once"])
    p.set_defaults(func=cmd_monitor)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(list(sys.argv[1:] if argv is None else argv))
    try:
        return args.func(args)
    except (registry.InvalidName, RuntimeError) as exc:
        print(f"✘ {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
