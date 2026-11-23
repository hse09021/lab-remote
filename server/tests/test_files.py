"""파일 — 🔑 경로 탈출을 막는다."""

import os

import pytest

from app import files


@pytest.fixture()
def base(project_root, tmp_path):
    root = project_root
    with open(os.path.join(root, "src", "a.py"), "w") as fh:
        fh.write("print(1)\n")
    secret = tmp_path / "outside"
    secret.mkdir()
    (secret / "key.txt").write_text("secret")
    os.symlink(secret, os.path.join(root, "out-link"))
    os.symlink(os.path.join(root, "src"), os.path.join(root, "in-link"))
    return root


@pytest.mark.parametrize(
    "rel",
    ["../outside/key.txt", "/etc/passwd", "~/.bashrc", "src/../../outside", "a\x00b", "src\\..\\x"],
)
def test_밖으로_나가는_경로는_거절(base, rel):
    with pytest.raises(files.FileRefused):
        files.resolve(base, rel)


def test_밖을_가리키는_링크는_따라가지_않는다(base):
    with pytest.raises(files.FileRefused):
        files.read_text(base, "out-link/key.txt")
    with pytest.raises(files.FileRefused):
        files.list_dir(base, "out-link")
    with pytest.raises(files.FileRefused):
        files.write_text(base, "out-link/key.txt", "pwned")
    with pytest.raises(files.FileRefused):
        files.make(base, "out-link/new.txt", "file")
    assert os.listdir(os.path.join(os.path.dirname(base), "..", "outside")) == ["key.txt"]


def test_목록에는_보이되_밖이라고_표시(base):
    listed = {e["name"]: e for e in files.list_dir(base)["entries"]}
    assert listed["out-link"]["outside"] is True and listed["out-link"]["link"] is True
    assert listed["in-link"]["kind"] == "dir" and listed["in-link"]["outside"] is False
    assert listed["src"]["size"] is None  # 폴더 크기는 재지 않는다
    assert listed["src"]["kind"] == "dir"


def test_안을_가리키는_링크는_따라간다(base):
    assert files.read_text(base, "in-link/a.py")["text"] == "print(1)\n"


def test_링크를_지우면_링크만_지운다(base, tmp_path):
    files.delete(base, base, "out-link", confirm="out-link")
    assert not os.path.lexists(os.path.join(base, "out-link"))
    assert (tmp_path / "outside" / "key.txt").exists()


def test_쓰기와_만들기(base):
    files.make(base, "notes", "dir")
    files.write_text(base, "notes/a.md", "# hi\n", create=True)
    assert files.read_text(base, "notes/a.md")["text"] == "# hi\n"
    with pytest.raises(files.FileRefused, match="이미 있어요"):
        files.make(base, "notes/a.md", "file")
    files.write_text(base, "notes/a.md", "# bye\n")
    assert files.read_text(base, "notes/a.md")["text"] == "# bye\n"


def test_이진_파일과_큰_파일은_내용을_안_준다(base):
    with open(os.path.join(base, "w.bin"), "wb") as fh:
        fh.write(b"\x00\x01\x02")
    assert files.read_text(base, "w.bin")["reason"] == "binary"


def test_업로드는_덮어쓰지_않는다(base):
    files.upload(base, "src/data.csv", [b"a,b\n", b"1,2\n"])
    assert files.read_text(base, "src/data.csv")["text"] == "a,b\n1,2\n"
    with pytest.raises(files.FileRefused, match="이미 있어요"):
        files.upload(base, "src/data.csv", [b"x"])
    files.upload(base, "src/data.csv", [b"x"], overwrite=True)
    assert files.read_text(base, "src/data.csv")["text"] == "x"


def test_이동과_이름_바꾸기(base):
    files.move(base, base, "src/a.py", "src/b.py")
    assert os.path.exists(os.path.join(base, "src", "b.py"))
    files.make(base, "dst", "dir")
    with pytest.raises(files.FileRefused, match="이미 있어요"):
        files.move(base, base, "src", "dst")
    with pytest.raises(files.FileRefused, match="자기 안"):
        files.move(base, base, "src", "src/inner")


def test_루트와_git_은_지우거나_옮기지_않는다(base):
    os.mkdir(os.path.join(base, ".git"))
    for rel in ("", ".", ".git"):
        with pytest.raises(files.FileRefused):
            files.delete(base, base, rel, confirm=os.path.basename(rel) or ".")
    with pytest.raises(files.FileRefused):
        files.move(base, base, ".git", "git-old")


def test_지우기는_이름_확인이_맞아야(base):
    with pytest.raises(files.FileRefused, match="확인"):
        files.delete(base, base, "src", confirm="nope")
    files.delete(base, base, "src", confirm="src")
    assert not os.path.exists(os.path.join(base, "src"))


def test_실행_중인_학습이_쓰는_폴더는_못_지운다(base, monkeypatch):
    busy = os.path.join(base, "src")
    monkeypatch.setattr(files, "busy_paths", lambda root: [busy])
    with pytest.raises(files.FileRefused, match="실행 중"):
        files.delete(base, base, "src", confirm="src")
    with pytest.raises(files.FileRefused, match="실행 중"):
        files.delete(base, base, "src/a.py", confirm="a.py")


def test_worktree_기준_폴더는_프로젝트_안이어야(base):
    assert files.base_of(base, "src") == os.path.join(base, "src")
    for bad in ("../", "out-link", "nope"):
        with pytest.raises(files.FileRefused):
            files.base_of(base, bad)
