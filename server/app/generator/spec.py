"""프로젝트 생성에 필요한 입력 한 덩어리."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime

from .. import loop_layout as L
from .. import policy_defaults as D

__all__ = ["ProjectSpec", "PYTHON_VERSION"]

#: 생성되는 실험 환경의 파이썬. 서버(`labremote`)와 맞춘다.
PYTHON_VERSION = "3.11"


@dataclass
class ProjectSpec:
    name: str
    goal: str = "[연구 목표 — 한 줄로 적어 주세요]"
    mode: str = D.DEFAULT_MODE
    env_name: str = ""
    first_exp: str = ""  # "EXP-001" 을 주면 그 폴더를 만든다
    remote: str = ""
    created_at: str = field(default_factory=lambda: datetime.now().astimezone().isoformat(timespec="seconds"))

    def __post_init__(self) -> None:
        if not self.env_name:
            self.env_name = self.name  # 환경 이름은 프로젝트 이름과 같게
        # 🔑 우리 코드가 도는 환경(`labremote`)·`base` 는 실험용으로 쓸 수
        # 없다. `.pth` 는 인터프리터가 뜰 때 실행되므로, 거기 패키지를 깔면
        # 훅·오케스트레이터 프로세스 안(샌드박스 **밖**)에서 코드가 돈다.
        from .. import registry
        from ..runner import condaenv

        got = condaenv.check(self.env_name)
        if not got["ok"]:
            # `InvalidName` 으로 던진다 — 이름이 잘못된 것이고, CLI 가 이미
            # 그걸 잡아 종료코드 2 로 돌려준다.
            raise registry.InvalidName(
                f"conda 환경 이름을 다시 정해 주세요 — {got['reason']} "
                "(--env-name 으로 바꿀 수 있어요)"
            )

    @property
    def mode_name(self) -> str:
        for item in D.MODES:
            if item["id"] == self.mode:
                return item["name"]
        return self.mode

    def values(self) -> dict[str, str]:
        """템플릿에 끼울 값. `$키` 로 쓴다."""
        return {
            "project_name": self.name,
            "goal": self.goal,
            "mode": self.mode,
            "mode_name": self.mode_name,
            "env_name": self.env_name,
            "python_version": PYTHON_VERSION,
            "created_at": self.created_at,
            "exp_id": self.first_exp or "EXP-001",
            # LOOP_LAYOUT 의 경로를 그대로 템플릿 문구에 쓴다
            "state_path": L.LOOP_LAYOUT["state"],
            # ②: AI 가 못 고치는 "현재 실험" 표시 (selfProtect)
            "current_path": L.LOOP_LAYOUT["current"],
            "config_path": L.LOOP_LAYOUT["config"],
            "evaluation_path": L.LOOP_LAYOUT["evaluation"],
            "process_path": L.LOOP_LAYOUT["process"],
            "background_path": L.LOOP_LAYOUT["background"],
            "stop_recovery_path": L.LOOP_LAYOUT["stop_recovery"],
            "file_directory_path": L.LOOP_LAYOUT["file_directory"],
            "experiment_spec_path": L.LOOP_LAYOUT["experiment_spec"],
            "experiment_log_path": L.LOOP_LAYOUT["experiment_log"],
            "decision_log_path": L.LOOP_LAYOUT["decision_log"],
            "failures_path": L.LOOP_LAYOUT["failures"],
            "approval_log_path": L.LOOP_LAYOUT["approval_log"],
            "experiments_dir": L.LOOP_LAYOUT["experiments_dir"],
        }
