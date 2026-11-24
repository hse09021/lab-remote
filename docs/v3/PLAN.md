# lab.remote v3 구현 계획

이 문서는 데스크톱의 Claude Code가 v3를 구현할 때 기준으로 삼는 문서예요.
목업은 `docs/v3/mockups/` 에 있고, 화면별 안내는 `docs/v3/mockups/README.md` 에 있어요.
목업 파일을 읽는 법(`<x-dc>`, `{{ }}`, `sc-if`, `sc-for`, `class Component`)은 `docs/v1/HANDOFF.md` 1장과 같아요.

> 이 문서와 기존 문서(`docs/v1/HANDOFF.md`, `CLAUDE.md`)가 부딪히면 **이 문서가 우선**이에요. (v1의 spec · plan 등은 2026-11-24에 정리했어요 — git 기록에 남아 있어요.)
> 특히 v1의 "Hooks로 강제하는 잠금", "권한 프리셋", "연구 전체 자동화 루프", "실험 큐", "AI 실험 설계 초안"은 v3에서 모두 빠져요.

---

## 0. 시작 전에 (반드시 먼저)

1. `git status`, `git log --oneline -10` 으로 지금 상태를 확인하고, 커밋 안 된 변경이 있으면 멈추고 알려 주세요.
2. `v3` 브랜치를 만들어 그 위에서 작업해요. **push 는 사람이 요청할 때만** 해요.
3. 각 단계(6장)가 끝날 때마다 테스트를 돌리고, 바뀐 것을 짧게 정리해서 보여 준 뒤 다음 단계로 가요.
4. 무언가를 지우거나 되돌릴 수 없는 작업(파일 삭제, 마이그레이션, `git worktree remove`, conda 환경 삭제 등)을 코드로 실행하기 전에는 항상 먼저 물어봐요.
5. 확인 못 한 값(SDK 옵션 이름, 모델 목록 등)은 지어내지 말고, 공식 문서나 설치된 패키지에서 확인해요. 확인이 안 되면 `[확인 필요]` 로 남기고 알려 줘요.

---

## 1. 원칙 (확정)

1. **시스템 설정은 최소한만.** git clone 후 설치 명령 몇 줄로 끝나야 해요. lab.remote 가 바꾸는 것은 아래뿐이에요.
   - conda 환경 `labremote` (`~/miniconda3/envs/labremote`)
   - 자동 시작을 켤 때만: 사용자 서비스 `~/.config/systemd/user/labremote-session.service` + `loginctl enable-linger` (꺼져 있었을 때만 — 끌 때 원래대로). code tunnel 은 사람이 VS Code 공식 명령으로 켜요(lab.remote 가 바꾸지 않음)
   - 등록한 프로젝트마다 `<프로젝트>/.labremote/`
   - 그 밖의 cron, systemd 타이머, `.bashrc`, `~/.claude/`, `.condarc`, 프로젝트의 `.gitignore` 는 **절대 고치지 않아요.**
2. **Claude Code 설정과 훅을 건드리지 않아요.** 채팅은 Python `claude-agent-sdk` 로 사용자가 이미 설치하고 로그인한 Claude Code 를 불러 써요. 읽을 설정 범위는 SDK 옵션(`setting_sources` 등)으로 정하고, 권한은 코드로 넘겨요. `--dangerously-skip-permissions`(또는 같은 효과의 모드)는 쓰지 않아요.
3. **가볍게.** 서버는 `127.0.0.1` 에만 열고, nice 19 / ionice idle 로 돌고, GPU 를 쓰지 않아요. 자원 정보는 화면을 볼 때만 폴링해요.
4. **AI 자동화 없음.** AI 연구 루프, 실험 큐, "앞 실행이 끝나면 시작" 같은 연쇄 실행은 없어요. 예약은 사람이 시각으로 건 것만 돌아요.
5. **접속이 끊겨도 학습은 계속.** 실행은 `systemd-run --user --scope` + tmux + 로그 파일로 돌려요(`labremote run`).
6. **나만 쓰는 도구지만 설치는 쉽게.** 다른 사람도 Claude Code 설치·로그인 → clone → 설치 명령으로 쓸 수 있어야 해요. lab.remote 가 Claude 로그인을 대신 제공하지 않아요.
7. **비밀값.** Discord 웹훅 주소는 lab.remote 데이터 폴더에 권한 600 으로만 저장하고, 로그·화면·에러 메시지에 원문을 찍지 않아요(화면에는 `••••` 로 가려서). `.env` 는 커밋하지 않아요.

