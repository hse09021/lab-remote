# lab.remote — Remote AI Research Workbench

GPU 데스크톱에서 돌리는 AI 연구를 어디서든 브라우저로 **보고 · 실행하고 · 알림 받는** 개인용 웹 도구입니다.

연구 폴더를 등록하면 파일 · git · 학습 실행 · Claude Code 세션을 한 화면에서 다룰 수 있습니다. 휴대폰에서 에이전트의 승인 요청에 답하고, 학습이 끝나거나 끊기면 Discord로 알림을 받습니다. 논문은 Obsidian vault를 그대로 읽어 라이브러리 · 지식 그래프 · 리더로 보여 줍니다.

## 특징

- **어디서든 접속** — 서버는 이 컴퓨터(`127.0.0.1`)에만 열리고, 밖에서는 VS Code의 code tunnel로 접속합니다. 휴대폰 화면도 지원합니다.
- **끊겨도 계속 도는 학습** — 학습은 tmux 안에서 돌기 때문에 브라우저를 닫거나 접속이 끊겨도 멈추지 않습니다. 서버를 다시 켜도 실행은 살아 있습니다.
- **Claude Code 세션 관리** — 사용자가 로그인해 둔 Claude Code를 `claude-agent-sdk`로 불러 씁니다. 도구 승인 · 질문 답변 · Mode · 모델 · Effort 설정을 화면에서 처리합니다.
- **논문 읽기 도구** — PDF와 arXiv HTML을 오가며 읽고, 섹션 · 그림 · 표 · 수식 설명, 번역, AI 요약 · 분석을 누를 때만 받습니다.
- **알림** — 승인 요청 · 실행 결과 · 예약 · PR · 머지 · 시스템 경고를 Inbox에 모으고, 규칙에 따라 Discord로 보냅니다.
- **AI 자동화 없음** — AI 연구 루프, 실험 큐, 연쇄 실행이 없습니다. 예약은 사람이 시각을 정한 것만 돌고, Claude는 사람이 버튼을 누를 때만 호출됩니다.
- **시스템 설정 최소화** — `~/.bashrc` · `~/.claude/` · `.condarc` · cron · systemd 타이머 · 연구 프로젝트의 `.gitignore`는 절대 수정하지 않습니다. `--dangerously-skip-permissions`도 사용하지 않습니다.
- **가벼운 서버** — nice 19 · ionice idle로 돌고 GPU를 사용하지 않습니다.

## 화면

| 화면 | 기능 |
|---|---|
| **Dashboard** | 답이 필요한 세션 · 작업 중 · 끝남을 한눈에 봅니다. 세션 카드에 할 일 진행, git 변경(+/−), PR 상태가 표시됩니다. **Overview** · **Agents**(세션 · 하위 에이전트 · 학습 실행 그래프) · **Schedule**(24시간 띠와 예약 표) 보기를 제공합니다 |
| **Projects** | 등록한 연구 폴더의 파일 · worktree · 세션과 실행 · 설정을 관리합니다 |
| **IDE** | 브라우저 편집기(Monaco) · 터미널 · 검색 · 소스 제어(커밋, main에 합치기, PR) · 실행 탭을 제공합니다. 에이전트가 만든 파일에는 어느 세션이 썼는지 표시됩니다 |
| **ADE** | Claude Code 세션과 대화합니다. 오른쪽에 **Scenario** · 변경 · 실행 패널이 있습니다 |
| **Papers** | Obsidian vault의 논문 노트를 **List** · **Graph**로 봅니다. arXiv 링크나 PDF로 논문을 추가하고, AI 요약 · 라이브러리에 묻기 · 모음 · BibTeX를 지원합니다 |
| **Inbox** | 모든 알림을 모으고, Discord로 보낼 알림 종류와 조용한 시간을 설정합니다 |
| **설정** | Conda 환경 만들기 · 패키지 관리, System(서버 · 터널 · 자동 시작 상태) |

## 요구 사항

- Linux + systemd
- Miniconda (또는 conda)
- tmux (`sudo apt install tmux`)
- **Claude Code — 설치와 로그인까지 완료된 상태** (터미널에서 `claude`를 한 번 실행해 로그인)
- Node.js >= 20 (웹 화면 빌드용)
- (선택) VS Code — 밖에서 접속할 때 code tunnel용
- (선택) `gh` (GitHub CLI) — PR 만들기 · 열린 PR 보기

lab.remote는 Claude 로그인을 대신 제공하지 않습니다. 환경에 `ANTHROPIC_API_KEY`가 설정되어 있으면 구독이 아닌 종량제로 과금될 수 있으며, `labremote doctor`가 이를 알려 줍니다.

## 설치

저장소를 클론한 뒤 설치 스크립트를 실행합니다.

```bash
git clone https://github.com/hse09021/lab-remote.git ~/lab-remote
cd ~/lab-remote
./install.sh            # 실행할 명령만 확인하려면 ./install.sh --dry-run
```

`install.sh`는 다음 네 가지를 수행합니다.

1. conda 환경 `labremote` 생성 (이미 있으면 그대로 사용)
2. 서버 패키지 설치 (`pip install -e server[api]`)
3. 웹 화면 빌드 (`npm ci && npm run build`)
4. `labremote doctor` 점검

셸 설정을 수정하지 않으므로 명령은 환경 경로로 실행합니다. 자주 쓴다면 alias를 직접 추가해도 됩니다.

```bash
~/miniconda3/envs/labremote/bin/labremote doctor     # ✘가 없으면 정상입니다
alias labremote=~/miniconda3/envs/labremote/bin/labremote
```

## 업데이트

이미 설치한 lab.remote를 최신 버전으로 올릴 때는 아래 명령을 사용합니다.

