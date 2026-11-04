"""`run.json` 검증 — **보안 경계**다.

AI 가 `run.json` 에 임의 명령을 적고 오케스트레이터가 그걸 돌리면 훅을
**완전히 우회**한다. 훅은 Claude 의 도구 호출만 보기 때문이다.
"""

import json
import os
import shutil

import pytest

from app.runner import spec as S

FAKE = os.path.join(os.path.dirname(__file__), "fixtures", "fake_train.py")


@pytest.fixture()
def exp(project, project_root):
    """`src/train.py` 와 `Config.yaml` 이 있는 프로젝트 + 실험 폴더 하나."""
    os.makedirs(os.path.join(project_root, "src"), exist_ok=True)
    shutil.copy(FAKE, os.path.join(project_root, "src", "train.py"))
    os.makedirs(os.path.join(project_root, "src", "도구"), exist_ok=True)
    shutil.copy(FAKE, os.path.join(project_root, "src", "도구", "plot.py"))
    write_config(project_root, entrypoints=["src/train.py"])
    os.makedirs(os.path.join(project_root, "experiments", "EXP-001"), exist_ok=True)
    return project_root


def write_config(root, *, entrypoints, env_allow=None, extra=""):
    body = "goal:\n  metric: loss\n\nenv:\n  conda: labremote-test\n\nrun:\n"
    body += "  entrypoints: [" + ", ".join(entrypoints) + "]\n"
    body += "  envAllow: [" + ", ".join(env_allow or []) + "]\n"
    body += "  resumeArg: --resume-from\n  timeoutSec: 60\n  graceSec: 2\n"
    body += extra
    path = os.path.join(root, "specifications", "Config.yaml")
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as fh:
        fh.write(body)
    return path


def write_run(root, payload, exp_id="EXP-001"):
    path = os.path.join(root, "experiments", exp_id, "run.json")
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(payload, fh, ensure_ascii=False)
    return path


def load(root, payload, exp_id="EXP-001"):
    write_run(root, payload, exp_id)
    return S.load("hook-sandbox", root, exp_id)


# --- 되는 것 -----------------------------------------------------------------


def test_가장_단순한_명세(exp):
    got = load(exp, {"entrypoint": "src/train.py"})
    assert got.entrypoint == "src/train.py"
    assert got.entrypoint_abs == os.path.join(exp, "src/train.py")
    assert got.args == []
    assert got.timeout_sec == 60  # Config.yaml 의 값
    assert got.grace_sec == 2
    assert got.conda_env == "labremote-test"


def test_인자와_환경_변수(exp):
    write_config(exp, entrypoints=["src/train.py"], env_allow=["CUDA_VISIBLE_DEVICES"])
    got = load(
        exp,
        {
            "entrypoint": "src/train.py",
            "args": ["--epochs", 3, "--lr", "1e-4"],
            "env": {"CUDA_VISIBLE_DEVICES": "0"},
        },
    )
    assert got.args == ["--epochs", "3", "--lr", "1e-4"]  # 숫자는 문자열로
    assert got.env == {"CUDA_VISIBLE_DEVICES": "0"}


def test_run_json_의_타임아웃이_Config_보다_먼저(exp):
    assert load(exp, {"entrypoint": "src/train.py", "timeout_sec": 10}).timeout_sec == 10


def test_체크포인트에서_이어_돌린다(exp):
    checkpoint = os.path.join(exp, "experiments/EXP-001/output/epoch_002.ckpt")
    os.makedirs(os.path.dirname(checkpoint), exist_ok=True)
    with open(checkpoint, "w", encoding="utf-8") as fh:
        fh.write('{"epoch": 2}')
    got = load(exp, {"entrypoint": "src/train.py", "resume_from": "experiments/EXP-001/output/epoch_002.ckpt"})
    assert got.args == ["--resume-from", checkpoint]


# --- entrypoint 화이트리스트 ---------------------------------------------------


def test_목록에_없는_entrypoint_는_거절(exp):
    with pytest.raises(S.SpecError) as err:
        load(exp, {"entrypoint": "src/도구/plot.py"})
    assert "허락된 entrypoint 가 아니에요" in str(err.value)


def test_목록이_비어_있으면_아무것도_안_돌린다(exp):
    write_config(exp, entrypoints=[])
    with pytest.raises(S.SpecError) as err:
        load(exp, {"entrypoint": "src/train.py"})
    assert "run.entrypoints 가 비어 있어요" in str(err.value)


def test_자리표시는_entrypoint_가_아니다(exp):
    """`[학습 스크립트 — 미정]` 같은 자리표시로는 안 돌아간다."""
    write_config(exp, entrypoints=["'[학습 스크립트 — 미정]'"])
    with pytest.raises(S.SpecError) as err:
        load(exp, {"entrypoint": "src/train.py"})
    assert "비어 있어요" in str(err.value)


