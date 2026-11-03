# 운영 메모 — 훅 설치와 실측

백엔드 ①(프로젝트 생성기 + Hooks)을 돌리는 데 필요한 절차를 모아 둡니다.
구현 계획은 플랜 파일에, 여기는 **실제로 치는 명령**과 **실측 결과**를 적습니다.

## 이 머신

| 항목 | 값 |
|---|---|
| 역할 | GPU 서버 본체. 실측도 여기서 합니다 |
| `claude` | `/home/hse09021/.local/bin/claude` · 2.1.317 (버전 폴더가 아니라 이 링크를 씁니다) |
| 파이썬 | `/home/hse09021/miniconda3/envs/labremote/bin/python` (conda 환경 `labremote`, 3.11) |
| 프로젝트 루트 | `~/projects` · `LAB_PROJECTS_DIR` 로 바꿀 수 있지만 **훅에는 설치 시점 값이 박힙니다** |
| 서버 코드 | `~/Desktop/lab-remote/server` |

## ⚠ 꼭 지킬 것

**Claude Code 는 항상 실험 프로젝트 폴더 안에서 켜세요.**

훅 래퍼는 `CLAUDE_PROJECT_DIR`(없으면 `cwd`)이 프로젝트 루트 아래인지만 봅니다.
폴더 **밖에서** 켜고 안쪽 파일을 건드리면 래퍼가 그냥 통과시켜서 잠긴 항목이
막히지 않습니다. 이건 설계상의 한계이고, `labremote hooks status` 와
`labremote doctor` 가 매번 같은 안내를 찍습니다.

다른 한계 두 가지:

- 훅이 도는 범위는 **설치할 때 박은 루트 아래뿐**입니다. 런타임
  `LAB_PROJECTS_DIR` 로는 못 바꿔요 — 환경 변수가 없는 Claude Code 에서
  잠금이 조용히 꺼지는 걸 막으려고 일부러 그렇게 했습니다. 바꾸려면
  `hooks install` 을 다시 돌리세요.
- 쓰기 가능한 **MCP 서버**를 붙이면 이 게이트를 지나갑니다. ①단계에서는
  실험 프로젝트에 `.mcp.json` 을 두지 않습니다.

## 훅 설치·제거

```bash
cd ~/Desktop/lab-remote/server
PY=/home/hse09021/miniconda3/envs/labremote/bin/python

# 지금 상태 보기
$PY -m app.hooks.install status

# 필드명 실측용 (아무것도 막지 않고 stdin 만 받아 적어요)
$PY -m app.hooks.install install --mode dump

# 진짜 판정기 (판정 모듈이 다 생긴 뒤에만 됩니다)
$PY -m app.hooks.install install --mode enforce

# 되돌리기 — 우리 항목만 빼고 손으로 넣은 설정은 그대로 둬요
$PY -m app.hooks.install uninstall
```

- 설치는 `~/.claude/settings.json` 을 **병합**합니다. 고치기 전에
  `~/.claude/settings.json.labremote-<타임스탬프>.bak` 로 백업하고 그 경로를 찍어요.
- 래퍼는 `server/data/bin/labremote-hook.sh` 에 렌더됩니다. 머신마다 다른
  절대 경로가 박히므로 커밋하지 않습니다(`server/data/` 는 gitignore).
- 9단계에서 `labremote hooks install` 로 묶입니다.

## 실측 1단계 — 훅 입력 필드명 ✅ 끝남

**2026-11-03 · Claude Code 2.1.317 (native) · 이 머신**

덤프 39건을 받았고 원본은 `server/tests/fixtures/hook_events/` 에 픽스처로
들어가 있습니다(세션·프롬프트 ID 와 사용자명은 가렸습니다).

### PreToolUse 최상위

```
session_id, transcript_path, cwd, prompt_id, permission_mode,
effort{level}, hook_event_name, tool_name, tool_input, tool_use_id
```

`prompt_id` 는 문서에 없던 필드인데 **있어서 다행인 값**입니다. 승인 대기 건을
세션이 아니라 **응답 단위**로 마감할 수 있게 해 줍니다.