---

## 2. v1 에서 빼는 것

**먼저 목록을 만들어 보여 주고, 승인받은 뒤에 지워요.** 아래는 이름으로 짐작한 후보예요. 각 모듈이 실제로 무엇을 하는지 읽어 보고 "삭제 / 유지 / 일부만 유지" 표를 만들어 주세요.

- 서버 후보: `app/hooks/`, `app/grants.py`, `app/policy.py`, `app/policy_defaults.py`, `app/denials.py`, `app/approval_log.py`, `app/loop_layout.py`, `app/loopstate.py`, `app/orchestrator/`, `app/generator/`(실험 설계 초안이라면), `app/templates/project`(강제 폴더 구조라면), `app/claude_settings.py`(`~/.claude` 나 `.claude/settings.json` 을 쓰는 코드라면), `app/agent/sandboxcheck.py`, 훅 설치 CLI 명령
- 유지 후보: `app/monitor/`(gpu, host, metrics), `app/runner/`, `app/git/`, `app/notifier.py`, `app/store/`, `app/db.py`, `app/paths.py`, `app/doctor.py`(v3 기준으로 고쳐서), `app/service/`(자동 시작)
- 웹: `features/experiments/PermissionSettings*`, `ExperimentDesignDraft*`, `features/mobile/MobileDesignDraft*`, `api/permissions.ts`, `api/design.ts` 와 관련 mock
- 문서: `CLAUDE.md` 규칙 중 "권한 잠금 3가지는 Hooks에서 강제" 문단, `docs/v1/HANDOFF.md`·`docs/v1/spec.md` 의 v1 전용 부분 → v3 기준으로 고치거나 "v1 (보관)" 표시

---

## 3. 데이터를 어디에 두나

| 위치 | 저장하는 것 |
|---|---|
| lab.remote 데이터 폴더 (예: `~/.local/share/labremote/` 또는 repo 안 `data/` — 지금 코드의 `paths.py` 기준을 따르세요) | 등록한 프로젝트 목록, 예약, 알림 기록(Inbox), 알림 규칙·조용한 시간, Discord 웹훅 주소(600), conda 설치 기록과 삭제 전 백업, 화면 상태(고정한 프로젝트 등) |
| `<프로젝트>/.labremote/` | `settings.json`(기본 conda 환경, 자주 쓰는 실행 명령, 지표 파일 규칙, repo 공유 여부), `scenarios/`, `worktrees/`, 실행 기록 목록(EXP 번호·상태·명령·로그 위치), 세션 ↔ worktree 연결 |

- `.labremote/` 안에 `*` 한 줄짜리 `.gitignore` 를 넣어서 폴더가 스스로 git 에서 빠지게 해요.
- 프로젝트 설정 "repo 에 같이 올리기"를 켜면 그 `.gitignore` 를 바꿔서 `settings.json` 과 `scenarios/` 만 추적되게 해요(기본 꺼짐).
- 프로젝트 등록 해제 시 `.labremote/` 를 지울지 물어봐요(기본은 남겨 두기).
- 학습 결과(`runs/` 등)는 프로젝트 코드가 정한 곳에 그대로 있어요. lab.remote 는 읽기만 해요.

---

## 4. 구조

### 4.1 서버 (Python, conda `labremote`)

