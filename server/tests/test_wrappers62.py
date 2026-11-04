"""실행 래퍼 62종 회귀표 (0단계 실측 + 계획 0-5).

0단계 실측(2026-11-04)에서 `rm -rf <프로젝트 밖>`(잠긴 항목 ①)을 래퍼로
감싸 보니 **62종 중 52종이 분류를 빠져나갔다.** 분류가 없으면 `_record` 도
안 불려 **승인 로그에 흔적조차 남지 않았다.**

이 표가 그 실측을 그대로 테스트로 옮긴 것이다. 각 래퍼로 감싼 삭제가
**반드시** `outside`(잠긴 항목) · `suspicious`(해석 포기) ·
`denied-command`(금지 명령) 중 하나로 떨어져야 한다.

> ⚠ **이건 보조 수단이다.** 명령 문자열 분석은 완전할 수 없다 — 62종을
> 메워도 63번째가 나온다. 1차 방어는 Claude Bash 샌드박스다(실측 14:
> 훅이 allow 를 준 명령을 샌드박스가 막았다). 여기서 하는 일은 **승인
> 경로와 기록**을 잃지 않는 것이다.
"""

import pytest

from app.hooks import bashparse
from app.hooks import decide as D

#: 프로젝트 폴더 밖. 잠긴 항목 ①의 대상이다.
OUTSIDE = "/home/사용자/sbx-victim"
INNER = f"rm -rf {OUTSIDE}"

#: 막혀야 하는 판정. 셋 중 하나면 된다 — 승인 경로와 기록이 살아 있다는 뜻이다.
BLOCKED = {"outside", "suspicious", "denied-command"}

#: 래퍼 62종. 0단계 실측 표와 같은 순서·같은 꼴이다.
WRAPPED = [
    # (래퍼 없음)
    INNER,
    # A. 그냥 앞에 붙는 것
    f"env {INNER}",
    f"env VAR=1 {INNER}",
    f"env -u PATH {INNER}",
    f"VAR=1 {INNER}",
    f"nohup {INNER}",
    f"setsid {INNER}",
    f"command {INNER}",
    f"exec {INNER}",
    f"time {INNER}",
    f"sudo {INNER}",
    f"sudo -u hse09021 {INNER}",
    f"doas {INNER}",
    f"runuser -u hse09021 {INNER}",
    f"setpriv --reuid 1000 {INNER}",
    # B. 옵션이 값을 먹는 것 — 실측에서 여기가 많이 뚫렸다
    f"nice {INNER}",
    f"nice -n 10 {INNER}",
    f"nice --adjustment 10 {INNER}",
    f"ionice {INNER}",
    f"ionice -c2 {INNER}",
    f"ionice -c 2 -n 7 {INNER}",
    f"stdbuf -oL {INNER}",
    f"stdbuf -o L -e L {INNER}",
    f"chrt -f 10 {INNER}",
    f"chrt -p 0 {INNER}",
    f"taskset -c 0-3 {INNER}",
    f"taskset 0x3 {INNER}",
    f"timeout 30 {INNER}",
    f"timeout -k 5 30 {INNER}",
    f"timeout --signal=TERM 30 {INNER}",
    f"flock /tmp/잠금 {INNER}",
    f"flock -w 5 /tmp/잠금 {INNER}",
    f"watch -n 5 {INNER}",
    f"script -qc '{INNER}' /dev/null",
    # C. 실행 환경 래퍼
    f"conda run {INNER}",
    f"conda run -n base {INNER}",
    f"conda run --name base {INNER}",
    f"mamba run -n base {INNER}",
    f"micromamba run -n base {INNER}",
    f"poetry run {INNER}",
    f"poetry -C . run {INNER}",
    f"pdm run {INNER}",
    f"hatch run {INNER}",
    f"hatch -e test run {INNER}",
    f"uv run {INNER}",
    f"uv run --with x {INNER}",
    f"rye run {INNER}",
    f"pipx run {INNER}",
    f"npx {INNER}",
    f"npx -p pkg {INNER}",
    f"pnpm exec {INNER}",
    f"pnpm dlx {INNER}",
    f"yarn exec {INNER}",
    f"yarn dlx {INNER}",
    f"xargs {INNER}",
    f"xargs -I {{}} {INNER}",
    f"parallel -j2 {INNER}",
    # D. 셸 문자열을 품는 것 — 재귀로 다시 분류한다
    f"bash -c '{INNER}'",
    f"sh -c '{INNER}'",
    f"zsh -c '{INNER}'",
    f"dash -c '{INNER}'",
    f"ksh -c '{INNER}'",
    f"su -c '{INNER}'",
    f"nix-shell --run '{INNER}'",
    f"busybox sh -c '{INNER}'",
    f"find . -name x -exec {INNER} ;",
    f"find . -name x -execdir {INNER} ;",
    # E. 분석 불가 — 이름으로 막는다
    f"unshare -r {INNER}",
    f"nsenter -t 1 -m {INNER}",
    f"chroot / {INNER}",
    f"setarch x86_64 {INNER}",
    f"bwrap --dev-bind / / {INNER}",
    f"systemd-run --user {INNER}",
    f"strace {INNER}",
    f"ltrace {INNER}",
    f"gdb --ex 'shell {INNER}'",
    f"docker run -v /:/host alpine {INNER}",
    f"podman run -v /:/host alpine {INNER}",
    f"at now -f <(echo '{INNER}')",
    f"batch <<< '{INNER}'",
    f"crontab -l | {{ cat; echo '* * * * * {INNER}'; }} | crontab -",
    # 치환으로 가린 것
    f"eval '{INNER}'",
    f"bash -c \"$(echo '{INNER}')\"",
]


