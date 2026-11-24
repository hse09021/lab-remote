# lab.remote 운영

설치는 [SETUP.md](SETUP.md), 설계 기준은 [v3/PLAN.md](v3/PLAN.md)예요. 이 문서에는 설치한 뒤 운영하면서 볼 내용을 모았어요.
`docs/v1/HANDOFF.md`는 목업 읽는 법과 디자인 토큰 참고용으로만 남아 있어요.

## 어디에 무엇이 있나

| 위치 | 내용 |
|---|---|
| `server/data/` (또는 `LAB_DATA_DIR`) | `projects.json` (등록한 프로젝트) · `lab.db` (Inbox · 예약 · 알림 기록) · `discord.json` (웹훅, 600) · `notify.json` · `ui.json` · `papers.json` · `remote.json` (외부 주소) · `autostart.json` (자동 시작을 켜기 전의 linger 값) · `conda/` (설치 기록 · 삭제 전 백업) · `logs/` |
| `<프로젝트>/.labremote/` | `settings.json` · `runs/EXP-NNN/` (명령 · 로그 · 종료 코드) · `sessions/` (에이전트 세션) · `scenarios/` · `worktrees/` |
| `~/.config/systemd/user/labremote-session.service` | 자동 시작을 켰을 때만 |

vault(Papers 화면에서 지정한 Obsidian 폴더)는 읽기만 해요. 논문을 추가할 때만 `Papers/<이름>.md`와 `Papers/pdf/<이름>.pdf`를 **새로** 만들고, 이미 있는 노트는 덮어쓰지 않아요.

백업은 데이터 폴더 전체를 복사하면 돼요. `lab.db`는 서버를 중지한 뒤 복사하는 게 안전해요.

## 실행 구조

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

- 학습과 터미널은 서버와 별도 서비스라 서버를 다시 시작해도 중단되지 않아요. 재부팅하면 중단되고 "끊김"으로 표시돼요.
- 에이전트 세션은 서버가 종료되면 함께 종료돼요. 서버가 다시 시작되면 세션 목록에서 선택해 이어서 진행해요.
- 예약 시각은 서버가 확인해요. 서버가 실행 중이 아니어서 예약 시각이 10분 넘게 지난 예약은 나중에 실행하지 않고 건너뛰어요.

## 자주 하는 일

| 하려는 것 | 명령 |
|---|---|
| 상태 한눈에 보기 | `labremote doctor` · System 화면 |
| 서버 출력 보기 | `/usr/bin/tmux -L labremote attach -t labremote` (터미널에서 실행 · 나갈 때는 `Ctrl+b d`), 터미널 없이 현재 화면만 보려면 `/usr/bin/tmux -L labremote capture-pane -p -t labremote` |
| 서비스 로그 | `journalctl --user -u labremote-session -n 100` · `server/data/logs/session.log` |
| 서버 다시 시작 | System › "세션 다시 시작" 또는 `systemctl --user restart labremote-session` |
| 업데이트 | `git pull && ./install.sh`를 실행한 뒤 서버 다시 시작 |
| 실행 목록 · 로그 · 중지 | `labremote runs` · `labremote runs log EXP-007` · `labremote runs stop EXP-007` |
| 실행 중인 터미널에 접속 | 화면의 터미널 접속 버튼 또는 `tmux -L labremote-<프로젝트>-EXP-007 attach -r` |
| 터널 · 외부 주소 | `labremote remote` · `labremote remote set https://…` · `labremote remote clear` |
| 알림 테스트 | `labremote notify test` |

## 문제가 생기면

| 증상 | 볼 곳 |
|---|---|
| 외부에서 열면 "이 주소로는 열 수 없어요" | 그 주소를 아직 등록하지 않았어요 — `labremote remote set https://<그 주소>` |
| 로그아웃하면 서버가 종료돼요 | linger가 비활성화돼 있어요 — `labremote autostart install`을 다시 실행하면 활성화돼요 |
| 헤더의 "Tunnel" 점이 회색이에요 | 서버에는 연결되지만 터널이 실행 중이 아니에요 — `code tunnel service install` |
| 헤더가 "서버 끊김" | 서버가 실행 중이 아니에요 — `labremote autostart status` · `journalctl --user -u labremote-session` |
| GPU "조회 불가" | 드라이버가 업데이트된 뒤 아직 재부팅하지 않았을 수 있어요 — `labremote doctor`의 GPU 드라이버 줄 |
| 채팅이 안 열려요 | 터미널에서 `claude`를 실행해 로그인이 유지돼 있는지 확인해요 — `doctor`의 Claude Code 줄 |

## GPU 드라이버 자동 업데이트 막기 (선택)

우분투 자동 업데이트가 드라이버를 업데이트하고 재부팅하지 않으면 커널과 유저랜드의 버전이 어긋나
`nvidia-smi`가 아예 동작하지 않아요(`Failed to initialize NVML`). 그러면 학습이 전부 실패해요.
lab.remote는 시스템 설정을 수정하지 않아요. 막으려면 `/etc/apt/apt.conf.d/52labremote-nvidia`를 직접 만들어 주세요(`sudo` 필요).

```
Unattended-Upgrade::Package-Blacklist {
    "nvidia-";
    "libnvidia-";
    "cuda-";
    "linux-image-";
    "linux-headers-";
    "linux-modules-";
    "linux-objects-nvidia-";
    "linux-signatures-nvidia-";
};
Unattended-Upgrade::Automatic-Reboot "false";
```

확인:

```bash
apt-config dump | grep Package-Blacklist
labremote doctor          # "드라이버 자동 업데이트" 참고 줄이 사라져요
```

`doctor`는 파일 이름이 아니라 `apt-config dump`에서 실제로 적용된 값을 봐요. 드라이버는 직접 업데이트하고, 업데이트한 뒤에는 바로 재부팅해 주세요.

## 보안 규칙 (코드에 고정된 것)

- 서버는 `127.0.0.1`에만 열어요. 다른 주소로 여는 옵션은 없어요.
- `Host`가 `127.0.0.1` · `localhost` · `::1` · 등록한 외부 주소 · `LAB_ALLOWED_HOSTS`가 아니면 거절해요 (DNS rebinding 방지).
- 변경 요청에는 `X-Lab-Remote: 1` 헤더가 있어야 하고 `Origin`도 같은 규칙으로 검사해요. WebSocket(터미널)에도 같은 규칙을 적용해요.
- Discord 웹훅 주소는 데이터 폴더에 권한 600으로만 저장하고, 로그 · 화면 · 에러에는 원문을 출력하지 않아요.
- 에이전트는 `--dangerously-skip-permissions` 같은 모드를 쓰지 않아요. 승인은 화면 · Inbox · Discord 링크 중 먼저 온 답을 따라요.
- AI 자동화는 없어요. 연구 루프 · 실험 큐 · 연쇄 실행이 없고, 예약은 사람이 지정한 시각에만 실행돼요.
- 터널이 열려 있으면 GitHub 계정만으로 이 데스크톱에 접근할 수 있어요. 2단계 인증을 꼭 활성화해 주세요.
