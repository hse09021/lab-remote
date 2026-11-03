# 종료 조건 프롬프트

`specifications/Config.yaml` 과 `docs/Stop_and_recovery.md` 를 채울 때 써요.

---

연구 목표: {goal}
쓸 수 있는 자원: {resources}

다음을 정해 주세요.

- 목표 지표와 임계값 (`docs/Evaluation.md` 와 같아야 해요)
- 최대 실행 횟수
- 쓸 수 있는 GPU 시간
- 마감
- 사용량 한도에 걸렸을 때 어떻게 할지 (기본은 기다리기 — 자동 구매 안 함)

그리고 `docs/Stop_and_recovery.md` 에 사람이 읽는 말로 풀어 써 주세요.
실패했을 때 체크포인트에서 재개할지, 새 폴더에서 다시 돌릴지도요.
