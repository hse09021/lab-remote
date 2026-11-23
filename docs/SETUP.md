# lab.remote 설치

데스크톱(GPU)에서 연구를 돌리고, 어디서든 브라우저로 보고 · 실행하고 · 알림 받는 개인용 도구예요.
설치는 clone 하고 몇 줄이면 끝나요. 끝났는지는 `labremote doctor` 로 확인해요 — `✘` 가 없으면 돼요.

## lab.remote 가 바꾸는 것 (전부)

| 무엇 | 언제 | 되돌리기 |
|---|---|---|
| conda 환경 `labremote` | `./install.sh` | `conda env remove -n labremote` |
| 사용자 서비스 `~/.config/systemd/user/labremote-session.service` | `labremote autostart install` | `labremote autostart uninstall` |
| linger (`loginctl enable-linger`) — 꺼져 있을 때만 | `labremote autostart install` | uninstall 이 원래 값으로 돌려요 |
| 등록한 프로젝트마다 `<프로젝트>/.labremote/` (스스로 git 에서 빠져요) | 프로젝트를 등록할 때 | 등록 해제 때 지울지 골라요 |

`~/.bashrc` · `~/.claude/` · `.condarc` · cron · systemd 타이머 · 프로젝트의 `.gitignore` 는 고치지 않아요.
나머지 상태는 전부 lab.remote 데이터 폴더(기본 `server/data/`)에 있어요.

---

## 1. 먼저 있어야 하는 것

| 무엇 | 왜 | 확인 |
|---|---|---|
| Linux + systemd | 실행 · 자동 시작 | `systemctl --user status` |
| Miniconda (또는 conda) | 서버 환경 · 실험 환경 | `conda --version` |
| tmux | 접속이 끊겨도 학습이 계속 돌게 | `tmux -V` (`sudo apt install tmux`) |
| **Claude Code — 설치하고 로그인까지** | 채팅 · 승인 · 시나리오 | `claude` 를 한 번 열어 로그인 |
| Node.js 20 이상 | 웹 화면 빌드 (한 번) | `npm --version` |
| (밖에서 쓸 때) VS Code | code tunnel | `code --version` |

lab.remote 는 Claude 로그인을 대신하지 않아요. 터미널에서 쓰는 그 Claude Code 를 그대로 불러요.
`ANTHROPIC_API_KEY` 가 환경에 있으면 구독이 아니라 종량제로 과금될 수 있어요 — `doctor` 가 알려 줘요.

## 2. 받고 설치하기

```bash
git clone <이 저장소> ~/lab-remote
cd ~/lab-remote
./install.sh            # 무엇을 돌릴지만 보려면 ./install.sh --dry-run
```

`install.sh` 는 conda 환경 `labremote` 를 만들고(있으면 그대로), 서버 패키지를 설치하고, 웹 화면을 빌드하고,
`labremote doctor` 를 돌려요. 셸 설정은 고치지 않으니 명령은 환경 경로로 불러요.

```bash
~/miniconda3/envs/labremote/bin/labremote doctor
```

(자주 쓰면 `alias labremote=~/miniconda3/envs/labremote/bin/labremote` 를 **직접** 셸 설정에 넣어도 돼요.)

## 3. 띄우기

```bash
labremote serve          # http://127.0.0.1:8000 · nice 19 · ionice idle
```

이 데스크톱 브라우저에서 `http://127.0.0.1:8000` 을 열어요. 서버는 `127.0.0.1` 에만 열려요.

## 4. 켜 두기 (자동 시작)

```bash
labremote autostart install     # 무엇이 바뀌는지 먼저 보여 주고 물어봐요
labremote autostart status
labremote autostart uninstall
```

켜면 `labremote-session` 서비스가 tmux `labremote` 안에서 `labremote serve` 를 띄워요.
재부팅하거나 로그아웃해도 떠 있어요. 서버 출력은 `tmux -L labremote attach -t labremote` (나올 때 `Ctrl+b d`).
학습 실행은 이 서비스와 따로 돌아서 서비스를 다시 켜도 살아요. 끄기와 다시 켜기는 System 화면에서도 돼요.

## 5. 밖에서 접속 (code tunnel)

터널은 **VS Code 가 띄워요.** lab.remote 는 상태만 읽어요 (System 화면 · 헤더의 Tunnel 점 · `labremote remote`).

```bash
code tunnel user login --provider github
code tunnel service install --accept-server-license-terms     # 재부팅 뒤에도 켜져 있게
```

1. 휴대폰 · 다른 PC 에서 `https://vscode.dev/tunnel/<이름>` 을 열고 같은 GitHub 계정으로 로그인해요.
2. Ports 보기에서 **Forward a Port** → `8000`. 기본은 Private 이라 같은 계정으로 로그인해야 열려요 (Public 으로 바꾸지 마세요).
3. 나온 **Forwarded Address** 를 lab.remote 에 알려 줘요.

   ```bash
   labremote remote set https://<Forwarded Address>
   ```

   (System 화면의 "밖에서 접속" 칸에 적어도 돼요.) 적으면 서버가 그 주소로 오는 요청을 받고,
   Discord 알림에 "답하기" 링크가 붙어요. 적지 않은 주소로 오면 서버가 거절해요.

> **보안** — 터널이 열려 있으면 그 GitHub 계정만 있으면 이 데스크톱의 터미널과 파일에 들어올 수 있어요.
> **GitHub 2단계 인증을 켜 두세요.**

> [확인 필요] `code tunnel service install` 이 Linux 에서 무엇을 만드는지(사용자 서비스인지, linger 가 필요한지)는
> VS Code 문서에 없어요. 미리 보기(Preview) 기능이에요. 또 VS Code Server 문서의 FAQ 에는 "서비스로 호스팅은
> 라이선스상 허용되지 않는다" 는 문장이 있는데 라이선스 원문에는 그 문구가 없어요 — 판단은 사람이 해요.
> 서비스로 두기 싫으면 쓸 때만 터미널에서 `code tunnel` 을 띄워도 돼요(재부팅하면 다시 띄워야 해요).
> 전달한 주소가 계속 유지되는지(클라이언트를 닫은 뒤에도)도 아직 실측하지 않았어요.

## 6. 알림 (Discord)

Inbox 화면 › 알림 설정에서 웹훅 주소를 넣어요. 주소는 데이터 폴더에 권한 600 으로만 저장되고
화면 · 로그에는 가려서 보여요. `labremote notify test` 로 시험해요.

## 7. 점검

```bash
labremote doctor
```

`✘` 는 고쳐야 하는 것, `⚠` 는 알려 주기만 하는 것(종료코드를 바꾸지 않아요)이에요.
터널 · 자동 시작은 쓰지 않으면 `⚠` 나 "꺼져 있어요" 로 나와도 괜찮아요.

## 8. 지우기

```bash
labremote autostart uninstall      # 자동 시작을 켰다면
conda env remove -n labremote
rm -rf ~/lab-remote
# 등록했던 프로젝트의 .labremote/ 는 남아요. 필요하면 프로젝트마다 지워요.
# code tunnel 을 켰다면: code tunnel service uninstall · code tunnel user logout
```
