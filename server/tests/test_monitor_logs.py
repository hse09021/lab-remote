"""로그 꼬리 — **증분으로** 읽는다.

학습 로그는 수십 MB 가 된다. 5초마다 통째로 읽으면 디스크를 계속 때린다.
"""

import os
import time

from app.monitor import logs as LG


def write(path, text, mode="a"):
    with open(path, mode, encoding="utf-8") as fh:
        fh.write(text)


def test_꼬리를_읽는다(tmp_path):
    path = tmp_path / "train.log"
    write(path, "첫 줄\n둘째 줄\n셋째 줄\n", "w")
    got = LG.tail(str(path))
    assert got["ok"] is True
    assert got["lines"] == ["첫 줄", "둘째 줄", "셋째 줄"]


def test_줄_수를_제한한다(tmp_path):
    path = tmp_path / "train.log"
    write(path, "".join(f"줄 {i}\n" for i in range(100)), "w")
    assert LG.tail(str(path), lines=3)["lines"] == ["줄 97", "줄 98", "줄 99"]


def test_큰_파일은_끝에서만_읽는다(tmp_path):
    path = tmp_path / "train.log"
    write(path, "앞쪽 " * 10000 + "\n끝 줄\n", "w")
    got = LG.tail(str(path), limit=200)
    assert got["lines"][-1] == "끝 줄"
    assert len(got["text"]) <= 200


def test_잘린_첫_줄은_버린다(tmp_path):
    """앞이 잘려서 반쪽이 된 줄을 넘기면 지표 파싱이 깨진다."""
    path = tmp_path / "train.log"
    write(path, "아주아주아주 긴 첫 줄입니다\n짧은 둘째\n", "w")
    got = LG.tail(str(path), limit=20)
    assert "아주아주" not in got["text"]


def test_없는_파일은_정상_실패(tmp_path):
    got = LG.tail(str(tmp_path / "없음.log"))
    assert got["ok"] is False and got["lines"] == []


# --- 증분 ---------------------------------------------------------------------


def test_늘어난_만큼만_읽는다(tmp_path):
    path = tmp_path / "train.log"
    write(path, "첫 줄\n", "w")
    follower = LG.Follower(str(path))
    assert follower.read()["lines"] == ["첫 줄"]
    assert follower.read()["lines"] == []  # 안 늘었다
    write(path, "둘째 줄\n")
    got = follower.read()
    assert got["lines"] == ["둘째 줄"]
    assert got["grew"] > 0


def test_반쪽_줄은_다음까지_들고_있는다(tmp_path):
    """`\\n` 이 아직 안 온 줄을 넘기면 지표 파싱이 깨진다."""
    path = tmp_path / "train.log"
    write(path, "완성된 줄\n반쪽", "w")
    follower = LG.Follower(str(path))
    assert follower.read()["lines"] == ["완성된 줄"]
    write(path, " 나머지\n")
    assert follower.read()["lines"] == ["반쪽 나머지"]


def test_파일이_줄어들면_처음부터(tmp_path):
    """새 실험이 로그를 다시 쓴 경우."""
    path = tmp_path / "train.log"
    write(path, "옛 줄 하나\n옛 줄 둘\n", "w")
    follower = LG.Follower(str(path))
    follower.read()
    write(path, "새 줄\n", "w")
    assert follower.read()["lines"] == ["새 줄"]


def test_없는_파일도_안_터진다(tmp_path):
    follower = LG.Follower(str(tmp_path / "없음.log"))
    got = follower.read()
    assert got["ok"] is False and got["lines"] == []


def test_안_자란_시간을_센다(tmp_path):
    path = tmp_path / "train.log"
    write(path, "줄\n", "w")
    follower = LG.Follower(str(path))
    follower.read()
    assert follower.stalled_sec(time.time()) < 5
    assert follower.stalled_sec(follower.mtime + 1000) >= 1000


def test_한_번도_안_읽었으면_0(tmp_path):
    assert LG.Follower(str(tmp_path / "x.log")).stalled_sec(time.time()) == 0.0
