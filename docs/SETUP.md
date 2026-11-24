# lab.remote 설치

데스크톱(GPU)에서 연구를 진행하고, 어디서든 브라우저로 보고 · 실행하고 · 알림을 받는 개인용 도구예요.
설치는 clone한 뒤 명령 몇 줄이면 끝나요. 설치가 제대로 됐는지는 `labremote doctor`로 확인해요. `✘`가 없으면 정상이에요.

## lab.remote가 바꾸는 것 (전부)

| 무엇 | 언제 | 되돌리기 |
|---|---|---|
| conda 환경 `labremote` | `./install.sh` | `conda env remove -n labremote` |
| 사용자 서비스 `~/.config/systemd/user/labremote-session.service` | `labremote autostart install` | `labremote autostart uninstall` |
| linger (`loginctl enable-linger`) — 비활성화돼 있을 때만 | `labremote autostart install` | uninstall이 원래대로 되돌려요 (code tunnel 서비스가 있으면 유지) |
| 등록한 프로젝트마다 `<프로젝트>/.labremote/` (자체 `.gitignore`로 git에서 제외돼요) | 프로젝트를 등록할 때 | 등록을 해제할 때 삭제 여부를 선택해요 |

`~/.bashrc` · `~/.claude/` · `.condarc` · cron · systemd 타이머 · 프로젝트의 `.gitignore`는 수정하지 않아요.
나머지 상태는 전부 lab.remote 데이터 폴더(기본 `server/data/`)에 있어요.

---

## 1. 필요한 것

| 무엇 | 왜 | 확인 |
|---|---|---|
| Linux + systemd | 실행 · 자동 시작 | `systemctl --user status` |
| Miniconda (또는 conda) | 서버 환경 · 실험 환경 | `conda --version` |
| tmux | 접속이 끊겨도 학습이 계속 실행되도록 | `tmux -V` (`sudo apt install tmux`) |
| **Claude Code — 설치와 로그인까지 완료** | 채팅 · 승인 · 시나리오 | `claude`를 한 번 실행해 로그인 |
| Node.js 20 이상 | 웹 화면 빌드 (한 번) | `npm --version` |
| (원격 접속할 때) VS Code | code tunnel | `code --version` |

lab.remote는 Claude 로그인을 대신하지 않아요. 터미널에서 쓰는 Claude Code를 그대로 불러와 사용해요.
`ANTHROPIC_API_KEY`가 환경 변수에 있으면 구독이 아니라 종량제로 과금될 수 있어요. `labremote doctor`가 이를 알려 줘요.

## 2. 다운로드와 설치

```bash
git clone <이 저장소> ~/lab-remote
cd ~/lab-remote
./install.sh            # 무엇을 돌릴지만 보려면 ./install.sh --dry-run
```

`install.sh`는 conda 환경 `labremote`를 만들고(있으면 그대로), 서버 패키지를 설치하고, 웹 화면을 빌드하고,
`labremote doctor`를 실행해요. 셸 설정은 수정하지 않으므로 명령은 환경 경로로 실행해요.

```bash
~/miniconda3/envs/labremote/bin/labremote doctor
```

(자주 쓰면 `alias labremote=~/miniconda3/envs/labremote/bin/labremote`를 **직접** 셸 설정에 넣어도 돼요.)

## 3. 실행하기

```bash
labremote serve          # http://127.0.0.1:8000 · nice 19 · ionice idle
```

이 데스크톱의 브라우저에서 `http://127.0.0.1:8000`을 열어요. 서버는 `127.0.0.1`에만 열려요.

## 4. 자동 시작

```bash
labremote autostart install     # 무엇이 바뀌는지 먼저 보여 주고 물어봐요
labremote autostart status
labremote autostart uninstall
```

