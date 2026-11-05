# 루프 $loop_no 회차 · 분석 (C)

`$exp_id` 가 끝났어요. 결과를 보고 기록을 남겨 주세요.

- 종료 상태: $exit_state (종료코드 $exit_code)
- 원본 출력: `experiments/$exp_id/output/`
- 걸린 시간: $elapsed

## 기록 순서 (PDF 9쪽 Update Order)

이 순서를 지켜 주세요. 앞 단계가 비어 있으면 뒤를 쓰지 마세요.

1. 원본 출력 (이미 있어요 — 고치지 마세요)
2. `experiments/$exp_id/result.csv`
3. `experiments/$exp_id/analysis.md`
4. `logs/Experiment_log.csv`
5. `logs/Decision_log.md`
6. `logs/Failures.md` (실패했을 때만)
7. `state/State.yaml`

`result.csv` 의 열은 `templates/result_example.csv` 와 같아야 해요:
`step,split,metric,value`.

## 학습이 실패했으면 (종료 상태가 `done` 이 아니면)

- **`result.csv` 를 만들지 마세요.** 학습이 쓰는 파일이에요. 안 나왔으면
  없는 게 맞아요 — 지어낸 값보다 빈 자리가 나아요.
- 대신 **`analysis.md` 와 `logs/Failures.md` 를 꼭 써 주세요.** 증상·원인·
  해결을 적어 주세요. `output/train.log` 와 `output/exit_code` 가 근거예요.
- 성공 기준 충족 여부는 `판정 불가` 라고 적어 주세요.

## 평가

`docs/Evaluation.md` 의 지표와 성공 기준을 그대로 따라 주세요.
**결과를 확인한 뒤에 기준을 바꾸지 않아요.**

## 끝으로 Final Report

마지막에 아래 모양 그대로 적어 주세요. 시스템이 이걸 읽어요.

```
## Final Report
- 실험 ID: $exp_id
- 검증한 가설:
- 변경한 조작변인:
- 실행 상태:
- 주요 결과:
- 성공 기준 충족 여부:
- 생성·수정한 파일:
- 다음 행동:
- 사람의 검토 필요 여부:
```

실행하지 않은 결과를 **지어내거나 추정하지 마세요.**

$context