def test_프로젝트_밖_entrypoint_는_거절(exp, tmp_path):
    outside = tmp_path / "남의스크립트.py"
    outside.write_text("print(1)\n", encoding="utf-8")
    write_config(exp, entrypoints=[f"'{outside}'"])
    with pytest.raises(S.SpecError) as err:
        load(exp, {"entrypoint": str(outside)})
    assert "프로젝트 폴더 밖" in str(err.value)


def test_상대경로로_빠져나가는_것도_거절(exp):
    write_config(exp, entrypoints=["'../../etc/passwd'"])
    with pytest.raises(S.SpecError):
        load(exp, {"entrypoint": "../../etc/passwd"})


def test_파일이_없으면_거절(exp):
    write_config(exp, entrypoints=["src/없는파일.py"])
    with pytest.raises(S.SpecError) as err:
        load(exp, {"entrypoint": "src/없는파일.py"})
    assert "파일이 없어요" in str(err.value)


# --- 자유 문자열을 받지 않는다 -------------------------------------------------


def test_명령_문자열은_키부터_없다(exp):
    with pytest.raises(S.SpecError) as err:
        load(exp, {"entrypoint": "src/train.py", "command": "rm -rf /"})
    assert "모르는 키가 있어요" in str(err.value)


def test_args_가_문자열이면_거절(exp):
    """문자열로 받으면 어디선가 셸에 먹일 유혹이 생긴다."""
    with pytest.raises(S.SpecError) as err:
        load(exp, {"entrypoint": "src/train.py", "args": "--epochs 3; rm -rf /"})
    assert "배열이어야 해요" in str(err.value)


def test_args_에_셸_문자가_있어도_그냥_인자다(exp):
    """검증은 통과한다 — `shell=False` 라 해석되지 않는다(process 쪽 시험)."""
    got = load(exp, {"entrypoint": "src/train.py", "args": ["; rm -rf /", "&& echo x", "`whoami`"]})
    assert got.args == ["; rm -rf /", "&& echo x", "`whoami`"]


@pytest.mark.parametrize("bad", [[True], [None], [["중첩"]], [{"키": "값"}]])
def test_args_는_문자열만(exp, bad):
    with pytest.raises(S.SpecError):
        load(exp, {"entrypoint": "src/train.py", "args": bad})


def test_인자가_너무_많으면_거절(exp):
    with pytest.raises(S.SpecError) as err:
        load(exp, {"entrypoint": "src/train.py", "args": ["-x"] * 500})
    assert "너무 많아요" in str(err.value)


# --- 환경 변수 ----------------------------------------------------------------


def test_목록에_없는_환경_변수는_거절(exp):
    with pytest.raises(S.SpecError) as err:
        load(exp, {"entrypoint": "src/train.py", "env": {"WANDB_MODE": "offline"}})
    assert "허락된 환경 변수가 아니에요" in str(err.value)


@pytest.mark.parametrize("name", sorted(S.ENV_NEVER))
def test_끼워_넣는_변수는_목록에_있어도_거절(exp, name):
    """`LD_PRELOAD`·`PYTHONPATH`·`PATH` 는 환경 변수가 아니라 코드 주입 경로다."""
    write_config(exp, entrypoints=["src/train.py"], env_allow=[name])
    with pytest.raises(S.SpecError) as err:
        load(exp, {"entrypoint": "src/train.py", "env": {name: "/tmp/나쁜것"}})
    assert "넘길 수 없어요" in str(err.value)


def test_API_키는_환경으로도_못_넘긴다(exp):
    """구독으로만 돌린다. 추가 결제는 어떤 경우에도 안 한다."""
    assert "ANTHROPIC_API_KEY" in S.ENV_NEVER


def test_폴더_밖을_가리키는_환경_변수는_경고로_남는다(exp):
    """샌드박스 안에서 그 경로 쓰기는 **성공한 것처럼 보이지만** 안 남는다."""
    write_config(exp, entrypoints=["src/train.py"], env_allow=["DATA_ROOT"])
    got = load(exp, {"entrypoint": "src/train.py", "env": {"DATA_ROOT": "/tmp/자료"}})
    assert got.warnings and "남지 않아요" in got.warnings[0]


@pytest.mark.parametrize("name", sorted(S.ENV_MANAGED))
def test_캐시_변수는_실행기가_정한다(exp, name):
    """AI 가 `HF_HOME=~/.claude` 를 넣는 길을 없앤다. `TMPDIR` 이 샌드박스의
    tmpfs(메모리)로 가는 것도 막는다."""
    write_config(exp, entrypoints=["src/train.py"], env_allow=[name])
    with pytest.raises(S.SpecError) as err:
        load(exp, {"entrypoint": "src/train.py", "env": {name: "/tmp/아무데나"}})
    assert "실행기가 공용 캐시 폴더로 정해요" in str(err.value)


