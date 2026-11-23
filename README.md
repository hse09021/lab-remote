# lab.remote

GPU가 있는 데스크톱에서 AI 연구를 돌리고, 어디서든 브라우저로 **보고 · 실행하고 · 알림 받는** 개인용 도구예요.

연구 폴더를 등록하면 그 폴더의 파일 · git · 학습 실행 · Claude Code 세션을 한 화면에서 다뤄요. 휴대폰에서 승인 요청에 답하고, 학습이 끝나거나 끊기면 Discord로 알림을 받아요. 논문은 Obsidian vault를 그대로 읽어서 라이브러리 · 지식 그래프 · 리더로 보여 줘요.

> 혼자 쓰는 도구예요. 서버는 이 컴퓨터(`127.0.0.1`)에만 열리고, 밖에서는 VS Code의 code tunnel로 들어와요.

## 무엇을 하나

| 화면 | 하는 일 |
|---|---|
| **Dashboard** | 답이 필요한 세션 · 작업 중 · 끝남을 한눈에 봐요. 세션 카드마다 할 일 진행, git 변경(+/−), PR 상태가 보여요. 보기는 세 가지예요 — **Overview** · **Agents**(세션 · 하위 에이전트 · 학습 실행 그래프) · **Schedule**(24시간 띠와 예약 표) |
| **Projects** | 등록한 연구 폴더의 파일 · worktree · 세션과 실행 · 설정을 다뤄요. 학습은 tmux 안에서 돌아서 접속이 끊겨도 계속 돌아요 |
| **IDE** | 브라우저 안의 편집기(Monaco) · 터미널 · 검색 · 소스 제어(커밋, main에 합치기, PR) · 실행 탭이 있어요. 에이전트가 만든 파일에는 어느 세션이 썼는지 보여요 |
| **ADE** | Claude Code 세션과 대화해요. 도구 승인 · 질문에 답하기, Mode · 모델 · Effort 고르기, 세션 이름 바꾸기 · 닫기를 해요. 오른쪽에 **Scenario** · 변경 · 실행이 있어요 |
| **Papers** | Obsidian vault의 논문 노트를 **List** · **Graph**로 봐요. arXiv 링크나 PDF로 논문을 추가하고, AI 요약 · 라이브러리에 묻기 · 모음 · BibTeX를 써요 |
| **논문 리더** | PDF와 arXiv HTML을 오가며 읽어요. 섹션 · 그림 · 표 · 수식 설명, 고른 글 번역 · 질문, AI 하이라이트와 참고문헌, 내 하이라이트 · 메모를 남겨요 |
| **Inbox** | 승인 요청 · 실행 결과 · 예약 · PR · 머지 · 시스템 경고를 모아요. Discord로 보낼 알림과 조용한 시간을 정해요 |
| **설정** | Conda 환경 만들기 · 패키지 관리, System(서버 · 터널 · 자동 시작 상태) |

휴대폰에서는 화면이 좁게 바뀌고 아래에 탭이 생겨요.

### 하지 않는 것

- **AI 자동화를 하지 않아요.** AI 연구 루프 · 실험 큐 · "앞 실행이 끝나면 시작" 같은 연쇄 실행이 없어요. 예약은 사람이 시각으로 건 것만 돌아요.
- **Claude는 사람이 누를 때만 불러요.** 요약 · 설명 · 분석 모두 버튼을 누를 때만 돌아요.
- **시스템 설정을 고치지 않아요.** `~/.bashrc` · `~/.claude/` · `.condarc` · cron · systemd 타이머 · 연구 프로젝트의 `.gitignore`를 건드리지 않아요. `--dangerously-skip-permissions`도 쓰지 않아요.
- **push하지 않아요.** PR은 브랜치가 이미 원격에 올라가 있을 때만 열어요.
- 서버는 nice 19 · ionice idle로 돌고 GPU를 쓰지 않아요.

## 설치

### 먼저 있어야 하는 것

| 무엇 | 왜 |
|---|---|
| Linux + systemd | 실행 · 자동 시작 |
| Miniconda (또는 conda) | 서버 환경 · 실험 환경 |
| tmux | 접속이 끊겨도 학습이 계속 돌게 (`sudo apt install tmux`) |
| **Claude Code — 설치하고 로그인까지** | 채팅 · 승인 · Scenario · 논문 AI. 터미널에서 `claude`를 한 번 열어 로그인해요 |
| Node.js 20 이상 | 웹 화면 빌드 (설치할 때 한 번) |
| (선택) VS Code | 밖에서 접속 (code tunnel) |
| (선택) `gh` (GitHub CLI) | PR 만들기 · 열린 PR 보기 |

