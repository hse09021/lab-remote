"""`labremote` 명령.

서브커맨드는 전부 라이브러리 함수를 얇게 감싼다. 로직은 모듈에 있고 여기는
인자 해석과 출력만 맡는다 — ③단계의 FastAPI 가 같은 함수를 부를 수 있게.
"""

from __future__ import annotations

import argparse
import json
import sys

from . import approval_log, doctor, policy, registry, runstate
from .generator import scaffold
from .generator.spec import ProjectSpec
from . import policy_defaults as D
from .hooks import check as hooks_check
from .hooks import install as hooks_install

__all__ = ["main"]


def _print(data, as_json: bool, text: str = "") -> None:
    if as_json:
        print(json.dumps(data, ensure_ascii=False, indent=2))
    else:
        print(text)


# --- init-project -----------------------------------------------------------


def cmd_init_project(args) -> int:
    spec = ProjectSpec(
        name=args.name,
        goal=args.goal or ProjectSpec(name=args.name).goal,
        mode=args.mode,
        env_name=args.env_name or "",
        first_exp=args.first_exp or "",
        remote=args.remote or "",
    )

    if args.dry_run:
        report = scaffold.dry_run(spec)
        if args.json:
            print(json.dumps(report, ensure_ascii=False, indent=2))
        else:
            print(f"만들 곳   {report['target']}")
            print(f"파일      {report['count']}개\n")
            print(report["tree"])
        return 0

    result = scaffold.create_project(spec, if_exists=args.if_exists, create_env=args.create_env)
    if args.json:
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 0

    if args.if_exists == "update":
        print(f"갱신      {result['target']}")
        print(f"추가      {len(result['added'])}개")
        print(f"다시 씀   {', '.join(result['refreshed'])}")
        if result.get("backup"):
            print(f"백업      {result['backup']}")
        return 0

    print(f"만들었어요 {result['target']}")
    print(f"파일       {result['count']}개")
    print(f"첫 커밋    {result['commit'][:12]}")
    print(f"정책       {result['policy']} ({result['mode']})")
    print(f"conda      {result['env'].get('reason')}")
    if result.get("remote"):
        print(f"원격       {result['remote']} (push 는 ②에서)")
    print()
    print("다음에 할 일")
    print(f"  cd {result['target']}")
    print("  labremote hooks install --mode enforce")
    print("  labremote hooks check")
    return 0


# --- hooks ------------------------------------------------------------------


def cmd_hooks(args) -> int:
    if args.hooks_cmd == "check":
        report = hooks_check.run_check(args.project)
        if args.json:
            print(json.dumps(report, ensure_ascii=False, indent=2))
            return 0 if report["ok"] else 1
        if "rows" not in report:
            print(f"✘ {report['reason']}")
            return 1
        print(f"프로젝트  {report['project']} ({report['root']})\n")
        for row in report["rows"]:
            mark = "✔" if row["ok"] else "✘"
            print(f"{mark} {row['label']:<18} 기대 {row['expected']:<6} 실제 {row['got']}")
        print()
        print("전부 통과했어요" if report["ok"] else "다른 결과가 있어요")
        return 0 if report["ok"] else 1

    return hooks_install.main([args.hooks_cmd] + _install_flags(args))


def _install_flags(args) -> list[str]:
    flags = []
    for name in ("mode", "python", "roots"):
        value = getattr(args, name, None)
        if value:
            flags += [f"--{name}", value]
    return flags


# --- policy -----------------------------------------------------------------


def cmd_policy(args) -> int:
    if args.policy_cmd == "sync-template":
        print(policy.write_template())
        return 0

    pol = policy.load(args.project)
    if args.policy_cmd == "show":
        if args.json:
            print(json.dumps(pol.data, ensure_ascii=False, indent=2))
            return 0
        print(f"프로젝트  {pol.name} ({pol.root})")
        print(f"정책 파일 {pol.path}")
        print(f"프리셋    {pol.effective_mode()}\n")
        for action in pol.data["actions"]:
            key = action["key"]
            lock = " 🔒" if action["locked"] else "  "
            print(f"{lock} {action['name']:<24} {D.LABELS[pol.resolve(key)]}")
        return 0

    overrides = {}
    for item in args.override or []:
        key, _, value = item.partition("=")
        overrides[key.strip()] = value.strip()
    pol.set_saved(args.mode or pol.effective_mode(), overrides)
    policy.save(pol)

    approval_log.log_event(
        approval_log.event_path(pol.root, pol),
        {"event": "policy-set", "mode": pol.effective_mode(), "overrides": overrides, "by": "cli"},
    )
    _append_decision(pol, overrides)
    print(f"저장했어요 {pol.path}")
    print(f"프리셋     {pol.effective_mode()}")
    if overrides:
        print(f"예외       {overrides}")
    print("실행 중인 실험에는 적용되지 않아요. 다음 작업부터 반영돼요.")
    return 0


