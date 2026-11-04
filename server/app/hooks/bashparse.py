"""Bash 명령 -> 행동 유형.

**이 모듈은 보조 수단이다.** 쉘은 튜링 완전해서 정적 분석으로 완전 식별은
불가능하다. 그래도 꼭 필요한 이유가 실측에서 나왔다 — 2.1.317 에서 Edit 가
거절되자 Claude 는 곧바로

    sed -i -e 's/덤프/실측/g' -e 's/지워도/삭제해도/g' README.md && sed -n '1,3p' README.md

로 우회했고, 그것도 막히자 Write 로 또 시도했다. Write/Edit 만 막고 Bash 를
비워 두면 잠금이 사실상 없는 것과 같다.

못 잡는 것(문서화된 한계):
  - 변수 치환 `rm -rf $OUT`, glob 전개
  - `bash run.sh` · `make clean` 안의 내용
  - `python -c "open('/etc/x','w')"`
  - heredoc, `find . -delete`
  - 조건부 `cd` (단순 `cd X` 만 따라간다)
치환(`$( )`, 백틱, `eval`, `base64`, 파이프로 셸에 먹이기)이 보이면
해석을 포기하고 `suspicious` 로 올려 승인을 받는다.

표준 라이브러리만 쓴다.
"""

from __future__ import annotations

import glob as globmod
import os
import re
import shlex

from .. import paths
from .classify import Ctx, Finding, classify_path, is_hard_protected, is_secret

__all__ = [
    "classify",
    "classify_with_coverage",
    "split_segments",
    "strip_wrappers",
    "secret_findings",
    "is_allowlisted",
    "ALLOW_IF_SANDBOXED",
    "allowlisted_segments",
]

#: 안에 다른 명령을 끼워 넣는 흔적. 보이면 해석을 포기한다.
#: `<( )` 프로세스 치환도 같이 본다 — `bash <(curl …)` 이 그 꼴이다.
SUSPICIOUS_RE = re.compile(
    r"\$\(|`|<\(|(?<![\w-])eval(?![\w-])|(?<![\w-])base64(?![\w-])"
    r"|\|\s*(sh|bash|zsh|python[0-9.]*)\b"
)

#: 명령 앞에 붙어 실제 명령을 가리는 래퍼. 값은 **건너뛸 인자의 모양**이다.
#:
#: 0단계 실측(2026-11-04)에서 62종 중 52종이 분류를 빠져나갔다. 두 가지가
#: 원인이었다 — (1) 목록에 없는 래퍼, (2) 목록에 있어도 **옵션의 인자**를
#: 안 건너뛰어서 `nice -n 10 rm …` 이 `argv[0] == "-n"` 이 돼 버린 것.
#:
#:   "opts"  : `-n 10` 처럼 값을 하나 먹는 짧은 옵션들 (집합)
#:   "skip"  : 옵션을 뺀 **위치 인자**를 몇 개 건너뛰나 (`timeout 30`)
#:   "subs"  : 이 하위명령 뒤부터가 실제 명령 (`conda run -n E <명령>`)
WRAPPERS: dict[str, dict] = {
    # 그냥 앞에 붙는 것
    "env": {"opts": {"-u", "--unset", "-C", "--chdir", "-S", "--split-string"}},
    "nohup": {},
    "sudo": {"opts": {"-u", "-g", "-C", "-p", "-r", "-t", "-U"}},
    "doas": {"opts": {"-u", "-C"}},
    "command": {},
    "exec": {"opts": {"-a"}},
    "setsid": {},
    "time": {"opts": {"-f", "-o"}},
    "watch": {"opts": {"-n", "-d"}},
    # 옵션이 값을 먹는 것 — 여기서 52종의 상당수가 뚫렸다
    "nice": {"opts": {"-n", "--adjustment"}},
    "ionice": {"opts": {"-c", "-n", "-p", "-P", "-u"}},
    "stdbuf": {"opts": {"-i", "-o", "-e", "--input", "--output", "--error"}},
    # `chrt -f 10 <명령>` — 정책 플래그 뒤에 우선순위가 위치 인자로 온다.
    # `chrt -p …` 는 이미 돌고 있는 프로세스를 건드리는 꼴이라 위치 인자가 다르다.
    "chrt": {"opts": {"-p"}, "skip": 1, "skipUnless": {"-p"}},
    # `taskset 0x3 <명령>` 은 마스크가 위치 인자, `taskset -c 0-3 <명령>` 은
    # 옵션이 먹는다. 둘을 가르지 않으면 한쪽이 뚫린다.
    "taskset": {"opts": {"-c", "--cpu-list"}, "skip": 1, "skipUnless": {"-c", "--cpu-list"}},
    "setpriv": {"opts": {"--reuid", "--regid", "--groups", "--inh-caps"}},
    "runuser": {"opts": {"-u", "-g", "-G", "-c"}},
    "flock": {"opts": {"-w", "--timeout", "-E"}, "skip": 1},
    # 위치 인자를 먹는 것
    "timeout": {"opts": {"-k", "-s", "--signal", "--kill-after"}, "skip": 1},
    # 실행 환경 래퍼 — `run`/`exec` 하위명령 뒤부터가 실제 명령
    "conda": {"opts": {"-n", "--name", "-p", "--prefix"}, "subs": {"run"}},
    "mamba": {"opts": {"-n", "--name", "-p", "--prefix"}, "subs": {"run"}},
    "micromamba": {"opts": {"-n", "--name", "-p", "--prefix"}, "subs": {"run"}},
    "poetry": {"opts": {"-C", "--directory"}, "subs": {"run"}},
    "pdm": {"opts": {"-p", "--project"}, "subs": {"run"}},
    "hatch": {"opts": {"-e", "--env"}, "subs": {"run"}},
    "uv": {"opts": {"--python", "-p", "--with", "--project"}, "subs": {"run", "tool"}},
    "rye": {"opts": {}, "subs": {"run"}},
    "pipx": {"opts": {"--spec", "--python"}, "subs": {"run"}},
    "pnpm": {"opts": {"-C", "--dir"}, "subs": {"exec", "dlx"}},
    "yarn": {"opts": {"--cwd"}, "subs": {"exec", "dlx"}},
    "npx": {"opts": {"-p", "--package", "-c"}},
    "xargs": {"opts": {"-n", "-P", "-I", "-i", "-d", "-s", "-E", "-a", "--replace"}},
    "parallel": {"opts": {"-j", "-N", "--jobs"}},
}

