# lab.remote

원격 GPU 서버에서 AI 연구(논문 읽기 → 실험 설계 → 실행 → 기록)를 돌리는 개인용 시스템.

## 먼저 읽을 것
- `docs/HANDOFF.md` — 화면 목록, 디자인 토큰, 기술 스택, 구현 순서
- `docs/spec.md` — 기능 사양 (최종본)
- `docs/mockups/*.dc.html` — 화면별 목업. 구조와 동작의 기준

## 규칙
- UI 문구는 한국어, 해요체. 버튼은 짧은 동사.
- 색·간격·글자 크기는 `web/src/styles/tokens.css` 의 토큰만 사용.
- 목업에 있는 가짜 데이터는 `web/src/api/mock/` 로 옮기고 화면 코드에 하드코딩하지 않기.
- 확인 못 한 값은 지어내지 말고 `[대괄호 자리표시]` 로 남기기.
- API 키·웹훅 URL은 환경 변수로, `.env` 는 커밋하지 않기.
- 권한 관련 잠금 3가지(프로젝트 폴더 밖 쓰기, 실행 중 종료 조건·Evaluation.md 수정, 이전 실험 폴더 덮어쓰기)는 UI가 아니라 Hooks에서 강제.

## 명령
- 프론트엔드: `cd web && npm run dev`
- 백엔드: `cd server && uvicorn app.main:app --reload`
