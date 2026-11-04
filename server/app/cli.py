"""`labremote` 명령.

서브커맨드는 전부 라이브러리 함수를 얇게 감싼다. 로직은 모듈에 있고 여기는
인자 해석과 출력만 맡는다 — ③단계의 FastAPI 가 같은 함수를 부를 수 있게.
"""

from __future__ import annotations

import argparse
import os
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
        print(f"프로젝트  {report['project']} ({report['root']})")
        print("기록      남기지 않아요 (임시 폴더에서 돌렸어요)\n")
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

    if args.policy_cmd == "migrate":
        info = policy.migrate(args.project)
        if args.json:
            print(json.dumps(info, ensure_ascii=False, indent=2))
            return 0
        print(f"정책       {info['path']}")
        print(f"판         {info['from']} → {info['to']}")
        print(f"프리셋     {info['mode']} (그대로 옮겼어요)")
        print(f"예외       {info['overrides'] or '없음'}")
        settings = info["settings"]
        print(
            f"권한 모드  {settings['path']} · defaultMode={settings['mode']}"
            + ("" if settings["changed"] else " (이미 있었어요)")
        )
        log = info["log"]
        if log.get("changed"):
            print(f"승인 로그  {', '.join(log['added'])} 열 추가 · 백업 {log['backup']}")
        else:
            print(f"승인 로그  그대로 ({log.get('reason')})")
        if info["conflicts"]:
            print(f"⚠ 보호 경로와 겹치는 extraWritableRoots: {info['conflicts']}")
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


#: `labremote log` 의 요청 칸 너비
REQUEST_WIDTH = 60


def _shorten(text: str, width: int = REQUEST_WIDTH) -> str:
    """너비에 맞게 줄인다. **경로는 앞을 줄이고** 명령은 뒤를 줄인다.

    실측에서 `…/policies/hook-` 처럼 파일 이름이 잘려 무엇이 막혔는지 알 수
    없었다. 경로는 뒤쪽(파일 이름)이 중요하고, 명령은 앞쪽(명령 이름)이
    중요하다.
    """
    text = str(text or "")
    if len(text) <= width:
        return text
    looks_like_path = "/" in text and " " not in text.strip()
    if looks_like_path:
        return "…" + text[-(width - 1) :]
    return text[: width - 1] + "…"


def cmd_log(args) -> int:
    root = registry.root_of(args.project)
    if not root:
        print(f"등록되지 않은 프로젝트예요: {args.project}")
        return 1
    rows = approval_log.read_rows(approval_log.log_path(root))
    if not args.raw:
        # 한 호출은 한 줄. 늦게 붙은 "허용" 이 "거부 또는 미응답" 을 이긴다.
        rows = approval_log.group_rows(rows)
    tail = rows[-args.number :] if args.number else rows
    if args.json:
        print(json.dumps(tail, ensure_ascii=False, indent=2))
        return 0
    if not tail:
        print("기록이 아직 없어요")
        return 0
    for row in tail:
        pending = " (대기)" if row.get("resultPending") == "true" else ""
        print(
            f"{row['time']}  {row['action']:<22} {row['result']}{pending}  "
            f"{_shorten(row['request'])}"
        )
    return 0


# --- pending ----------------------------------------------------------------


def cmd_pending(args) -> int:
    root = registry.root_of(args.project)
    if not root:
        print(f"등록되지 않은 프로젝트예요: {args.project}")
        return 1

    if args.pending_cmd == "list":
        items = approval_log.list_pending(args.project)
        if args.json:
            print(json.dumps(items, ensure_ascii=False, indent=2))
            return 0
        if not items:
            print("열려 있는 승인 대기 건이 없어요")
            return 0
        for item in items:
            print(
                f"{item.get('openedAt')}  {item.get('action'):<22} "
                f"{_shorten(str(item.get('request') or ''))}"
            )
            print(f"{'':<22}  응답 {item.get('promptId')} · 세션 {item.get('sessionId')}")
            # 서브에이전트 건은 그 에이전트가 멈출 때 닫혀요. 열려 있는 이유가
            # 보이게 한 줄 더 찍어요.
            if item.get("agentId"):
                agent = str(item.get("agentType") or "서브에이전트")
                print(f"{'':<22}  에이전트 {agent} · {str(item['agentId'])[:8]}")
        return 0

    pol = policy.load(args.project)
    closed = approval_log.close_stale(
        args.project, root, pol, session_id=args.session or "", by="cli"
    )
    if args.json:
        print(json.dumps(closed, ensure_ascii=False, indent=2))
        return 0
    if not closed:
        print("닫을 대기 건이 없어요")
        return 0
    for item in closed:
        print(f"닫았어요  {item.get('action')} · {item.get('result')}")
    print(f"\n{len(closed)}건을 마감했어요. 기록에 마감 행을 덧붙였어요.")
    return 0


# --- requests (헤드리스 승인 요청) -------------------------------------------