#: 셸 문자열을 인자로 품는 것. 안의 문자열을 **재귀로 다시 분류**한다.
#: 깊이를 넘으면 `suspicious` 로 올려 승인을 받는다.
SHELL_WRAPPERS = {
    "bash": "-c",
    "sh": "-c",
    "zsh": "-c",
    "dash": "-c",
    "ksh": "-c",
    "busybox": None,  # `busybox sh -c …` 는 재귀로 풀린다
    "su": "-c",
    "nix-shell": "--run",
    # `script -qc '<명령>' /dev/null` — 짧은 옵션이 뭉쳐 온다
    "script": "-c",
}

#: 재귀 깊이 상한. 넘으면 해석을 포기한다.
MAX_SHELL_DEPTH = 2

# --- 헤드리스 허용 목록 ------------------------------------------------------
# 실측(2026-11-04): 헤드리스에서 훅의 `defer` 는 통과가 아니라 **정지**다.
# `ls -1` 조차 `stop_reason: "tool_deferred"` 로 아무것도 못 하고 끝나며 기록도
# 안 남는다. 그래서 헤드리스에서는 "아는 명령은 allow, 모르면 ask" 로 간다.
#
# **대화형에는 적용하지 않는다** — 거기서는 defer 가 정상 동작한다(사람에게 물음).
#
# 판정 순서가 중요하다. 허용 목록은 **맨 마지막**이고, findings 가 하나도
# 없을 때만 본다. 금지 명령·비밀 파일·서버 보호·폴더 밖 쓰기·산출물 보존·
# 잠금·정책이 전부 그 앞이다 (`_scan` 이 구조로 보장한다).

#: 읽기만 하는 명령. 기본 목록은 **코드가 단일 출처**다 —
#: 정책(`bash.allowExtra`)으로는 더할 수만 있고 뺄 수 없다.
ALLOW_PLAIN = {
    "ls", "cat", "head", "tail", "wc", "pwd", "echo", "file", "stat", "du", "df",
    "date", "which", "basename", "dirname", "cut", "uniq", "diff", "nvidia-smi",
    "cd",
}

#: **코드를 실행하는** 명령. 샌드박스가 실제로 켜져 있을 때만 통과시킨다.
#:
#: `pytest` 는 AI 가 쓴 테스트 코드를 돌린다. 샌드박스가 꺼져 있으면 그 코드가
#: `~/.ssh` 를 읽고 네트워크로 보낼 수 있다 — 실측에서 `~/.claude.json` 과
#: **정책 파일**까지 읽혔다. 켜져 있으면 둘 다 `FileNotFoundError` 다.
#: 꺼져 있으면 `ask` 로 떨어져 사람이 본다.
ALLOW_IF_SANDBOXED = {"pytest"}

#: `git` 에서 읽기만 하는 하위명령
GIT_READONLY = {"status", "log", "diff", "show", "branch", "rev-parse"}

#: `git branch` 에 붙어도 되는 옵션 (목록 보기만). `-d`·`-m` 은 고치는 것이다.
GIT_BRANCH_OPTS = {"-a", "-r", "-v", "-vv", "--list", "--all", "--remotes", "--verbose"}

#: 리다이렉트를 허용하는 대상. 버리는 곳만.
SINK_PATHS = {"/dev/null", "/dev/stderr", "/dev/stdout"}

#: 안의 파일을 고치거나 실행하는 위험 옵션
FIND_DANGEROUS = {"-exec", "-execdir", "-delete", "-ok", "-okdir", "-fprint", "-fprintf", "-fls"}

#: 삭제
DELETE_CMDS = {"rm", "unlink", "shred", "trash", "trash-put"}
#: 목적지에 쓰는 명령 (마지막 피연산자가 목적지)
COPY_CMDS = {"cp", "install"}
#: 파일을 만드는 명령 (모든 피연산자가 대상). `tee` 는 비우고 쓰므로 따로 본다.
CREATE_CMDS = {"touch", "mkdir"}
#: 패키지
PKG_CMDS = {"pip", "pip3", "uv", "conda", "mamba", "micromamba", "poetry", "apt", "apt-get", "npm", "pnpm", "yarn"}
PKG_SUBS = {"install", "add", "remove", "uninstall", "upgrade", "update"}
#: `conda env <이것>` 이라야 환경을 건드린다. `conda env list` 는 보기만 한다.
ENV_SUBS = {"create", "update", "remove"}
#: 바깥으로 나가는 명령
NET_CMDS = {"curl", "wget", "huggingface-cli", "hf", "gdown", "aria2c", "scp", "ssh", "nc", "ftp"}
#  rsync 는 원격 여부로 갈려서 argv_to_findings 안에서 따로 본다.
#: 실험을 띄우는 명령
RUN_CMDS = {"python", "python3", "torchrun", "accelerate", "deepspeed", "sbatch", "srun"}