```bash
cd ~/lab-remote
git pull
./install.sh
systemctl --user restart labremote-session    # 자동 시작을 켠 경우
```

등록한 프로젝트 · 알림 설정 · 웹훅 주소는 데이터 폴더(`server/data/`)에 있으므로 업데이트해도 유지됩니다. 실행 중인 학습은 서비스를 다시 켜도 멈추지 않습니다.

## 사용법

### 1. 서버 실행

```bash
labremote serve          # http://127.0.0.1:8000
```

이 컴퓨터의 브라우저에서 `http://127.0.0.1:8000`을 엽니다. 처음 열면 시작 안내가 표시되며, Claude Code 로그인 → 프로젝트 등록 → Discord 알림 순서로 진행하면 됩니다.

### 2. 자동 시작

```bash
labremote autostart install     # 변경 내용을 먼저 보여 주고 확인을 받습니다
labremote autostart status
```

사용자 서비스 `labremote-session`이 tmux 안에서 서버를 띄웁니다. 재부팅하거나 로그아웃해도 서버가 계속 떠 있습니다. linger는 꺼져 있었던 경우에만 켜고, 해제할 때 원래 값으로 되돌립니다.

### 3. 밖에서 접속 (선택)

터널은 VS Code가 띄우고, lab.remote는 상태만 읽습니다.

```bash
code tunnel user login --provider github
code tunnel service install --accept-server-license-terms
```

`https://vscode.dev/tunnel/<이름>`에서 포트 `8000`을 전달(Private 유지)한 뒤, 전달된 주소를 등록합니다.

```bash
labremote remote set https://<전달된 주소>
```

등록하지 않은 주소로 들어온 요청은 서버가 거절합니다. 등록하면 Discord 알림에 "답하기" 링크가 붙습니다.

> 터널이 열려 있으면 해당 GitHub 계정으로 이 컴퓨터의 터미널과 파일에 접근할 수 있습니다. **GitHub 2단계 인증을 반드시 켜 두세요.**

### 4. 알림 (선택)

Inbox › 알림 설정에서 Discord 웹훅 주소를 입력합니다. 시험 전송은 아래 명령으로 합니다.

```bash
labremote notify test
```

### 5. 학습 실행

화면(Projects › 세션 · 실행, IDE 실행 탭)에서 실행하거나 CLI를 사용합니다.

```bash
labremote run -p <프로젝트> -- python train.py
labremote runs list|stop|log [EXP-…]
```

### 6. 진단

```bash
labremote doctor
```

conda · tmux · Claude Code 로그인 · 웹 빌드 · 자동 시작 · 터널 · GPU 드라이버 등 전체 환경을 점검합니다. `✘`는 고쳐야 할 항목, `⚠`는 알림만 하는 항목입니다(종료코드에 영향 없음).

### 7. 자동 시작 해제 · 삭제

```bash
labremote autostart uninstall
conda env remove -n labremote
rm -rf ~/lab-remote
```

등록했던 프로젝트의 `.labremote/` 폴더는 남습니다. 필요하면 프로젝트마다 직접 지웁니다.

자세한 설치 과정은 [docs/SETUP.md](docs/SETUP.md), 운영과 문제 해결은 [docs/operations.md](docs/operations.md)를 참고하세요.

## lab.remote가 만드는 것

lab.remote가 시스템에 만드는 것은 아래가 전부입니다.

| 대상 | 생성 시점 | 되돌리기 |
|---|---|---|
| conda 환경 `labremote` | `./install.sh` | `conda env remove -n labremote` |
| 사용자 서비스 `~/.config/systemd/user/labremote-session.service` (+ 꺼져 있었다면 linger) | `labremote autostart install` | `labremote autostart uninstall` |
| 프로젝트마다 `<프로젝트>/.labremote/` (자체 `.gitignore`로 git에서 제외) | 프로젝트 등록 시 | 등록 해제 시 삭제 여부 선택 |
| 데이터 폴더 `server/data/` (등록 목록 · Inbox · 예약 · 설정 · 논문 캐시) | 서버 사용 시 | 폴더 삭제 |

## 보안과 데이터

- **Discord 웹훅 주소**는 데이터 폴더의 `discord.json`에 **권한 `0600`** 으로만 저장됩니다. 화면 · 로그 · 에러 메시지에는 가려서 표시되며, `server/data/`는 `.gitignore`에 포함되어 git에 올라가지 않습니다.
- **논문 vault**는 읽기만 합니다. 새로 쓰는 파일은 arXiv · PDF로 추가한 논문 노트와 AI 요약 파일(`<이름> 요약.md`)뿐입니다. arXiv HTML 본문은 vault가 아니라 데이터 폴더에 저장합니다.
- **git push는 하지 않습니다.** PR은 브랜치가 이미 원격에 올라가 있을 때만 엽니다.
- **변경 요청에는 전용 헤더가 필요합니다.** 다른 사이트에서 보낸 요청은 서버가 거절합니다.

## 개발

```text
server/   FastAPI 서버 (Python 3.11) — app/ · tests/
web/      React + Vite + TypeScript 화면 — src/
docs/     SETUP · operations · v3/PLAN.md(설계 기준) · v3/mockups/(화면 목업)
```

```bash
# 서버 환경
conda activate labremote

# 서버 테스트
cd server && pytest

# 서버 개발 모드 (자동 재시작)
cd server && uvicorn --factory app.main:create_app --reload

# 화면 개발 서버
cd web && npm run dev

# 타입 검사 · 빌드
cd web && npm run typecheck && npm run build
```

`web/.env`에 `VITE_USE_MOCK=all`을 설정하면 서버 없이 목업 데이터로 화면만 확인할 수 있습니다. 형식은 `web/.env.example`을 참고하세요.