- `app/main.py` 에 FastAPI 앱을 만들고(`pyproject` 의 `api` extra), `labremote serve` 로 띄워요. 빌드된 웹(`web/dist`)도 같은 서버가 내려줘요.
- 실시간 갱신은 WebSocket 하나(또는 SSE)로 이벤트를 보내요: 세션 메시지, 승인 요청·결과, 실행 상태, 알림.
- 모듈(새로 만들거나 고칠 것):
  - **projects**: 등록·해제, `.labremote/` 만들기, 프로젝트 설정 읽기·쓰기
  - **files**: 등록한 프로젝트 폴더 안에서만 목록·읽기·쓰기·업로드·다운로드·이름 바꾸기·삭제. 경로 탈출(`..`, 심볼릭 링크) 막기. 실행 중인 학습이 쓰는 폴더는 삭제 막기
  - **git / worktree**: 상태, diff, 커밋, `main` 에 합치기, PR(설치돼 있으면 `gh` 사용, 없으면 버튼 숨김). worktree 는 `.labremote/worktrees/<이름>` 에 만들고, `main` 에 합쳐진 것은 "정리" 대상으로 표시만 해요(지우기는 사람이 눌렀을 때만). 소스 제어는 VS Code 와 같은 구조로 브랜치 전환·만들기, 스테이징, 원격 저장소 연결, GitHub 게시(`gh`), 저장소 초기화, fetch·pull·push 를 지원해요 — 원격 전송은 사람이 누를 때만, push 는 확인 후 force 없이(2026-11-24 결정)
  - **agents** (연결 부품):
    - `agents/base.py`: 에이전트 공통 규칙 — 세션 시작, 메시지 보내기, 이벤트 스트림(텍스트, 도구 사용, 할 일, 하위 에이전트, 결과·사용량), 승인 요청과 답, 이어 가기(세션 ID), 중지, 설정(mode, model, effort)
    - `agents/claude.py`: Python `claude-agent-sdk` 구현. 승인은 SDK 의 권한 콜백(`can_use_tool` 등, 실제 이름은 확인)으로 받아서 "대기 중 승인" 저장소에 넣고, 어느 화면(채팅, Dashboard, Inbox, 모바일)이나 Discord 링크에서 답해도 먼저 온 답을 적용해요
    - Codex 는 나중에 `agents/codex.py` 하나로 붙일 수 있게, 화면과 데이터에 Claude 전용 이름을 쓰지 않아요("에이전트 세션", "승인 요청")
    - 동시 세션 상한(기본 4), 서버가 재시작돼도 세션 목록과 ID 를 복구해서 이어 갈 수 있게
  - **runs**: `labremote run`(CLI)과 같은 함수를 API 로도 노출. `systemd-run --user --scope tmux new -d -s run-<id> "conda run -n <env> <명령> | tee <로그>"`. 실행 기록, 지표 파일 읽기(설정의 규칙 → 없으면 흔한 위치 자동 탐색), 재부팅으로 끊긴 실행 감지, 터미널에 붙기용 tmux 세션 이름
  - **scheduler**: 서버 안의 시계로 예약 실행(한 번 / 매일 / 매주). 예약 시각에 GPU 가 다른 학습으로 바쁘면 끝날 때까지 기다렸다가 시작하고 "기다리는 중" 알림. 연쇄 예약 없음. 에이전트 예약은 세션을 열고 알림만(승인이 필요하면 거기서 멈춤). cron·systemd 타이머는 만들지 않아요
  - **scenarios**: 사용자가 요청할 때만, Claude 세션을 계획 모드(읽기 전용)로 열어 프로젝트 파일을 분석하고 정해진 JSON 형식(단계: 이름, 명령, 받는 파일, 내는 파일, 환경)으로 답하게 해서 `.labremote/scenarios/main.json` 에 저장. 분석한 파일들의 해시를 같이 저장해서 파일이 바뀌면 "코드가 바뀌었어요" 표시(자동으로 다시 그리지 않음)
  - **conda**: `conda env list --json`, `conda list --json -n <env>`, 설치는 먼저 dry-run 결과를 보여 주고 확인 후 설치. `base`·`labremote` 보호, 실행 중인 학습이 쓰는 환경 잠금, 삭제는 이름을 입력해야 가능하고 지우기 전 `environment.yml` 백업. `.condarc` 는 안 건드림
  - **inbox / notify**: 알림 저장, 읽음, 종류별 규칙, 조용한 시간, Discord 웹훅 전송(실패 재시도), 테스트 보내기
  - **papers**: v1 라이브러리·리더 기능 유지. 지식그래프용 API(인용: 참고문헌, 메모 링크: vault `[[ ]]`, 프로젝트 사용)
  - **system**: 서버·터널·자동 시작·GPU 상태, "lab.remote 가 바꾼 것" 목록, 예약 시계 상태
