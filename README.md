# lab.remote — Remote AI Research Workbench

GPU 데스크톱에서 진행하는 AI 연구를 어디서든 브라우저로 **보고 · 실행하고 · 알림 받는** 개인용 웹 도구입니다.

연구 폴더를 등록하면 파일 · git · 학습 실행 · Claude Code 세션을 한 화면에서 다룰 수 있습니다. 휴대폰에서 에이전트의 승인 요청에 답하고, 학습이 끝나거나 끊기면 Discord로 알림을 받습니다. 논문은 Obsidian vault를 그대로 읽어 라이브러리 · 지식 그래프 · 리더로 보여 줍니다.

## 특징

- **원격 접속** — 서버는 로컬 컴퓨터(`127.0.0.1`)에만 열리고, 외부에서는 VS Code의 code tunnel로 접속합니다. 휴대폰 화면도 지원합니다.
- **학습 지속성** — 학습은 tmux 안에서 실행되므로 브라우저를 닫거나 접속이 끊겨도 중단되지 않습니다. 서버를 다시 시작해도 마찬가지입니다.
- **Claude Code 세션 관리** — 사용자가 로그인한 Claude Code를 `claude-agent-sdk`로 불러와 사용합니다. 도구 승인과 질문 답변, Mode · 모델 · Effort 설정을 화면에서 처리합니다.
- **논문 읽기 도구** — PDF와 arXiv HTML 보기를 전환하며 읽을 수 있습니다. 섹션 · 그림 · 표 · 수식 설명, 번역, AI 요약 · 분석은 버튼을 누를 때만 요청합니다.
- **알림** — 승인 요청 · 실행 결과 · 예약 · PR · 머지 · 시스템 경고를 Inbox에 모으고, 규칙에 따라 Discord로 보냅니다.
- **시스템 설정 최소화** — `~/.bashrc` · `~/.claude/` · `.condarc` · cron · systemd 타이머 · 연구 프로젝트의 `.gitignore`는 절대 수정하지 않습니다. `--dangerously-skip-permissions`도 사용하지 않습니다.
- **가벼운 서버** — 서버는 nice 19 · ionice idle로 실행되며 GPU를 사용하지 않습니다.

## 기능

화면 위쪽 메뉴는 **Dashboard** · **Projects** · **Papers** · **Inbox**이고, 프로젝트마다 **IDE** · **ADE**가 있습니다. **Go to…**(Ctrl K · macOS는 ⌘K)로 프로젝트 · 논문 · 세션을 바로 찾아 이동할 수 있습니다.

### Dashboard

보기 세 가지를 전환합니다.

- **Overview** — 지금 필요한 일을 한 화면에 모읍니다.
  - 숫자 요약과 중간에 끊긴 실행 배너
  - 세션 카드: **답이 필요해요** · **작업 중** · **완료**. 카드마다 할 일 진행 상황, git 변경(+/−), PR 상태가 표시됩니다. 승인 요청은 카드에서 변경 내용을 펼쳐 보고 바로 허용하거나, ADE로 가서 답합니다.
  - 학습 실행(실행 중 · 오늘 종료), 열린 PR과 이번 주 머지(`gh` 필요)
  - 자원: GPU 사용률 · VRAM · 온도, CPU, 디스크, lab.remote 서버 자체의 사용량. 화면을 보는 동안 5초마다 갱신되며, VRAM이 거의 찼으면 경고합니다.
- **Agents** — 프로젝트별로 세션 · 하위 에이전트 · 학습 실행을 노드로 그린 그래프입니다. 부모-하위 관계는 실선, 참고 관계는 점선, 나(You)를 기다리는 세션은 주황 점선으로 이어집니다. "오늘 끝난 항목도 보기"로 끝난 것까지 볼 수 있습니다.
- **Schedule** — 오늘 08:00부터 24시간 타임라인과 예약 표입니다. 예약을 만들고, 활성화/비활성화 · 수정 · 삭제합니다.
  - 예약 종류는 **명령**(학습 실행 등)과 **에이전트**(예약 시각에 세션을 열고 요청만 보냄) 두 가지, 반복은 한 번 · 매일 · 매주입니다.
  - 예약 시각에 다른 학습이 GPU를 쓰고 있으면 끝날 때까지 기다렸다가 시작하고 알려 줍니다.
  - 예약은 lab.remote 서버가 시각을 확인해 실행합니다. cron이나 systemd 타이머는 만들지 않으며, 서버가 꺼져 있던 동안 지나간 예약을 나중에 몰아서 실행하지 않습니다. "이전 실행이 끝나면 시작" 같은 연쇄 예약은 지원하지 않습니다.

### Projects

