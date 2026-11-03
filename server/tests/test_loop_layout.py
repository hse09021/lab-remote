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


def test_훅이_지키는_파일은_기록_허용_목록과_겹치지_않는다():
    """승인 로그를 AI 가 "기록" 이라는 이름으로 고치지 못하게."""
    assert not set(L.self_protected_files()) & set(L.journal_files())
    assert not set(L.stop_locked_files()) & set(L.journal_files())
