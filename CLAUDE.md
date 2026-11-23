# lab.remote

데스크톱(GPU)에서 AI 연구를 돌리고, 어디서든 브라우저로 보고 · 실행하고 · 알림 받는 개인용 도구.
지금은 v3 로 옮기는 중이에요. 기준 문서는 `docs/v3/PLAN.md` 예요.

## 먼저 읽을 것
- `docs/v3/PLAN.md` — v3 원칙, 구조, 화면별 요구, 진행 단계. **다른 문서와 부딪히면 이게 우선**
- `docs/v3/mockups/` — 화면별 목업(구조·문구·동작의 기준). 안내는 `README.md`
- `docs/v1/HANDOFF.md` 1장·3장 — 목업 파일 읽는 법, 디자인 토큰 (나머지 장은 v1 기준이라 참고만)
- `README.md` — 이 시스템 소개와 설치 (사람용). 자세한 설치는 `docs/SETUP.md`, 운영은 `docs/operations.md`

## 원칙 (자세한 건 PLAN.md 1장)
- 시스템 설정은 최소한만: `~/.claude`, `.bashrc`, `.condarc`, cron, systemd 타이머, 연구 프로젝트의 `.gitignore` 는 건드리지 않기. lab.remote 가 만드는 건 conda 환경 `labremote`, (자동 시작 켤 때만) 사용자 서비스 + linger, 프로젝트마다 `.labremote/` 뿐
- Claude Code 는 Python `claude-agent-sdk` 로 사용자가 로그인해 둔 것을 불러 쓰기. 훅 설치 없음. `--dangerously-skip-permissions` 금지
- AI 자동화 없음: 연구 루프 · 실험 큐 · 연쇄 실행 없음. 예약은 사람이 시각으로 건 것만
- 서버는 `127.0.0.1` 에만, nice 19, GPU 사용 안 함
- 에이전트 관련 이름은 Claude 전용으로 짓지 않기(나중에 Codex 연결 부품을 붙일 수 있게)

## 규칙
- UI 문구는 한국어, 해요체. 버튼은 짧은 동사. 메뉴 · 보기 이름(Dashboard, Projects, Papers, Inbox, Overview, Agents, Schedule, List, Graph, IDE, ADE, Scenario)만 영어.
- 색 · 간격 · 글자 크기는 `web/src/styles/tokens.css` 의 토큰만 사용.
- 목업에 있는 가짜 데이터는 `web/src/api/mock/` 로 옮기고 화면 코드에 하드코딩하지 않기.
- 확인 못 한 값은 지어내지 말고 `[확인 필요]` 로 남기고 알리기.
- 비밀값: Discord 웹훅 주소는 lab.remote 데이터 폴더에 권한 600 으로만 저장하고 로그 · 화면 · 에러에 원문을 찍지 않기. `.env` 와 그 파일은 커밋하지 않고 읽거나 출력하지도 않기.
- 지우기 · 되돌릴 수 없는 작업은 먼저 묻기. push 는 사람이 요청할 때만.

## 명령
- 설치: `./install.sh` (자세한 건 `docs/SETUP.md`, 운영은 `docs/operations.md`)
- 서버 환경: `conda activate labremote`
- 프론트엔드: `cd web && npm run dev`
- 백엔드: `cd server && labremote serve` (개발 중 자동 재시작은 `uvicorn --factory app.main:create_app --reload`)
- 테스트: `cd server && pytest` / `cd web && npm run typecheck && npm run build`