"""헤드리스 Bash 허용 목록 (계획 1-2-1).

실측(2026-11-04): 헤드리스에서 훅의 `defer` 는 통과가 아니라 **정지**다.
`ls -1` 조차 `stop_reason: "tool_deferred"` 로 아무것도 못 하고 끝나며 기록도
안 남는다. 그래서 헤드리스는 "아는 명령은 allow, 모르면 ask" 로 간다.

**대화형에는 적용하지 않는다** — 거기서는 defer 가 정상 동작한다(사람에게 물음).

조건 다섯 개를 하나씩 고정한다.
  1. 금지 명령·비밀 파일·서버 보호·폴더 밖 쓰기·산출물 보호가 **먼저**.
  2. 이어진 명령은 **모든 조각**이 목록에 있어야 allow.
  3. 치환·리다이렉트가 있으면 ask (`/dev/null` 예외).
  4. 위험 옵션은 제외 (`find -exec`, `git push`, `grep -i`, `sort -o`).
  5. 기본 목록은 코드에, 정책으로는 **추가만**.
"""

import os

import pytest

from app.hooks import bashparse
from app.hooks import decide as D


def kinds(ctx, command):
    found = bashparse.classify_with_coverage(command, ctx)
    ctx.event = {"tool_name": "Bash", "tool_input": {"command": command}}
    out = {}
    for headless in (False, True):
        ctx.headless = headless
        out["헤드리스" if headless else "대화형"] = D.resolve(found, ctx).kind
    return out


def headless(ctx, command):
    return kinds(ctx, command)["헤드리스"]


def interactive(ctx, command):
    return kinds(ctx, command)["대화형"]


# --- 목록에 있는 것 -----------------------------------------------------------


@pytest.mark.parametrize(
    "command",
    [
        "ls -la",
        "cat README.md",
        "head -n 20 README.md",
        "tail -f logs/Decision_log.md",
        "wc -l README.md",
        "pwd",
        "echo 안녕",
        "file README.md",
        "stat README.md",
        "du -sh .",
        "df -h",
        "date",
        "which python",
        "basename src/train.py",
        "dirname src/train.py",
        "cut -d, -f1 README.md",
        "uniq README.md",
        "diff a b",
        "nvidia-smi",
        "cd src",
        "git status",
        "git log --oneline -5",
        "git diff",
        "git show HEAD",
        "git rev-parse HEAD",
        "git branch -a",
        "grep -rn 패턴 src",
        "sed -n '1,3p' README.md",
        "sort README.md",
        "find . -name '*.py'",
        "ls -la 2>/dev/null",
        "cd src && ls && cat x.py",
    ],
)
def test_아는_명령은_헤드리스에서_통과한다(ctx, command):
    assert headless(ctx, command) == "allow", command


@pytest.mark.parametrize("command", ["ls -la", "git status", "pytest -q"])
def test_대화형에서는_허용_목록을_안_쓴다(ctx, command):
    """사람이 보고 고른다. 훅이 함부로 allow 를 주지 않는다."""
    assert interactive(ctx, command) == "defer", command


# --- 코드 실행은 샌드박스가 켜져 있을 때만 --------------------------------------


def test_pytest_는_샌드박스가_꺼져_있으면_승인_대상(ctx):
    """AI 가 쓴 테스트 코드가 그대로 돈다. 실측에서 `~/.claude.json` 과
    **정책 파일**까지 읽혔다."""
    assert ctx.sandbox is False  # 기본은 꺼짐으로 본다 (fail-closed)
    assert headless(ctx, "pytest -q") == "deny"


def test_pytest_는_샌드박스가_켜져도_소켓_확인_전이면_승인_대상(ctx, sandboxed):
    """2단계 조건 4: 샌드박스가 **실제로 막는 게 확인돼야** allow.

    Claude Bash 샌드박스의 유닉스 소켓 차단은 사람이 확인하기 전까지
    미확인이다(S9). 그래서 샌드박스가 켜져 있어도 헤드리스 코드 실행은
    승인으로 간다.
    """
    from app import policy

    ctx.sandbox = policy.sandbox_state(sandboxed)["ok"]
    assert ctx.sandbox is True
    assert ctx.socket_verified is False  # 기본은 미확인 (fail-closed)
    assert headless(ctx, "pytest -q") == "deny"


def test_pytest_는_샌드박스와_소켓_확인이_둘_다_있어야_통과(ctx, sandboxed):
    from app import policy

    ctx.sandbox = policy.sandbox_state(sandboxed)["ok"]
    ctx.socket_verified = True
    assert headless(ctx, "pytest -q") == "allow"