#: 임의 코드를 문자열로 받는 인터프리터. 정적 분석이 불가능해서 승인으로 보낸다.
CODE_FLAG_CMDS = {
    "python": "-c",
    "python3": "-c",
    "perl": "-e",
    "ruby": "-e",
    "node": "-e",
}

#: 레시피가 무엇이든 실행하는 것
OPAQUE_CMDS = {"make", "gmake", "ninja", "cmake", "just", "task"}

#: 파일 권한·소유자를 바꾸는 명령. 경로를 그대로 분류한다 —
#: 지금까지는 분류가 없어서 `chmod 777 ~/.claude` 가 안 걸렸다.
PERM_CMDS = {"chmod", "chown", "chgrp", "setfacl"}

#: `lab.db` 는 ②의 상태 전부다. 도구 이름을 막아도 다른 도구로 열 수 있어서
#: **이름이 아니라 대상**으로 막는다.
DB_MARKERS = ("lab.db", "lab.db-wal", "lab.db-shm")

#: `python -m <이것>` 은 labremote 금지를 모듈로 우회하는 길이다.
SELF_MODULES = {"app", "app.cli", "app.orchestrator", "app.main", "labremote"}
#: git 원격. 정책 bash.gitRemoteAsNet 에 따라 net 으로 볼지 결정한다.
GIT_REMOTE_SUBS = {"clone", "fetch", "pull", "push"}


def split_segments(command: str) -> list[str]:
    """`;` `&&` `||` `|` `&` 줄바꿈으로 쪼갠다. 따옴표 안은 건드리지 않는다."""
    out: list[str] = []
    buf: list[str] = []
    quote = ""
    i, n = 0, len(command)
    while i < n:
        c = command[i]
        if quote:
            buf.append(c)
            if c == "\\" and quote == '"' and i + 1 < n:
                buf.append(command[i + 1])
                i += 2
                continue
            if c == quote:
                quote = ""
            i += 1
            continue
        if c in "'\"":
            quote = c
            buf.append(c)
            i += 1
            continue
        if c == "\\" and i + 1 < n:
            buf.append(c)
            buf.append(command[i + 1])
            i += 2
            continue
        if command.startswith("&&", i) or command.startswith("||", i):
            out.append("".join(buf))
            buf = []
            i += 2
            continue
        # `2>&1` · `>&2` · `&>파일` 의 `&` 는 **리다이렉트의 일부**다. 여기서
        # 쪼개면 `ls -la 2>&1 >/dev/null` 이 "ls -la 2>" 와 "1 >/dev/null" 로
        # 갈라져 뒤 조각의 명령 이름이 "1" 이 된다.
        if c == "&":
            before = buf[-1] if buf else ""
            after = command[i + 1] if i + 1 < n else ""
            if before in (">", "<") or after == ">":
                buf.append(c)
                i += 1
                continue
        if c in ";|&\n":
            out.append("".join(buf))
            buf = []
            i += 1
            continue
        buf.append(c)
        i += 1
    out.append("".join(buf))
    return [s.strip() for s in out if s.strip()]


def strip_wrappers(argv: list[str]) -> list[str]:
    """`VAR=1 nohup nice -n 10 conda run -n E python ...` 에서 실제 명령만 남긴다.

    래퍼마다 "건너뛸 인자" 규격(`WRAPPERS`)을 보고 벗긴다. 실측에서 뚫린
    주된 이유가 옵션의 **인자**를 안 건너뛴 것이었다 — `nice -n 10 rm -rf …`
    를 벗기면 `argv[0]` 이 `-n` 이 되어 아무 분류도 안 됐다.
    """
    i = 0
    guard = 0
    while i < len(argv) and guard < 64:
        guard += 1
        token = argv[i]
        if re.match(r"\A[A-Za-z_][A-Za-z0-9_]*=", token):  # VAR=값
            i += 1
            continue
        spec = WRAPPERS.get(os.path.basename(token))
        if spec is None:
            break
        i += 1
        opts = spec.get("opts") or set()
        subs = spec.get("subs") or set()
        skip = int(spec.get("skip") or 0)
        skip_unless = spec.get("skipUnless") or set()
        seen_sub = not subs  # 하위명령이 필요 없으면 이미 본 것으로 본다
        while i < len(argv):
            item = argv[i]
            if item == "--":
                i += 1
                break
            if item.startswith("-"):
                head = item.split("=", 1)[0]
                if head in skip_unless:
                    # 그 옵션이 값을 먹으니 위치 인자는 안 온다 (`taskset -c 0-3`)
                    skip = 0
                i += 1
                # `-n 10` 처럼 값이 다음 토큰에 있는 경우만 하나 더 건너뛴다
                if head in opts and "=" not in item and i < len(argv):
                    i += 1
                continue
            if not seen_sub:
                if item in subs:
                    seen_sub = True
                    i += 1
                    continue
                # `conda env list` 처럼 run/exec 가 아니면 래퍼가 아니다.
                return argv[i - 1 :] if i else argv
            if skip > 0:
                skip -= 1
                i += 1
                continue
            break
    return argv[i:]