def cmd_requests(args) -> int:
    root = registry.root_of(args.project)
    if not root:
        print(f"등록되지 않은 프로젝트예요: {args.project}")
        return 1

    items = approval_log.list_requests(args.project)
    if args.requests_cmd == "list":
        if args.json:
            print(json.dumps(items, ensure_ascii=False, indent=2))
            return 0
        if not items:
            print("남아 있는 승인 요청이 없어요")
            return 0
        for item in items:
            print(f"{item.get('openedAt')}  {item.get('requestId')}")
            print(f"  {item.get('action')} · {_shorten(str(item.get('request') or ''))}")
        print("\n②의 승인 대기열이 이 목록을 읽어 가요.")
        return 0

    targets = [args.id] if args.id else [str(i.get("requestId") or "") for i in items]
    pol = policy.load(args.project)
    gone = []
    for request_id in targets:
        if approval_log.clear_request(args.project, request_id):
            gone.append(request_id)
            approval_log.append_row(
                approval_log.log_path(root, pol),
                action="승인 요청 정리",
                request=request_id,
                result="정리됨",
                handled_by="시스템",
                tool_use_id=request_id,
            )
    if args.json:
        print(json.dumps({"cleared": gone}, ensure_ascii=False, indent=2))
        return 0
    print(f"{len(gone)}건을 정리했어요" if gone else "정리할 요청이 없어요")
    return 0


# --- doctor -----------------------------------------------------------------


def cmd_claude(args) -> int:
    """등록된 프로젝트에서 **경계를 지킨 채** 대화형 Claude 를 띄운다.

    맨손 `claude` 로 열면 프로젝트 `.claude/settings.json` 을 읽는다. 거기에
    AI 가 쓴 코드가 훅을 써 넣거나 `sandbox.enabled:false` 를 넣을 수
    있고(M4·M6), 그러면 사람이 여는 세션이 그걸 그대로 쓴다. 그래서 **여는
    길을 하나로 만든다.**

        1. 등록된 프로젝트인지 (아니면 거부 — 훅이 안 뜬다)
        2. projectguard — 변조면 **되돌리고 멈춘다** (`--force` 로만 진행)
        3. `--settings` 파일을 코드에서 다시 쓴다
        4. 헤드리스와 **같은 경계 플래그**로 대화형 claude 를 execvpe
    """
    from .agent import launch as launch_mod
    from .orchestrator import projectguard

    root = registry.root_of(args.name)
    if not root:
        print(f"✘ 등록된 실험 프로젝트가 아니에요: {args.name}", file=sys.stderr)
        print("  labremote init-project <이름> 으로 만들거나 이름을 확인해 주세요.", file=sys.stderr)
        return 2

    report = projectguard.check(root)
    if not report["ok"]:
        print("⚠ " + projectguard.describe(report))
        if not args.force:
            print()
            print("되돌리고 열려면 --force 를 붙여 주세요. 먼저 무엇이 바뀌었는지 보세요:")
            print(f"  {projectguard.settings_path(root)}")
            return 3
        got = projectguard.restore(root, args.name)
        print("↩ 정본으로 되돌렸어요: " + (", ".join(got["restored"]) or "없음"))
        if got.get("evidence"):
            print(f"  원본은 증거로 남겼어요: {got['evidence']}")

    run = launch_mod.AgentRun(
        project=args.name,
        root=root,
        prompt="",
        session_id="",
        permission_mode=args.permission_mode or D.DEFAULT_PERMISSION_MODE,
        headless=False,
        interactive=True,
        extra_flags=list(args.extra or []),
    )
    launch_mod.check_cwd(run)
    run.settings_path = launch_mod.render_settings(root, project=args.name)
    argv = launch_mod.build_argv(run)
    env = launch_mod.build_env(run)

    if args.dry_run:
        print(" ".join(argv))
        return 0

    print(f"▶ {args.name} · {root}")
    print(f"  설정: {run.settings_path}")
    os.chdir(root)
    os.execvpe(argv[0], argv, env)
    return 0  # pragma: no cover — execvpe 는 돌아오지 않는다