lab.remote는 Claude 로그인을 대신하지 않아요. 터미널에서 쓰는 그 Claude Code를 [`claude-agent-sdk`](https://pypi.org/project/claude-agent-sdk/)로 불러 써요. `ANTHROPIC_API_KEY`가 환경에 있으면 구독이 아니라 종량제로 과금될 수 있어요 — `labremote doctor`가 알려 줘요.

### 받고 설치하기

```bash
git clone https://github.com/hse09021/lab-remote.git ~/lab-remote
cd ~/lab-remote
./install.sh            # 무엇을 돌릴지만 보려면 ./install.sh --dry-run
```

`install.sh`는 네 가지를 해요.

1. conda 환경 `labremote`를 만들어요 (있으면 그대로 써요).
2. 서버 패키지를 설치해요 (`pip install -e server[api]`).
3. 웹 화면을 빌드해요 (`npm ci && npm run build`).
4. `labremote doctor`로 점검해요.

셸 설정은 고치지 않으니 명령은 환경 경로로 불러요. 자주 쓰면 alias를 직접 넣어도 돼요.

```bash
~/miniconda3/envs/labremote/bin/labremote doctor     # ✘가 없으면 돼요
alias labremote=~/miniconda3/envs/labremote/bin/labremote
```

### 띄우기

```bash
labremote serve          # http://127.0.0.1:8000
```

이 컴퓨터의 브라우저에서 `http://127.0.0.1:8000`을 열어요. 처음 열면 시작 안내가 나와요 — Claude Code 로그인 → 프로젝트 등록 → Discord 알림 순서예요.

### 켜 두기 (재부팅해도)

```bash
labremote autostart install     # 무엇이 바뀌는지 먼저 보여 주고 물어봐요
labremote autostart status
labremote autostart uninstall   # 원래대로
```

사용자 서비스 `labremote-session`이 tmux 안에서 서버를 띄워요. linger가 꺼져 있었을 때만 켜고, 끌 때 원래대로 돌려요. 학습 실행은 서비스와 따로 돌아서 서비스를 다시 켜도 살아요.

### 밖에서 접속 (선택)

터널은 VS Code가 띄우고, lab.remote는 상태만 읽어요.

```bash
code tunnel user login --provider github
code tunnel service install --accept-server-license-terms
```

`https://vscode.dev/tunnel/<이름>`에서 포트 `8000`을 전달(Private 그대로)한 뒤, 나온 주소를 알려 줘요.

```bash
labremote remote set https://<전달된 주소>
```

> 터널이 열려 있으면 그 GitHub 계정으로 이 컴퓨터의 터미널과 파일에 들어올 수 있어요. **GitHub 2단계 인증을 켜 두세요.**

### 알림 (선택)

Inbox › 알림 설정에서 Discord 웹훅 주소를 넣어요. `labremote notify test`로 시험해요.

자세한 설치 · 지우기는 [docs/SETUP.md](docs/SETUP.md), 켜 둔 뒤의 운영과 문제 해결은 [docs/operations.md](docs/operations.md)를 봐 주세요.

## lab.remote가 만드는 것 (전부)

| 무엇 | 언제 | 되돌리기 |
|---|---|---|
| conda 환경 `labremote` | `./install.sh` | `conda env remove -n labremote` |
| 사용자 서비스 `~/.config/systemd/user/labremote-session.service` (+ 꺼져 있었으면 linger) | `labremote autostart install` | `labremote autostart uninstall` |
| 등록한 프로젝트마다 `<프로젝트>/.labremote/` (스스로 git에서 빠져요) | 프로젝트를 등록할 때 | 등록을 해제할 때 지울지 골라요 |
| 데이터 폴더 `server/data/` (등록 목록 · Inbox · 예약 · 설정 · 논문 캐시) | 서버를 쓸 때 | 폴더를 지우면 돼요 |

비밀값은 이렇게 다뤄요.

- Discord 웹훅 주소는 데이터 폴더의 `discord.json`에 **권한 600**으로만 저장해요. 화면 · 로그 · 에러에는 가려서 보여요. `server/data/`는 `.gitignore`에 있어서 git에 올라가지 않아요.
- 논문 vault는 읽기만 해요. 새로 쓰는 건 arXiv · PDF로 추가한 논문 노트와 AI 요약 파일(`<이름> 요약.md`)뿐이에요.

## 명령

```bash
labremote serve [--port 8000]   # 서버 (127.0.0.1)
labremote doctor                # 설치 · 환경 점검 (✘ 고칠 것 · ⚠ 알려 주기만)
labremote run -p <프로젝트> -- python train.py   # 학습 실행 (tmux · 접속이 끊겨도 계속)
labremote runs list|stop|log [EXP-…]           # 실행 기록 · 중지 · 로그
labremote autostart install|uninstall|status
labremote remote show|set|clear
labremote notify test
```

## 개발

```text
server/   FastAPI 서버 (Python 3.11) — app/ · tests/
web/      React + Vite + TypeScript 화면 — src/
docs/     SETUP · operations · v3/PLAN.md(설계 기준) · v3/mockups/(화면 목업)
```

```bash
conda activate labremote
cd server && pytest                                   # 서버 테스트
cd server && uvicorn --factory app.main:create_app --reload   # 자동 재시작
cd web && npm run dev                                 # 화면 개발 서버
cd web && npm run typecheck && npm run build          # 타입 검사 · 빌드
```

`web/.env`에 `VITE_USE_MOCK=all`을 적으면 서버 없이 목업 데이터로 화면만 볼 수 있어요. 형식은 `web/.env.example`을 봐 주세요.