- CLI: `labremote serve`, `labremote run -- <명령>`, `labremote autostart install|uninstall`, `labremote doctor`(v3 기준으로: conda 환경, Claude Code 설치·로그인, tmux, systemd --user, linger, 터널)

### 4.2 웹 (React + TS, 지금 `web/` 그대로)

- 라우트(제안): `/` → `/dashboard`, `/dashboard?view=overview|agents|schedule`, `/projects`, `/projects/:id?tab=files|worktrees|work|settings`, `/projects/:id/ide`, `/projects/:id/ade`, `/papers?view=list|graph`, `/papers/:id`, `/inbox`, `/settings/conda`, `/settings/system`
- 전역 헤더(한 줄): **Dashboard · Projects · Papers · Inbox(배지)**, 오른쪽에 **Go to… ⌘K**, GPU, 연결 상태, ⚙ 메뉴(Conda, System)
- 공통 컴포넌트: `ChatPanel`(IDE 오른쪽과 ADE 가운데가 같은 컴포넌트), `ApprovalCard`, `ModelMenu`·`ModeMenu`(Effort·Ultracode 포함), `ScenarioView`, `RunPanel`(지금 실행 + 시간 정해서 실행), `StatusBadge`(상태 이름은 한 벌로 통일), `WorkspaceBar`(프로젝트 › 브랜치 선택 › IDE | ADE 전환)
- 목업의 가짜 데이터는 `web/src/api/mock/` 로 옮기고, 서버 API 가 생기는 대로 하나씩 실제로 바꿔요.
- 색·간격·글자는 `web/src/styles/tokens.css` 토큰만. UI 문구는 한국어 해요체, 메뉴·보기 이름(Dashboard, Overview, Agents, Schedule, Projects, Papers, Inbox, List, Graph, IDE, ADE, Scenario)은 영어.
- 새 의존성: 웹 터미널용 `@xterm/xterm`(+ fit addon) 정도. 그 밖에 큰 라이브러리를 추가하기 전에는 물어봐요.

---

## 5. 화면별 요구 (목업과 짝)