자동 시작을 켜면 `labremote-session` 서비스가 tmux `labremote` 안에서 `labremote serve`를 실행해요.
재부팅하거나 로그아웃해도 계속 실행돼요. 서버 출력은 터미널에서 `/usr/bin/tmux -L labremote attach -t labremote`로 확인해요(나갈 때는 `Ctrl+b d`). 터미널 없이 현재 화면만 보려면 `/usr/bin/tmux -L labremote capture-pane -p -t labremote`를 실행해요.
학습은 이 서비스와 별도로 실행되므로 서비스를 다시 시작해도 중단되지 않아요. System 화면에서도 자동 시작을 끄거나 서버를 다시 시작할 수 있어요.

## 5. 원격 접속 (code tunnel)

터널은 **VS Code가 실행해요.** lab.remote는 상태만 확인해요 (System 화면 · 헤더의 Tunnel 점 · `labremote remote`).

```bash
code tunnel user login --provider github
code tunnel service install --accept-server-license-terms     # 재부팅 뒤에도 켜져 있게
```

1. 휴대폰이나 다른 PC에서 `https://vscode.dev/tunnel/<이름>`을 열고 같은 GitHub 계정으로 로그인해요.
2. Ports 보기에서 **Forward a Port** → `8000`. 기본은 Private이라 같은 계정으로 로그인해야 열려요 (Public으로 바꾸지 마세요).
3. 표시된 **Forwarded Address**를 lab.remote에 등록해요.

   ```bash
   labremote remote set https://<Forwarded Address>
   ```

   (System 화면에서 입력해도 돼요.) 등록하면 서버가 그 주소로 들어오는 요청을 받고,
   Discord 알림에 "답하기" 링크가 추가돼요. 등록하지 않은 주소로 들어온 요청은 서버가 거절해요.

> **보안** — 터널이 열려 있을 때는 그 GitHub 계정만으로 이 데스크톱의 터미널과 파일에 접근할 수 있어요.
> **GitHub 2단계 인증을 꼭 활성화해 주세요.**

> `code tunnel service install`은 사용자 서비스 `~/.config/systemd/user/code-tunnel.service`
> (→ `~/.vscode/cli/code-tunnel.service`)를 만들고 활성화해요 (실측 2026-11-23). 로그아웃한 뒤에도 실행되려면 linger가
> 필요해요. 자동 시작을 켰다면 이미 활성화돼 있어요. 그래서 `labremote autostart uninstall`은 터널 서비스가 있으면
> linger를 비활성화하지 않아요.
>
> VS Code Server 문서의 FAQ에는 "서비스로 호스팅은 라이선스상 허용되지 않는다"는 문장이 있는데 라이선스 원문에는
> 그 문구가 없어요. 서비스로 등록할지는 직접 판단해 주세요. 서비스로 등록하고 싶지 않다면 필요할 때만 터미널에서 `code tunnel`을 실행해도 돼요.
>
> 전달한 포트 주소는 vscode.dev 창을 닫은 뒤에도 계속 열려요 (실측 2026-11-23, 휴대폰). 주소는 `https://<id>-8000.<지역>.devtunnels.ms` 형식이에요.

## 6. 알림 (Discord)

Inbox 화면 › 알림 설정에서 웹훅 주소를 입력해요. 주소는 데이터 폴더에 권한 600으로만 저장되고
화면과 로그에는 가려서 표시돼요. `labremote notify test`로 테스트 알림을 보내 볼 수 있어요.

## 7. 점검

```bash
labremote doctor
```

`✘`는 해결해야 하는 항목, `⚠`는 참고용 경고예요(종료 코드에 영향을 주지 않아요).
터널이나 자동 시작을 쓰지 않는다면 해당 항목이 `⚠`나 비활성으로 나와도 괜찮아요.

## 8. 삭제

```bash
labremote autostart uninstall      # 자동 시작을 켰다면
conda env remove -n labremote
rm -rf ~/lab-remote
# 등록했던 프로젝트의 .labremote/ 는 남아요. 필요하면 프로젝트마다 지워요.
# code tunnel을 켰다면: code tunnel service uninstall · code tunnel user logout
```
