# lab.remote 웹 UI 핸드오프

> **v1 (보관)** — lab.remote v3 의 기준은 `docs/v3/PLAN.md` 예요. 이 문서는 참고용으로 남겨 둔 v1 문서이고, 부딪히면 PLAN.md 를 따라요.
> 단, **1장(목업 읽는 법)·3장(디자인 토큰)** 은 v3 에서도 그대로 써요.

원격 AI 연구 시스템의 웹 UI 목업을 실제 코드로 옮기기 위한 문서예요.
목업은 `docs/mockups/` 에 있고, 이 문서는 Claude Code가 먼저 읽을 안내서예요.

## 1. 목업 파일 읽는 법

`*.dc.html` 은 디자인 캔버스 전용 형식이라 브라우저에서 바로 열면 제대로 안 보여요(전용 런타임 `support.js` 가 없어요).
대신 **구조와 동작의 명세서**로 읽으면 돼요.

- `<x-dc>` 안의 HTML: 화면 구조와 인라인 스타일. 색·간격·글자 크기는 이 값을 그대로 따르면 돼요.
- `{{ name }}`: 아래 스크립트가 계산해서 넣는 값.
- `<sc-if value="{{ x }}">`: 조건부 렌더링. React의 `{x && ...}`.
- `<sc-for list="{{ xs }}" as="x">`: 반복. React의 `xs.map(x => ...)`.
- `onClick="{{ fn }}"` 등: 이벤트 핸들러.
- `<script type="text/x-dc">` 의 `class Component`:
  - `constructor` 의 `this.state` → 화면 상태 (React `useState`)
  - `renderVals()` → 상태로부터 화면 값을 계산 (React 컴포넌트 본문)
  - 하드코딩된 배열(PAPERS, SECTIONS, refs 등)은 **목업용 가짜 데이터**예요. 실제로는 API에서 받아요.
- `canvas.json`: 캔버스 배치 정보라 개발에는 필요 없어요.
- `paper/`: 논문 리더 목업용 예시 논문(Attention Is All You Need) 쪽 이미지와 그림. 개발용 샘플로만 쓰고 배포물에는 넣지 않아요.

## 2. 화면 목록

| 파일 | 화면 | 경로(제안) | 핵심 기능 |
|---|---|---|---|
| `FocusLibrary.dc.html` | 논문 라이브러리 | `/papers` | 사이드바(최근·검색·상태·Research Field 태그·휴지통), 목록/촘촘히 보기, 읽음 상태 드롭다운, 논문 업로드(PDF·URL), 요약 MD 패널(정리된 보기 ↔ MD 원문 편집), 선택 바(실험 설계 초안·BibTeX), 떠 있는 "라이브러리에 묻기" |
| `FocusReader.dc.html` | 논문 리더 | `/papers/:id` | PDF/arXiv HTML 전환(읽던 위치 유지), AI 아웃라인·읽은 위치·하이라이트 켜고 끄기, 섹션별 AI 설명 버튼(E), 그림·수식 설명받기, 인용 카드, 텍스트 선택 메뉴(설명·인포그래픽·하이라이트·번역·주석·AI에게 질문), 떠 있는 대화창(최소화 시 원래 자리에 알약으로), 수치 불일치 알림, 오른쪽 AI 패널(요약·채팅·인용·노트) |
| `AltFocus.dc.html` | 실험 대시보드 | `/experiments` | 프로젝트·보기 사이드바, 새 실험 메뉴, 승인 대기 배너, 지표 5칸, 학습 곡선, 자원, 실험·큐 표, 결정·이벤트 기록 |
| `FocusAuthority.dc.html` | 권한 설정 | `/experiments/permissions` | 권한 프리셋 3종, 항목별 자동 허용/승인 필요/차단(잠김 3개), 종료 조건, 알림(Discord·Claude 앱), 승인 기록 |
| `FocusDesign.dc.html` | 실험 설계 초안 | `/experiments/new/from-paper` | 논문에서 뽑은 값 표(근거 링크·추정 필요 표시), 실험 설계, 생성될 파일, Claude와 설계 토론 패널 |
| `FocusCode.dc.html` | 코드 에디터 | `/code` | VS Code 배치: 작업 표시줄(탐색기·검색·소스 제어·실험 실행), 탐색기 새 파일/새 폴더/새로 고침/모두 접기, Monaco 편집기 탭, 하단 문제·출력·터미널, Claude Code 채팅(권한 프리셋 선택), 패널 크기 조절 |
| `FocusMobile.dc.html` | 모바일 | 같은 경로의 반응형 | 아래 탭(논문·실험·코드), 승인 대기, EXP 진행, 큐, 정지 확인 시트, 논문 요약 시트, 코드 diff·Claude Code 요청 |

