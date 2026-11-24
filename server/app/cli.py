"""`labremote` 명령 (v3).

서브커맨드는 라이브러리 함수를 얇게 감싼다. 로직은 모듈에 있고 여기는 인자
해석과 출력만 맡는다 — 서버(FastAPI)가 같은 함수를 부를 수 있게.

지금 있는 것: `serve`, `run`, `runs`, `doctor`, `notify test`,
`autostart install|uninstall|status`, `remote set|clear|show`, `monitor once`
(docs/v3/PLAN.md 4.1 · 6장).
"""

from __future__ import annotations

import argparse
import json
import os
import shlex
import sys
import time

from . import doctor, projects, registry

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
        print("✘ 웹훅 주소가 없어요 — Inbox 화면에서 입력해 주세요", file=sys.stderr)
        return 2
    with db_mod.open_db() as conn:
        got = notifier.send(
            conn,
            "test",
            project=args.name or "",
            subject=f"test-{int(time.time())}",
            title="알림이 도착했어요",
            body="`labremote notify test`로 보낸 테스트 알림이에요.",
            fields=[("보낸 곳", notify.USER_AGENT)],
        )
    # `notifier.send`는 `sent`·`status`를 돌려준다 (`ok`가 아니다).
    if got.get("suppressed"):
        print("· 방금 같은 알림을 보내서 이번 건은 건너뛰었어요 (중복 제거).")
        return 0
    if not got.get("sent"):
        print(f"✘ 보내지 못했어요: {got.get('reason') or got.get('error') or '사유 없음'}",
              file=sys.stderr)
        if got.get("status") == 403:
            print("  403이면 웹훅 주소가 틀렸거나 지워졌을 수 있어요.", file=sys.stderr)
        return 2
    print(f"✔ 보냈어요 (상태 {got.get('status')})")
    return 0


def _confirm(question: str, yes: bool) -> bool:
    if yes:
        return True
    if not sys.stdin.isatty():
        print("✘ 확인할 수 없어요 — 터미널에서 실행하거나 --yes 옵션을 붙여 주세요.", file=sys.stderr)
        return False
    try:
        return input(f"{question} [y/N] ").strip().lower() in ("y", "yes", "네", "ㅇ")
    except EOFError:
        return False


def cmd_autostart(args) -> int:
    """⚙️ 자동 시작 — 사용자 서비스 하나 + (꺼져 있으면) linger. 바꾸기 전에 묻는다."""
    from .service import autostart, units

    if args.action == "status":
        got = units.status()
        if args.json:
            print(json.dumps({**got, "record": autostart.record()}, ensure_ascii=False, indent=2))
            return 0
        if not got["systemctl"]:
            print("systemctl이 없어요 — systemd가 아닌 환경이에요.")
            return 1
        row = got["units"].get(units.NAME) or {}
        print(f"{units.NAME}  유닛 {'있어요' if row.get('file') else '없어요'} · {row.get('enabled')} · {row.get('active')}"
              + (f" · 포트 {row['port']}" if row.get("port") else "")
              + (f" · 재시작 {row['restarts']}회" if row.get("restarts") is not None else ""))
        linger = got["linger"]
        print("linger    " + ("활성화돼 있어요" if linger else "비활성화돼 있어요" if linger is False else "확인하지 못했어요"))
        tmux = units._tmux() or "tmux"
        print(f"서버 출력  {tmux} -L {units.TMUX_SOCKET} attach -t {units.TMUX_SOCKET}   (터미널에서 실행 · 나갈 때는 Ctrl+b d)")
        print(f"          {tmux} -L {units.TMUX_SOCKET} capture-pane -p -t {units.TMUX_SOCKET}   (터미널 없이 현재 화면만)")
        return 0

    try:
        if args.action == "install":
            if args.dry_run:
                print(f"--- {units.unit_path()} ---")
                print(units.render(port=args.port))
                return 0
            print("자동 시작을 켜면 다음 항목이 변경돼요 (sudo는 필요 없어요):")
            for st in autostart.plan(port=args.port):
                print(f"  · {st['what']}\n      {st['detail']}")
            print("code tunnel은 여기서 설정하지 않아요. 따로 `code tunnel service install`로 설치해 주세요 (docs/SETUP.md).")
            if not _confirm("켤까요?", args.yes):
                print("취소했어요. 아무것도 바꾸지 않았어요.")
                return 1
            steps = autostart.install(port=args.port)
        else:
            if not os.path.exists(units.unit_path()) and not autostart.record():
                print("자동 시작이 이미 비활성화돼 있어요.")
                return 0
            print("자동 시작을 끄면 서비스를 중지하고 유닛 파일을 삭제해요. linger는 lab.remote가 활성화한 경우에만 원래대로 되돌려요"
                  " (code tunnel 서비스도 linger를 사용하므로 그 서비스가 있으면 유지해요).")
            print("학습은 서비스와 별도로 실행되므로 중지되지 않아요.")
            if not _confirm("끌까요?", args.yes):
                print("취소했어요. 아무것도 바꾸지 않았어요.")
                return 1
            steps = autostart.uninstall()
    except autostart.AutostartError as exc:
        print(f"✘ {exc}", file=sys.stderr)
        return 2
    for st in steps:
        print(f"{'✔' if st['ok'] else '⚠'} {st['what']}" + (f" — {st['detail']}" if st.get("detail") else ""))
    if args.action == "install":
        print(f"\n서버 출력 보기: {units._tmux() or 'tmux'} -L {units.TMUX_SOCKET} attach -t {units.TMUX_SOCKET}   (터미널에서 실행)")
    return 0


