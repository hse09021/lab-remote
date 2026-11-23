-- lab.remote v3 의 `lab.db` 스키마. app/db.py 가 빈 DB 에 이 파일을 통째로 돌린다.
--
-- v1 의 승인·큐·루프·앵커·사용량 표는 v3 에서 빠졌다(docs/v3/PLAN.md 2장).
-- 시각은 전부 ISO8601 문자열(현지 시간대 포함)이다.

CREATE TABLE IF NOT EXISTS schema_meta (
  key   TEXT PRIMARY KEY,
  value TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS projects (
  name       TEXT PRIMARY KEY,
  root       TEXT NOT NULL,
  created_at TEXT NOT NULL
);

-- 학습 지표. NaN·Inf 는 value 를 NULL 로 두고 flag 에 적는다. REAL 에 NaN 을
-- 넣으면 왕복이 깨진다(읽을 때 None 이 되거나 비교가 전부 거짓이 된다).
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

-- 사람이 보는 사건 기록.
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

-- 보낸 알림. dedupe_key 가 UNIQUE 라 같은 알림을 두 번 넣으려 하면 INSERT 가
-- 실패한다. 그게 중복 제거다 (notifier.py).
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