상단 메뉴 순서는 **논문 · 실험 · 코드**.

### 공통 동작
- 패널 경계선 드래그로 너비 조절(키보드 좌우 화살표 16px), 사이드바 접기/펼치기(접으면 48px 띠).
- 읽음 상태: 처음 열면 자동으로 "읽는 중", 끝까지 읽으면 "완료로 표시할까요?" 안내, 사용자가 드롭다운으로 언제든 변경.
- 권한 프리셋 변경은 실행 중인 실험엔 적용하지 않고 다음 작업부터 적용, 기록을 남김.

## 3. 디자인 토큰 (스타일 C)

```css
:root {
  --bg: #FFFFFF;
  --surface-muted: #F6F7F7;   /* 사이드바, 카드 배경 */
  --surface-sunken: #F0F2F2;  /* 세그먼트 컨트롤 배경 */
  --border: #E1E5E4;
  --border-soft: #EEF1F0;
  --text: #141A19;
  --text-muted: #56605E;
  --text-soft: #3D4644;
  --accent: #0E6E5C;          /* teal */
  --accent-dark: #0B5A4B;
  --accent-tint: #E3F2EE;
  --accent-row: #F6FBF9;
  --attention: #B4530F;       /* 승인 대기, 확인 필요 */
  --attention-tint: #FDF0E5;
  --attention-text: #8A3D09;
  --primary-btn: #141A19;
  --font-sans: 'Noto Sans KR', sans-serif;
  --font-mono: 'Roboto Mono', monospace;
  --font-paper: 'Noto Serif', serif; /* 리더 본문 */
}
```

리더 하이라이트 색: 핵심 혁신 `#F5DE8E`, 방법 `#A9DACB`, 결과 `#BCD0F2`, 확인 필요 `#F6C29A`, 내 메모 `#D6C7F1`.

## 4. 확정된 기술 스택

| 영역 | 선택 |
|---|---|
| 백엔드 | Python + FastAPI, 작업 큐 SQLite |
| 에이전트 | Claude Code 헤드리스(`claude -p`) + 프롬프트 템플릿 파일 |
| 권한 강제 | Claude Code Hooks(Python 스크립트가 정책 파일 하나를 읽음) |
| 실행 | systemd + tmux, Ubuntu, GPU 1장, 순차 큐 |
| 모니터링 | pynvml, psutil, W&B API |
| 알림 | 승인: Claude 앱 Remote Control 푸시 / 시스템 이벤트: Discord 웹훅(URL은 .gitignore) |
| 프론트엔드 | React + Vite |
| 코드 편집기 | Monaco Editor (직접 구현) |
| 논문 파싱 | arXiv HTML 우선(BeautifulSoup + lxml 전처리) → 없으면 GROBID + PyMuPDF |
| 뷰어 | PDF.js(텍스트 레이어), arXiv HTML 직접 표시 |
| 인용 그래프 | Semantic Scholar / OpenAlex + Cytoscape.js |
| 임베딩 | SPECTER2 (CPU) |
| 접속 | Tailscale |