왼쪽은 프로젝트 목록(검색 · 정렬 · 고정, 상태 점), 오른쪽은 선택한 프로젝트의 상세(경로 · git · conda · 세션 · 학습, IDE/ADE로 이동)입니다. 기존 폴더를 찾아 등록하거나, 새 폴더를 만들면서 바로 git 저장소로 시작(`git init`, `main` 브랜치)할 수 있습니다.

- **파일** — worktree를 골라 파일을 탐색하고, 업로드 · 새 파일/폴더 · 이름 바꾸기와 이동 · 삭제를 합니다. 같은 이름이 있으면 덮어쓰지 않습니다.
- **Worktrees** — 작업마다 worktree를 하나씩 씁니다(ADE에서 세션을 만들면 함께 생성). 커밋하지 않은 변경이 있거나 그 worktree에서 학습 · 세션이 실행 중이면 정리하지 않습니다.
- **세션 · 실행** — 이 프로젝트의 세션과 실행 기록을 봅니다. 새로 실행 · 예약 실행 · 다시 실행 · 이어서 실행을 하고, 로그를 보거나 터미널 접속 명령을 복사합니다. **중지**는 Ctrl+C를 보내 체크포인트를 저장할 시간을 주고, **강제 중지**는 즉시 종료합니다.
- **설정** — 기본 conda 환경, 자주 쓰는 명령, 지표 파일 규칙, 이 프로젝트에서 사용하는 논문을 정합니다. 설정을 git 저장소에 포함할지 고를 수 있고, 등록을 해제해도 프로젝트 폴더와 파일은 그대로 남습니다.

### IDE

브라우저에서 쓰는 편집 화면입니다(넓은 화면 전용).

