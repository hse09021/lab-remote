"""Loop Engineering 경로의 단일 출처 시험.

`test_자리표시가_남아_있지_않다` 는 `docs/Loop*.pdf` 를 읽어
LOOP_LAYOUT 을 채우기 전까지 **일부러 실패한다.** 자리표시를 남긴 채
생성기·훅 판정을 확정하지 못하게 막는 문턱이다.
"""

import pytest

from app import loop_layout as L


def test_자리표시가_남아_있지_않다():
    assert L.pending_keys() == [], (
        "docs/Loop*.pdf 를 읽어 LOOP_LAYOUT 을 채워 주세요. 남은 키: "
        + ", ".join(L.pending_keys())
    )


def test_assert_complete_는_자리표시를_잡는다():
    if L.pending_keys():
        with pytest.raises(L.LayoutPending):
            L.assert_complete()
    else:
        L.assert_complete()


def test_path_는_자리표시에_예외를_던진다():
    for key in L.pending_keys():
        with pytest.raises(L.LayoutPending):
            L.path(key)


def test_모든_값이_안전한_상대경로():
    for key, value in L.LOOP_LAYOUT.items():
        if value == L.PENDING:
            continue
        assert not value.startswith("/"), key
        assert ".." not in value.split("/"), key
        assert not value.endswith("/"), key
        assert "\\" not in value, key


def test_파일_경로는_겹치지_않는다():
    values = [v for v in L.LOOP_LAYOUT.values() if v != L.PENDING]
    assert len(values) == len(set(values))


def test_파생_목록이_LOOP_LAYOUT_에서_나온다():
    assert L.stop_locked_files() == [
        L.LOOP_LAYOUT["config"],
        L.LOOP_LAYOUT["evaluation"],
    ]
    # 사람이 읽는 복구 설명은 잠금 대상이 아니다.
    assert L.LOOP_LAYOUT["stop_recovery"] not in L.stop_locked_files()

    journal = L.journal_files()
    for key in L.JOURNAL_KEYS:
        assert L.LOOP_LAYOUT[key] in journal
    assert f"{L.experiments_dir()}/*/analysis.md" in journal

    assert L.hparam_files() == [f"{L.experiments_dir()}/*/config.yaml"]

    protected = L.self_protected_files()
    assert ".claude/**" in protected
    assert L.LOOP_LAYOUT["approval_log"] in protected


def test_PDF_7쪽_트리와_같다():
    """PDF 7쪽 "파일 구조 예시" 를 그대로 옮겼는지. 추정으로 돌아가지 않게 못박는다."""
    assert L.LOOP_LAYOUT["state"] == "state/State.yaml"
    # 기록 3개는 state/ 가 아니라 logs/ 다 (PDF 7쪽)
    assert L.LOOP_LAYOUT["experiment_log"] == "logs/Experiment_log.csv"
    assert L.LOOP_LAYOUT["decision_log"] == "logs/Decision_log.md"
    assert L.LOOP_LAYOUT["failures"] == "logs/Failures.md"
    assert L.LOOP_LAYOUT["experiment_spec"] == "specifications/Experiment_spec.md"
    assert L.LOOP_LAYOUT["config"] == "specifications/Config.yaml"
    for key in ("background", "process", "evaluation", "stop_recovery", "file_directory"):
        assert L.LOOP_LAYOUT[key].startswith("docs/")


def test_실험_폴더_파일은_소문자():
    """6쪽(Config.yaml·Analysis.md)과 7쪽(config.yaml·analysis.md)이 어긋난다.
    리눅스는 대소문자를 구분하므로 7쪽 트리 + 웹 목업 쪽으로 못박는다."""
    assert L.EXPERIMENT_FILES == {
        "config": "config.yaml",
        "result": "result.csv",
        "analysis": "analysis.md",
        "output_dir": "output",
    }
    assert L.hparam_files() == ["experiments/*/config.yaml"]


def test_승인_로그는_기록_파일이_아니다():
    """둘 다 logs/ 에 있지만 Approval_log.csv 는 훅 소유라 AI 가 못 쓴다."""
    assert L.LOOP_LAYOUT["approval_log"] in L.self_protected_files()
    assert L.LOOP_LAYOUT["approval_log"] not in L.journal_files()
    assert L.LOOP_LAYOUT["experiment_log"] in L.journal_files()


def test_훅이_지키는_파일은_기록_허용_목록과_겹치지_않는다():
    """승인 로그를 AI 가 "기록" 이라는 이름으로 고치지 못하게."""
    assert not set(L.self_protected_files()) & set(L.journal_files())
    assert not set(L.stop_locked_files()) & set(L.journal_files())