def _plausible_command(token: str) -> bool:
    """래퍼를 벗긴 뒤 남은 것이 **명령 이름**으로 보이는가.

    숫자만 남거나 공백이 섞여 있으면 벗기기가 어긋난 것이다. 그런 세그먼트를
    미분류로 흘리면 대화형에서 `defer` 가 되어 그냥 지나간다. 해석 실패는
    승인 경로로 올린다.
    """
    name = os.path.basename(token or "")
    if not name or " " in name:
        return False
    return not name.replace(".", "").replace("-", "").isdigit()


def _shell_payloads(argv: list[str]) -> list[str]:
    """`bash -c '…'` 처럼 품고 있는 **셸 문자열**들을 뽑는다."""
    if not argv:
        return []
    name = os.path.basename(argv[0])
    if name not in SHELL_WRAPPERS:
        return []
    flag = SHELL_WRAPPERS[name]
    out: list[str] = []
    letter = flag[1:] if flag and flag.startswith("-") and not flag.startswith("--") else ""
    for index, token in enumerate(argv[1:], start=1):
        if not flag:
            continue
        if token == flag and index + 1 < len(argv):
            out.append(argv[index + 1])
        elif token.startswith(f"{flag}="):
            out.append(token.split("=", 1)[1])
        elif (
            letter
            and token.startswith("-")
            and not token.startswith("--")
            and token.endswith(letter)
            and index + 1 < len(argv)
        ):
            # `script -qc '<명령>'` 처럼 짧은 옵션이 뭉쳐 온 꼴
            out.append(argv[index + 1])
    if not out and name == "busybox" and len(argv) > 2:
        # `busybox sh -c '…'` — 뒤를 그대로 다시 본다
        return _shell_payloads(argv[1:])
    return out


def _exec_payload(argv: list[str]) -> list[str]:
    r"""`find … -exec CMD {} \;` 의 CMD 부분. 없으면 빈 목록."""
    if not argv or os.path.basename(argv[0]) != "find":
        return []
    for index, token in enumerate(argv):
        if token in ("-exec", "-execdir", "-ok", "-okdir"):
            rest = []
            for item in argv[index + 1 :]:
                if item in (";", "+", "\\;"):
                    break
                rest.append(item)
            return rest
    return []


def _is_option(token: str) -> bool:
    return token.startswith("-") and token != "-"


def _operands(argv: list[str]) -> list[str]:
    """옵션을 뺀 피연산자. `--` 뒤는 전부 피연산자."""
    out: list[str] = []
    seen_dashdash = False
    for token in argv[1:]:
        if seen_dashdash:
            out.append(token)
            continue
        if token == "--":
            seen_dashdash = True
            continue
        if _is_option(token):
            continue
        out.append(token)
    return out


def _sed_targets(argv: list[str]) -> list[str]:
    """`sed -i` 가 고치는 파일. 제자리 수정이 아니면 빈 리스트.

    실측 우회 명령이 바로 이 꼴이었다:
        sed -i -e 's/A/B/g' -e 's/C/D/g' README.md
    """
    in_place = False
    script_taken = False
    files: list[str] = []
    i = 1
    while i < len(argv):
        token = argv[i]
        if token == "--":
            files.extend(argv[i + 1 :])
            break
        if token.startswith("--"):
            name, _, value = token.partition("=")
            if name == "--in-place":
                in_place = True
            elif name in ("--expression", "--file"):
                script_taken = True
                if not value:
                    i += 1
            i += 1
            continue
        if _is_option(token):
            rest = token[1:]
            k = 0
            while k < len(rest):
                flag = rest[k]
                if flag == "i":  # -i / -i.bak — 뒤는 접미사
                    in_place = True
                    break
                if flag in "ef":  # -e expr / -f file
                    script_taken = True
                    if k + 1 >= len(rest):  # 인자가 다음 토큰에 있다
                        i += 1
                    break
                k += 1
            i += 1
            continue
        if not script_taken:
            script_taken = True  # 첫 비옵션은 스크립트
        else:
            files.append(token)
        i += 1
    return files if in_place else []


def _redirect_targets(segment: str) -> list[tuple[str, bool]]:
    """`> file` `>> file` `2> file` 의 `(대상, 덧붙이기인가)`.

    `>` 는 **비우고** 쓰므로 원본 출력을 날린다 (`: > output/x`). `>>` 는
    덧붙이기라 파괴적이지 않다. 산출물 보존 판정이 이 둘을 구분해야 한다.
    """
    out: list[tuple[str, bool]] = []
    try:
        tokens = shlex.split(segment, posix=True)
    except ValueError:
        return out
    i = 0
    while i < len(tokens):
        token = tokens[i]
        match = re.match(r"\A[0-9&]?(>>?)(.*)\Z", token)
        if match:
            append = match.group(1) == ">>"
            target = match.group(2)
            # `2>&1` · `>&2` 는 파일이 아니라 **파일 서술자 복제**다. 파일로
            # 읽으면 `&1` 이라는 이름의 파일을 쓰는 것처럼 보인다.
            if target.startswith("&"):
                i += 1
                continue
            if target:
                out.append((target, append))
            elif i + 1 < len(tokens):
                out.append((tokens[i + 1], append))
                i += 1
        i += 1
    return out


