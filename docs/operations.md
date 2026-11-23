# lab.remote 운영

설치는 [SETUP.md](SETUP.md), 설계 기준은 [v3/PLAN.md](v3/PLAN.md)예요. 이 문서는 켜 둔 뒤에 볼 것들이에요.
`docs/v1/`은 v1 보관용이에요.

## 어디에 무엇이 있나

| 위치 | 내용 |
|---|---|
| `server/data/` (또는 `LAB_DATA_DIR`) | `projects.json` (등록한 프로젝트) · `lab.db` (Inbox · 예약 · 알림 기록) · `discord.json` (웹훅, 600) · `notify.json` · `ui.json` · `papers.json` · `remote.json` (바깥 주소) · `autostart.json` (켜기 전 linger) · `conda/` (설치 기록 · 삭제 전 백업) · `logs/` |
| `<프로젝트>/.labremote/` | `settings.json` · `runs/EXP-NNN/` (명령 · 로그 · 종료코드) · `sessions/` (에이전트 세션) · `scenarios/` · `worktrees/` |
| `~/.config/systemd/user/labremote-session.service` | 자동 시작을 켰을 때만 |

vault(Papers 화면에서 정한 Obsidian 폴더)는 읽기만 해요. 논문을 추가할 때만 `Papers/<이름>.md`와 `Papers/pdf/<이름>.pdf`를 **새로** 만들고, 있는 노트는 덮지 않아요.

데이터 폴더를 통째로 복사하면 백업이에요. `lab.db`는 서버를 끈 뒤 복사하는 게 안전해요.

## 무엇이 어떻게 떠 있나

```
labremote-session.service (자동 시작을 켰을 때)
  └ tmux -L labremote "labremote"
      └ labremote serve   127.0.0.1:8000 · nice 19 · ionice idle
          ├ 예약 시계 (15초마다) · 실행 감시
          └ 에이전트 세션 (claude-agent-sdk → 사용자가 로그인한 claude)
학습 실행   systemd-run --user의 transient 서비스 + tmux (-L labremote-<프로젝트>-<EXP>) · nice 0
웹 터미널   systemd-run --user의 transient 서비스 + tmux (-L labremote-term-<프로젝트>)
code tunnel VS Code가 따로 (code tunnel service install)
```

- 학습과 터미널은 서버와 다른 서비스라 서버를 다시 켜도 살아요. 재부팅하면 끊기고, 다음에 "끊김"으로 보여요.
- 에이전트 세션은 서버와 같이 끝나요. 다시 뜨면 세션 목록에서 골라 이어 가요.
- 예약은 서버가 시간을 재요. 서버가 꺼져 있던 동안의 예약은 10분이 지나면 건너뛰어요.

## 자주 하는 일

| 하려는 것 | 명령 |
|---|---|
| 상태 한눈에 | `labremote doctor` · System 화면 |
| 서버 출력 보기 | `/usr/bin/tmux -L labremote attach -t labremote` (터미널 창에서 · 나올 때 `Ctrl+b d`), 터미널 없이 지금 화면만 보려면 `/usr/bin/tmux -L labremote capture-pane -p -t labremote` |
| 서비스 로그 | `journalctl --user -u labremote-session -n 100` · `server/data/logs/session.log` |
| 서버 다시 켜기 | System › "세션 다시 켜기" 또는 `systemctl --user restart labremote-session` |
| 업데이트 | `git pull && ./install.sh` 뒤에 다시 켜기 |
| 실행 목록 · 로그 · 멈추기 | `labremote runs` · `labremote runs log EXP-007` · `labremote runs stop EXP-007` |
| 실행 터미널에 붙기 | 화면의 "붙기" 또는 `tmux -L labremote-<프로젝트>-EXP-007 attach -r` |
| 터널 · 바깥 주소 | `labremote remote` · `labremote remote set https://…` · `labremote remote clear` |
| 알림 시험 | `labremote notify test` |

## 문제가 생기면

| 증상 | 볼 곳 |
|---|---|
| 밖에서 열면 "이 주소로는 열 수 없어요" | 그 주소를 아직 안 적었어요 — `labremote remote set https://<그 주소>` |
| 로그아웃하면 서버가 내려가요 | linger 꺼짐 — `labremote autostart install`을 다시 (꺼져 있으면 켜요) |
| 헤더 점이 회색 "Tunnel" | 서버는 닿는데 터널이 꺼져 있어요 — `code tunnel service install` |
| 헤더가 "서버 끊김" | 서버가 안 떠 있어요 — `labremote autostart status` · `journalctl --user -u labremote-session` |
| GPU "조회 불가" | 드라이버가 올라가고 재부팅 전일 수 있어요 — `labremote doctor`의 GPU 드라이버 줄 |
| 채팅이 안 열려요 | `claude`를 터미널에서 열어 로그인이 살아 있는지 — `doctor`의 Claude Code 줄 |

## 보안 규칙 (코드에 박혀 있는 것)

- 서버는 `127.0.0.1`에만 열어요. 다른 주소로 여는 옵션은 없어요.
- `Host`가 `127.0.0.1` · `localhost` · `::1` · 적어 둔 바깥 주소 · `LAB_ALLOWED_HOSTS`가 아니면 거절해요 (DNS rebinding 막기).
- 바꾸는 요청에는 `X-Lab-Remote: 1` 헤더가 있어야 하고 `Origin`도 같은 규칙으로 봐요. WebSocket(터미널)도 같아요.
- Discord 웹훅 주소는 데이터 폴더에 600으로만, 로그 · 화면 · 에러에 원문을 찍지 않아요.
- 에이전트는 `--dangerously-skip-permissions` 같은 모드를 쓰지 않아요. 승인은 화면 · Inbox · Discord 링크 중 먼저 온 답이에요.
- AI 자동화 없음: 연구 루프 · 실험 큐 · 연쇄 실행이 없어요. 예약은 사람이 건 시각에만 돌아요.
- 터널이 열려 있으면 GitHub 계정이 곧 이 데스크톱 열쇠예요 — 2단계 인증을 켜 두세요.
