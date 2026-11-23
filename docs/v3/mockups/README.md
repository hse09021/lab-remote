# v3 목업

디자인 캔버스에서 만든 v3 화면이에요. 구현 기준은 `docs/v3/PLAN.md` 이고, 파일 읽는 법은 `docs/v1/HANDOFF.md` 1장과 같아요.
브라우저에서 바로 열면 제대로 안 보여요(`support.js` 런타임이 없어요). 구조·문구·동작의 명세서로 읽어 주세요.

| 파일 | 화면 | 메모 |
|---|---|---|
| `MissionControl.dc.html` | Dashboard | `state.view` 로 Overview / Agents / Schedule 전환 |
| `Projects.dc.html` | Projects | 왼쪽 목록 + 오른쪽 상세, 탭 4개 |
| `IDE.dc.html` | IDE | v1 코드 에디터 배치. Scenario 아이콘, 실행 탭(예약), ChatPanel 입력창 |
| `ADE.dc.html` | ADE | IDE 와 같은 틀. 세션 패널, 가운데 채팅, 오른쪽 Scenario / 변경 / 실행 |
| `PaperLibrary.dc.html` | Papers · List | v1 라이브러리 + List/Graph 전환 |
| `PaperGraph.dc.html` | Papers · Graph | Obsidian 방식 지식그래프 |
| `PaperReader.dc.html` | 논문 리더 | v1 리더. 논문 그림(`paper/`)은 저작권 때문에 없어요 |
| `Inbox.dc.html` | Inbox | 알림 + Discord 웹훅 설정 |
| `Conda.dc.html` | Conda (⚙) | 환경·패키지 관리, 보호·잠금 |
| `System.dc.html` | System (⚙) | 설치 상태, 바꾼 것, 자동 시작 |

- 전역 헤더는 모든 파일에 같은 마크업으로 들어 있어요(맨 위 `<header>`).
- 목업 안의 숫자·이름(EXP-007, lora-rank-ablation 등)은 가짜 데이터예요.