def _dd_target(argv: list[str]) -> list[str]:
    return [t[3:] for t in argv[1:] if t.startswith("of=") and len(t) > 3]


#: 와일드카드를 펼칠 때 받는 최대 개수. `*` 하나로 폴더를 통째로 훑는 걸 막는다.
GLOB_LIMIT = 200


def _expand(token: str, cwd: str) -> list[str]:
    """와일드카드가 있으면 `cwd` 기준으로 펼친다. 없으면 그대로 한 개.

    `.en*`·`.e?v` 처럼 비밀 파일 이름을 가린 채 읽는 걸 막으려고 쓴다.
    셸이 실제로 하는 전개와 완전히 같을 수는 없고(변수 치환은 이미
    `suspicious` 로 올린다), 못 펼치면 원래 토큰만 돌려준다.
    """
    if not any(c in token for c in "*?["):
        return [token]
    try:
        pattern = token if os.path.isabs(token) else os.path.join(cwd, token)
        found = sorted(globmod.glob(pattern, recursive=False))[:GLOB_LIMIT]
    except (OSError, ValueError, re.error):
        return [token]
    return found or [token]


def secret_findings(segment: str, argv: list[str], ctx: Ctx) -> list[Finding]:
    """명령이 건드리는 모든 피연산자 중 비밀 파일이 있으면 Finding.

    읽기 명령 목록을 따로 관리하지 않고 **피연산자 전체**를 본다. 그래야
    `cat`·`head`·`grep`·`cp .env ./x`·`tar` 를 한 번에 덮는다. 읽기든
    쓰기든 비밀 파일이 대상이면 막는다.

    못 막는 것: `grep -r SECRET .` 처럼 **대상이 폴더**인 재귀 읽기.
    그래서 "비밀은 프로젝트 폴더 밖에 둔다" 가 1차 방어다
    (docs/operations.md 의 한계).
    """
    out: list[Finding] = []
    seen: set[str] = set()
    for token in argv[1:]:
        if _is_option(token):
            continue
        # `of=x` · `VAR=x` 는 값 쪽이 경로다
        keyed = re.match(r"\A[A-Za-z_][A-Za-z0-9_]*=(.+)\Z", token)
        if keyed:
            token = keyed.group(1)
        for item in _expand(token, ctx.cwd):
            target = paths.safe_resolve(item, ctx.cwd)
            if target in seen:
                continue
            seen.add(target)
            if is_secret(target, ctx):
                out.append(
                    Finding("secret", target=target, detail=segment[:120], writes=True)
                )
    return out


def _short_flags(argv: list[str]) -> str:
    """짧은 옵션 글자들을 모아 돌려준다. `-rn` 처럼 뭉친 것도 풀어서."""
    out = []
    for token in argv[1:]:
        if token.startswith("-") and not token.startswith("--") and token != "-":
            out.append(token[1:].split("=", 1)[0])
    return "".join(out)


def _long_flags(argv: list[str]) -> set[str]:
    return {t.split("=", 1)[0] for t in argv[1:] if t.startswith("--")}


def _allow_find(argv: list[str]) -> bool:
    """`-exec`·`-delete` 가 없을 때만. 있으면 무엇이든 실행·삭제한다."""
    return not (set(argv[1:]) & FIND_DANGEROUS)


def _allow_git(argv: list[str]) -> bool:
    """읽기 하위명령만. `branch` 는 목록 보기 옵션만."""
    subs = [t for t in argv[1:] if not t.startswith("-")]
    if not subs or subs[0] not in GIT_READONLY:
        return False
    if subs[0] == "branch":
        return all(
            t in GIT_BRANCH_OPTS
            for t in argv[1:]
            if t.startswith("-")
        )
    return True


def _allow_no_inplace(argv: list[str]) -> bool:
    """`grep`·`sed` 는 `-i` 가 없을 때만 (sed -i 는 제자리 수정이다)."""
    return "i" not in _short_flags(argv) and "--in-place" not in _long_flags(argv)


def _allow_sort(argv: list[str]) -> bool:
    """`sort -o 파일` 은 파일을 쓴다."""
    return "o" not in _short_flags(argv) and "--output" not in _long_flags(argv)


#: 조건부 허용. 이름 -> 조건 함수
ALLOW_CONDITIONAL = {
    "find": _allow_find,
    "git": _allow_git,
    "grep": _allow_no_inplace,
    "egrep": _allow_no_inplace,
    "rgrep": _allow_no_inplace,
    "sed": _allow_no_inplace,
    "sort": _allow_sort,
}


def allow_extra(ctx: Ctx) -> set[str]:
    """정책이 **더한** 명령. 기본 목록을 줄이지는 못한다."""
    extra = (getattr(ctx.policy, "bash", {}) or {}).get("allowExtra") or []
    return {str(x).strip() for x in extra if str(x).strip()}


