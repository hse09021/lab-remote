-- lab.remote ②의 단일 출처. app/db.py 가 판 1 로 이 파일을 통째로 돌린다.
--
-- 훅은 이 DB 를 **읽지 않는다.** 훅은 runstate JSON 미러만 본다
-- (tests/test_stdlib_only.py 가 훅 경로의 sqlite3 import 를 막는다).
-- 시각은 전부 ISO8601 문자열(현지 시간대 포함)이다 — 사람이 읽을 로그와
-- 같은 모양이어야 대조가 쉽다.

CREATE TABLE IF NOT EXISTS schema_meta (
  key   TEXT PRIMARY KEY,
  value TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS projects (
  name       TEXT PRIMARY KEY,
  root       TEXT NOT NULL,
  created_at TEXT NOT NULL
);

-- 프로젝트별 루프 상태. state 는 아래 값만 쓴다.
--   idle planning running reviewing waiting_approval
--   usage_limited paused blocked stopped done
CREATE TABLE IF NOT EXISTS loop_state (
  project       TEXT PRIMARY KEY,
  state         TEXT NOT NULL DEFAULT 'idle',
  paused        INTEGER NOT NULL DEFAULT 0,
  paused_reason TEXT,
  paused_until  TEXT,
  loop_no       INTEGER NOT NULL DEFAULT 0,
  current_job_id INTEGER,
  stop_reason   TEXT,
  updated_at    TEXT NOT NULL
);

-- 작업 큐.
--   kind  : plan | train | review | resume | journal_fix
--   state : queued | leased | running | done | failed | timeout
--           | cancelled | blocked | waiting_approval
--
-- running_slot 이 GPU 1개 순차 실행을 **DB 로** 보장한다. running 일 때만 0 이고
-- 그 밖에는 NULL 이다. SQLite 는 UNIQUE 인덱스에서 NULL 중복을 허용하므로
-- "running 은 전역 1건" 이 된다. 워커가 둘 떠도 두 번째 UPDATE 가 실패한다.
CREATE TABLE IF NOT EXISTS jobs (
  id            INTEGER PRIMARY KEY AUTOINCREMENT,
  project       TEXT NOT NULL,
  kind          TEXT NOT NULL,
  experiment_id TEXT,
  parent_job_id INTEGER,
  priority      INTEGER NOT NULL DEFAULT 0,
  state         TEXT NOT NULL DEFAULT 'queued',
  running_slot  INTEGER,
  attempt       INTEGER NOT NULL DEFAULT 0,
  max_attempts  INTEGER NOT NULL DEFAULT 3,
  payload       TEXT,
  pid           INTEGER,
  pgid          INTEGER,
  log_path      TEXT,
  session_id    TEXT,
  model_used    TEXT,
  timeout_sec   INTEGER,
  exit_code     INTEGER,
  error         TEXT,
  queued_at     TEXT NOT NULL,
  started_at    TEXT,
  ended_at      TEXT,
  heartbeat_at  TEXT
);

CREATE UNIQUE INDEX IF NOT EXISTS ux_jobs_running ON jobs(running_slot);
CREATE INDEX IF NOT EXISTS ix_jobs_queue ON jobs(project, state, priority, id);

CREATE TABLE IF NOT EXISTS experiments (
  project      TEXT NOT NULL,
  exp_id       TEXT NOT NULL,
  parent       TEXT,
  knob         TEXT,
  state        TEXT NOT NULL DEFAULT 'planned',
  progress     INTEGER NOT NULL DEFAULT 0,
  metric_name  TEXT,
  metric_value REAL,
  best_metric  REAL,
  branch       TEXT,
  commit_sha   TEXT,
  report       TEXT,
  gpu_sec      INTEGER NOT NULL DEFAULT 0,
  started_at   TEXT,
  ended_at     TEXT,
  updated_at   TEXT NOT NULL,
  PRIMARY KEY (project, exp_id)
);

-- NaN·Inf 는 value 를 NULL 로 두고 flag 에 적는다. REAL 에 NaN 을 넣으면
-- 왕복이 깨진다(읽을 때 None 이 되거나 비교가 전부 거짓이 된다).
CREATE TABLE IF NOT EXISTS metrics (
  id      INTEGER PRIMARY KEY AUTOINCREMENT,
  project TEXT NOT NULL,
  exp_id  TEXT NOT NULL,
  step    INTEGER,
  epoch   INTEGER,
  name    TEXT NOT NULL,
  value   REAL,
  flag    TEXT,
  at      TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS ix_metrics_exp ON metrics(project, exp_id, name, id);

CREATE TABLE IF NOT EXISTS resources (
  id              INTEGER PRIMARY KEY AUTOINCREMENT,
  at              TEXT NOT NULL,
  gpu_available   INTEGER NOT NULL DEFAULT 0,
  gpu_util        REAL,
  gpu_mem_used_mb INTEGER,
  gpu_temp_c      REAL,
  cpu_pct         REAL,
  ram_pct         REAL,
  disk_free_gb    REAL,
  note            TEXT
);

-- web/src/api/types.ts 의 EventEntry 와 같은 모양으로 내보낸다.
CREATE TABLE IF NOT EXISTS events (
  id      INTEGER PRIMARY KEY AUTOINCREMENT,
  project TEXT NOT NULL,
  at      TEXT NOT NULL,
  kind    TEXT NOT NULL,
  tone    TEXT,
  text    TEXT NOT NULL,
  ref     TEXT
);

CREATE INDEX IF NOT EXISTS ix_events_project ON events(project, id);

-- 훅이 data/requests/ 에 남긴 승인 요청의 거울. 결정과 1회용 허가를 묶는다.
CREATE TABLE IF NOT EXISTS approvals (
  id          INTEGER PRIMARY KEY AUTOINCREMENT,
  project     TEXT NOT NULL,
  request_id  TEXT NOT NULL,
  job_id      INTEGER,
  session_id  TEXT,
  tool        TEXT,
  action_key  TEXT,
  rel         TEXT,
  request     TEXT,
  reason      TEXT,
  fingerprint TEXT,
  loose_key   TEXT,
  state       TEXT NOT NULL DEFAULT 'open',
  grant_id    TEXT,
  opened_at   TEXT NOT NULL,
  decided_at  TEXT,
  decided_by  TEXT,
  attempts    INTEGER NOT NULL DEFAULT 0,
  -- 승인 내용의 출처 (원칙 (나)). 'denials' 는 오케스트레이터가 자기 자식의
  -- 결과 JSON(permission_denials)에서 만든 것, 'hook' 은 훅의 요청 파일에서
  -- 거울한 것(참고용)이다.
  source      TEXT NOT NULL DEFAULT 'hook',
  -- **본문 없는** 입력 요약 (길이·해시). 비밀이 섞일 수 있어 원본
  -- tool_input 은 DB 에 넣지 않는다.
  tool_summary TEXT,
  UNIQUE (project, request_id)
);

-- dedupe_key 가 UNIQUE 라 같은 알림을 두 번 넣으려 하면 INSERT 가 실패한다.
-- 그게 중복 제거다 (notifier.py).
CREATE TABLE IF NOT EXISTS notifications (
  id          INTEGER PRIMARY KEY AUTOINCREMENT,
  dedupe_key  TEXT NOT NULL UNIQUE,
  project     TEXT,
  kind        TEXT NOT NULL,
  route       TEXT,
  title       TEXT,
  body        TEXT,
  state       TEXT NOT NULL DEFAULT 'pending',
  attempt     INTEGER NOT NULL DEFAULT 0,
  first_at    TEXT NOT NULL,
  last_at     TEXT,
  http_status INTEGER,
  error       TEXT
);

-- ③(웹)이 ②에게 보내는 명령. ②에 HTTP 를 넣지 않고 이 표로 받는다.
--   kind: stop_experiment | pause_loop | resume_loop | cancel_job | ...
CREATE TABLE IF NOT EXISTS commands (
  id         INTEGER PRIMARY KEY AUTOINCREMENT,
  project    TEXT,
  kind       TEXT NOT NULL,
  payload    TEXT,
  state      TEXT NOT NULL DEFAULT 'pending',
  created_at TEXT NOT NULL,
  done_at    TEXT,
  result     TEXT
);

CREATE INDEX IF NOT EXISTS ix_commands_pending ON commands(state, id);

-- 한도로 보이는 실패의 원문을 그대로 보관한다. 패턴을 코드에 박지 않고
-- 나중에 실제 문구가 모이면 ~/.config/labremote/usage_patterns.json 에 적는다.
CREATE TABLE IF NOT EXISTS usage_limits (
  id          INTEGER PRIMARY KEY AUTOINCREMENT,
  project     TEXT,
  at          TEXT NOT NULL,
  detected_by TEXT,
  exit_code   INTEGER,
  raw         TEXT,
  resume_at   TEXT,
  resumed_at  TEXT,
  notified_at TEXT
);

-- 📌 앵커 — **AI 가 못 쓰는 곳에 둔 기준값.**
--
-- 프로젝트 안의 기록은 샌드박스에서 쓰기 가능하다(M4). `.git` 의 refs·objects
-- 도 마찬가지라 브랜치를 지우거나 이전 커밋을 바꿔치기해서 실험 기록을 위조할
-- 수 있다. 그래서 오케스트레이터가 **자기가 한 일**의 기준값을 여기 적고,
-- 다음에 대조한다. 어긋나면 루프를 멈추고 사람을 부른다.
--
-- kind 로 여러 종류를 담는다:
--   git_head        key=브랜치 이름, value=커밋 해시 (T5)
--   approval_log    key='csv',       value=마지막 해시 체인 값, count=줄 수 (S7)
CREATE TABLE IF NOT EXISTS anchors (
  project    TEXT NOT NULL,
  kind       TEXT NOT NULL,
  key        TEXT NOT NULL DEFAULT '',
  value      TEXT NOT NULL,
  count      INTEGER,
  note       TEXT,
  at         TEXT NOT NULL,
  PRIMARY KEY (project, kind, key)
);
