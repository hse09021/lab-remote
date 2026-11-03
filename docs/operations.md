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

## 실측 1단계 — 훅 입력 필드명

**분류 로직을 확정하기 전에 반드시 먼저 합니다.** 설치된 Claude Code 의 실제
`tool_input` 키(`old_str` vs `old_string`, `file_text` vs `content`)를 눈으로
확인해야 그 뒤가 추측이 아니게 됩니다.

```bash
# 0) 버전 기록
claude --version          # → [실측 결과]
claude doctor             # → [실측 결과]

# 1) 덤프 훅 설치
cd ~/Desktop/lab-remote/server
/home/hse09021/miniconda3/envs/labremote/bin/python -m app.hooks.install install --mode dump

# 2) 반드시 프로젝트 폴더 **안에서** 실행
cd ~/projects/dump-scratch

claude -p "README.md 아래에 '안녕' 한 줄 덧붙여 줘"
claude -p "experiments/EXP-001/config.yaml 의 rank 를 48로 바꿔 줘"
claude -p "docs 폴더 안에 scratch.md 를 만들고 한 줄 써 줘"
claude -p "ls -la 로 파일 목록을 보여 줘"
claude -p "README.md 와 docs/scratch.md 를 한 번에 고쳐 줘"
claude -p "https://example.com 을 읽어서 한 줄로 요약해 줘"

# 3) 받아 적힌 것 보기
ls -1 ~/Desktop/lab-remote/server/data/hook_dumps/
cat ~/Desktop/lab-remote/server/data/hook_dumps/*PreToolUse-Edit*.json
```

덤프는 `server/data/hook_dumps/<타임스탬프>-<이벤트>-<도구>.json` 에 쌓입니다.
판정은 전혀 하지 않고 `exit 0` 만 하므로 작업이 막히지 않습니다.

확인할 것:

- [ ] `tool_input` 의 실제 키 — `file_path` vs `path`
- [ ] Edit 의 키 — **`old_str`/`new_str` vs `old_string`/`new_string`**
- [ ] Write 의 본문 키 — `file_text` vs `content`
- [ ] MultiEdit 의 `edits` 안에 `file_path` 가 있는지, 상위에 공통 경로가 있는지
- [ ] 최상위에 `cwd`·`permission_mode`·`tool_use_id`·`session_id` 가 오는지
- [ ] `hook_event_name` 의 정확한 표기
- [ ] **Stop 에 `session_id` 가 오는지** (승인 대기 건을 세션별로 마감하는 근거)
- [ ] Bash 의 `tool_input` 모양 (`command`·`description`·`timeout`)

실측이 끝나면 덤프 JSON 을 `server/tests/fixtures/hook_events/` 로 복사해
픽스처로 씁니다.

```bash
cp ~/Desktop/lab-remote/server/data/hook_dumps/*.json \
   ~/Desktop/lab-remote/server/tests/fixtures/hook_events/
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

| # | 방식 | 일으킬 행동 | 확인할 것 | 결과 |
|---|---|---|---|---|
| 1 | `claude -p` (헤드리스) | `pip install peft` | `ask` 일 때 세션이 멈추나, 거절로 끝나나 | [실측 전] |
| 2 | tmux 대화형 + Remote Control | 같은 행동 | 폰으로 푸시가 오나 (`/config` 의 `Push when actions required`) | [실측 전] |
| 3 | 2와 같은 세션 | "앞으로 계속 허용" 뒤 같은 행동 재시도 | **매번 다시 묻는지** | [실측 전] |
| 4 | 2와 같은 세션 | 폰에서 거부 | Stop 훅이 `거부 또는 미응답` 으로 마감하나 | [실측 전] |

결과에 따라 정책 파일의 `headless.onAsk` 기본값이 정해집니다.
그때까지는 `"ask"` 입니다.

## 임시 폴더

`~/projects/dump-scratch` 는 필드명 실측 전용입니다. 끝나면 지우세요.

```bash
rm -rf ~/projects/dump-scratch
```

진짜 검증용 프로젝트 `~/projects/hook-sandbox` 는 생성기(8단계)가 만듭니다.
그래서 실측용 폴더 이름을 `hook-sandbox` 와 다르게 뒀습니다 — 생성기가
`--if-exists fail` 로 거절하지 않게요.