def test_샌드박스가_켜져도_대상은_프로젝트_안이어야(ctx, sandboxed):
    ctx.sandbox = True
    assert headless(ctx, "pytest /etc") == "deny"


def test_코드_실행_목록은_코드에_있다():
    assert bashparse.ALLOW_IF_SANDBOXED == {"pytest"}
    assert "pytest" not in bashparse.ALLOW_PLAIN


# --- 조건 1: 판정 순서 --------------------------------------------------------


def test_금지_명령이_허용_목록보다_먼저(ctx):
    """`labremote` 는 denyCommands 다. 허용 목록을 쳐다보지도 않는다."""
    assert headless(ctx, "labremote approve hook-sandbox toolu_1") == "deny"


def test_비밀_파일이_허용_목록보다_먼저(ctx, project_root):
    """`cat` 은 목록에 있지만 대상이 비밀이면 막는다."""
    with open(os.path.join(project_root, ".env"), "w", encoding="utf-8") as fh:
        fh.write("WANDB_API_KEY=비밀\n")
    assert headless(ctx, "cat .env") == "deny"


def test_서버_보호_파일이_허용_목록보다_먼저(ctx):
    from app import policy_defaults as Dft

    server = Dft.hard_protected_roots()[0]
    assert headless(ctx, f"cat {server}/app/hooks/decide.py") == "deny"


def test_폴더_밖_쓰기가_허용_목록보다_먼저(ctx):
    assert headless(ctx, "ls -la > /etc/목록.txt") == "deny"


def test_산출물_보호가_허용_목록보다_먼저(ctx, project_root):
    from app import runstate

    runstate.set_running("hook-sandbox", "EXP-007", pid=os.getpid())
    ctx.run = runstate.load("hook-sandbox")
    path = os.path.join(project_root, "experiments/EXP-007/output")
    os.makedirs(path, exist_ok=True)
    with open(os.path.join(path, "train.log"), "w", encoding="utf-8") as fh:
        fh.write("원본\n")
    assert headless(ctx, "sort experiments/EXP-007/output/train.log -o experiments/EXP-007/output/train.log") == "deny"


def test_잠금이_허용_목록보다_먼저(ctx, project_root):
    from app import runstate

    runstate.set_running("hook-sandbox", "EXP-007", pid=os.getpid())
    ctx.run = runstate.load("hook-sandbox")
    assert headless(ctx, "cat docs/Evaluation.md > docs/Evaluation.md") == "deny"


def test_정책_행동_유형이_허용_목록보다_먼저(ctx):
    """`pip install` 은 pkg 다. 허용 목록에 pip 가 없는 것과 별개로 정책이 먼저."""
    assert headless(ctx, "pip install peft") == "deny"  # 수동제어 -> ask -> 헤드리스 거절


# --- 조건 2: 조각 하나라도 모르면 전체 ask ------------------------------------


def test_조각_하나라도_모르면_전체가_막힌다(ctx):
    assert headless(ctx, "ls -la && 처음보는도구 --무엇") == "deny"
    assert interactive(ctx, "ls -la && 처음보는도구 --무엇") == "defer"


@pytest.mark.parametrize("joiner", ["&&", "||", ";", "|"])
def test_어떤_연결자든_모든_조각을_본다(ctx, joiner):
    assert headless(ctx, f"ls {joiner} 처음보는도구") == "deny", joiner
    assert headless(ctx, f"ls {joiner} cat README.md") == "allow", joiner


# --- 조건 3: 치환·리다이렉트 ---------------------------------------------------


@pytest.mark.parametrize(
    "command",
    [
        "ls $(whoami)",
        "ls `whoami`",
        "cat <(ls)",
        "echo hi > 메모.txt",
        "echo hi >> 메모.txt",
        "ls -la > 목록.txt",
    ],
)
def test_치환과_리다이렉트는_허용_목록에서_빠진다(ctx, command):
    assert headless(ctx, command) == "deny", command


@pytest.mark.parametrize(
    "command", ["ls -la > /dev/null", "ls -la 2>/dev/null", "echo x > /dev/stderr"]
)
def test_버리는_곳으로_가는_리다이렉트는_예외(ctx, command):
    assert headless(ctx, command) == "allow", command


# --- 조건 4: 위험 옵션 제외 ----------------------------------------------------