def _targets_inside(argv: list[str], ctx: Ctx) -> bool:
    """피연산자가 전부 프로젝트 안(또는 버리는 곳)을 가리키는가.

    폴더 밖 **읽기**는 정책상 허용이다(`allowOutsideRead`). 그래도 허용
    목록이 그걸 **조용히** 열어 주지는 않는다 — 다른 프로젝트의 노트를
    읽는 것과 `README.md` 를 읽는 것은 사람이 한 번 보고 고를 일이다.
    헤드리스에서만 쓰는 목록이라 여기서 좁혀도 대화형은 그대로다.
    """
    for item in _operands(argv):
        if item in SINK_PATHS or not item:
            continue
        target = paths.safe_resolve(item, ctx.cwd)
        if target in SINK_PATHS:
            continue
        if not paths.is_inside(ctx.root, target):
            return False
    return True


def is_allowlisted(segment: str, argv: list[str], ctx: Ctx) -> bool:
    """헤드리스에서 그냥 통과시켜도 되는 명령인가.

    **findings 가 하나도 없을 때만** 불린다(`_scan`). 그래서 여기 오는 건
    "금지 명령도 아니고 비밀 파일도 안 건드리고 폴더 밖도 안 쓰고 정책
    행동 유형에도 안 걸린" 명령이다. 그 중 **아는 것**만 통과시킨다.
    """
    if not argv:
        return False
    # 리다이렉트가 있으면 안 된다 — 버리는 곳(`/dev/null`)만 예외.
    for target, _ in _redirect_targets(segment):
        if target not in SINK_PATHS:
            return False
    name = os.path.basename(argv[0])
    if name in ALLOW_IF_SANDBOXED and not getattr(ctx, "sandbox", False):
        # 샌드박스가 꺼져 있으면 AI 가 쓴 코드가 그대로 돈다. 사람이 본다.
        return False
    if (
        name not in ALLOW_CONDITIONAL
        and name not in ALLOW_IF_SANDBOXED
        and not (name in ALLOW_PLAIN or name in allow_extra(ctx))
    ):
        return False
    if not _targets_inside(argv, ctx):
        return False
    if name in ALLOW_CONDITIONAL:
        return ALLOW_CONDITIONAL[name](argv)
    return True


def _is_entrypoint(argv: list[str], operands: list[str], entrypoints: list) -> bool:
    """`Config.yaml` 의 entrypoint 를 직접 돌리는 꼴인가.

    훅은 YAML 을 읽지 않는다(표준 라이브러리만 쓴다). 그래서 entrypoint 목록은
    **정책 파일로 복사**해 둔다 — 정책은 프로젝트 밖이라 AI 가 못 고친다.
    """
    wanted = {str(e).strip() for e in entrypoints if str(e).strip()}
    leaves = {os.path.basename(w) for w in wanted}
    for token in [argv[0], *operands]:
        clean = token.lstrip("./")
        if clean in wanted or token in wanted or os.path.basename(token) in leaves:
            return True
    return False


