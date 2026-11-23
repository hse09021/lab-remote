"""Papers — vault 읽기 · 읽음 상태 · 지식그래프 (8단계)."""

import json
import os

import pytest
from fastapi.testclient import TestClient

from app import main, papers, projects

H = {"X-Lab-Remote": "1"}


def _write(path, text):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as fh:
        fh.write(text)


@pytest.fixture()
def vault(tmp_path):
    root = tmp_path / "vault"
    _write(str(root / "Papers" / "LoRA.md"), """---
title: "LoRA: Low-Rank Adaptation"
authors: [Hu, Shen, Wallis, Allen-Zhu]
year: 2021
venue: ICLR 2022
category: 효율적 학습
arxiv: 2106.09685
aliases: [LoRA]
cites:
  - "[[Attention Is All You Need]]"
---
## 요약
저랭크 어댑터.
""")
    _write(str(root / "Papers" / "Transformer.md"), """---
title: Attention Is All You Need
authors: Vaswani
year: 2017
category: 아키텍처
---
""")
    _write(str(root / "메모" / "아이디어.md"), "LoRA 랭크 실험은 [[LoRA|로라]] 와 [[demo]] 에서.\n[[없는 노트]]\n")
    _write(str(root / "메모" / "외톨이.md"), "아무 링크 없음\n")
    _write(str(root / ".obsidian" / "x.md"), "[[LoRA]]\n")
    return str(root)


def test_vault_설정(vault, tmp_path, isolated_data):
    assert papers.info()["custom"] is False
    assert papers.vault_path() == os.path.join(str(isolated_data), "vault")
    with pytest.raises(papers.PapersError):
        papers.set_vault(str(tmp_path / "없음"))
    with pytest.raises(papers.PapersError):
        papers.set_vault(os.path.expanduser("~"))
    got = papers.set_vault(vault)
    assert got == {"path": os.path.realpath(vault), "custom": True, "exists": True, "papers": 2, "notes": 2}
    assert papers.set_vault("")["custom"] is False


def test_목록과_상태는_노트를_안_고친다(vault):
    papers.set_vault(vault)
    before = open(os.path.join(vault, "Papers", "LoRA.md"), encoding="utf-8").read()
    rows = {p["id"]: p for p in papers.list_papers()}
    lora = rows["LoRA"]
    assert lora["title"] == "LoRA: Low-Rank Adaptation"
    assert lora["authors"] == "Hu, Shen, Wallis et al. · 2021"
    assert lora["field"] == "효율적 학습" and lora["source"] == "arxiv-html"
    assert lora["summaryState"] == "done" and rows["Transformer"]["summaryState"] == "none"
    assert lora["status"] == "todo"
    papers.set_status("LoRA", "reading")
    assert {p["id"]: p for p in papers.list_papers()}["LoRA"]["status"] == "reading"
    with pytest.raises(papers.PapersError):
        papers.set_status("LoRA", "x")
    assert open(os.path.join(vault, "Papers", "LoRA.md"), encoding="utf-8").read() == before
    assert papers.body_of("LoRA").startswith("## 요약")


def test_지식그래프(vault, project):
    papers.set_vault(vault)
    g = papers.graph()
    ids = {n["id"]: n for n in g["nodes"]}
    # 인용: 제목으로 적은 링크가 파일 이름 id 로 이어진다
    assert {"from": "LoRA", "to": "Transformer", "kind": "cite"} in g["edges"]
    # 메모: 별칭 링크 · 프로젝트 이름 링크. 외톨이 메모와 .obsidian 은 빠진다
    note = "note:메모/아이디어.md"
    assert ids[note]["kind"] == "note"
    assert {"from": note, "to": "LoRA", "kind": "note"} in g["edges"]
    assert {"from": note, "to": "project:demo", "kind": "note"} in g["edges"]
    assert "note:메모/외톨이.md" not in ids
    assert not any(".obsidian" in n["id"] for n in g["nodes"])
    # 프로젝트에서 사용 — 설정에서 고른 것
    assert not any(e["kind"] == "use" for e in g["edges"])
    s = projects.load_settings(project)
    s["papers"] = ["LoRA", "없는 논문"]
    projects.save_settings(project, s)
    g = papers.graph()
    assert [e for e in g["edges"] if e["kind"] == "use"] == [{"from": "project:demo", "to": "LoRA", "kind": "use"}]


def test_API(vault, tmp_path, project):
    client = TestClient(main.create_app(web_dist=str(tmp_path / "dist")), base_url="http://127.0.0.1:8000")
    assert client.put("/api/papers/vault", json={"path": vault}).status_code == 403  # 헤더 없음
    assert client.put("/api/papers/vault", json={"path": vault}, headers=H).json()["papers"] == 2
    assert len(client.get("/api/papers").json()) == 2
    assert client.patch("/api/papers/LoRA", json={"status": "done"}, headers=H).json()["status"] == "done"
    assert client.patch("/api/papers/LoRA", json={"status": "nope"}, headers=H).status_code == 400
    assert "저랭크" in client.get("/api/papers/summary-md").json()["LoRA"]
    g = client.get("/api/papers/graph").json()
    assert {n["kind"] for n in g["nodes"]} == {"paper", "note", "project"}
    # 프로젝트 설정의 papers 는 정리돼서 저장된다
    r = client.put("/api/projects/demo/settings", json={**projects.load_settings(project), "papers": [" LoRA ", "LoRA"]}, headers=H)
    assert r.status_code == 200, r.text
    assert projects.load_settings(project)["papers"] == ["LoRA"]
    assert json.loads(open(os.path.join(str(tmp_path / "data"), "papers.json")).read())["status"]["LoRA"] == "done"
