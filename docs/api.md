# API 목록

웹 UI가 쓰는 읽기·쓰기 경로예요. FastAPI를 만들 때 이 문서를 기준으로 삼아요.

지금은 `VITE_USE_MOCK=true` 라서 `web/src/api/mock/` 의 JSON과 목업 저장소가 응답을 흉내 내요.
`VITE_USE_MOCK=false` 로 바꾸면 같은 경로로 `VITE_API_BASE`(기본 `/api`)에 실제 요청이 나가요.

- 타입 이름은 전부 `web/src/api/types.ts` 에 있어요 (예외는 표에 적었어요).
- 모든 응답은 JSON. 쓰기는 `Content-Type: application/json`.
- 실패는 `ApiError(status, path)` 로 올라와요. 401은 인증 레이어(spec IV)가 붙으면 채워요.
- **경로가 늘거나 바뀌면 이 문서도 같이 고쳐요.**

## 읽기

| 메서드 | 경로 | 응답 타입 | 쿼리 키 | 쓰는 화면 |
|---|---|---|---|---|
| GET | `/projects` | `ProjectsPayload` | `['projects']` | `/experiments`, `/experiments/permissions` |
| GET | `/experiments` | `Experiment[]` | `['experiments','list']` | `/experiments` |
| GET | `/experiments/dashboard` | `Dashboard` | `['experiments','dashboard']` | `/experiments` |
| GET | `/experiments/events` | `EventEntry[]` | `['experiments','events']` | `/experiments` |
| GET | `/experiments/permissions` | `PermissionsPayload` | `['experiments','permissions']` | `/experiments/permissions`, `/code`(프리셋 버튼) |
| GET | `/papers` | `Paper[]` | `['papers']` | `/papers`, `/papers/:id` |
| GET | `/papers/summaries` | `PaperSummaryMap` | `['papers','summaries']` | `/papers`, `/papers/:id` |
| GET | `/papers/summary-md` | `Record<paperId, string>` | `['papers','summary-md']` | `/papers`, `/papers/:id` |
| GET | `/papers/chat` | `LibraryChat` | `['papers','chat']` | `/papers`(라이브러리에 묻기) |
| GET | `/papers/{id}/reader` | `PaperReaderPayload` | `['papers',id,'reader']` | `/papers/:id` |
| GET | `/papers/{id}/annotations` | `UserAnnotation[]` ¹ | `['papers',id,'annotations']` | `/papers/:id` |
| GET | `/papers/{id}/design` | `DesignDraft` | `['papers',id,'design']` | `/experiments/new/from-paper` |
| GET | `/code/files` | `CodeFile[]` | `['code','files']` | `/code` |
| GET | `/code/tree` | `FileNode` | `['code','tree']` | `/code` |
| GET | `/code/terminal` | `TerminalPayload` | `['code','terminal']` | `/code` |
| GET | `/code/commits` | `Commit[]` | `['code','commits']` | `/code` |
| GET | `/code/chat` | `CodeChatPayload` | `['code','chat']` | `/code` |
| GET | `/code/run` | `RunPayload` | `['code','run']` | `/code` |

¹ `UserAnnotation` 은 `web/src/api/mockStore.ts` 에 있어요 (저장소가 단일 출처라서요).

## 쓰기

바꾼 다음 해당 쿼리를 무효화해서 화면이 새 값을 읽어요.