def cmd_remote(args) -> int:
    """🌐 바깥 주소 — 터널로 전달한 lab.remote 주소 (Host 허용 + Discord 답하기 링크)."""
    from . import remote, tunnel

    try:
        if args.action == "set":
            if not args.url:
                print("✘ 주소를 입력해 주세요: labremote remote set https://…", file=sys.stderr)
                return 2
            got = remote.set_url(args.url)
            print(f"✔ 외부 주소를 등록했어요: {got['publicUrl']}")
            print("  이제 서버가 이 주소로 들어오는 요청을 받아요. Discord 알림에 '답하기' 링크가 추가돼요.")
            return 0
        if args.action == "clear":
            remote.clear()
            print("✔ 외부 주소를 지웠어요.")
            return 0
    except remote.RemoteError as exc:
        print(f"✘ {exc}", file=sys.stderr)
        return 2
    info = remote.info()
    t = tunnel.status(fresh=True)
    if args.json:
        print(json.dumps({**info, "tunnel": t}, ensure_ascii=False, indent=2))
        return 0
    state = {"up": "실행 중이에요", "off": "실행 중이 아니에요", "absent": "VS Code CLI가 없어요", "unknown": "확인하지 못했어요"}[t["state"]]
    print(f"code tunnel  {state}" + (f" · {t['url']}" if t["url"] else "")
          + (" · 서비스로 설치됨" if t["service"] else "")
          + ("" if t["loggedIn"] is None else " · 로그인됨" if t["loggedIn"] else " · 로그인 안 됨"))
    print(f"외부 주소     {info['publicUrl'] or '없음 (labremote remote set https://…)'}")
    if info["envHosts"]:
        print(f"LAB_ALLOWED_HOSTS  {', '.join(info['envHosts'])}")
    return 0


def cmd_monitor(args) -> int:
    """📈 GPU·호스트를 한 번 읽는다."""
    from .monitor import gpu as gpu_mod
    from .monitor import host as host_mod

    # CPU는 **두 표본의 차분**이다 (/proc/stat). 짧게 두 번 읽는다.
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