def cmd_git_backups(args) -> int:
    """`git bundle` 백업 목록. 복구는 사람이 손으로 한다 (되돌릴 수 없어서)."""
    from .git import bundle as bundle_mod

    root = registry.root_of(args.name)
    if not root:
        print(f"✘ 등록된 실험 프로젝트가 아니에요: {args.name}", file=sys.stderr)
        return 2
    if args.make:
        got = bundle_mod.create(root, args.name, note=args.note or "손으로 떴어요")
        if not got["ok"]:
            print(f"✘ 백업을 못 떴어요: {got['reason']}", file=sys.stderr)
            return 2
        print(f"✔ {got['path']} ({got['bytes']:,}바이트)")
        for dropped in got["pruned"]:
            print(f"  오래된 백업을 지웠어요: {os.path.basename(dropped)}")
        return 0

    items = bundle_mod.listing(args.name)
    if args.json:
        print(json.dumps(items, ensure_ascii=False, indent=2))
        return 0
    if not items:
        print(f"백업이 없어요. 폴더: {bundle_mod.backup_dir(args.name)}")
        print("기록 커밋 때 자동으로 떠요. 지금 뜨려면 --make 를 붙여 주세요.")
        return 0
    print(f"백업 {len(items)}개 · {bundle_mod.backup_dir(args.name)}")
    for item in items:
        checked = bundle_mod.verify(item["path"], root=root, deep=True)
        mark = "✔" if checked["ok"] else "✘"
        note = f" · {item['note']}" if item["note"] else ""
        print(f"  {mark} {item['at']}  {item['bytes']:>10,}바이트{note}")
        if not checked["ok"]:
            print(f"      {checked['reason'][:120]}")
    print()
    print("복구 (되돌릴 수 없어서 사람이 직접 해요):")
    print(f"  git bundle verify {items[0]['path']}")
    print(f"  git clone {items[0]['path']} /tmp/recovered")
    print(f"  cd {root} && git fetch {items[0]['path']} "
          "'refs/heads/*:refs/heads/백업/*'")
    return 0


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
    pm = psub.add_parser("migrate", help="정책 파일을 지금 판으로 올려요 (프리셋·예외는 보존)")
    pm.add_argument("project")
    p.set_defaults(func=cmd_policy)

    p = sub.add_parser("pending", help="승인 대기 건 보기·마감")
    gsub = p.add_subparsers(dest="pending_cmd", required=True)
    gl = gsub.add_parser("list", help="열려 있는 대기 건")
    gl.add_argument("project")
    gs = gsub.add_parser("sweep", help="열려 있는 대기 건을 '거부 또는 미응답' 으로 마감")
    gs.add_argument("project")
    gs.add_argument("--session", help="이 세션 것만")
    p.set_defaults(func=cmd_pending)

    p = sub.add_parser("requests", help="헤드리스에서 막은 승인 요청 (②의 대기열용)")
    rsub = p.add_subparsers(dest="requests_cmd", required=True)
    rl = rsub.add_parser("list")
    rl.add_argument("project")
    rc = rsub.add_parser("clear")
    rc.add_argument("project")
    rc.add_argument("--id", help="이 요청만")
    p.set_defaults(func=cmd_requests)

    p = sub.add_parser("run-state", help="실험 실행 상태를 바꿔요")
    p.add_argument("project")
    p.add_argument("--running", metavar="EXP-NNN")
    p.add_argument("--idle", action="store_true")
    p.add_argument("--pid", type=int)
    p.set_defaults(func=cmd_run_state)

    p = sub.add_parser("log", help="승인 기록 보기")
    p.add_argument("project")
    p.add_argument("-n", "--number", type=int, default=20)
    p.add_argument(
        "--raw",
        action="store_true",
        help="묶지 않고 남은 행 그대로 (append-only 원본)",
    )
    p.set_defaults(func=cmd_log)

    p = sub.add_parser(
        "claude",
        help="실험 프로젝트에서 대화형 Claude 를 띄워요 (경계 플래그를 붙여서)",
    )
    p.add_argument("name")
    p.add_argument(
        "--permission-mode",
        help="권한 모드 (기본: 정책의 값). 대화형은 manual 도 돼요",
    )
    p.add_argument(
        "--force",
        action="store_true",
        help="프로젝트 설정이 변조됐어도 되돌리고 열어요",
    )
    p.add_argument("--dry-run", action="store_true", help="띄우지 않고 명령만 보여 줘요")
    # `--` 뒤의 인자는 `main()` 이 떼어서 `args.extra` 로 넣는다. argparse 의
    # `nargs="*"`·`REMAINDER` 는 둘 다 `--dry-run` 같은 우리 옵션을 같이
    # 먹거나 `--bare` 를 모르는 인자로 거부한다.
    p.set_defaults(extra=[])
    p.set_defaults(func=cmd_claude)

    p = sub.add_parser(
        "git-backups", help="git bundle 백업 보기 (기록 위조에서 되살릴 정본)"
    )
    p.add_argument("name")
    p.add_argument("--make", action="store_true", help="지금 하나 떠요")
    p.add_argument("--note", help="--make 와 함께 · 메모 한 줄")
    p.set_defaults(func=cmd_git_backups)

    p = sub.add_parser("doctor", help="설치와 설정 점검")
    p.set_defaults(func=cmd_doctor)
    return parser


def main(argv: list[str] | None = None) -> int:
    items = list(sys.argv[1:] if argv is None else argv)
    passthrough: list[str] = []
    if "--" in items:
        cut = items.index("--")
        items, passthrough = items[:cut], items[cut + 1 :]
    args = build_parser().parse_args(items)
    if passthrough:
        args.extra = passthrough
    try:
        return args.func(args)
    except (scaffold.ScaffoldError, policy.PolicyError, registry.InvalidName, RuntimeError) as exc:
        print(f"✘ {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
