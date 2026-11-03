"""만들 파일 목록. 생성기의 **단일 출처**다.

`--dry-run --json` 이 내놓는 목록이 곧 웹 UI 의 "생성될 파일 목록 미리 보기"
데이터이고, `docs/File_directory.md` 의 트리도 여기서 나온다. 그래서 계획과
실제 디스크가 어긋날 수 없다.

경로는 전부 `app/loop_layout.py` 에서 온다.
"""

from __future__ import annotations

from dataclasses import dataclass

from .. import loop_layout as L
from .spec import ProjectSpec

__all__ = ["PlannedFile", "build_plan", "OWNERS"]

#: owner 의 뜻
#:   user  사람이 고치는 파일. 생성기가 다시 쓰지 않는다.
#:   ai    AI 가 채우는 파일. 생성기는 틀만 만든다.
#:   gen   생성기가 소유. `--if-exists update` 에서 갱신해도 되는 유일한 것.
#:   lock  잠긴 파일.
#:   hook  훅이 소유. AI 가 못 쓴다.
OWNERS = ("user", "ai", "gen", "lock", "hook")


@dataclass
class PlannedFile:
    path: str  # 프로젝트 루트 기준 상대 경로
    owner: str
    template: str = ""  # app/templates/project 기준. 비면 빈 파일
    tracked: bool = True  # git 이 따라가는가
    role: str = ""  # docs/File_directory.md 의 설명


def build_plan(spec: ProjectSpec) -> list[PlannedFile]:
    LY = L.LOOP_LAYOUT
    EX = L.EXPERIMENT_FILES
    plan: list[PlannedFile] = [
        PlannedFile(LY["claude_md"], "user", "CLAUDE.md.tmpl", role="고정 지침. 잠긴 항목과 기록 의무"),
        PlannedFile(LY["readme"], "ai", "README.md.tmpl", role="실험 개요와 결과 요약"),
        PlannedFile(".gitignore", "gen", "gitignore.tmpl", role="용량·비밀 값 제외 규칙"),
        PlannedFile(".env.example", "gen", "env.example.tmpl", role="필요한 환경 변수 이름"),
        PlannedFile(".env", "user", "env.example.tmpl", tracked=False, role="실제 비밀 값 (커밋 안 함)"),
        # docs/
        PlannedFile(LY["background"], "ai", "docs/Background.md.tmpl", role="배경 지식"),
        PlannedFile(LY["process"], "user", "docs/Process.md.tmpl", role="구조화된 실험 절차"),
        PlannedFile(LY["evaluation"], "lock", "docs/Evaluation.md.tmpl", role="지표와 성공 기준 (잠김)"),
        PlannedFile(LY["stop_recovery"], "user", "docs/Stop_and_recovery.md.tmpl", role="종료·복구 규칙"),
        PlannedFile(LY["file_directory"], "gen", "docs/File_directory.md.tmpl", role="각 파일의 역할"),
        # specifications/
        PlannedFile(LY["experiment_spec"], "ai", "specifications/Experiment_spec.md.tmpl", role="가설·변인·조건"),
        PlannedFile(LY["config"], "lock", "specifications/Config.yaml.tmpl", role="종료 조건과 실행 환경 (잠김)"),
        PlannedFile(LY["environment"], "gen", "specifications/environment.yml.tmpl", role="conda 환경 정의"),
        # state/
        PlannedFile(LY["state"], "ai", "state/State.yaml.tmpl", role="현재 루프 상태 (매번 덮어씀)"),
        # logs/
        PlannedFile(LY["experiment_log"], "ai", "logs/Experiment_log.csv.tmpl", role="모든 실험의 비교표"),
        PlannedFile(LY["decision_log"], "ai", "logs/Decision_log.md.tmpl", role="결정과 근거"),
        PlannedFile(LY["failures"], "ai", "logs/Failures.md.tmpl", role="실패 사례와 해결"),
        PlannedFile(LY["approval_log"], "hook", "logs/Approval_log.csv.tmpl", role="허용·거절·차단 기록 (훅 소유)"),
        # templates/
        PlannedFile(LY["results_example"], "gen", "templates/Results_example.md.tmpl", role="결과 기록 양식"),
        PlannedFile(LY["result_example"], "gen", "templates/result_example.csv.tmpl", role="정형 결과 양식"),
        PlannedFile(f"{LY['output_example_dir']}/.gitkeep", "gen", role="원본 출력 예시 자리"),
        # 빈 폴더
        PlannedFile(f"{LY['experiments_dir']}/.gitkeep", "gen", role="실험 폴더들이 들어갈 자리"),
        PlannedFile(f"{LY['src_dir']}/.gitkeep", "gen", role="실험 코드"),
        PlannedFile(f"{LY['data_dir']}/.gitkeep", "gen", tracked=False, role="데이터셋 (커밋 안 함)"),
    ]

    if spec.first_exp:
        plan.append(
            PlannedFile(
                f"{LY['experiments_dir']}/{spec.first_exp}/{EX['config']}",
                "ai",
                "experiments/EXP/config.yaml.tmpl",
                role="첫 실험의 실행 설정",
            )
        )
    return plan


def tracked_paths(plan: list[PlannedFile]) -> list[str]:
    return sorted(item.path for item in plan if item.tracked)