def lower_priority() -> dict:
    """nice 19 + ionice idle. 실패해도 서버는 뜬다 — 무엇이 됐는지만 알린다."""
    import shutil
    import subprocess

    out = {"nice": None, "ionice": False}
    try:
        current = os.getpriority(os.PRIO_PROCESS, 0)
        if current < 19:
            os.setpriority(os.PRIO_PROCESS, 0, 19)
        out["nice"] = os.getpriority(os.PRIO_PROCESS, 0)
    except OSError:
        pass
    ionice = shutil.which("ionice")
    if ionice:
        try:
            done = subprocess.run(
                [ionice, "-c", "3", "-p", str(os.getpid())], capture_output=True, timeout=5
            )
            out["ionice"] = done.returncode == 0
        except (OSError, subprocess.SubprocessError):
            pass
    return out


def cmd_serve(args) -> int:
    """`127.0.0.1`에만 연다. 다른 주소로 여는 옵션은 일부러 없다."""
    try:
        import uvicorn

        from .main import create_app
    except ImportError:
        print("✘ fastapi · uvicorn이 설치돼 있지 않아요 — pip install -e '.[api]'", file=sys.stderr)
        return 2
    prio = lower_priority()
    print(
        f"lab.remote · http://127.0.0.1:{args.port} · nice {prio['nice']} · "
        f"ionice {'idle' if prio['ionice'] else '기본값'}",
        flush=True,
    )
    # 열린 SSE(실시간 갱신) 연결이 있으면 uvicorn은 끝없이 기다린다 — 5초 뒤에는 끊고 끝낸다
    # (자동 시작이 서버를 다시 띄울 수 있게. 실측 2026-11-23: 브라우저 탭 하나로 멈췄어요)
    # 쉬는 연결을 75초 유지 — 기본 5초면 터널(code tunnel)이 15초 간격 요청마다 중계 세션과
    # SSH 키 교환을 새로 해서 밖에서 볼 때 매번 느려요 (실측 2026-11-24: 30분에 중계 세션 54번)
    uvicorn.run(
        create_app(port=args.port),
        host="127.0.0.1",
        port=args.port,
        log_level="warning",
        timeout_graceful_shutdown=5,
        timeout_keep_alive=75,
    )
    return 0


def _project_here(name: str | None) -> tuple[str, str, str]:
    """`(이름, 루트, 지금 폴더의 루트 기준 상대 경로)`. 이름을 안 주면 지금 폴더로 찾는다."""
    from . import paths

    if name:
        root = projects.require(name)
        return name, root, ""
    hit = registry.lookup(os.getcwd())
    if not hit:
        raise RuntimeError("등록한 프로젝트 폴더 안에서 실행하거나 -p <이름> 옵션을 붙여 주세요.")
    root, found = hit
    rel = paths.rel_or_none(root, paths.real(os.getcwd())) or ""
    return found, root, "" if rel == "." else rel


def cmd_run(args) -> int:
    """`labremote run [-p 이름] [--env E | --no-env] [--name N] -- 명령…`"""
    from . import runs

    command = list(args.command or [])
    if command and command[0] == "--":
        command = command[1:]
    if not command:
        print("✘ 실행할 명령을 -- 뒤에 지정해 주세요: labremote run -- python train.py", file=sys.stderr)
        return 2
    name, root, here = _project_here(args.project)
    env = "" if args.no_env else (args.env or projects.load_settings(root).get("condaEnv") or "")
    text = command[0] if len(command) == 1 else " ".join(shlex.quote(c) for c in command)
    try:
        run = runs.start(name, text, env=env, cwd=args.cwd if args.cwd is not None else here, name=args.name or "")
    except runs.RunError as exc:
        print(f"✘ {exc}", file=sys.stderr)
        return 2
    if args.json:
        print(json.dumps(run, ensure_ascii=False, indent=2))
    else:
        print(f"▶ 실행을 시작했어요: {name} · {run['id']} ({'conda ' + env if env else 'conda 없이'})")
        print(f"  로그     {run['log']}")
        print(f"  접속     {run['attach']}")
    return 0