| 화면 | 목업 | 꼭 들어갈 것 |
|---|---|---|
| Dashboard | `MissionControl.dc.html` | 보기 전환 **Overview / Agents / Schedule**. Overview: 인사·요약, 끊긴 실행 배너, 숫자 5칸, 답 필요/작업 중/완료 카드(할 일 진행, git 상태, ADE 로 가기, "바로 허용"은 diff 요약을 펼친 뒤 허용(제안)), 열린 PR, 최근 머지, 자원. Agents: Hide 방식 그래프 — 프로젝트별 상자, You 노드, 세션·하위 에이전트·학습 실행 노드, 실선(부모-하위), 점선(참고), 주황 점선(나를 기다림), "오늘 끝난 것도 보기". Schedule: 24시간 띠 + 예약 표(켜기/끄기, 수정, 삭제) + 규칙 안내, 이 화면에서 바로 예약 만들기(제안) |
| Projects | `Projects.dc.html` | 왼쪽 목록(검색, 정렬, 고정, 상태 점·요약), 오른쪽 상세 헤더(경로, git, conda, 세션, 학습, IDE/ADE) + 탭 Files(worktree 선택 + 파일 표) / Worktrees / Sessions·Runs / Settings(기본 conda 환경 + "환경 관리" 링크, 자주 쓰는 명령, 지표 파일 규칙, repo 에 같이 올리기, 등록 해제) |
| IDE | `IDE.dc.html` | 위쪽 WorkspaceBar, 왼쪽 아이콘줄(탐색기, 검색, 소스 제어, **Scenario**, 실행), Monaco 편집기 탭, 아래 터미널 탭(bash, 실행 중인 학습 tmux 붙기, 새 터미널), 오른쪽 ChatPanel, 아래 상태줄. 실행 탭: 명령·위치·환경, 실제 실행 명령 보기, **지금 실행 / 시간 정해서 실행…**, 실행 중·최근 실행 |
| ADE | `ADE.dc.html` | IDE 와 같은 틀. 왼쪽 아이콘줄(탐색기, 소스 제어, **세션**), 세션 목록(프로젝트 › worktree › 세션, 하위 에이전트, 전체/내 차례, 검색), 가운데 ChatPanel(도구 사용 줄, 할 일, 승인 카드: diff·이유 입력·허용/이 세션에서 계속 허용/거부), 오른쪽 탭 **Scenario / 변경 / 실행**. 탐색기·소스 제어에서 파일을 누르면 오른쪽 변경 탭에 diff |
| ChatPanel 입력창 | `IDE.dc.html`, `ADE.dc.html` | VS Code Claude Code 확장과 같은 구성: 입력칸 + 마이크, 아랫줄 `+`(첨부) `/`(슬래시 명령) 모델 칩("Opus 5.5 High" 처럼 모델 + Effort), 오른쪽 Mode 버튼(✋ Manual) + 보내기. 모델 메뉴: "Select a model" 목록 + Effort 5단계 + Ultracode. Mode 메뉴: Manual / Edit automatically / Plan / Auto + "⇧ + tab to switch" + Effort + Ultracode. 바깥을 누르거나 Esc 로 닫힘. 입력창이 좁으면(약 330px 이하) 모델 칩이 다음 줄로, Mode 는 아이콘만 |
| Papers | `PaperLibrary.dc.html`, `PaperGraph.dc.html`, `PaperReader.dc.html` | 라이브러리 제목 옆 **List / Graph** 전환. 리더는 라이브러리의 상세(← 라이브러리, "그래프에서 보기"). 그래프: 노드(논문 3분류·프로젝트·메모), 연결 종류 켜고 끄기, 선택 노드 주변만 보기, 오른쪽 연결 목록, "Claude 에게 묻기"는 누를 때만. **계획 관련 버튼은 모두 없음**. 8단계 결정(2026-11-23): vault 는 **읽기만**(위치는 사람이 정하고, 안 정하면 데이터 폴더 `vault/`), 읽음 상태는 데이터 폴더 `papers.json`, "프로젝트에서 사용" 은 프로젝트 설정의 `papers`(사람이 고름), "Claude 에게 묻기" 는 ADE 새 세션에 질문만 채움. 논문 추가(2026-11-24): arXiv 링크(arXiv API 로 메타 · 초록 + PDF) · PDF 올리기만 vault `Papers/` 에 **새 파일**을 쓰고, 있는 노트는 덮지 않음. 리더 본문 · AI 요약 · PDF 파싱은 아직 mock |
| Inbox | `Inbox.dc.html` | 종류 필터(전체, 답 필요, 실행, 예약, PR·머지, 시스템), 안 읽은 것만, 알림마다 바로 처리 버튼, Discord 웹훅 상태(가린 주소, 테스트, 바꾸기, 끊기), 보낼 알림 스위치, 조용한 시간. 헤더 배지는 "내가 처리해야 하는 것"(답 필요 + 실패·끊김)만 셈(제안) |
| Conda | `Conda.dc.html` | 환경 목록(보호됨/사용 중 표시), 환경 정보, 잠김·보호 배너, 패키지 설치(conda/pip, 바뀌는 것 미리 보기 → 설치), 패키지 표(업데이트/제거), 삭제(이름 입력) |
| System | `System.dc.html` | 서버·터널·자동 시작·GPU 상태, "lab.remote 가 바꾼 것" 표(`.labremote/` 포함), 자동 시작 구조(예약 시계, Claude 세션 수), 알림 요약, 보안 안내, 지우기 명령 |