| 메서드 | 경로 | 요청 본문 | 무효화하는 쿼리 | 쓰는 화면 |
|---|---|---|---|---|
| PATCH | `/papers/{id}` | `{ id, status: ReadStatus }` | `['papers']` | `/papers`, `/papers/:id` |
| POST | `/papers` | `Paper` | `['papers']` | `/papers/:id` 인용 카드 보관하기 |
| DELETE | `/papers/{id}` | — | `['papers']` | `/papers/:id` 보관 취소 |
| PUT | `/papers/{id}/summary-md` | `{ markdown: string \| null }` ² | `['papers','summary-md']` | `/papers`, `/papers/:id` |
| PUT | `/papers/{id}/discrepancy` | `{ target: string }` | `['papers',id,'reader']` | `/papers/:id` 수치 불일치 |
| POST | `/papers/{id}/annotations` | `NewAnnotation` 또는 `UserAnnotation` ³ | `['papers',id,'annotations']` | `/papers/:id` |
| PATCH | `/papers/{id}/annotations/{annotationId}` | `{ text: string }` | 〃 | `/papers/:id` 주석 고치기 |
| DELETE | `/papers/{id}/annotations/{annotationId}` | — | 〃 | `/papers/:id` 삭제 |
| PUT | `/experiments/permissions` | `{ mode: PermissionMode, overrides: Record<string, Permission> }` | `['experiments','permissions']` | `/experiments/permissions` |
| PUT | `/papers/{id}/design` | `{ values: Record<string, string> }` | `['papers',id,'design']` | `/experiments/new/from-paper` |
| POST | `/experiments/{id}/stop` | — | `['experiments']` | 모바일 `/experiments` 정지 확인 시트 |
| PUT | `/experiments/loop` | `{ paused: boolean }` | `['experiments']` | 모바일 `/experiments` 루프 일시정지 |

² `null` 이면 수정본을 지우고 요약에서 만든 값으로 돌아가요.
³ `id` 가 들어 있으면 **되돌리기**예요 — 지웠던 것을 `id`·`createdAt` 그대로 되살려요.

## 서버가 채워 줘야 하는 것

목업 JSON에 처음 상태로 `null` 을 넣어 둔 자리예요. 실제 서버도 같은 필드를 내려줘야 해요.

| 타입 | 필드 | 뜻 |
|---|---|---|
| `PermissionsPayload` | `saved` | 저장해 둔 권한 설정. 저장한 적 없으면 `null` |
| `DiscrepancyNote` | `chosen` | 수치 불일치에서 고른 재현 목표. 안 골랐으면 `null` |
| `DesignDraft` | `saved` | 설계 초안에 입력해 둔 값. 없으면 `null` |
| `Paper` | `field`, `model` | 아직 분류 전이면 `null` (화면은 "분류 대기"로 보여 줘요) |
| `PaperReaderPayload` | `pdfUrl` | 원문 PDF 주소. 지금은 개발용 `/fixtures/<id>.pdf`, 서버가 붙으면 실제 주소 |
| `Dashboard` | `loopPaused` | 루프가 멈춰 있는지 |

## 모바일

768px 이하에서는 같은 경로를 **같은 `api/` 로** 읽고 써요 (`useIsMobile()` 로 레이아웃만 갈아끼워요).
그래서 모바일에서 바꾼 값(실험 정지, 읽음 상태, 권한 프리셋)이 데스크톱에도 그대로 보여요.

모바일에서 읽기만 하는 화면 — `/experiments/permissions`(프리셋만 바꿀 수 있어요),
`/experiments/new/from-paper`(값 확인만).

## 아직 없는 것

- **인증** (spec IV) — 로그인과 401 처리. `client.ts` 에 자리만 비워 뒀어요.
- **실시간 갱신** — 대시보드 지표·터미널 로그는 지금 폴링 없이 한 번만 읽어요. SSE/WebSocket 으로 바꿀 자리예요.
- **업로드** — 논문 PDF 업로드, URL 입력은 화면만 있고 경로가 없어요.
- **인용 그래프** — Semantic Scholar/OpenAlex 를 거쳐 올 값. 지금은 `[Semantic Scholar 값]` 자리표시.

## 개발용

- `?reset-mock` (개발 모드 + 목업 모드) — 목업 저장소를 처음 상태로 돌려요.
- 목업 저장소는 `localStorage` 의 `lab-remote.mock.v1` 하나에 담겨요.
- `/fixtures/*` 는 Vite 개발 서버 전용이에요 (논문 PDF·쪽 이미지·arXiv HTML). 배포물에는 안 들어가요.
- `/pdfjs/standard_fonts/`, `/pdfjs/cmaps/` 는 PDF.js 가 쓰는 자산이에요.
  CDN 으로 나가지 않게 `vite.config.ts` 의 `pdfAssetsPlugin` 이 같은 출처로 내줘요.