# --- 데이터셋 경로 (읽기 전용) --------------------------------------------------


def test_데이터셋_경로를_읽어_온다(exp, tmp_path):
    data = tmp_path / "자료"
    data.mkdir()
    write_config(exp, entrypoints=["src/train.py"], extra=f"  dataPaths: ['{data}']\n")
    got = load(exp, {"entrypoint": "src/train.py"})
    assert got.data_paths == [os.path.realpath(str(data))]


def test_없는_데이터셋_경로는_경고로_건너뛴다(exp):
    write_config(exp, entrypoints=["src/train.py"], extra="  dataPaths: ['/없는자료']\n")
    got = load(exp, {"entrypoint": "src/train.py"})
    assert got.data_paths == []
    assert any("없어요" in w for w in got.warnings)


def test_보호_경로를_데이터셋으로_열_수_없다(exp):
    """"데이터셋" 이라는 이름으로 정책·자격 증명을 읽는 길을 막는다."""
    from app import policy_defaults as Dft

    server = Dft.hard_protected_roots()[0]
    write_config(exp, entrypoints=["src/train.py"], extra=f"  dataPaths: ['{server}']\n")
    with pytest.raises(S.SpecError) as err:
        load(exp, {"entrypoint": "src/train.py"})
    assert "보호 경로와 겹쳐요" in str(err.value)


def test_보호_경로를_품는_데이터셋도_거절(exp):
    write_config(exp, entrypoints=["src/train.py"], extra="  dataPaths: ['~']\n")
    with pytest.raises(S.SpecError):
        load(exp, {"entrypoint": "src/train.py"})


def test_데이터셋_경로가_배열이_아니면_거절(exp):
    write_config(exp, entrypoints=["src/train.py"], extra="  dataPaths: /자료\n")
    with pytest.raises(S.SpecError):
        load(exp, {"entrypoint": "src/train.py"})


def test_자리표시_데이터셋_경로는_건너뛴다(exp):
    write_config(exp, entrypoints=["src/train.py"], extra="  dataPaths: ['[데이터셋 경로 — 미정]']\n")
    assert load(exp, {"entrypoint": "src/train.py"}).data_paths == []


# --- 그 밖의 fail-closed -------------------------------------------------------


def test_모르는_키는_거절(exp):
    with pytest.raises(S.SpecError):
        load(exp, {"entrypoint": "src/train.py", "sandbox": False})


def test_실험_ID_가_폴더와_다르면_거절(exp):
    with pytest.raises(S.SpecError) as err:
        load(exp, {"entrypoint": "src/train.py", "experiment_id": "EXP-999"})
    assert "폴더와 달라요" in str(err.value)


def test_run_json_이_없으면_거절(exp):
    with pytest.raises(S.SpecError) as err:
        S.load("hook-sandbox", exp, "EXP-002")
    assert "run.json 이 없어요" in str(err.value)


def test_run_json_이_깨졌으면_거절(exp):
    path = write_run(exp, {"entrypoint": "src/train.py"})
    with open(path, "w", encoding="utf-8") as fh:
        fh.write("{이건 JSON 이 아니에요")
    with pytest.raises(S.SpecError) as err:
        S.load("hook-sandbox", exp, "EXP-001")
    assert "읽을 수 없어요" in str(err.value)


def test_Config_가_없으면_거절(exp):
    os.remove(os.path.join(exp, "specifications", "Config.yaml"))
    with pytest.raises(S.SpecError) as err:
        load(exp, {"entrypoint": "src/train.py"})
    assert "Config.yaml 가 없어요" in str(err.value)


def test_타임아웃이_숫자가_아니면_거절(exp):
    with pytest.raises(S.SpecError):
        load(exp, {"entrypoint": "src/train.py", "timeout_sec": "오래"})


def test_타임아웃이_0_이면_거절(exp):
    with pytest.raises(S.SpecError):
        load(exp, {"entrypoint": "src/train.py", "timeout_sec": 0})


def test_없는_체크포인트는_거절(exp):
    with pytest.raises(S.SpecError) as err:
        load(exp, {"entrypoint": "src/train.py", "resume_from": "output/없는것.ckpt"})
    assert "체크포인트가 없어요" in str(err.value)


def test_경로_속성은_실험_폴더_안을_가리킨다(exp):
    got = load(exp, {"entrypoint": "src/train.py"})
    assert got.exp_dir == os.path.join(exp, "experiments/EXP-001")
    assert got.log_path.endswith("experiments/EXP-001/output/train.log")
    assert got.exit_code_path.endswith("experiments/EXP-001/output/exit_code")