### Claude Code 옵션 매핑 (확인함 — 아래 "확인 결과")

- Mode → SDK 권한 모드: Manual → 기본(편집마다 승인), Edit automatically → 편집 자동 허용, Plan → 계획 모드, Auto → 안전 검사 통과 시 자동 허용. **설치된 `claude-agent-sdk` 와 Claude Code 버전에서 실제로 지원하는 값과 이름을 확인**해서 매핑하고, 지원하지 않는 모드·Effort 단계·Ultracode 는 UI 에서 숨겨요. 기본값은 Manual.
- 모델 목록은 하드코딩하지 말고 Claude Code / SDK 에서 받아오는 방법을 찾아요. 방법이 없으면 서버 설정 파일의 목록을 쓰고 그 사실을 화면 아래 작은 글씨로 알려요.
- Mode·Model·Effort 는 세션마다 적용되고 `~/.claude` 를 바꾸지 않아요.

#### 확인 결과 (2026-11-23 · `claude-agent-sdk` 0.2.187 · Claude Code 2.1.318)

설치된 패키지 · 실행 파일 · 공식 문서(code.claude.com/docs)로 확인했고, 실제 세션으로 한 번씩 돌려 봤어요.

| 항목 | 결과 | 근거 |
|---|---|---|
| Claude Code 부르기 | `cli_path` 로 사용자가 설치한 `claude`. SDK 에 딸린 사본은 안 씀 | 설치된 SDK |
| 읽을 설정 | `setting_sources=["user","project","local"]` (터미널에서 쓸 때와 같게 — 사람이 고름) | 사람 결정 |
| Mode | Manual → `default`, Edit automatically → `acceptEdits`, Plan → `plan`, Auto → `auto`. `bypassPermissions`·`dontAsk` 는 안 씀. Auto 는 모델이 지원할 때만 보임 | SDK `PermissionMode` |
| Effort | `low`·`medium`·`high`·`xhigh`·`max`. 모델마다 지원 단계가 다름. 세션 중 바꾸는 함수가 없어 다음 연결부터 적용 | SDK `EffortLevel`, server info |
| 모델 목록 | 하드코딩하지 않고 연결 직후 `get_server_info()["models"]`(모델별 지원 Effort 포함). 계정 정보는 화면에 안 보냄 | 실측 |
| 승인 | `can_use_tool` 콜백 → 대기 중 승인 → 먼저 온 답. "이 세션에서 계속 허용" 은 lab.remote 가 세션 안에서만 기억(설정 파일 안 씀) | SDK, 실측 |
| 질문(AskUserQuestion) | `can_use_tool` 로 옴. 답은 `updated_input={"questions": 원래 질문, "answers": {질문 글: label 또는 [label]}}`, 보기 대신 쓴 글은 `response` | 문서 agent-sdk/user-input, 실측 |
| 할 일 도구 | Opus 4.7·Sonnet 4.6·Haiku 4.5 이하 모델에서만 기본으로 켜짐. `allowed_tools` 에 할 일 도구 이름(TodoWrite·Task*)을 넣어 켬 | 문서 agent-sdk/todo-tracking, 실측 |
| Ultracode | Effort 단계가 아니라 Claude Code 설정 키 `"ultracode": true`. 세션마다 `settings`(인라인 JSON → `--settings`)로 켬. xhigh 를 지원하는 모델에서만 | 문서 model-config · settings-reference |
| 로그인 확인 | 연결만 해서 `account.subscriptionType` 으로 봄(자격 증명 파일 안 읽음, 이메일 안 찍음) | 실측 |
| 터널 (9단계) | 터널은 사람이 `code tunnel service install` 로 켜고 lab.remote 는 `code tunnel status` · `code tunnel user show` 로 읽기만 (2026-11-23 결정). 전달한 바깥 주소는 `labremote remote set` 으로 적으면 Host 허용 + Discord "답하기" 링크 | VS Code CLI 1.131 도움말 · 실측(꺼진 상태) |
| 터널 실측 (켜짐) | `status` = `{"tunnel":{"name","started_at","tunnel":"Connected","last_connected_at","last_disconnected_at","last_fail_reason"},"service_installed":true}`. `service install` 은 사용자 서비스 `code-tunnel.service` 를 만들고 linger 를 권함 → 자동 시작을 꺼도 터널 서비스가 있으면 linger 유지 | 실측 2026-11-23 · CLI 1.131 |
| 밖에서 접속 | 휴대폰에서 전달 주소(`https://<id>-8000.<지역>.devtunnels.ms`)로 열림. vscode.dev 창을 닫아도 계속 열림 | 실측 2026-11-23 (사람) |
| 남은 것 | Ultracode 를 실제로 돌린 결과(사용량이 커서 안 돌려 봄) | — |

