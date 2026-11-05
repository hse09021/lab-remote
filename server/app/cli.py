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
            if item.get("reason"):
                # 🔑 사유는 **훅이 쓴 값**이다. `permission_denials` 에는 사유
                # 칸이 없다(M2). 승인 내용·지문과 같은 무게로 보면 안 되므로
                # 어디서 왔는지 밝힌다.
                from .orchestrator.approvals import HOOK_REASON_LABEL

                print(f"  {HOOK_REASON_LABEL}: {_shorten(str(item['reason']))}")
        print("\n②의 승인 대기열이 이 목록을 읽어 가요.")
        print("승인 내용과 지문은 오케스트레이터가 claude 결과 JSON 에서 만들어요 —")
        print("이 파일은 참고용이에요.")
        return 0

    targets = [args.id] if args.id else [str(i.get("requestId") or "") for i in items]
    pol = policy.load(args.project)
    gone = []
    for request_id in targets:
        if approval_log.clear_request(args.project, request_id):
            gone.append(request_id)
            approval_log.append_row(
                approval_log.log_path(root, pol),
                project=args.project,
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


def cmd_installs(args) -> int:
    """📦 패키지 설치 승인. 승인하면 **오케스트레이터가 바로 설치한다.**

    Claude 의 Bash 로는 설치가 조용히 실패한다(S1 의 M3) — conda 환경이
    프로젝트 폴더 밖이라 샌드박스가 쓰기를 버린다. 그래서 이 경로가 있다.
    """
    from . import db as db_mod
    from .orchestrator import installs as installs_mod

    with db_mod.open_db() as conn:
        if args.action == "list":
            items = installs_mod.pending(conn, args.name)
            if args.json:
                print(json.dumps(items, ensure_ascii=False, indent=2))
                return 0
            if not items:
                print("기다리는 설치 요청이 없어요.")
                return 0
            for item in items:
                print(f"[{item['id']}] {item['project']} · {item['request']}")
                if item.get("reason"):
                    print(f"      사유: {item['reason']}")
                print(f"      열린 때: {item['opened_at']} · 횟수 {item['attempts']}")
            print()
            print(f"승인: labremote installs approve <프로젝트> <번호>")
            return 0

        if not args.name or args.id is None:
            print("✘ 프로젝트와 번호를 주세요", file=sys.stderr)
            return 2

        if args.action == "approve":
            got = installs_mod.approve(
                conn, args.name, args.id,
                allow_source=args.allow_source, note=args.note or "",
            )
            if not got["ok"]:
                # ⚠ 전에는 `reason` 칸이 없어서 `✘ None` 을 찍었다 (S9 e2e).
                print(f"✘ {got.get('reason') or '설치가 실패했어요'}", file=sys.stderr)
                if got.get("needsEnv"):
                    print(
                        f"  conda create -n {got['needsEnv']} python=3.11 -y",
                        file=sys.stderr,
                    )
                    print("  그다음 다시 승인해 주세요 (승인은 아직 열려 있어요).",
                          file=sys.stderr)
                result = got.get("result")
                if result and result.get("output"):
                    print()
                    print("--- 원문 ---", file=sys.stderr)
                    print(result["output"][-1500:], file=sys.stderr)
                return 2
            print(f"✔ 설치했어요 ({got['env']})")
            return 0

        got = installs_mod.deny(conn, args.name, args.id, reason=args.reason or "")
        if not got["ok"]:
            print(f"✘ {got.get('reason')}", file=sys.stderr)
            return 2
        print("✔ 거절했어요")
        return 0


def cmd_tools(args) -> int:
    """📌 Claude Code 판과 도구 목록을 대조·기록한다.

    판이 바뀌면 도구 이름이 바뀔 수 있고, 그러면 방어에 **조용한 틈**이
    생긴다 — `Task` → `Agent` 가 그랬다. 그래서 헤드리스 루프는 판이
    기록과 다르면 멈추고, 이 명령으로 다시 재서 풀어 준다.
    """
    from .agent import launch as launch_mod
    from .agent import version as version_mod
    from .hooks import classify

    got = version_mod.check()
    print(f"지금 판        {got['current'] or '[못 읽었어요]'}")
    print(f"실측한 판      {got['recorded'] or '(없어요)'}" + (f" · {got['at']}" if got["at"] else ""))
    if got["ok"]:
        print("✔ 같아요 — 헤드리스 루프가 돌 수 있어요")
    else:
        print(f"⚠ {got['reason']}")

    if args.probe:
        if not args.name:
            print("✘ 어느 프로젝트에서 물어볼지 알려 주세요", file=sys.stderr)
            return 2
        print()
        print(f"세션에 도구 목록을 물어보는 중이에요 ({args.name})…")
        probed = version_mod.probe_tools(args.name)
        if not probed["ok"]:
            print(f"✘ {probed['reason']}", file=sys.stderr)
            return 2
        tools = probed["tools"]
        print(f"받은 도구 {len(tools)}개: {', '.join(tools)}")
        diff = version_mod.compare(tools)
        print()
        alarms = ("new", "missingAllowed")
        for key, title in (
            ("new", "🔴 새로 생긴 도구 — classify.TOOLS_2_1_318 에 적고 분류해 주세요"),
            ("missingAllowed", "🔴 쓰겠다고 한 도구가 없어요 — 루프가 깨져요"),
            ("absent", "· 이 세션에 안 보인 도구 (경보 아니에요 — 계정·환경에 따라 달라요)"),
        ):
            if diff[key]:
                print(f"{title}: {', '.join(diff[key])}")
        if not any(diff[k] for k in alarms):
            print("✔ 새 도구 없음 · 쓰는 도구 전부 있음")
        version_mod.record(got["current"], tools=tools, note=f"probe · {args.name}")
        print()
        print(f"✔ 기록했어요: {version_mod.record_path()}")
        return 0

    if args.accept:
        if not got["current"]:
            print("✘ 지금 판을 못 읽어서 기록할 수 없어요", file=sys.stderr)
            return 2
        saved = version_mod.recorded()
        version_mod.record(
            got["current"], tools=saved.get("tools"), note=args.note or "사람이 확인했어요"
        )
        print(f"✔ 판만 기록했어요: {got['current']} (도구 목록은 그대로 둬요)")
        return 0

    print()
    print(f"쓰는 도구 ({len(launch_mod.ALLOWED_TOOLS)}개): {', '.join(launch_mod.ALLOWED_TOOLS)}")
    print(f"끄는 도구 ({len(launch_mod.DISALLOWED_TOOLS)}개): {', '.join(launch_mod.DISALLOWED_TOOLS)}")
    print(f"이 판에 없는 이름: {', '.join(sorted(classify.PHANTOM_TOOLS))}")
    if not got["ok"]:
        print()
        print("다시 재려면:  labremote tools --probe <프로젝트>")
        print("목록이 같다고 보고 판만 기록하려면:  labremote tools --accept")
    return 0 if got["ok"] else 1


def cmd_keys(args) -> int:
    """🔑 허가 서명 키만 만든다·점검한다.

    승인(`labremote approvals approve`)이 1회용 허가를 **HMAC 으로 서명**한다.
    키가 없으면 `grants.verify` 가 전부 거짓이 되어 **헤드리스 승인이 아예
    안 된다** — 훅이 허가를 무시하고 그대로 막는다(fail-closed).

    `labremote service install`(8단계)이 하기로 했던 일인데, 그 명령은 systemd
    유닛까지 건드린다. 키만 필요할 때 그걸 돌릴 이유가 없다.

    **키 값은 절대 찍지 않는다.** 경로·권한·길이만 보여 준다.
    """
    from . import config

    path = config.grant_key_path()
    if args.action == "show":
        mode = config.mode_of(path)
        if mode is None:
            print(f"✘ 키가 없어요: {path}")
            print("  labremote keys init 로 만들어 주세요.")
            return 1
        raw = config.grant_key()
        print(f"경로   {path}")
        print(f"권한   {oct(mode)[2:]}" + ("" if config.is_private(path) else "  ⚠ 남이 읽을 수 있어요"))
        print(f"길이   {len(raw or b'')}자")  # 값은 찍지 않아요
        return 0 if config.is_private(path) and raw else 1

    # init
    if os.path.exists(path):
        mode = config.mode_of(path)
        private = config.is_private(path)
        print(f"키가 이미 있어요: {path}")
        print(f"  권한 {oct(mode or 0)[2:]}" + ("" if private else "  ⚠ 남이 읽을 수 있어요"))
        if not private:
            print("  labremote keys init --fix-mode 로 권한만 0600 으로 고칠 수 있어요.")
            if args.fix_mode:
                config.ensure_grant_key()  # 있으면 권한만 고친다
                print(f"✔ 권한을 {oct(config.mode_of(path) or 0)[2:]} 로 고쳤어요")
                return 0
            return 1
        print("  **덮어쓰지 않아요** — 키를 바꾸면 아직 안 쓴 허가가 전부 무효가 돼요.")
        return 0

    made = config.ensure_grant_key()
    print(f"✔ 키를 만들었어요: {made}")
    print(f"  권한 {oct(config.mode_of(made) or 0)[2:]} · 32바이트 랜덤 (값은 찍지 않아요)")
    print()
    print("이 폴더는 훅의 SECRET_FILES 라 Claude 가 읽기까지 막혀요.")
    print("백업하지 마세요 — 잃으면 새로 만들면 되고, 새 키는 아직 안 쓴 허가만 무효로 해요.")
    return 0


def cmd_approvals(args) -> int:
    """🎟 승인 대기열 — 사람이 승인하는 자리.

    승인 **내용과 지문**은 오케스트레이터가 `claude -p` 결과 JSON 의
    `permission_denials` 에서 만든 것이다(원칙 (나), S4). 훅이 쓴 사유는
    "훅 참고(검증 안 됨)" 로 따로 보여 준다 — `permission_denials` 에 사유
    칸이 없다(M2).
    """
    from . import db as db_mod
    from . import grants
    from .orchestrator import approvals as AP_ORCH
    from .store import approvals as APS

    with db_mod.open_db() as conn:
        if args.action == "list":
            rows = [
                r for r in APS.pending(conn, args.name or None)
                if r.get("action_key") != "install"
            ]
            if args.json:
                print(json.dumps(rows, ensure_ascii=False, indent=2))
                return 0
            if not rows:
                print("기다리는 승인이 없어요.")
                return 0
            for row in rows:
                mark = "📋" if row.get("source") == "denials" else "🪝"
                print(f"{mark} [{row['id']}] {row['project']} · {row['request_id']}")
                print(f"     {row.get('action_key')} · {_shorten(str(row.get('request') or ''))}")
                print(f"     열린 때 {row['opened_at']} · 횟수 {row['attempts']}"
                      f" · 출처 {row.get('source')}")
                if str(row.get("action_key") or "") in grants.NO_GRANT_ACTIONS:
                    # 승인해도 아무 일이 안 일어난다 (M3) — 기록만 거짓이 된다
                    print("     ⛔ 승인 불가 — 설치 요청 경로로 "
                          "(state/Install_request.json → labremote installs approve)")
                    print("        이 요청은 거절(deny)만 할 수 있어요")
            print()
            print("📋 = 결과 JSON 에서 만든 것 (지문을 우리가 계산) · 🪝 = 훅 파일에서 거울")
            print(f"자세히:  labremote approvals show {rows[0]['project']} {rows[0]['request_id']}")
            print(f"승인:    labremote approvals approve {rows[0]['project']} {rows[0]['request_id']}")
            return 0

        if not args.name or not args.id:
            print("✘ 프로젝트와 요청 ID 를 주세요", file=sys.stderr)
            return 2

        row = APS.by_request(conn, args.name, args.id)
        if not row:
            print(f"✘ 그런 승인 요청이 없어요: {args.id}", file=sys.stderr)
            return 2

        if args.action == "show":
            if args.json:
                print(json.dumps(row, ensure_ascii=False, indent=2))
                return 0
            print(f"요청      {row['request_id']}")
            print(f"프로젝트   {row['project']}")
            print(f"도구      {row.get('tool')}")
            print(f"행동      {row.get('action_key')}")
            print(f"내용      {row.get('request')}")
            print(f"지문      {row.get('fingerprint')}")
            print(f"출처      {row.get('source')}"
                  + ("  (오케스트레이터가 결과 JSON 에서 계산)"
                     if row.get("source") == "denials" else "  (훅 파일에서 거울)"))
            print(f"세션      {row.get('session_id')}")
            print(f"상태      {row['state']} · 횟수 {row['attempts']}")
            if str(row.get("action_key") or "") in grants.NO_GRANT_ACTIONS:
                print()
                print("⛔ 승인 불가")
                for line in grants.NO_GRANT_REASON.split(". "):
                    print(f"  {line.strip()}")
            if row.get("tool_summary"):
                print(f"입력 요약  {row['tool_summary']}")
            if row.get("reason"):
                print()
                print(f"{AP_ORCH.HOOK_REASON_LABEL}:")
                for line in str(row["reason"]).splitlines():
                    print(f"  {line}")
            return 0

        if args.action == "approve":
            try:
                grant = AP_ORCH.approve(
                    conn, args.name, args.id,
                    ttl_sec=_ttl(args.ttl), loose=args.loose, note=args.note or "",
                )
            except grants.GrantError as exc:
                print(f"✘ {exc}", file=sys.stderr)
                return 2
            print(f"✔ 승인했어요 · {grant['grantId']}")
            print(f"  행동   {', '.join(grant['actions'])}")
            print(f"  만료   {grant['expiresAt']}")
            print(f"  세션   {grant['sessionId']}  (이 세션에서만 먹어요)")
            print()
            print("오케스트레이터가 같은 세션을 --resume 으로 이어 가요.")
            return 0

        try:
            AP_ORCH.deny(conn, args.name, args.id, reason=args.reason or "")
        except Exception as exc:
            print(f"✘ {exc}", file=sys.stderr)
            return 2
        print("✔ 거절했어요")
        return 0


def _ttl(text: str | None) -> int:
    """`10m`·`2h`·`600` 을 초로. 없으면 기본값."""
    from . import grants as grants_mod

    if not text:
        return grants_mod.DEFAULT_TTL_SEC
    raw = str(text).strip().lower()
    unit = {"s": 1, "m": 60, "h": 3600}
    if raw and raw[-1] in unit:
        return max(1, int(float(raw[:-1]) * unit[raw[-1]]))
    return max(1, int(float(raw)))


def cmd_audit(args) -> int:
    """📒 승인 기록의 **진본**과 사본을 대조한다.

    프로젝트의 `logs/Approval_log.csv` 는 AI 가 쓴 코드가 고칠 수 있다(M4).
    진본은 `server/data/audit/<프로젝트>.jsonl` 이고 AI 는 거기에 못 쓴다(M1b).
    """
    from . import approval_log, audit

    root = registry.root_of(args.name)
    if not root:
        print(f"✘ 등록된 실험 프로젝트가 아니에요: {args.name}", file=sys.stderr)
        return 2
    try:
        pol = policy.load(args.name)
    except Exception:
        pol = None
    csv_path = approval_log.log_path(root, pol)
    report = audit.compare(args.name, csv_path)

    if args.json:
        print(json.dumps(report, ensure_ascii=False, indent=2))
        return 0 if report["ok"] else 1

    print(f"진본  {audit.audit_path(args.name)}  {report['truth']}줄")
    print(f"사본  {csv_path}  {report['copy']}줄")
    if report["ok"]:
        print("✔ 같아요")
        return 0

    print()
    print(audit.describe(report))

    if args.seed:
        print()
        got = audit.seed(args.name, csv_path)
        if not got["ok"]:
            print(f"✘ {got['reason']}", file=sys.stderr)
            return 2
        print(f"✔ 지금 사본을 진본의 출발점으로 삼았어요 ({got['rows']}줄)")
        print("  이제부터 훅이 진본에 직접 남겨요. 사본이 바뀌면 잡혀요.")
        return 0

    if args.rebuild:
        print()
        got = audit.rebuild(args.name, csv_path)
        if not got["ok"]:
            print(f"✘ 다시 만들지 못했어요: {got['reason']}", file=sys.stderr)
            return 2
        print(f"✔ 진본으로 사본을 다시 만들었어요 ({got['rows']}줄)")
        print("  루프를 다시 열려면: labremote run-state " + args.name + " --idle")
        return 0

    print()
    print(f"다시 만들려면:  labremote audit {args.name} --rebuild")
    return 1


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


def cmd_up(args) -> int:
    """▶ 오케스트레이터 루프를 **터미널에서** 띄운다 (systemd 없이).

    개발·검증용이다. 8단계의 systemd 유닛과 **같은 루프**를 돈다 —
    `app/orchestrator/__main__.main()` 하나뿐이다.
    """
    from .orchestrator import __main__ as loop_main

    argv = []
    if args.once:
        argv.append("--once")
    if not args.foreground and not args.once:
        print("⚠ 지금은 앞단(foreground)으로만 돌려요 — 뒤로 보내려면 8단계의")
        print("  systemd 유닛을 쓰거나 `labremote up --foreground &` 로 해 주세요.")
        print()
    print("루프를 띄워요. 멈추려면 Ctrl-C.")
    try:
        return loop_main.main(argv)
    except KeyboardInterrupt:
        print()
        print("멈췄어요. 돌고 있던 학습은 안 죽어요 (start_new_session).")
        return 0


def cmd_queue(args) -> int:
    """📋 작업 큐. 루프가 집어 가는 일 목록."""
    from . import db as db_mod
    from .store import jobs as J
    from .store import loops as LP

    with db_mod.open_db() as conn:
        if args.action == "list":
            states = tuple(args.state) if args.state else None
            rows = J.listing(conn, args.name or None, states, limit=args.limit)
            if args.json:
                print(json.dumps(rows, ensure_ascii=False, indent=2))
                return 0
            if not rows:
                print("큐가 비어 있어요.")
                return 0
            for row in rows:
                mark = {"running": "▶", "queued": "·", "done": "✔",
                        "failed": "✘", "timeout": "✘", "blocked": "⛔",
                        "cancelled": "—", "waiting_approval": "⏸",
                        "leased": "·"}.get(row["state"], "?")
                exp = row.get("experiment_id") or "-"
                print(f"{mark} [{row['id']}] {row['project']} · {row['kind']} · {exp}"
                      f" · {row['state']}")
                if row.get("error"):
                    print(f"      {_shorten(str(row['error']))}")
            return 0

        if not args.name:
            print("✘ 프로젝트 이름을 주세요", file=sys.stderr)
            return 2

        if args.action == "add":
            root = registry.root_of(args.name)
            if not root:
                print(f"✘ 등록된 실험 프로젝트가 아니에요: {args.name}", file=sys.stderr)
                return 2
            kind = "plan" if args.dummy else (args.kind or "plan")
            job_id = J.add(
                conn, args.name, kind,
                payload={"dummy": True} if args.dummy else None,
            )
            conn.commit()
            print(f"✔ 작업을 넣었어요: [{job_id}] {kind}")
            if args.dummy:
                print("  가짜 학습으로 한 바퀴 돌려요. `labremote up --once` 로 띄워 주세요.")
            return 0

        if args.action == "pause":
            LP.pause(conn, args.name, reason=args.reason or "사람이 멈췄어요")
            print(f"✔ 루프를 멈췄어요: {args.name}")
            print("  돌고 있는 학습은 건드리지 않아요. 다음 작업부터 멈춰요.")
            return 0

        if args.action == "resume":
            LP.resume(conn, args.name)
            print(f"✔ 루프를 다시 열었어요: {args.name}")
            return 0

        # cancel
        if args.id is None:
            print("✘ 취소할 작업 번호를 주세요", file=sys.stderr)
            return 2
        try:
            J.cancel(conn, args.id, error=args.reason or "사람이 취소했어요")
            conn.commit()
        except Exception as exc:
            print(f"✘ {exc}", file=sys.stderr)
            return 2
        print(f"✔ 취소했어요: [{args.id}]")
        return 0


def cmd_monitor(args) -> int:
    """📈 GPU·호스트·로그를 읽어 스냅샷으로."""
    from . import db as db_mod
    from .monitor import daemon, snapshot

    if args.action == "once":
        from .monitor import gpu as gpu_mod
        from .monitor import host as host_mod

        # CPU 는 **두 표본의 차분**이다 (psutil 없이 /proc/stat 으로 잰다).
        # 한 번만 읽으면 `None` 이 나온다 — 짧게 두 번 읽는다.
        before = host_mod.cpu_times()
        with db_mod.open_db() as conn:
            got = daemon.tick(conn, host_before=before)
        gpu = gpu_mod.probe()
        host = host_mod.probe(".", before=before)
        if args.json:
            print(json.dumps(
                {"tick": got, "gpu": gpu, "host": host}, ensure_ascii=False, indent=2
            ))
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
        if got["wrote"]:
            print("스냅샷  " + ", ".join(got["wrote"]))
            for name in got["wrote"]:
                print(f"       {snapshot.status_path(name)}")
        else:
            print("스냅샷  쓴 게 없어요 (등록된 프로젝트가 없나요?)")
        for problem in got["problems"]:
            print(f"⚠ {problem}")
        return 1 if got["problems"] else 0

    # status
    rows = []
    for root, name in sorted(registry.load().items()):
        path = snapshot.status_path(name)
        row = {"project": name, "path": path, "exists": os.path.exists(path)}
        if row["exists"]:
            try:
                with open(path, encoding="utf-8") as fh:
                    data = json.load(fh)
                row["generatedAt"] = data.get("generatedAt")
                row["loopLabel"] = (data.get("dashboard") or {}).get("loopLabel")
            except (OSError, ValueError) as exc:
                row["error"] = str(exc)
        rows.append(row)
    if args.json:
        print(json.dumps(rows, ensure_ascii=False, indent=2))
        return 0
    if not rows:
        print("등록된 프로젝트가 없어요.")
        return 0
    for row in rows:
        if not row["exists"]:
            print(f"· {row['project']} · 스냅샷이 아직 없어요 "
                  "(labremote monitor once 로 한 번 찍어 주세요)")
            continue
        print(f"✔ {row['project']} · {row.get('loopLabel') or '-'}"
              f" · {row.get('generatedAt')}")
        print(f"     {row['path']}")
    return 0


def cmd_notify(args) -> int:
    """🔔 웹훅을 한 번 쏴 본다. **주소는 찍지 않는다.**"""
    from . import db as db_mod
    from . import notify, notifier

    if not notify.webhook_url():
        print("✘ 웹훅 주소가 없어요", file=sys.stderr)
        print(f"  {config_hint()}", file=sys.stderr)
        return 2
    with db_mod.open_db() as conn:
        got = notifier.send(
            conn,
            "test",
            project=args.name or "",
            subject=f"test-{int(__import__('time').time())}",
            title="알림이 닿았어요",
            body="`labremote notify test` 로 보낸 시험 알림이에요.",
            fields=[
                ("보낸 쪽", notify.USER_AGENT),
                ("확인할 것", "사유 전문이 잘리지 않고 오는지"),
            ],
        )
    if not got.get("ok"):
        print(f"✘ 못 보냈어요: {got.get('reason') or got}", file=sys.stderr)
        if got.get("httpStatus") == 403:
            print("  403 이면 웹훅 URL 이 틀렸거나 지워졌을 수 있어요.", file=sys.stderr)
        return 2
    print(f"✔ 보냈어요 (상태 {got.get('httpStatus')})")
    if got.get("suppressed"):
        print("  방금 같은 알림을 보내서 이번 건은 눌렸어요 (중복 제거).")
    return 0


def config_hint() -> str:
    from . import config

    return f"docs/SETUP.md 의 웹훅 단계를 봐 주세요: {config.config_path()}"


def cmd_service(args) -> int:
    """⚙️ systemd 사용자 유닛을 **렌더**한다. 활성화는 사람이 한다.

    `enable`·`linger` 는 사람의 세션 설정이고, `enable --now` 는 **루프를
    실제로 띄운다** — 그건 사람이 "이제 돌려라" 라고 말하는 순간이어야 한다.
    """
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
        print()
        print("8단계에서 실제 재부팅까지 확인해요.")
        return 0

    # status
    got = units.status()
    if args.json:
        print(json.dumps(got, ensure_ascii=False, indent=2))
        return 0
    if not got["systemctl"]:
        print("systemctl 이 없어요 — systemd 가 아닌 환경이에요.")
        return 1
    linger = got["linger"]
    print("linger   " + ("켜져 있어요" if linger else
                         "꺼져 있어요 ⚠ 로그아웃하면 서비스가 죽어요" if linger is False
                         else "못 읽었어요"))
    for name, row in sorted(got["units"].items()):
        print(f"{name}")
        print(f"  유닛 파일  {'있어요' if row['file'] else '없어요 (labremote service install)'}")
        print(f"  enabled   {row.get('enabled')}")
        print(f"  active    {row.get('active')}")
    bad = [n for n, r in got["units"].items() if not r["file"]]
    return 1 if (bad or linger is False) else 0


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

    p = sub.add_parser("up", help="오케스트레이터 루프를 터미널에서 띄워요")
    p.add_argument("--foreground", action="store_true", help="앞단에서 돌려요 (기본)")
    p.add_argument("--once", action="store_true", help="한 바퀴만 돌고 끝내요")
    p.set_defaults(func=cmd_up)

    p = sub.add_parser("queue", help="작업 큐 보기·넣기·멈춤·취소")
    p.add_argument("action", choices=["list", "add", "pause", "resume", "cancel"])
    p.add_argument("name", nargs="?", help="프로젝트 이름")
    p.add_argument("id", nargs="?", type=int, help="cancel 할 작업 번호")
    p.add_argument("--kind", choices=["plan", "train", "review", "resume", "journal_fix"],
                   help="add 할 작업 종류 (기본 plan)")
    p.add_argument("--dummy", action="store_true", help="가짜 학습으로 한 바퀴 (9단계 검증 1번)")
    p.add_argument("--state", action="append", help="list 를 상태로 걸러요 (여러 번)")
    p.add_argument("--limit", type=int, default=20, help="list 개수 (기본 20)")
    p.add_argument("--reason", help="pause·cancel 사유")
    p.set_defaults(func=cmd_queue)

    p = sub.add_parser("monitor", help="GPU·호스트·로그 스냅샷")
    p.add_argument("action", choices=["once", "status"])
    p.set_defaults(func=cmd_monitor)

    p = sub.add_parser("notify", help="알림 시험 (주소는 안 찍어요)")
    p.add_argument("action", choices=["test"])
    p.add_argument("name", nargs="?", help="프로젝트 이름 (선택)")
    p.set_defaults(func=cmd_notify)

    p = sub.add_parser("service", help="systemd 사용자 유닛 렌더 (활성화는 사람이)")
    p.add_argument("action", choices=["install", "status"])
    p.add_argument("--dry-run", action="store_true", help="쓰지 않고 내용만 보여 줘요")
    p.set_defaults(func=cmd_service)

    p = sub.add_parser("keys", help="허가 서명 키 만들기·점검 (승인에 필요해요)")
    p.add_argument("action", nargs="?", choices=["init", "show"], default="show")
    p.add_argument(
        "--fix-mode",
        action="store_true",
        help="이미 있는 키의 권한만 0600 으로 고쳐요 (키는 안 바꿔요)",
    )
    p.set_defaults(func=cmd_keys)

    p = sub.add_parser("approvals", help="승인 대기열 — 사람이 승인하는 자리")
    p.add_argument("action", choices=["list", "show", "approve", "deny"])
    p.add_argument("name", nargs="?", help="프로젝트 이름")
    p.add_argument("id", nargs="?", help="요청 ID (tool_use_id)")
    p.add_argument("--ttl", help="허가 만료 (예: 10m · 2h · 600). 기본 10분")
    p.add_argument(
        "--loose",
        action="store_true",
        help="입력이 조금 달라도 허용해요 (Bash 는 지원하지 않아요)",
    )
    p.add_argument("--note", help="승인 메모")
    p.add_argument("--reason", help="거절 사유")
    p.set_defaults(func=cmd_approvals)

    p = sub.add_parser(
        "audit", help="승인 기록 진본과 사본 대조 (사본이 바뀌면 루프가 멈춰요)"
    )
    p.add_argument("name")
    p.add_argument(
        "--rebuild", action="store_true", help="진본으로 사본을 다시 만들어요"
    )
    p.add_argument(
        "--seed",
        action="store_true",
        help="진본이 없을 때 **한 번만** · 지금 사본을 출발점으로 삼아요",
    )
    p.set_defaults(func=cmd_audit)

    p = sub.add_parser(
        "tools", help="Claude Code 판과 도구 목록 대조·기록 (판이 바뀌면 루프가 멈춰요)"
    )
    p.add_argument("name", nargs="?", help="--probe 와 함께 · 물어볼 프로젝트")
    p.add_argument(
        "--probe", action="store_true",
        help="세션에 도구 목록을 물어 다시 재고 기록해요 (토큰을 써요)",
    )
    p.add_argument(
        "--accept", action="store_true",
        help="도구 목록이 같다고 보고 **판만** 기록해요 (사람이 확인한 뒤)",
    )
    p.add_argument("--note", help="--accept 와 함께 · 메모")
    p.set_defaults(func=cmd_tools)

    p = sub.add_parser("installs", help="패키지 설치 승인 (오케스트레이터가 설치해요)")
    p.add_argument("action", choices=["list", "approve", "deny"])
    p.add_argument("name", nargs="?", help="프로젝트 이름")
    p.add_argument("id", nargs="?", type=int, help="승인 번호")
    p.add_argument(
        "--allow-source",
        action="store_true",
        help="소스 배포(sdist)도 허용해요 — setup.py 가 실행돼요. 요청에도 "
        "allowSource 가 있어야 해요",
    )
    p.add_argument("--note", help="승인 메모")
    p.add_argument("--reason", help="거절 사유")
    p.set_defaults(func=cmd_installs)

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