### 논문 원문 확보 순서
1. arXiv 공식 HTML → 2. ar5iv → 3. arXiv LaTeX 원본을 LaTeXML로 직접 변환 → 4. Semantic Scholar/OpenAlex로 arXiv 판 찾기 → 5. PDF만(GROBID + PyMuPDF, 수식은 영역을 잘라 Claude 이미지 입력) → 스캔본이면 OCR(ocrmypdf) 먼저.
원문 위치 링크: HTML은 `[[파일.html#S3.SS2|§3.2]]`, PDF는 `[[파일.pdf#page=4]] · p.4, §3.2`.

## 5. 프론트엔드 구조(제안)

```
web/
  src/
    styles/tokens.css
    components/        # Button, SegmentedControl, StatusPill, Resizer, CollapsibleSidebar, Sheet, Toast
    layout/AppHeader.tsx
    features/
      papers/          # Library, Reader(PdfView, HtmlView, Outline, AiPanel, FloatingChat, CiteCard, SelectionMenu)
      experiments/     # Dashboard, Permissions, DesignDraft
      code/            # Editor(Monaco), Explorer, SourceControl, RunPanel, ClaudeChat
    api/               # FastAPI 클라이언트 + 목업 데이터(mock/*.json)
```

처음에는 `api/mock/*.json` 의 가짜 데이터로 화면을 다 만든 다음, FastAPI가 준비되는 대로 하나씩 실제 API로 바꿔요.

## 6. 목업에서 비워 둔 것 (실제 구현 때 채울 것)
- 인용 카드의 피인용 수: `[Semantic Scholar 값]` 자리표시.
- 논문별 하이퍼파라미터 등 확인 못 한 값: `[부록 표의 값]` 같은 대괄호 자리표시.
- 리더 HTML 보기의 본문 문단은 회색 줄로 대신했어요. 실제로는 arXiv HTML 본문을 그대로 표시.
- 미리 써 둔 AI 설명은 일부 섹션·그림·수식만 있어요. 실제로는 Claude가 해당 위치 본문으로 생성.
- 인포그래픽은 고정 그림 하나뿐. 실제로는 Claude가 SVG/Mermaid를 만들고 `vault/Papers/attachments/` 에 저장.
- 목업끼리 권한 프리셋 상태가 공유되지 않아요. 실제로는 정책 파일 하나를 함께 읽고 씀.

## 7. 구현 순서 (MVP)
1. ✅ **프로젝트 생성기 + Hooks** — 2026-11-04 완료.
   실측 결과와 한계는 [docs/operations.md](operations.md) 에 있어요.
   Claude Code 2.1.317 에서 판단 표 16줄·승인 경로 3종을 직접 돌려 확인했고,
   잠긴 항목 3개 + 서버 보호 파일·비밀 파일·산출물 보존을 Hooks 가 강제해요.
2. 오케스트레이터 + 모니터 + 웹훅
3. 최소 웹 UI (실험 대시보드 → 권한 설정 → 코드 에디터)
4. 논문 요약 + vault + 재현 실험 설계
5. 라이브러리 검색, PDF 뷰어 기능
6. 인용 그래프와 나머지

### ①에서 ②로 넘기는 것

①을 닫으면서 경계를 그어 둔 세 가지예요. 자세한 근거는
[docs/operations.md](operations.md) 의 "②로 넘기는 것" 절에 있어요.

- **승인 대기열** — 헤드리스에서 막은 승인 요청이
  `server/data/requests/<프로젝트>/` 에 쌓여요 (`labremote requests list`).
  닫아 줄 주체가 ②예요.
- **알림에 사유 싣기** — 훅이 쓴 사유는 PC Write 승인창과 휴대폰 화면에서
  **안 보여요.** ask 를 낼 때 `notify` 로 사유를 함께 보내야 해요.
- **State.yaml ↔ runstate 정합** — 실측에서 둘이 어긋났어요(loop 0 vs
  EXP-002 running). 오케스트레이터가 실험을 시작·종료할 때 같이 갱신해요.
- 세션을 띄울 때 `--permission-mode default` 를 명시해요
  (2.1.317 은 사용자 설정에 `defaultMode` 가 없으면 `auto` 로 떠요).