### tool_input

| 도구 | 실제 키 | 제 추정이었던 것 |
|---|---|---|
| `Edit` | `file_path`(절대), **`old_string`**, **`new_string`**, `replace_all` | ~~`old_str`/`new_str`~~ ❌ |
| `Write` | `file_path`(절대), **`content`** | ~~`file_text`~~ ❌ |
| `Bash` | `command`, `description` | ✅ |
| `WebFetch` | `url`, `prompt` | ✅ |
| `Read` | `file_path` | ✅ |
| `ToolSearch` | `query`, `max_results` | (새로 나옴) |

틀린 후보 키는 지우지 않고 `app/hooks/classify.py` 상수에 "실측 안 됨" 주석과
함께 남겨 뒀습니다. 어느 후보로도 경로를 못 읽으면 **차단**합니다.

### 이벤트별

- `PostToolUse` = PreToolUse + `tool_response{stdout,stderr,interrupted,…}` + `duration_ms`
- `Stop` = `session_id`, `transcript_path`, `cwd`, **`prompt_id`**, `permission_mode`,
  `effort`, `hook_event_name`, `stop_hook_active`, `last_assistant_message`,
  `background_tasks`, `session_crons`
- `SessionEnd` = `session_id`, `transcript_path`, `cwd`, `prompt_id`,
  `hook_event_name`, `reason` — `permission_mode` 와 `effort` 는 **안 옵니다**

### MultiEdit 은 한 번도 안 나왔습니다

한 파일 두 군데를 한 번에 고치라고 시켜도 Claude 는 `Edit` 를 썼습니다.
그래도 matcher 와 분류 코드에서 **빼지 않았습니다** — 다른 버전이나 다른
모델이 쓸 수 있고, 빠져 있으면 그게 그대로 구멍이 되니까요.
(`classify.MULTI_EDIT_TOOLS`, 근거는 주석에)

### ⚠ 가장 중요한 관찰 — 거절되면 우회합니다

`claude -p` 에서 쓰기 도구가 거절되자 Claude 는 **다른 도구로 돌아갔습니다.**

```
1) Edit  거절  →  2) Bash sed -i … README.md  거절  →  3) Write README.md  거절
```

실제 명령 (`20261103-232300-996652-PreToolUse-Bash.json`):

```
sed -i -e 's/덤프/실측/g' -e 's/지워도/삭제해도/g' README.md && sed -n '1,3p' README.md
```

Write/Edit 만 막고 Bash 를 비워 두면 잠금이 사실상 없는 것과 같습니다.
그래서 대응을 셋 넣었습니다.

1. **같은 판정** — `sed -i`, `>`/`>>` 리다이렉션, `tee`, `cp`, `touch`,
   `truncate`, `dd of=`, `mv` 가 Edit 와 똑같은 경로 판정을 받습니다.
   위 명령은 `&&` 로 갈라 앞은 쓰기, 뒤(`sed -n`)는 읽기로 봅니다.
2. **사유로 막기** — 모든 deny·ask 사유 끝에
   *"다른 도구나 명령으로 돌아가지 말고 작업을 멈추고 보고해 주세요"* 가 붙습니다.
3. **기록** — 같은 세션에서 막힌 파일에 **다른 도구로** 다시 오면
   `logs/hook_events.jsonl` 에 `bypassAttempt` 로, 승인 로그에 `우회 시도` 행으로 남습니다.

### 읽기 전용 도구는 matcher 에 안 넣습니다

`ToolSearch` 는 도구 스키마만 불러옵니다(`tool_input = {query, max_results}`).
`Read`·`Glob`·`Grep` 과 함께 판정 대상이 아닙니다 — 넣으면 승인 소음만 늘고
막을 것이 없습니다. 다만 ToolSearch 로 **쓰기 가능한 MCP 도구**를 불러올 수는
있으니, MCP 구멍(아래 한계)과 같은 문제로 묶어 둡니다.

