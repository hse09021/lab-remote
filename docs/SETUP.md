# lab.remote 설치와 설정

이 문서는 **사람이 직접 해야 하는 것**만 모았습니다. 코드가 할 수 있는 건
코드가 합니다 — 여기 있는 건 사용자 설정, `sudo`, 재부팅처럼 시스템이 손대면
안 되는 것들입니다.

> 왜 코드가 안 하나: 실측 중에 제가 실제 `~/.claude/settings.json` 을 고쳐서
> 이 PC 의 모든 Claude 세션이 갇힌 적이 있습니다. 그 뒤로 **사람의 설정
> 파일은 코드가 쓰지 않습니다** (`docs/operations.md` 의 "규칙 0").

끝났는지 확인하는 방법은 하나입니다.

```bash
labremote doctor
```

`✘` 가 없으면 됩니다. `⚠` 는 권고라 종료코드를 바꾸지 않습니다 — 그래도
아래를 다 하면 `⚠` 도 사라집니다.

---

## 1. 훅 설치

```bash
cd ~/Desktop/lab-remote/server
labremote hooks install --mode enforce
```

이게 `~/.claude/settings.json` 에 **훅 등록만** 씁니다. 샌드박스 설정은 거기
쓰지 않습니다 — 그러면 개발 세션까지 갇힙니다. 샌드박스는 런처가
`server/data/agent/headless-settings.json` 으로 넘깁니다.

확인: `labremote doctor` 의 `훅 등록`·`래퍼 파일`·`Bash 샌드박스` 가 ✔.

---

## 2. 실험 프로젝트마다 **별도 conda 환경**

> 🔑 **가장 중요한 항목입니다.** 실험용 환경을 `labremote`(우리 코드가 도는
> 환경)나 `base` 로 두면 **지금까지의 모든 방어가 우회됩니다.**

`.pth` 파일은 **인터프리터가 뜰 때 실행됩니다.** `site-packages` 에
`import os; os.system(...)` 한 줄이 든 `.pth` 가 있으면, 그 환경의 파이썬이
뜨는 순간 돕니다 — `import` 를 안 해도 됩니다.

훅은 래퍼에 박힌 파이썬으로 **도구 호출마다** 뜨고, 오케스트레이터도 같은
환경에서 돕니다. 둘 다 샌드박스 **밖, 사용자 권한**입니다. 그래서 실험용
환경이 `labremote` 면 **사람이 승인한 패키지 하나가** 잠금 판정 코드 안의
임의 코드 실행이 됩니다.

```bash
# 프로젝트마다 하나씩. 이름은 프로젝트 이름과 같게 두면 헷갈리지 않아요.
conda create -n hook-sandbox python=3.11 -y

# 학습에 필요한 것은 여기에만 깔아요
conda run -n hook-sandbox python -m pip install torch
```

`specifications/Config.yaml` 의 `env.conda` 가 그 이름이어야 합니다. 생성기가
기본으로 **프로젝트 이름**을 넣고, `labremote`·`base` 같은 이름은
**거절합니다**.

확인: `labremote doctor` 의 `실험 conda 환경 · <이름>` 이 ✔.

> 패키지를 **Claude 에게 깔라고 시키지 마세요.** Claude 의 Bash 에서는
> `pip install` 이 **조용히 실패합니다**(conda 환경이 프로젝트 폴더 밖이라
> 샌드박스가 쓰기를 버립니다). Claude 가 `state/Install_request.json` 에
> 요청을 남기면 `labremote installs approve` 로 승인하고, 설치는
> 오케스트레이터가 합니다.

---

## 3. 맨손 `claude` 를 멈춰 세우기 (셸 함수)

실험 프로젝트는 **`labremote claude <프로젝트>` 로 열어야 합니다.** 맨손
`claude` 로 열면 프로젝트 `.claude/settings.json` 을 읽는데, 그 파일은 AI 가
쓴 코드가 고칠 수 있습니다(샌드박스는 작업 폴더 쓰기를 못 막습니다). 거기
훅이나 `sandbox.enabled: false` 가 끼면 **울타리가 사라진 상태로 열립니다.**

`CLAUDE.md`·`README`·`doctor` 가 안내하지만 습관은 안내보다 셉니다. 아래를
**`~/.bashrc` 맨 아래에** 붙여 주세요 (zsh 를 쓰면 `~/.zshrc` 에도).

```bash
# ── lab.remote ────────────────────────────────────────────────────────────
# 실험 프로젝트 폴더에서 맨손 `claude` 를 치면 멈춰 세워요.
# 그 폴더의 .claude/settings.json 은 AI 가 쓴 코드가 고칠 수 있어서,
# 맨손으로 열면 권한 울타리가 사라진 상태로 열릴 수 있어요.
labremote_projects_root="${LAB_PROJECTS_DIR:-$HOME/projects}"

claude() {
  local here root name
  here="$(pwd -P)"
  root="$(cd "$labremote_projects_root" 2>/dev/null && pwd -P)" || root=""
  if [ -n "$root" ] && [ "${here#"$root"/}" != "$here" ]; then
    name="${here#"$root"/}"
    name="${name%%/*}"
    printf '%s\n' \
      "⚠ 실험 프로젝트 폴더예요: $name" \
      "   맨손 claude 로 열면 프로젝트 .claude/settings.json 을 읽어요." \
      "   그 파일은 AI 가 쓴 코드가 고칠 수 있어서 울타리가 사라질 수 있어요." \
      "" \
      "   이렇게 열어 주세요:" \
      "     labremote claude $name" \
      "" \
      "   그래도 맨손으로 열려면:  command claude ..."
    return 1
  fi
  command claude "$@"
}
# ──────────────────────────────────────────────────────────────────────────
```

