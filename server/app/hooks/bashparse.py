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
from .classify import Ctx, Finding, classify_path, is_secret

__all__ = ["classify", "split_segments", "strip_wrappers", "secret_findings"]

#: 안에 다른 명령을 끼워 넣는 흔적. 보이면 해석을 포기한다.
SUSPICIOUS_RE = re.compile(
    r"\$\(|`|(?<![\w-])eval(?![\w-])|(?<![\w-])base64(?![\w-])"
    r"|\|\s*(sh|bash|zsh|python[0-9.]*)\b"
)

#: 명령 앞에 붙어 실제 명령을 가리는 것들
WRAPPERS = {"env", "nohup", "sudo", "stdbuf", "nice", "ionice", "time", "command", "exec"}

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
    """`VAR=1 nohup sudo python ...` 에서 실제 명령만 남긴다."""
    i = 0
    while i < len(argv):
        token = argv[i]
        if re.match(r"\A[A-Za-z_][A-Za-z0-9_]*=", token):  # VAR=값
            i += 1
            continue
        name = os.path.basename(token)
        if name in WRAPPERS:
            i += 1
            # timeout 은 첫 인자가 시간이다
            continue
        if name == "timeout":
            i += 1
            if i < len(argv) and not argv[i].startswith("-"):
                i += 1
            continue
        break
    return argv[i:]


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
            if match.group(2):
                out.append((match.group(2), append))
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


def argv_to_findings(argv: list[str], ctx: Ctx) -> list[Finding]:
    name = os.path.basename(argv[0]) if argv else ""
    if not name:
        return []

    deny_cmds = (getattr(ctx.policy, "bash", {}) or {}).get("denyCommands") or []
    if name in deny_cmds:
        return [Finding("denied-command", target=name, detail=" ".join(argv[:3]), writes=True)]

    operands = _operands(argv)
    out: list[Finding] = []

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


def classify(command: str, ctx: Ctx) -> list[Finding]:
    cfg = getattr(ctx.policy, "bash", {}) or {}
    if cfg.get("escalateOnSubstitution", True) and SUSPICIOUS_RE.search(command):
        return [Finding("suspicious", target=command[:200], writes=True)]

    out: list[Finding] = []
    cwd = ctx.cwd
    for segment in split_segments(command):
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
            continue

        # 읽기든 쓰기든 비밀 파일이 대상이면 막는다 (옵션·와일드카드 포함).
        out.extend(secret_findings(segment, argv, here))

        # 단순 `cd X` 는 따라간다. 조건부 cd 는 포기한다(문서화된 한계).
        if os.path.basename(argv[0]) == "cd":
            operands = _operands(argv)
            if operands:
                cwd = paths.safe_resolve(operands[0], cwd)
            continue

        out.extend(argv_to_findings(argv, Ctx(**{**ctx.__dict__, "cwd": cwd})))
    return out
