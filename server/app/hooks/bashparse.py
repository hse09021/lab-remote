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

import os
import re
import shlex

from .. import paths
from .classify import Ctx, Finding, classify_path

__all__ = ["classify", "split_segments", "strip_wrappers"]

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
#: 파일을 만드는 명령 (모든 피연산자가 대상)
CREATE_CMDS = {"touch", "mkdir", "tee"}
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


def _redirect_targets(segment: str) -> list[str]:
    """`> file` `>> file` `2> file` 의 대상."""
    out: list[str] = []
    try:
        tokens = shlex.split(segment, posix=True)
    except ValueError:
        return out
    i = 0
    while i < len(tokens):
        token = tokens[i]
        match = re.match(r"\A[0-9&]?>>?(.*)\Z", token)
        if match:
            if match.group(1):
                out.append(match.group(1))
            elif i + 1 < len(tokens):
                out.append(tokens[i + 1])
                i += 1
        i += 1
    return out


def _dd_target(argv: list[str]) -> list[str]:
    return [t[3:] for t in argv[1:] if t.startswith("of=") and len(t) > 3]


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
            for item in operands[:-1]:
                out.extend(classify_path(item, ctx, deleting=True))
            out.extend(classify_path(operands[-1], ctx))
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
            out.extend(classify_path(operands[-1], ctx))
        return out

    if name in CREATE_CMDS:
        for item in operands:
            out.extend(classify_path(item, ctx))
        return out

    if name == "truncate":
        for item in operands:
            out.extend(classify_path(item, ctx))
        return out

    if name == "dd":
        for item in _dd_target(argv):
            out.extend(classify_path(item, ctx))
        return out

    if name == "sed":
        for item in _sed_targets(argv):
            out.extend(classify_path(item, ctx))
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

        for item in _redirect_targets(segment):
            out.extend(classify_path(item, Ctx(**{**ctx.__dict__, "cwd": cwd})))

        argv = strip_wrappers(argv)
        if not argv:
            continue

        # 단순 `cd X` 는 따라간다. 조건부 cd 는 포기한다(문서화된 한계).
        if os.path.basename(argv[0]) == "cd":
            operands = _operands(argv)
            if operands:
                cwd = paths.safe_resolve(operands[0], cwd)
            continue

        out.extend(argv_to_findings(argv, Ctx(**{**ctx.__dict__, "cwd": cwd})))
    return out