붙인 뒤 `source ~/.bashrc` 하거나 터미널을 새로 열어 주세요.

- **`command claude` 로 빠져나갈 수 있습니다.** 막는 장치가 아니라 **멈춰
  세우는 장치**입니다. 사람이 자기 셸에 넣는 것이니 그게 맞습니다.
- 프로젝트 **밖**에서는 아무 영향이 없습니다.
- `doctor` 가 `~/.bashrc`·`~/.zshrc`·`~/.bash_aliases`·`~/.profile` 에서
  `labremote claude` 라는 글자를 찾아 ✔/⚠ 를 보여 줍니다. **읽기만 합니다** —
  코드가 셸 설정을 고치지 않습니다.

---

## 4. Claude Code 자동 업데이트 끄기 (권합니다)

2.1.317 → 2.1.318 이 **저절로** 바뀌었고, 그 판에서 서브에이전트 도구 이름이
`Task` → `Agent` 로 달라져 **"서브에이전트는 꺼 뒀다" 는 설정이 무효가
됐습니다.** 조용한 실패였습니다.

오케스트레이터가 띄우는 `claude` 는 **이미 끕니다**(`DISABLE_AUTOUPDATER=1`).
하지만 사람이 자기 터미널에서 `claude` 를 쓰면 그쪽이 바이너리를 갈아
버립니다. 같이 끄려면 `~/.bashrc` 에:

```bash
export DISABLE_AUTOUPDATER=1
```

> 설정 파일(`~/.claude.json`)의 `autoUpdates: false` 는 **native 설치에서
> 무시될 수 있습니다**(번들의 판정 코드를 읽어 확인했습니다). 환경 변수가
> 유일하게 믿을 만한 길입니다.

올릴 때는 **일부러** 올리고, 올린 뒤 도구 목록을 다시 재세요.

```bash
claude update                        # 사람이 직접
labremote tools --probe hook-sandbox # 도구 목록 다시 재고 기록
```

재기 전까지 **헤드리스 루프는 멈춥니다**(`labremote doctor` 가 ⚠ 로 알려
줍니다). 대화형(`labremote claude`)은 막지 않습니다.

## 5. 웹훅 (Discord 알림)

```bash
mkdir -p ~/.config/labremote
cat > ~/.config/labremote/config.toml <<'EOF'
[discord]
webhook = "https://discord.com/api/webhooks/…"
EOF
chmod 600 ~/.config/labremote/config.toml
```

`~/.config/labremote/**` 는 이미 훅의 `SECRET_FILES` 라 Claude 가 **읽기까지
막힙니다.** 웹훅 주소와 허가 서명 키를 둘 자리로 맞춤입니다.

---

## 6. [미작성 — 7·8단계에서 채웁니다]

- `loginctl enable-linger` 와 systemd 사용자 서비스 (8단계)
- GPU 드라이버 불일치 해결 (재부팅) 과 nvidia 자동 업데이트 제외
- 승인 대기열 CLI (`labremote approvals`) 사용법 (7단계)

---

## git 기록이 위조됐을 때 되살리기

`.git` 은 프로젝트 안이라 AI 가 쓴 코드가 **기록 자체**(refs·objects)를 바꿀
수 있습니다. 앵커가 그걸 잡아 루프를 `blocked` 로 멈추고 알립니다. 되살리는
것은 **사람이** 합니다 — 무엇이 진짜 기록인지 코드는 알 수 없습니다.

```bash
# 1. 어떤 백업이 있나. ✔ 는 깊은 검증(clone)까지 통과한 것이에요.
labremote git-backups hook-sandbox

# 2. 먼저 다른 곳에 되살려서 눈으로 확인해요
git clone ~/Desktop/lab-remote/server/data/backups/hook-sandbox/<시각>.bundle \
          /tmp/recovered
cd /tmp/recovered && git log --oneline --all | head -30

# 3. 맞으면 지금 저장소로 가져와요 (덮어쓰지 않고 `백업/` 이름으로)
cd ~/projects/hook-sandbox
git fetch ~/Desktop/lab-remote/server/data/backups/hook-sandbox/<시각>.bundle \
          'refs/heads/*:refs/heads/백업/*'

# 4. 비교한 뒤 사람이 결정해요
git diff 백업/main main
git switch main && git reset --hard 백업/main   # 되돌리기로 정했으면

# 5. 루프를 다시 열어 줘요
labremote run-state hook-sandbox --idle
```

백업은 기록 커밋마다 자동으로 뜨고 새것 10개만 남습니다.
`server/data/backups/` 아래라 AI 가 쓴 코드가 **지울 수도 고칠 수도 없습니다.**

---

## 프로젝트 설정이 바뀌어 있다고 나올 때

```
⚠ 프로젝트 설정이 정본과 달라요:
  · .claude/settings.json · sandbox.enabled 가 꺼져 있어요
```

`labremote claude <프로젝트>` 가 멈춰 세웁니다. 무엇이 바뀌었는지 먼저
보세요 — AI 가 쓴 코드가 울타리를 고치려 한 흔적일 수 있습니다.

```bash
cat ~/projects/<프로젝트>/.claude/settings.json      # 무엇이 들어갔나
labremote claude <프로젝트> --force                   # 되돌리고 열기
ls ~/Desktop/lab-remote/server/data/tamper/<프로젝트>/ # 되돌린 원본(증거)
```
