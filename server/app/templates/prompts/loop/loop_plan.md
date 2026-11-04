# 루프 $loop_no 회차 · 설계 (A)

지금은 **설계만** 해요. 실험은 시스템이 돌려요.

## 먼저 읽어 주세요

`state/Current.yaml` — 지금 어느 실험이 도는지, 무엇이 왜 잠겨 있는지가 여기
있어요. 시스템이 쓰는 파일이라 당신은 못 고쳐요.

그다음 `CLAUDE.md` 의 "기준 문서 참조 순서" 대로 읽어 주세요.

## 이번에 할 일

1. 현재 상태를 확인해요 (`state/State.yaml`).
2. 실험 조건을 검증해요 — 조작변인은 **하나**, 통제변인은 그대로.
3. 새 실험 폴더 `experiments/$next_exp/` 를 만들어요.
4. `experiments/$next_exp/config.yaml` 에 하이퍼파라미터를 적어요.
5. `experiments/$next_exp/run.json` 에 **실행 명세**를 적어요.

## run.json 규약

```json
{
  "entrypoint": "<specifications/Config.yaml 의 run.entrypoints 에 있는 것>",
  "args": ["--epochs", "50", "--lr", "1e-4"],
  "timeout_sec": 21600
}
```

- `entrypoint` 는 `Config.yaml` 의 목록에 **있는 것만** 돼요.
- `args` 는 **문자열 배열**이에요. 한 문자열로 적으면 거절돼요.
- `command` 같은 자유 문자열은 받지 않아요.
- 환경 변수는 `Config.yaml` 의 `run.envAllow` 에 이름이 있는 것만요.
  캐시 변수(`HF_HOME`·`TMPDIR` …)는 시스템이 정해요.

## 하지 않을 것

- **학습을 직접 돌리지 마세요.** `run.json` 만 쓰면 시스템이 돌려요.
- **패키지를 직접 설치하지 마세요.** `pip install` 은 제 Bash 에서 **조용히
  실패해요** — conda 환경이 프로젝트 폴더 밖이라 샌드박스가 쓰기를 버려서,
  성공한 것처럼 보이고 실제로는 안 깔려요. 필요하면
  `state/Install_request.json` 에 **이름과 버전만** 적어 주세요.

  ```json
  {"version": 1,
   "packages": [{"name": "peft", "spec": "==0.13.2"}],
   "reason": "왜 필요한지 한 줄"}
  ```

  사람이 승인하면 시스템이 설치하고 결과를 `state/Install_result.json` 에
  적어 줘요. URL·경로·`-e`·설치 옵션은 받지 않아요.
- 이전 실험 폴더를 고치지 마세요.
- `specifications/Config.yaml` 과 `docs/Evaluation.md` 는 실험이 도는 중에
  잠겨 있어요.

막히면 **우회하지 말고 멈추고 보고해 주세요.**

## 이번 루프의 맥락

$context