def cmd_runs(args) -> int:
    from . import runs

    name, _root, _here = _project_here(args.project)
    try:
        if args.action == "list":
            items = runs.list_runs(name)
            if args.json:
                print(json.dumps(items, ensure_ascii=False, indent=2))
            else:
                for r in items:
                    code = "" if r.get("exitCode") is None else f" · 종료 코드 {r['exitCode']}"
                    print(f"{r['id']:<9} {r['stateLabel']:<5} {r.get('name') or ''} {r['command'][:60]}{code}")
                if not items:
                    print("실행 기록이 없어요.")
            return 0
        if not args.id:
            print("✘ 실행 번호(EXP-…)를 지정해 주세요.", file=sys.stderr)
            return 2
        if args.action == "stop":
            r = runs.stop(name, args.id, force=args.force)
            print(f"■ {r['id']} · {r['stateLabel']}")
            return 0
        print(runs.log_tail(name, args.id, lines=args.lines)["text"])
        return 0
    except runs.RunError as exc:
        print(f"✘ {exc}", file=sys.stderr)
        return 2


# --- 파서 -------------------------------------------------------------------


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="labremote", description="lab.remote")
    parser.add_argument("--json", action="store_true", help="JSON으로 출력해요")
    sub = parser.add_subparsers(dest="command", required=True)

    p = sub.add_parser("serve", help="서버를 실행해요 (127.0.0.1에서만)")
    p.add_argument("--port", type=int, default=8000)
    p.set_defaults(func=cmd_serve)

    p = sub.add_parser("run", help="명령을 실행해요 (접속이 끊겨도 계속 실행)")
    p.add_argument("-p", "--project", help="프로젝트 이름 (생략하면 현재 폴더)")
    p.add_argument("--env", help="conda 환경 (생략하면 프로젝트 설정의 기본 환경)")
    p.add_argument("--no-env", action="store_true", help="conda 없이 실행해요")
    p.add_argument("--cwd", help="프로젝트 안의 실행 위치 (생략하면 현재 폴더)")
    p.add_argument("--name", help="실행 이름 (생략하면 EXP 번호만)")
    p.add_argument("command", nargs=argparse.REMAINDER, help="-- 뒤에 실행할 명령")
    p.set_defaults(func=cmd_run)

    p = sub.add_parser("runs", help="실행 기록 보기 · 중지 · 로그")
    p.add_argument("action", choices=["list", "stop", "log"], nargs="?", default="list")
    p.add_argument("id", nargs="?", help="EXP-…")
    p.add_argument("-p", "--project")
    p.add_argument("--force", action="store_true", help="stop: tmux 세션 전체를 종료해요")
    p.add_argument("--lines", type=int, default=200)
    p.set_defaults(func=cmd_runs)

    p = sub.add_parser("doctor", help="설치와 환경 점검")
    p.set_defaults(func=cmd_doctor)

    p = sub.add_parser("notify", help="테스트 알림 보내기 (주소는 출력하지 않아요)")
    p.add_argument("action", choices=["test"])
    p.add_argument("name", nargs="?", help="프로젝트 이름 (선택)")
    p.set_defaults(func=cmd_notify)

    p = sub.add_parser("autostart", help="자동 시작 켜기 · 끄기 (변경하기 전에 확인해요)")
    p.add_argument("action", choices=["install", "uninstall", "status"])
    p.add_argument("--port", type=int, default=8000)
    p.add_argument("--yes", action="store_true", help="묻지 않고 진행해요")
    p.add_argument("--dry-run", action="store_true", help="install: 유닛 내용만 보여 줘요")
    p.set_defaults(func=cmd_autostart)

    p = sub.add_parser("remote", help="외부 주소(터널로 전달한 주소) · 터널 상태")
    p.add_argument("action", choices=["show", "set", "clear"], nargs="?", default="show")
    p.add_argument("url", nargs="?")
    p.set_defaults(func=cmd_remote)

    p = sub.add_parser("monitor", help="GPU · 호스트 상태를 한 번 조회해요")
    p.add_argument("action", choices=["once"])
    p.set_defaults(func=cmd_monitor)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(list(sys.argv[1:] if argv is None else argv))
    try:
        return args.func(args)
    except (registry.InvalidName, RuntimeError, projects.ProjectError) as exc:
        print(f"✘ {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