def argv_to_findings(argv: list[str], ctx: Ctx) -> list[Finding]:
    name = os.path.basename(argv[0]) if argv else ""
    if not name:
        return []

    deny_cmds = (getattr(ctx.policy, "bash", {}) or {}).get("denyCommands") or []
    if name in deny_cmds:
        return [Finding("denied-command", target=name, detail=" ".join(argv[:3]), writes=True)]

    # ②의 상태 파일은 어떤 도구로든 못 건드린다. 도구 이름만 막으면
    # `cp lab.db /tmp/x` 나 파이썬 한 줄로 돌아간다.
    for token in argv[1:]:
        base = os.path.basename(token.split("=", 1)[-1])
        if base in DB_MARKERS or any(base.startswith(m) for m in DB_MARKERS):
            return [
                Finding(
                    "denied-command",
                    target=f"{name} … {base}",
                    detail="lab.remote 의 상태 DB",
                    writes=True,
                )
            ]

    operands = _operands(argv)
    out: list[Finding] = []

    # `labremote` 를 막아도 모듈로 부를 수 있다: `python -m app.cli approve …`
    if name in ("python", "python3") and "-m" in argv[1:3]:
        try:
            module = argv[argv.index("-m") + 1]
        except (ValueError, IndexError):
            module = ""
        if module in SELF_MODULES or module.split(".")[0] == "app":
            return [
                Finding(
                    "denied-command",
                    target=f"{name} -m {module}",
                    detail="lab.remote 자신을 부르는 길",
                    writes=True,
                )
            ]

    # 임의 코드 문자열. 무엇을 건드릴지 알 수 없다.
    flag = CODE_FLAG_CMDS.get(name)
    if flag and flag in argv[1:]:
        return [Finding("suspicious", target=" ".join(argv[:3]), writes=True)]

    if name in OPAQUE_CMDS:
        return [Finding("suspicious", target=" ".join(argv[:3]), writes=True)]

    # 훅·정책 코드를 직접 돌리는 길
    if name in RUN_CMDS:
        for item in operands:
            target = paths.safe_resolve(item, ctx.cwd)
            if is_hard_protected(target):
                return [
                    Finding(
                        "hardProtect",
                        target=target,
                        detail=f"{name} 으로 직접 실행",
                        writes=True,
                    )
                ]

    if name in PERM_CMDS:
        # 첫 피연산자는 권한 모드(`777`·`u+x`)다. 나머지가 경로다.
        for item in operands[1:] if len(operands) > 1 else []:
            out.extend(classify_path(item, ctx, overwrite=True))
        return out

    if name == "ln":
        # 심볼릭 링크로 보호 경로를 프로젝트 안에 끌어오는 길. 원본·목적지 둘 다 본다.
        for item in operands:
            out.extend(classify_path(item, ctx, overwrite=True))
        return out

    entrypoints = (getattr(ctx.policy, "bash", {}) or {}).get("entrypoints") or []
    if entrypoints and _is_entrypoint(argv, operands, entrypoints):
        # 학습은 오케스트레이터가 띄운다. Claude 가 직접 돌리면 승인을 받는다.
        return [Finding("newexp", target=" ".join(argv[:4]))]

    if name in DELETE_CMDS:
        for item in operands:
            out.extend(classify_path(item, ctx, deleting=True))
        return out

    if name == "mv":
        if len(operands) >= 2:
            # 출처는 사라진다 — output/ 밖으로 빼는 것도 삭제로 본다.
            for item in operands[:-1]:
                out.extend(classify_path(item, ctx, deleting=True))
            out.extend(classify_path(operands[-1], ctx, overwrite=True))
        return out

    if name == "rsync":
        # 원격(host:path)이 끼어 있으면 네트워크, 아니면 그냥 복사다.
        if any(":" in token for token in operands):
            return [Finding("net", target=" ".join(argv[:3]))]
        if operands:
            out.extend(classify_path(operands[-1], ctx))
        return out

    if name in COPY_CMDS:
        if operands:
            out.extend(classify_path(operands[-1], ctx, overwrite=True))
        return out

    if name == "tee":
        # `tee x` 는 비우고 쓴다. `tee -a x` 는 덧붙인다.
        append = any(t in ("-a", "--append") for t in argv[1:])
        for item in operands:
            out.extend(classify_path(item, ctx, truncating=not append))
        return out

    if name in CREATE_CMDS:
        for item in operands:
            out.extend(classify_path(item, ctx))
        return out

    if name == "truncate":
        for item in operands:
            out.extend(classify_path(item, ctx, truncating=True))
        return out

    if name == "dd":
        # conv=notrunc 가 없으면 목적지를 자른다
        notrunc = any("notrunc" in t for t in argv[1:] if t.startswith("conv="))
        for item in _dd_target(argv):
            out.extend(classify_path(item, ctx, truncating=not notrunc, overwrite=True))
        return out

    if name == "sed":
        for item in _sed_targets(argv):
            out.extend(classify_path(item, ctx, overwrite=True))
        return out

    if name in PKG_CMDS:
        subs = [t for t in argv[1:4] if not _is_option(t)]
        # `conda env list` 는 보기만 한다. `conda env create` 라야 설치다.
        if subs[:1] == ["env"]:
            if len(subs) > 1 and subs[1] in ENV_SUBS:
                return [Finding("pkg", target=" ".join(argv[:4]))]
            return []
        if any(token in PKG_SUBS for token in subs):
            return [Finding("pkg", target=" ".join(argv[:4]))]
        return []

    if name == "python" or name == "python3":
        # `python -m pip install ...` 도 패키지 설치다
        if "-m" in argv[1:3]:
            try:
                module = argv[argv.index("-m") + 1]
            except (ValueError, IndexError):
                module = ""
            if os.path.basename(module) in PKG_CMDS:
                return [Finding("pkg", target=" ".join(argv[:5]))]

    if name in NET_CMDS:
        return [Finding("net", target=" ".join(argv[:3]))]

    if name in ("git", "gh"):
        as_net = (getattr(ctx.policy, "bash", {}) or {}).get("gitRemoteAsNet")
        if as_net and (len(argv) > 1 and argv[1] in GIT_REMOTE_SUBS or name == "gh"):
            return [Finding("net", target=" ".join(argv[:3]))]
        return []

    if name in RUN_CMDS:
        if any(token.endswith(".py") for token in operands) or name != "python":
            return [Finding("newexp", target=" ".join(argv[:4]))]
        return []

    if name == "tmux" and any("train" in token for token in argv[1:]):
        return [Finding("newexp", target=" ".join(argv[:4]))]

    return []