- **편집기** — Monaco 편집기 탭. 2 MB가 넘는 파일이나 텍스트가 아닌 파일은 열지 않습니다.
- **왼쪽 아이콘줄**
  - 탐색기: 파일 트리, 새 파일 · 새 폴더
  - 검색: 프로젝트 전체 검색(대소문자 구분 선택)
  - 소스 제어: 변경 diff 보기 · 되돌리기, 커밋, main에 머지, PR 만들기(`gh`, 브랜치가 원격에 push되어 있어야 함)
  - **Scenario**: 아래 [Scenario](#scenario) 참고
  - 실행: 명령 · 위치 · conda 환경을 정해 **지금 실행** 또는 **예약 실행…**. 실제로 실행될 명령을 미리 볼 수 있고, 실행 중 · 최근 실행 목록이 있습니다.
- **터미널** — bash 탭을 여러 개 열 수 있고, 브라우저를 닫아도 데스크톱에서 계속 실행됩니다. 실행 중인 학습의 tmux에 접속하면 실수로 Ctrl+C를 눌러 중단되지 않도록 읽기 전용으로 엽니다.
- **오른쪽 패널** — Claude Code 채팅(ADE와 같은 입력창). 세션 기록은 ADE에서 이어 볼 수 있습니다.

### ADE

Claude Code 세션과 대화하는 화면으로, IDE와 같은 틀입니다.

- **세션 목록** — 프로젝트 › worktree › 세션 순서로, 하위 에이전트까지 보여 줍니다. 전체/내 차례 필터와 검색, 세션 이름 바꾸기 · 닫기(기록은 유지)가 있습니다.
- **채팅** — 도구 사용 내역과 할 일 목록이 대화 중에 표시됩니다.
  - **승인 카드**: 변경 diff를 보고 허용 · 거부합니다. 거부할 때 이유나 다른 지시를 남길 수 있고, "이 세션에서 계속 허용"은 lab.remote가 그 세션 안에서만 기억합니다(설정 파일에 쓰지 않음).
  - **질문**: 에이전트가 묻는 질문에 선택지(여러 개 선택 포함)로 답하거나 직접 입력합니다.
  - 같은 요청이 Dashboard · Inbox · Discord에도 표시되며, 먼저 답한 곳의 답이 적용됩니다.
- **입력창** — VS Code Claude Code 확장과 같은 구성입니다.
  - 파일 첨부(프로젝트의 `.labremote/attachments/`에 저장하고 경로를 첨부), 슬래시 명령, 음성 입력
  - 모델과 Effort 선택. 모델 목록은 설치된 Claude Code에서 받아오며, 모델이 지원하는 Effort 단계만 보입니다. Ultracode는 지원하는 모델에서만 켤 수 있습니다.
  - Mode: **Manual**(편집마다 승인, 기본값) · **Edit automatically**(편집은 바로, 명령은 승인) · **Plan**(계획을 먼저 보여 줌) · **Auto**(안전 검사를 통과한 작업은 바로 진행, 지원하는 모델에서만)
  - Mode · 모델 · Effort는 세션마다 적용되며 `~/.claude` 설정을 바꾸지 않습니다.
- **오른쪽 탭** — **Scenario** · 변경(탐색기나 소스 제어에서 누른 파일의 diff) · 실행

### Scenario

Claude가 프로젝트 코드를 **읽기만** 하고 데이터 준비 → 학습 → 평가 같은 실행 순서를 그림으로 그려 줍니다. 단계마다 명령 · 입력 · 출력 · 환경이 표시되고, 명령을 실행 탭에 바로 채울 수 있습니다. 코드가 바뀌면 "코드 변경됨"으로 알려 주며, 그리기는 버튼을 누를 때만 요청합니다.

### Papers

Obsidian vault의 논문 노트를 읽어 보여 줍니다. 기존 노트는 수정하지 않습니다.

- **List** — 라이브러리입니다.
  - 사이드바: 최근 열어본 논문 · 전체 · 읽을 예정 · 읽는 중 · 완료 · 휴지통, 직접 만드는 모음, vault 위치 설정
  - 논문 추가: arXiv 링크(메타데이터 · 초록 · PDF를 받아옴) 또는 PDF 업로드. vault의 `Papers/`에 새 노트를 만들고, 이미 있는 노트는 덮어쓰지 않습니다.
  - 논문마다 읽음 상태 · 태그 · AI 요약, BibTeX 복사, "프로젝트에서 사용" 연결
  - **라이브러리에 묻기**: Claude가 vault의 노트를 읽고 답합니다(대화는 저장하지 않음).
- **Graph** — 논문 · 메모 · 프로젝트를 노드로 그린 지식 그래프입니다. 인용(참고문헌), 메모 링크(vault의 `[[링크]]`), 프로젝트에서 사용 관계를 켜고 끌 수 있고, 선택한 노드 주변만 볼 수 있습니다. "Claude에게 묻기"는 선택한 노드의 관계를 묻는 질문을 ADE 새 세션에 채워 줍니다.
- **리더** — 논문을 여는 화면입니다.
  - **PDF** ↔ **arXiv HTML** 보기 전환. HTML 본문과 그림은 한 번 받아 두면 다음부터 바로 열립니다.
  - 아웃라인: 논문 목차, AI 아웃라인, 읽은 위치. 끝까지 읽으면 완료로 표시할지 묻습니다.
  - 텍스트를 선택하면 **설명 · 하이라이트 · 번역 · 주석 · AI에게 질문** 메뉴가 뜹니다.
  - 섹션 · 그림 · 표 · 수식마다 설명 버튼이 있고, 그림 복사 · LaTeX 복사를 지원합니다.
  - 본문의 인용 번호를 누르면 인용 카드가 뜨고, 인용된 논문을 바로 열 수 있습니다.
  - **AI 패널** 탭: AI 분석(핵심 혁신 · 방법 · 결과 · 확인 필요 구절을 하이라이트하고 참고문헌 정리) · 요약(vault에 `<이름> 요약.md`로 저장) · 채팅 · 인용 · 노트(내 하이라이트 · 주석 · 메모)
  - 모든 AI 기능은 버튼을 누를 때만 Claude에게 요청합니다.

### Inbox

- 승인 요청 · 실행 결과 · 예약 · PR · 머지 · 시스템 경고를 한곳에 모읍니다. 종류별 필터가 있고, 알림마다 바로 처리하는 버튼(ADE에서 답하기, 로그 보기, 이어서 실행, GitHub에서 보기 등)이 있습니다.
- 헤더의 배지는 내가 처리해야 하는 것(답 필요, 실행 실패 · 끊김) 중 안 읽은 것만 셉니다.
- **Discord 연동** — 웹훅 주소 입력 · 변경 · 연결 해제, 테스트 알림. 주소는 일부를 가려서만 표시합니다.
- **Discord로 보낼 알림** — 종류별로 켜고 끕니다. PR 리뷰 알림은 `gh`가 있으면 10분마다 GitHub에서 가져옵니다.
- **조용한 시간** — 이 시간에는 답 필요와 실패 알림만 Discord로 보냅니다.

### 설정 · Conda

- conda 설치 폴더 아래의 환경 목록. conda 기본 환경은 **보호됨**(읽기 전용), lab.remote 서버가 쓰는 환경은 삭제할 수 없고, 학습이 쓰는 중인 환경은 잠깁니다.
- 새 환경 만들기 · 복제
- 패키지 설치(conda/pip): 먼저 dry-run으로 바뀌는 내용을 미리 보여 준 뒤 설치합니다.
- 패키지 표: 검색 · 업데이트 · 제거
- 환경 삭제: 이름을 입력해 확인하며, 삭제하기 전에 `environment.yml`을 데이터 폴더에 백업합니다.
- `.condarc`는 변경하지 않습니다.

### 설정 · System

- lab.remote 서버 · Claude Code 로그인 · 자동 시작 · 터널 · GPU 드라이버(커널과 유저랜드 버전 일치 여부) 상태
- "lab.remote가 변경한 것" 표: 무엇을 어디에 언제 만들었고 어떻게 되돌리는지
- 자동 시작 구조, 세션 다시 시작, 자동 시작 끄기(linger를 원래 값으로 되돌릴지 함께 안내)
- 외부 접속 주소 등록, Discord 알림 요약

### 휴대폰

좁은 화면에서는 메뉴가 아래쪽 탭(홈 · Projects · Papers · Inbox)으로 바뀌고, Dashboard · Inbox에서 승인 요청에 답할 수 있습니다. Papers는 휴대폰용 목록으로 바뀌어 읽음 상태 변경 · 3줄 요약 · 라이브러리에 묻기를 지원합니다. 논문 읽기와 하이라이트, IDE는 PC에서 사용합니다.

## 요구 사항

- Linux + systemd
- Miniconda (또는 conda)
- tmux (`sudo apt install tmux`)
- **Claude Code — 설치와 로그인까지 완료된 상태** (터미널에서 `claude`를 한 번 실행해 로그인)
- Node.js >= 20 (웹 화면 빌드용)
- (선택) VS Code — 원격 접속(code tunnel)용
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

이미 설치한 lab.remote를 최신 버전으로 업데이트할 때는 아래 명령을 사용합니다.

```bash
cd ~/lab-remote
git pull
./install.sh
systemctl --user restart labremote-session    # 자동 시작을 켠 경우
```

등록한 프로젝트 · 알림 설정 · 웹훅 주소는 데이터 폴더(`server/data/`)에 있으므로 업데이트해도 유지됩니다. 실행 중인 학습은 서비스를 다시 시작해도 중단되지 않습니다.

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

사용자 서비스 `labremote-session`이 tmux 안에서 서버를 실행합니다. 재부팅하거나 로그아웃해도 서버가 계속 실행됩니다. linger는 비활성화되어 있던 경우에만 활성화하고, 자동 시작을 해제할 때 원래대로 되돌립니다.

### 3. 원격 접속 (선택)

터널은 VS Code가 실행하고, lab.remote는 상태만 확인합니다.

```bash
code tunnel user login --provider github
code tunnel service install --accept-server-license-terms
```

`https://vscode.dev/tunnel/<이름>`에서 포트 `8000`을 전달(Private 유지)한 뒤, 전달된 주소를 등록합니다.

```bash
labremote remote set https://<전달된 주소>
```

등록하지 않은 주소로 들어온 요청은 서버가 거절합니다. 등록하면 Discord 알림에 "답하기" 링크가 추가됩니다.

> 터널이 열려 있으면 해당 GitHub 계정으로 이 컴퓨터의 터미널과 파일에 접근할 수 있습니다. **GitHub 2단계 인증을 반드시 활성화하세요.**

### 4. 알림 (선택)

Inbox › 알림 설정에서 Discord 웹훅 주소를 입력합니다. 테스트 알림은 아래 명령으로 보냅니다.

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

conda · tmux · Claude Code 로그인 · 웹 빌드 · 자동 시작 · 터널 · GPU 드라이버 등 전체 환경을 점검합니다. `✘`는 해결해야 할 항목, `⚠`는 참고용 경고입니다(종료 코드에 영향 없음).

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
| 사용자 서비스 `~/.config/systemd/user/labremote-session.service` (+ 비활성화되어 있었다면 linger) | `labremote autostart install` | `labremote autostart uninstall` |
| 프로젝트마다 `<프로젝트>/.labremote/` (자체 `.gitignore`로 git에서 제외) | 프로젝트 등록 시 | 등록 해제 시 삭제 여부 선택 |
| 데이터 폴더 `server/data/` (등록 목록 · Inbox · 예약 · 설정 · 논문 캐시) | 서버 사용 시 | 폴더 삭제 |

## 보안과 데이터

- **Discord 웹훅 주소**는 데이터 폴더의 `discord.json`에 **권한 `0600`으로만** 저장됩니다. 화면 · 로그 · 에러 메시지에는 가려서 표시되며, `server/data/`는 `.gitignore`에 포함되어 git에 커밋되지 않습니다.
- **논문 vault**는 읽기만 합니다. 새로 쓰는 파일은 arXiv · PDF로 추가한 논문 노트와 AI 요약 파일(`<이름> 요약.md`)뿐입니다. arXiv HTML 본문은 vault가 아니라 데이터 폴더에 저장합니다.
- **git push는 하지 않습니다.** PR은 브랜치가 이미 원격에 push되어 있을 때만 엽니다.
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