def _append_decision(pol, overrides: dict) -> None:
    """권한 변경을 Decision_log.md 에 한 줄 남긴다."""
    import os

    from . import loop_layout as L

    path = os.path.join(pol.root, L.LOOP_LAYOUT["decision_log"])
    try:
        with open(path, "a", encoding="utf-8") as fh:
            fh.write(
                f"\n## {approval_log.now()} · 권한 설정 변경\n\n"
                f"- 프리셋: {pol.effective_mode()}\n"
                f"- 예외: {overrides or '없음'}\n"
                "- 실행 중인 실험에는 적용되지 않아요 (다음 작업부터).\n"
            )
    except OSError:
        pass


# --- run-state --------------------------------------------------------------


def cmd_run_state(args) -> int:
    if args.idle:
        runstate.set_idle(args.project)
    elif args.running:
        runstate.set_running(args.project, args.running, pid=args.pid)

    state = runstate.load(args.project)
    if args.json:
        print(json.dumps(state.__dict__, ensure_ascii=False, indent=2))
        return 0
    print(f"실행 중    {'예 · ' + str(state.experiment_id) if state.running else '아니요'}")
    if state.stale:
        print("           ⚠ running 인데 프로세스가 없어요")
    print(f"시작된 실험 {', '.join(state.started or []) or '없음'}")
    return 0


# --- log --------------------------------------------------------------------


def cmd_log(args) -> int:
    root = registry.root_of(args.project)
    if not root:
        print(f"등록되지 않은 프로젝트예요: {args.project}")
        return 1
    rows = approval_log.read_rows(approval_log.log_path(root))
    tail = rows[-args.number :] if args.number else rows
    if args.json:
        print(json.dumps(tail, ensure_ascii=False, indent=2))
        return 0
    if not tail:
        print("기록이 아직 없어요")
        return 0
    for row in tail:
        pending = " (대기)" if row.get("resultPending") == "true" else ""
        print(f"{row['time']}  {row['action']:<22} {row['result']}{pending}  {row['request'][:60]}")
    return 0


# --- doctor -----------------------------------------------------------------


def cmd_doctor(args) -> int:
    report = doctor.run()
    if args.json:
        print(json.dumps(report, ensure_ascii=False, indent=2))
    else:
        print(doctor.render(report))
    return 0 if report["ok"] else 1


# --- 파서 -------------------------------------------------------------------


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="labremote", description="lab.remote 실험 프로젝트와 권한 훅")
    parser.add_argument("--json", action="store_true", help="결과를 JSON 으로")
    sub = parser.add_subparsers(dest="cmd", required=True)

    p = sub.add_parser("init-project", help="실험 프로젝트를 만들어요")
    p.add_argument("name")
    p.add_argument("--goal", help="연구 목표 한 줄")
    p.add_argument("--mode", choices=list(D.MODE_IDS), default=D.DEFAULT_MODE)
    p.add_argument("--env-name", help="conda 환경 이름 (기본: 프로젝트 이름)")
    p.add_argument("--first-exp", help="첫 실험 폴더 (예: EXP-001)")
    p.add_argument("--remote", help="origin 으로 달 URL (push 는 ②에서)")
    p.add_argument("--if-exists", choices=["fail", "update"], default="fail")
    p.add_argument("--create-env", action="store_true", help="conda 환경도 실제로 만들어요")
    p.add_argument("--dry-run", action="store_true", help="만들 파일 목록만 보여 줘요")
    p.set_defaults(func=cmd_init_project)

    p = sub.add_parser("hooks", help="훅 설치·제거·확인")
    hsub = p.add_subparsers(dest="hooks_cmd", required=True)
    hi = hsub.add_parser("install")
    hi.add_argument("--mode", choices=sorted(hooks_install.MODES), default="enforce")
    hi.add_argument("--python")
    hi.add_argument("--roots")
    hsub.add_parser("uninstall")
    hsub.add_parser("status")
    hc = hsub.add_parser("check", help="설치된 훅에 이벤트를 먹여 기대값과 대조해요")
    hc.add_argument("--project")
    p.set_defaults(func=cmd_hooks)

    p = sub.add_parser("policy", help="권한 정책 조회·변경")
    psub = p.add_subparsers(dest="policy_cmd", required=True)
    ps = psub.add_parser("show")
    ps.add_argument("project")
    pt = psub.add_parser("set")
    pt.add_argument("project")
    pt.add_argument("--mode", choices=list(D.MODE_IDS))
    pt.add_argument("--override", action="append", metavar="행동=권한")
    psub.add_parser("sync-template", help="커밋되는 정책 템플릿을 코드에서 다시 만들어요")
    p.set_defaults(func=cmd_policy)

    p = sub.add_parser("run-state", help="실험 실행 상태를 바꿔요")
    p.add_argument("project")
    p.add_argument("--running", metavar="EXP-NNN")
    p.add_argument("--idle", action="store_true")
    p.add_argument("--pid", type=int)
    p.set_defaults(func=cmd_run_state)

    p = sub.add_parser("log", help="승인 기록 보기")
    p.add_argument("project")
    p.add_argument("-n", "--number", type=int, default=20)
    p.set_defaults(func=cmd_log)

    p = sub.add_parser("doctor", help="설치와 설정 점검")
    p.set_defaults(func=cmd_doctor)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        return args.func(args)
    except (scaffold.ScaffoldError, policy.PolicyError, registry.InvalidName, RuntimeError) as exc:
        print(f"✘ {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
