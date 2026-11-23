# Claude Code에 처음 줄 요청 예시

> **v1 (보관)** — lab.remote v3 의 기준은 `docs/v3/PLAN.md` 예요. 이 문서는 참고용으로 남겨 둔 v1 문서이고, 부딪히면 PLAN.md 를 따라요.

순서대로 하나씩 보내고, 끝날 때마다 브라우저에서 확인하세요.

## 1. 계획 세우기 (Plan 모드 권장)
```
docs/HANDOFF.md 와 docs/mockups/ 를 읽고, React + Vite + TypeScript 프론트엔드를 web/ 에 만드는 계획을 세워줘.
화면별 컴포넌트 구조, 공통 컴포넌트 목록, 목업 데이터를 web/src/api/mock/ 로 옮기는 방식을 포함해줘.
코드는 아직 쓰지 마.
```

## 2. 뼈대
```
계획대로 web/ 를 만들고 tokens.css, 상단 바(논문 · 실험 · 코드), 라우팅, 공통 컴포넌트
(Button, SegmentedControl, StatusPill, Resizer, CollapsibleSidebar, Sheet, Toast)만 먼저 만들어줘.
```

## 3. 화면 하나씩
```
docs/mockups/AltFocus.dc.html 을 /experiments 화면으로 옮겨줘.
마크업과 인라인 스타일은 목업과 똑같이 보이게 하고, state와 renderVals 로직은 React 상태로 바꿔줘.
가짜 데이터는 api/mock/experiments.json 으로 분리해줘.
```
같은 방식으로 FocusAuthority → FocusCode(Monaco) → FocusLibrary → FocusReader(PDF.js) → FocusDesign → 모바일 반응형 순서.

## 4. 확인
```
npm run dev 로 띄우고 Playwright로 각 화면 스크린샷을 찍어서 목업과 다른 점을 정리해줘.
```