def test_표가_62종_이상이다():
    """실측 표를 줄이지 않는다."""
    assert len(WRAPPED) >= 62, len(WRAPPED)


@pytest.mark.parametrize("command", WRAPPED, ids=range(len(WRAPPED)))
def test_래퍼로_감싼_폴더_밖_삭제는_전부_막힌다(ctx, command):
    found = bashparse.classify_with_coverage(command, ctx)
    got = {f.action for f in found}
    assert got & BLOCKED, f"{command!r} -> {sorted(got) or '(분류 없음)'}"


@pytest.mark.parametrize("command", WRAPPED, ids=range(len(WRAPPED)))
def test_래퍼로_감싼_삭제는_대화형에서도_헤드리스에서도_안_열린다(ctx, command):
    found = bashparse.classify_with_coverage(command, ctx)
    ctx.event = {"tool_name": "Bash", "tool_input": {"command": command}}
    for headless in (False, True):
        ctx.headless = headless
        assert D.resolve(found, ctx).kind != "allow", command


def test_재귀는_깊이에서_멈춘다(ctx):
    """중첩이 깊어지면 따옴표 처리가 실제 셸과 어긋난다. 포기하고 올린다."""
    deep = "bash -c 'bash -c \"bash -c \\\"rm -rf /x\\\"\"'"
    got = {f.action for f in bashparse.classify_with_coverage(deep, ctx)}
    assert got & BLOCKED, sorted(got)


def test_아는_명령은_래퍼로_감싸도_통과한다(ctx, sandboxed):
    """소음 확인 — 래퍼를 벗기는 게 멀쩡한 명령을 막지는 않는다."""
    from app import policy

    ctx.headless = True
    ctx.sandbox = policy.sandbox_state(sandboxed)["ok"]
    for command in ("nice -n 10 ls -la", "conda run -n base pytest -q", "timeout 30 git status"):
        found = bashparse.classify_with_coverage(command, ctx)
        ctx.event = {"tool_name": "Bash", "tool_input": {"command": command}}
        assert D.resolve(found, ctx).kind == "allow", command