---

## 6. 단계 (한 단계씩, 끝날 때마다 보고)

0. **정리**: 브랜치, 2장의 삭제 표 → 승인 → 제거, `CLAUDE.md`·문서 v3 기준으로 갱신, 테스트 정리
1. **서버 뼈대 + 웹 껍데기**: FastAPI, projects(+`.labremote/`), files, git/worktree 읽기, system 상태 / 전역 헤더, 라우트, 화면 껍데기(목업 데이터)
2. **실행**: `labremote run` 정리, 실행 기록, 지표 읽기, 끊긴 실행 감지, Dashboard Overview 를 실제 데이터로, Inbox + Discord
3. **채팅**: agents 연결 부품 + Claude 구현, 세션 저장·이어 가기, 승인 흐름(모든 화면에서 답하기), ADE 화면, ChatPanel(Mode·Model·Effort 포함)
4. **IDE**: Monaco 편집기, 탐색기·검색·소스 제어, 터미널 탭(WebSocket ↔ tmux), 실행 탭, WorkspaceBar(IDE ⇄ ADE 전환 시 같은 worktree 유지)
5. **예약**: scheduler, 실행 탭의 "시간 정해서 실행…", Dashboard Schedule, Dashboard Agents 그래프
6. **Scenario**: 분석 요청 → JSON → 저장·바뀜 감지 → IDE·ADE 패널, "실행 탭에 채우기"
7. **Conda** 화면과 보호 장치
8. **Papers**: List/Graph 전환, 지식그래프 API, 계획 관련 버튼 제거, Projects 화면 마무리
9. **설치·운영**: 설치 스크립트(clone 후 몇 줄), `doctor`, 자동 시작, 지우기 안내, `docs/SETUP.md`·`docs/operations.md` 갱신

각 단계의 완료 조건: 서버 테스트 통과(`pytest`), 웹 `npm run typecheck`·`npm run build` 통과, 해당 화면을 목업과 비교한 차이 목록.

---

## 7. 아직 정하지 않은 것 (구현하지 말고 자리만)

> 5장 표에서 "(제안)" 이 붙은 항목은 UX 검토에서 나온 제안이에요. 구현 전에 한 번 확인받아 주세요.

- 모바일 v3 화면(답 필요 + 승인, 실행·예약, Inbox 중심) — 목업 없음. 지금은 데스크톱 화면이 좁은 폭에서 깨지지 않는 정도만
- 처음 실행 안내(Claude Code 설치·로그인 확인 → 프로젝트 등록 → Discord), 오류 상태(로그인 만료, 세션 오류, 연결 끊김), 프로젝트 0개 화면 — 목업 없음
- Go to… ⌘K 의 검색 창 — 버튼만 있고 창은 목업 없음
- 상태 이름 통일 규칙(제안: 상태 배지는 한국어 — 답 필요 / 작업 중 / 실행 중 / 완료 / 실패)
- Codex 연결(`agents/codex.py`)
