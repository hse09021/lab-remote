#!/usr/bin/env bash
# lab.remote 설치 — git clone 한 폴더에서:  ./install.sh
#
# 하는 일 (PLAN 1장 "바꾸는 것" 안에서만):
#   1. conda 환경 labremote 만들기 (이미 있으면 그대로)
#   2. 서버 패키지 설치 (pip install -e server[api])
#   3. 웹 화면 빌드 (npm 이 있을 때)
#   4. labremote doctor
# 하지 않는 일: ~/.bashrc · ~/.claude · .condarc · cron · systemd 를 고치지 않아요.
# 자동 시작과 code tunnel 은 따로 켜요 (docs/SETUP.md).
#
#   ./install.sh --dry-run   돌릴 명령만 보여 줘요
set -euo pipefail

cd "$(dirname "$0")"
ROOT="$(pwd)"
DRY=0
[ "${1:-}" = "--dry-run" ] && DRY=1

say() { printf '\n▶ %s\n' "$*"; }
run() {
  printf '  $ %s\n' "$*"
  [ "$DRY" = 1 ] || "$@"
}

# conda — 셸 설정 없이도 찾아요
CONDA="${CONDA_EXE:-}"
if [ -z "$CONDA" ]; then
  CONDA="$(command -v conda || true)"
fi
for c in "$HOME/miniconda3/bin/conda" "$HOME/anaconda3/bin/conda" "$HOME/miniforge3/bin/conda"; do
  [ -n "$CONDA" ] && break
  [ -x "$c" ] && CONDA="$c"
done
if [ -z "$CONDA" ]; then
  echo "✘ conda 를 못 찾았어요. Miniconda 를 먼저 설치해 주세요." >&2
  exit 1
fi

say "1/4 conda 환경 labremote"
if "$CONDA" env list | awk '{print $1}' | grep -qx labremote; then
  echo "  이미 있어요 — 그대로 써요"
else
  run "$CONDA" create -y -n labremote python=3.11
fi
ENV_PREFIX="$("$CONDA" env list | awk '$1=="labremote"{print $NF}')"
ENV_PREFIX="${ENV_PREFIX:-$(dirname "$(dirname "$CONDA")")/envs/labremote}"
PY="$ENV_PREFIX/bin/python"

say "2/4 서버 패키지"
run "$PY" -m pip install -e "$ROOT/server[api]"

say "3/4 웹 화면 빌드"
# nvm 으로 깐 node 는 셸 설정 밖에서는 PATH 에 없어요 — 이 스크립트 안에서만 불러요
if ! command -v npm >/dev/null 2>&1 && [ -s "$HOME/.nvm/nvm.sh" ]; then
  # shellcheck disable=SC1091
  . "$HOME/.nvm/nvm.sh" >/dev/null
fi
if command -v npm >/dev/null 2>&1; then
  run bash -c "cd '$ROOT/web' && npm ci && npm run build"
elif [ -f "$ROOT/web/dist/index.html" ]; then
  echo "  npm 이 없어서 이미 있는 web/dist 를 그대로 써요"
else
  echo "  ⚠ npm(Node.js 20 이상)이 없어서 웹 화면을 빌드하지 못했어요. Node 를 설치한 뒤 다시 돌려 주세요."
fi

say "4/4 점검"
if [ "$DRY" = 1 ]; then
  printf '  $ %s\n' "(cd server && $PY -m app.cli doctor)"
else
  (cd "$ROOT/server" && "$PY" -m app.cli doctor) || true
fi

cat <<EOF

다 됐어요. 서버 띄우기:
  $ENV_PREFIX/bin/labremote serve            # http://127.0.0.1:8000
켜 두려면 (재부팅해도):
  $ENV_PREFIX/bin/labremote autostart install
밖에서 접속하려면 docs/SETUP.md 의 "밖에서 접속" 을 봐 주세요.
EOF