### 다시 돌릴 일이 있으면

```bash
cd ~/Desktop/lab-remote/server
PY=/home/hse09021/miniconda3/envs/labremote/bin/python
$PY -m app.hooks.install install --mode dump
cd ~/projects/dump-scratch && claude -p "…"
ls -1 ~/Desktop/lab-remote/server/data/hook_dumps/
```

## 실측 2단계 — 계약 확인

판정기를 붙인 뒤(6~7단계) 할 것입니다. 지금은 항목만 적어 둡니다.

- [ ] `defer` 가 정말 Claude Code 기본 권한 흐름으로 넘어가는지.
      `allow` 를 아끼는 설계 전체가 이 가정 위에 있습니다.
- [ ] 빈 stdout + `exit 0`(래퍼의 밖-건너뛰기)이 "결정 안 함" 으로 취급되는지
- [ ] `onFailure: "block"` 이 이 버전에서 실제로 동작하는지.
      훅을 일부러 `exit 1` 로 깨뜨려 봅니다.
- [ ] `permission_mode` 가 `acceptEdits`/`plan`/권한 우회 계열일 때 잠금 deny 가 유효한지
- [ ] 10분 넘게 도는 Bash(실제 학습) 중에 훅이 끼어들거나 끊지 않는지
- [ ] 훅 설정을 바꾼 뒤 세션 재시작이 필요한지

## 실측 3단계 — 승인 경로

### 1차 결과 (2026-11-03, 덤프 모드)

**헤드리스(`claude -p`)에서는 승인 요청이 사람에게 가지 않고 자동으로
거절됩니다.** Claude 가 "권한이 승인되지 않았다" 고 보고하고 응답을 끝냅니다.
멈춰서 기다리지 않습니다.

- 거절된 호출은 **PostToolUse 가 오지 않고** 바로 `Stop` → `SessionEnd` 로 갑니다.
  → 그래서 대기 건 마감에 `Stop` 훅이 꼭 필요합니다. 없으면 대기 뱃지가
    영원히 켜져 있게 돼요.
- 이건 Claude Code 자체 권한 흐름의 동작입니다. **훅이 `ask` 를 돌려줬을 때도
  같은지는 아직 못 봤습니다** — 그건 enforce 설치 뒤에 확인합니다.

### 남은 확인

| # | 방식 | 일으킬 행동 | 확인할 것 | 결과 |
|---|---|---|---|---|
| 1 | `claude -p` (헤드리스) | `pip install peft` | **훅이 `ask` 를 돌려줄 때** 멈추나, 거절로 끝나나 | [enforce 설치 후] |
| 2 | tmux 대화형 + Remote Control | 같은 행동 | 폰으로 푸시가 오나 (`/config` 의 `Push when actions required`) | [실측 전] |
| 3 | 2와 같은 세션 | "앞으로 계속 허용" 뒤 같은 행동 재시도 | **매번 다시 묻는지** | [실측 전] |
| 4 | 2와 같은 세션 | 폰에서 거부 | Stop 훅이 `거부 또는 미응답` 으로 마감하나 | [실측 전] |

1번 결과에 따라 정책의 `headless.onAsk` 가 정해집니다. 지금은 `"ask"` 이고,
"헤드리스에선 승인이 안 간다" 로 확정되면 `"deny-with-reason"` 으로 바꿉니다
(사유 앞에 `[승인 필요: …]` 를 붙이고 Discord 로 "승인 대기" 를 알립니다).
**어느 쪽이든 자동 허용으로는 넘어가지 않습니다.**

## 임시 폴더

`~/projects/dump-scratch` 는 필드명 실측 전용입니다. 끝나면 지우세요.

```bash
rm -rf ~/projects/dump-scratch
```

진짜 검증용 프로젝트 `~/projects/hook-sandbox` 는 생성기(8단계)가 만듭니다.
그래서 실측용 폴더 이름을 `hook-sandbox` 와 다르게 뒀습니다 — 생성기가
`--if-exists fail` 로 거절하지 않게요.
