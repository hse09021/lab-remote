# 원격 AI 연구 시스템 구현 계획

> **v1 (보관)** — lab.remote v3 의 기준은 `docs/v3/PLAN.md` 예요. 이 문서는 참고용으로 남겨 둔 v1 문서이고, 부딪히면 PLAN.md 를 따라요.

Nov 2, 2026 · @김민규

## 시스템 구조

시스템은 사용자 접점, 상시 프로세스, 에이전트 계층, 저장소의 네 층으로 나뉘고, 직접 개발하는 부분은 상시 프로세스, Hooks, 웹 UI입니다.

&#91;embedded content: 시스템 구조 · 4개 층\]

웹 UI가 상시 프로세스를 제어하고, 오케스트레이터가 Claude Code CLI를 호출하며, Hooks가 그 실행을 감시합니다. 권한 승인과 대화는 Claude 앱의 Remote Control로, 시스템 이벤트는 Discord 웹훅으로 받습니다.

## 모듈별 담당 기능

기획서의 기능은 직접 개발할 6개 모듈로 나뉘며, 오케스트레이터가 시스템의 중심입니다.

| 모듈 | 담당 기능 | 기획서 섹션 |
| --- | --- | --- |
| 프로젝트 생성기 | Loop Engineering 폴더 구조, CLAUDE.md, File\_directory.md, gitignore, environment.yml 생성, conda 환경 추천·생성 | III-1, III-6 |
| Hooks | 권한 매트릭스를 Claude Code hooks와 settings로 변환, 프로젝트 폴더 밖 쓰기와 종료 조건·Evaluation.md·이전 실험 폴더 수정 차단, 승인·거절을 Approval\_log.csv에 기록 | III-4 |
| 오케스트레이터 | 작업 큐, 연구 전체 자동화의 루프 반복과 종료 조건 판정, 재부팅 후 복구, Remote Control 세션 관리, 사용량 한도 시 대기, Git 처리(기록은 main worktree, 코드는 실험 브랜치와 PR) | III-4, III-6, IV, V |
| 모니터 | 학습 로그와 W&B 지표에서 NaN, 발산, OOM 반복 감지, GPU·CPU·디스크 상태 수집, 끝난 실험의 재개용 체크포인트 정리, 이상 시 Discord 웹훅 알림 | III-4, IV |
| 논문 파이프라인 | PDF·arXiv HTML 수집과 파싱(페이지·섹션 위치 보존), 프롬프트 템플릿으로 요약 생성, OpenReview 리뷰 반영, vault 저장, 라이브러리 검색·비교표, Experiment Replication, 관계도 그래프 | I, II |
| 웹 UI | 인증, 실험·자원 대시보드, 권한과 종료 조건 설정 화면, 이후 PDF 뷰어와 그래프 화면 | I, II, IV |

- 논문 파이프라인은 범위가 가장 넓어서 내부에서 다시 단계를 나눠야 합니다.
- 웹 UI의 외부 접속은 Tailscale처럼 포트를 직접 열지 않는 방식을 사용합니다.
- III-3 Code Editor는 웹 UI 안에 직접 만듭니다. 편집기 엔진은 Monaco Editor(VS Code와 같은 엔진)를 쓰고, 파일 트리, AI 수정 내역과 diff, 잠긴 파일 표시, Git 커밋·PR, tmux 터미널을 함께 붙입니다.
- AI가 판단하고 글을 쓰는 작업은 코드에 박지 않고 별도 프롬프트 템플릿 파일로 관리합니다.

논문 입력은 PDF와 arXiv HTML을 모두 지원합니다. arXiv HTML이 있는 논문은 섹션 구조와 수식(MathML)이 깔끔하게 남아 있어 HTML을 우선 사용하고, HTML이 없거나 변환이 깨진 논문은 PDF로 처리합니다. HTML에는 페이지 번호가 없으므로 근거 위치는 섹션 번호(§4.1)와 해당 섹션 앵커 링크로 표기합니다.

## MVP 순서

1단계(프로젝트 생성기 + Hooks)부터 시작합니다. 가장 작으면서 바로 쓸 수 있고, 이후 단계가 모두 그 위에 올라갑니다.

1. 프로젝트 생성기 + Hooks: Claude Code와 Remote Control만으로 Loop 구조 실험을 안전하게 수동 진행
2. 오케스트레이터 + 모니터 + 웹훅: 자리를 비워도 실험이 루프로 돌고, 문제가 생기면 알림
3. 웹 UI 최소 버전: 대시보드와 권한·종료 조건 설정을 화면에서
4. 논문 요약 + vault + Experiment Replication: 논문에서 실험 설계까지 연결
5. 라이브러리 검색·비교, PDF 뷰어 기능: Explanation, Chat, Smart Citation 등
6. 관계도 그래프, Highlight, Visualization 등: 나머지 탐색·부가 기능

실험 쪽을 먼저 두는 이유는, 논문 읽기 도구는 당분간 기존 서비스로 대체할 수 있지만 원격 실험 자동화는 대체재가 없기 때문입니다.

## 다음 단계에서 정할 사항

기술 선택으로 넘어가기 전에 데스크탑 환경부터 확정해야 합니다.

- [x] 데스크탑 OS가 Ubuntu로 확정, 프로세스 관리는 systemd로 진행
- [x] GPU 수: 1개로 확정, 작업 큐는 실험을 한 번에 하나씩 순차 실행
- [x] 기술 스택: 아래 추천안으로 확정

## 기술 스택 (확정)

백엔드는 Python 하나로 통일하고, Ubuntu·GPU 1개 환경에 맞춰 별도 DB 서버나 메시지 큐 없이 가볍게 갑니다.

| 영역 | 추천 | 이유 |
| --- | --- | --- |
| 백엔드·오케스트레이터 | Python + FastAPI | ML, W&B, PDF 라이브러리와 같은 언어로 통일 |
| 상태·작업 큐 | SQLite | 1인 사용, 순차 실행이라 DB 서버나 Redis 불필요 |
| 프로세스 관리 | systemd + tmux | 부팅 시 자동 실행과 재시작, Remote Control 세션은 tmux 안에서 |
| Claude 호출 | Claude Code CLI 헤드리스 모드(claude -p) | 구독 그대로 사용, 프롬프트 템플릿 파일을 넘겨 실행 |
| Hooks | Python 스크립트 + 정책 파일 하나 | 권한 매트릭스를 한 곳에서 읽어 판정 |
| 모니터링 | pynvml, psutil, W&B API | GPU·시스템 지표와 학습 지표 수집 |
| 프런트엔드 | React + Vite | 대시보드, 논문 뷰어, 그래프 라이브러리가 풍부 |
| 논문 파싱 | PDF: GROBID + PyMuPDF, arXiv HTML: BeautifulSoup + lxml | PDF는 섹션·참고문헌 구조와 페이지 위치, HTML은 섹션 앵커와 MathML 수식을 그대로 활용 |
| 논문 뷰어 | PDF.js, arXiv HTML은 웹 UI에서 직접 표시 | 하이라이트와 원문 위치 이동의 기반 |
| 관계도 그래프 | Semantic Scholar·OpenAlex API + Cytoscape.js | 인용 데이터 수집과 그래프 표시 |
| 임베딩 | SPECTER2 (CPU 실행) | 논문용 임베딩, GPU는 실험 전용으로 비워둠 |
| 원격 접속 | Tailscale | 포트를 열지 않고 접속 |