@pytest.mark.parametrize(
    "command",
    [
        "find . -name '*.log' -delete",
        "find . -exec rm {} ;",
        "find . -execdir touch x ;",
        "find . -fprint 목록.txt",
        "git push origin main",
        "git commit -m x",
        "git checkout main",
        "git branch -d exp-001",
        "git branch -m 새이름",
        # 전역 옵션은 **화이트리스트만** 건너뛴다. 이 셋은 무엇이 실행되고
        # 어느 저장소를 보는지를 바꾼다.
        "git -c core.pager=sh status",
        "git --exec-path=/tmp status",
        "git --git-dir=/tmp/x.git log",
        "git --work-tree=/tmp status",
        "git -C",  # 값이 빠졌다 — 무엇을 가리키는지 모른다
        "sed -i 's/a/b/' 메모.txt",
        "sort -o 결과.txt README.md",
    ],
)
def test_위험_옵션은_허용_목록에서_빠진다(ctx, command):
    assert headless(ctx, command) != "allow", command


@pytest.mark.parametrize(
    "command",
    [
        "find . -name '*.py' -type f",
        "git branch --list",
        # `git -C <경로> diff` 는 **순수 읽기**인데 하위명령 앞의 전역
        # 옵션을 안 건너뛰어 `unclassified` 로 떨어졌다 — 설계 세션이
        # 자기 저장소 diff 를 보려다 승인 대기로 멈췄다 (실측 2026-11-05).
        "git -C . diff",
        "git -C . status --porcelain",
        "git --no-pager log --oneline -5",
        "git -P -C . show HEAD",
        "grep -n 패턴 src",
        "sort -r README.md",
        # `grep -i` 는 **대소문자를 안 가리는 것**이다 (읽기 전용).
        # `sed -i`(제자리 수정)와 같은 함수로 묶여 있어서 순수 읽기가
        # 승인 대기로 떨어졌다 — 9단계 1번에서 루프가 거기서 멈췄다.
        "grep -i 패턴 README.md",
        "grep -n -i '패턴|다른것' logs/Approval_log.csv",
        "fgrep -i 패턴 README.md",
    ],
)
def test_안전한_옵션은_그대로_통과(ctx, command):
    assert headless(ctx, command) == "allow", command


def test_sed_의_i_는_여전히_막힌다(ctx):
    """`grep -i` 를 열었다고 `sed -i` 까지 열리면 안 된다."""
    assert headless(ctx, "sed -i 's/a/b/' 메모.txt") != "allow"
    assert headless(ctx, "sed --in-place 's/a/b/' 메모.txt") != "allow"
    assert headless(ctx, "sed 's/a/b/' 메모.txt") == "allow"


# --- 조건 5: 기본 목록은 코드에, 정책은 추가만 ---------------------------------


def test_정책으로_명령을_더할_수_있다(ctx):
    assert headless(ctx, "htop -v") == "deny"
    ctx.policy.data["bash"]["allowExtra"] = ["htop"]
    assert headless(ctx, "htop -v") == "allow"


def test_정책으로_기본_목록을_줄일_수_없다(ctx):
    """AI 가 정책을 통해 목록을 넓히지 못하게, 기본 목록은 코드가 단일 출처다."""
    ctx.policy.data["bash"]["allowExtra"] = []
    assert headless(ctx, "ls -la") == "allow"
    ctx.policy.data["bash"].pop("allowExtra", None)
    assert headless(ctx, "ls -la") == "allow"


def test_기본_목록은_코드에_있다():
    from app import policy_defaults as Dft

    assert "ls" in bashparse.ALLOW_PLAIN
    # 정책 기본값에는 목록 자체가 없다 — 추가 칸만 있다
    assert Dft.BASH_DEFAULTS["allowExtra"] == []
    assert "allowList" not in Dft.BASH_DEFAULTS


def test_프로젝트_밖_읽기는_허용_목록에서_빠진다(ctx, tmp_path):
    """폴더 밖 읽기는 정책상 허용이지만, 허용 목록이 **조용히** 열어 주지는
    않는다. 다른 프로젝트의 노트를 읽는 건 사람이 한 번 보고 고를 일이다."""
    other = tmp_path / "남의노트.md"
    other.write_text("남의 실험 메모\n", encoding="utf-8")
    assert headless(ctx, f"cat {other}") == "deny"
    assert headless(ctx, "cat /etc/hosts") == "deny"


def test_프로젝트_안_읽기는_통과(ctx, project_root):
    with open(os.path.join(project_root, "README.md"), "w", encoding="utf-8") as fh:
        fh.write("개요\n")
    assert headless(ctx, "cat README.md") == "allow"
    assert headless(ctx, f"cat {project_root}/README.md") == "allow"


def test_경로를_안_받는_명령은_그대로_통과(ctx):
    for command in ("pwd", "date", "nvidia-smi", "which python"):
        assert headless(ctx, command) == "allow", command