def _scan(
    command: str, ctx: Ctx, depth: int = 0
) -> tuple[list[Finding], list[str], list[str]]:
    """세그먼트별로 훑는다 -> (찾아낸 것, **분류하지 못한 세그먼트**).

    두 번째 값이 ①의 경계 버그를 메운다. 아래 `classify_with_coverage` 의 주석.

    돌려주는 것은 `(찾아낸 것, 모르는 세그먼트, 허용 목록에 있는 세그먼트)` 다.
    뒤 둘은 `classify_with_coverage` 만 쓴다 — `classify()` 의 계약("명령 안에
    들어 있는 **행동 유형**")을 더럽히지 않으려고 따로 돌려준다.

    `depth` 는 `bash -c '…'` 같은 셸 래퍼를 풀어 들어간 깊이다.
    `MAX_SHELL_DEPTH` 를 넘으면 해석을 포기하고 `suspicious` 로 올린다 —
    중첩이 깊어질수록 따옴표 처리가 실제 셸과 어긋날 확률이 올라간다.
    """
    cfg = getattr(ctx.policy, "bash", {}) or {}
    if cfg.get("escalateOnSubstitution", True) and SUSPICIOUS_RE.search(command):
        # 치환이 보이면 세그먼트를 쪼개는 것조차 의미가 없다. 통째로 올린다.
        return [Finding("suspicious", target=command[:200], writes=True)], [], []

    out: list[Finding] = []
    unknown: list[str] = []
    allowed: list[str] = []
    cwd = ctx.cwd
    for segment in split_segments(command):
        before = len(out)
        try:
            argv = shlex.split(segment, posix=True)
        except ValueError:
            out.append(Finding("unparsed", target=segment[:200], writes=True))
            continue

        here = Ctx(**{**ctx.__dict__, "cwd": cwd})
        for item, append in _redirect_targets(segment):
            # `>>` 는 덧붙이기라 원본을 날리지 않는다 (실험이 로그를 쌓는 모양).
            out.extend(
                classify_path(item, here, truncating=not append, overwrite=not append)
            )

        argv = strip_wrappers(argv)
        if not argv:
            # `env` 한 개처럼 래퍼만 남은 꼴. 무엇을 하려는지 알 수 없다.
            if len(out) == before:
                unknown.append(segment)
            continue

        # 읽기든 쓰기든 비밀 파일이 대상이면 막는다 (옵션·와일드카드 포함).
        out.extend(secret_findings(segment, argv, here))

        # 단순 `cd X` 는 따라간다. 조건부 cd 는 포기한다(문서화된 한계).
        # 끝까지 따라간 명령이라 "분류 못 한 것" 에 넣지 않는다.
        if os.path.basename(argv[0]) == "cd":
            operands = _operands(argv)
            if operands:
                cwd = paths.safe_resolve(operands[0], cwd)
            if len(out) == before:
                allowed.append(segment)
            continue

        here_cwd = Ctx(**{**ctx.__dict__, "cwd": cwd})
        if not _plausible_command(argv[0]):
            # 래퍼를 벗겼는데 명령 이름이 아닌 게 남았다 = 해석에 실패했다.
            # 조용히 미분류로 넘기지 않고 승인 경로로 올린다.
            out.append(Finding("suspicious", target=segment[:200], writes=True))
            continue
        out.extend(argv_to_findings(argv, here_cwd))

        # `bash -c '…'` · `find … -exec CMD \;` 는 **안의 명령을 다시 분류**한다.
        nested = _shell_payloads(argv)
        if nested:
            if depth >= MAX_SHELL_DEPTH:
                out.append(
                    Finding("suspicious", target=segment[:200], writes=True)
                )
            else:
                for payload in nested:
                    inner, inner_unknown, inner_allowed = _scan(
                        payload, here_cwd, depth=depth + 1
                    )
                    out.extend(inner)
                    unknown.extend(inner_unknown)
                    allowed.extend(inner_allowed)
        exec_argv = _exec_payload(argv)
        if exec_argv:
            out.extend(argv_to_findings(strip_wrappers(exec_argv), here_cwd))

        if len(out) == before and segment not in allowed:
            if is_allowlisted(segment, argv, here_cwd):
                # 아는 명령이다. 헤드리스에서 `defer` 는 정지라서 allow 가 필요하다.
                allowed.append(segment)
            else:
                unknown.append(segment)
    return out, unknown, allowed


def classify(command: str, ctx: Ctx) -> list[Finding]:
    """명령 안에 들어 있는 **행동 유형**만. 판정은 `classify_with_coverage` 를 쓴다."""
    return _scan(command, ctx)[0]


def allowlisted_segments(command: str, ctx: Ctx) -> list[str]:
    """허용 목록에 있어서 그냥 통과시킬 세그먼트 (헤드리스용)."""
    return _scan(command, ctx)[2]


def classify_with_coverage(command: str, ctx: Ctx) -> list[Finding]:
    """`classify()` + **분류하지 못한 세그먼트**를 `unclassified` Finding 으로.

    ①의 경계 버그를 메운다. 미분류 세그먼트는 findings 에 아무것도 보태지
    않았고, `combine()` 은 "가장 제한적인 것이 이긴다" 인데 **없는 것은 제한을
    보태지 않는다.** 그래서 허용되는 조각 하나가 전체를 통과시켰다 (실측):

        echo x > src/t.txt                                 -> ['code'] -> allow
        echo x > src/t.txt && conda run -n base rm -rf <밖>  -> ['code'] -> allow  ⚠
        echo x > src/t.txt && rm -rf <밖>                    -> ['code','outside'] -> deny

    이제 두 번째 줄이 `['code', 'unclassified']` 가 되어 allow 로 떨어지지
    않는다. 대화형은 defer(사람에게 묻기), 헤드리스는 ask(승인 대기열)다 —
    `decide.decide` 의 `unclassified` 분기.

    **이건 보조 수단이다.** 1차 방어는 Claude Bash 샌드박스다(실측 14).
    여기서 하는 일은 "모르는 건 자동으로 열지 않는다" 와 **기록을 남기는 것**이다.
    """
    found, unknown, allowed = _scan(command, ctx)
    seen: set[str] = set()
    for segment in unknown:
        key = segment[:200]
        if key in seen:
            continue
        seen.add(key)
        found.append(
            Finding("unclassified", target=key, detail=command[:200], writes=True)
        )
    if unknown:
        # 모르는 조각이 하나라도 있으면 전체가 승인 대상이다. 허용 목록은
        # **전부 아는 명령일 때만** 의미가 있다 (조건 2).
        return found
    for segment in allowed:
        key = segment[:200]
        if key in seen:
            continue
        seen.add(key)
        found.append(Finding("bashAllowed", target=key, detail=command[:200]))
    return found
