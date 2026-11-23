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
    _write(str(root / "메모" / "아이디어.md"), "LoRA 랭크 실험은 [[LoRA|로라]] 와 [[demo]]에서.\n[[없는 노트]]\n")
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
    # 요약 상태는 AI 요약 기준 (노트 본문이 있어도 요약이 없으면 none)
    assert lora["summaryState"] == "none" and rows["Transformer"]["summaryState"] == "none"
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
    assert "저랭크" in client.get("/api/papers/notes").json()["LoRA"]
    assert client.get("/api/papers/summary-md").json() == {}
    g = client.get("/api/papers/graph").json()
    assert {n["kind"] for n in g["nodes"]} == {"paper", "note", "project"}
    # 프로젝트 설정의 papers 는 정리돼서 저장된다
    r = client.put("/api/projects/demo/settings", json={**projects.load_settings(project), "papers": [" LoRA ", "LoRA"]}, headers=H)
    assert r.status_code == 200, r.text
    assert projects.load_settings(project)["papers"] == ["LoRA"]
    assert json.loads(open(os.path.join(str(tmp_path / "data"), "papers.json")).read())["status"]["LoRA"] == "done"


# --- 논문 추가 (vault 에 새 파일만) ---------------------------------------------

ATOM = """<?xml version='1.0' encoding='UTF-8'?>
<feed xmlns:arxiv="http://arxiv.org/schemas/atom" xmlns="http://www.w3.org/2005/Atom">
  <entry>
    <id>http://arxiv.org/abs/1706.03762v7</id>
    <title>Attention Is All
      You Need</title>
    <summary>The dominant sequence transduction models.</summary>
    <published>2017-06-12T17:57:34Z</published>
    <arxiv:primary_category term="cs.CL"/>
    <author><name>Ashish Vaswani</name></author>
    <author><name>Jean-Baptiste Doe</name></author>
  </entry>
</feed>"""


def _fetch(pdf=b"%PDF-1.5 fake"):
    calls = []

    def fetch(url, *, limit, timeout=30):
        calls.append(url)
        return ATOM.encode() if "export.arxiv.org" in url else pdf

    fetch.calls = calls
    return fetch


@pytest.mark.parametrize("text", ["https://arxiv.org/abs/1706.03762", "https://arxiv.org/pdf/1706.03762v7.pdf", "arXiv:1706.03762", "1706.03762v2", "https://arxiv.org/abs/hep-th/9901001"])
def test_arxiv_번호(text):
    assert papers.arxiv_id(text) in ("1706.03762", "hep-th/9901001")


@pytest.mark.parametrize("text", ["", "https://example.com/1706.03762", "1706", "../../etc/passwd"])
def test_arxiv_번호가_아니면_거절(text):
    with pytest.raises(papers.PapersError):
        papers.arxiv_id(text)


def test_arxiv_로_추가(vault):
    papers.set_vault(vault)
    fetch = _fetch()
    got = papers.add_arxiv("https://arxiv.org/abs/1706.03762v7", fetch=fetch)
    # 이미 있는 Transformer.md 는 arxiv 번호가 없어서 새로 만든다 — 같은 제목이라도 덮지 않는다
    assert got["created"] and got["pdf"] and got["id"] == "Attention Is All You Need"
    text = open(os.path.join(vault, "Papers", "Attention Is All You Need.md"), encoding="utf-8").read()
    assert 'arxiv: "1706.03762"' in text and "year: 2017" in text and 'category: "cs.CL"' in text
    assert "## 초록" in text
    assert open(os.path.join(vault, "Papers", "pdf", "Attention Is All You Need.pdf"), "rb").read().startswith(b"%PDF-")
    row = {p["id"]: p for p in papers.list_papers()}["Attention Is All You Need"]
    assert row["authors"] == "Ashish Vaswani, Jean-Baptiste Doe · 2017" and row["field"] == "cs.CL" and row["hasPdf"]
    assert papers.pdf_of("Attention Is All You Need").endswith(".pdf")
    # 다시 추가하면 새로 만들지 않고 그 논문을 돌려준다
    again = papers.add_arxiv("1706.03762", fetch=fetch)
    assert again == {"id": "Attention Is All You Need", "created": False, "path": "vault/Papers/Attention Is All You Need.md"}
    # 원래 노트는 그대로
    assert "Attention Is All You Need" in open(os.path.join(vault, "Papers", "Transformer.md"), encoding="utf-8").read()


def test_PDF_를_못_받아도_노트는_만든다(vault):
    papers.set_vault(vault)
    got = papers.add_arxiv("1706.03762", fetch=_fetch(pdf=b"<html>not pdf"))
    assert got["created"] and not got["pdf"]
    with pytest.raises(papers.PapersError):
        papers.pdf_of(got["id"])


def test_없는_arxiv_번호(vault):
    papers.set_vault(vault)
    empty = lambda url, *, limit, timeout=30: b"<feed xmlns='http://www.w3.org/2005/Atom'></feed>"  # noqa: E731
    with pytest.raises(papers.PapersError, match="없는 번호"):
        papers.add_arxiv("2401.00001", fetch=empty)


def test_PDF_올리기는_덮어쓰지_않는다(vault):
    papers.set_vault(vault)
    with pytest.raises(papers.PapersError, match="PDF 파일이 아니에요"):
        papers.add_pdf("x.pdf", b"hello")
    a = papers.add_pdf("../LoRA.pdf", b"%PDF-1.4 a")
    b = papers.add_pdf("LoRA.pdf", b"%PDF-1.4 b")
    # 이미 있는 LoRA.md 를 덮지 않고 번호를 붙인다
    assert a["id"] == "LoRA (2)" and b["id"] == "LoRA (3)"
    assert "Low-Rank" in open(os.path.join(vault, "Papers", "LoRA.md"), encoding="utf-8").read()
    assert open(os.path.join(vault, "Papers", "pdf", "LoRA.pdf"), "rb").read() == b"%PDF-1.4 a"


def test_추가_API(vault, tmp_path, monkeypatch):
    client = TestClient(main.create_app(web_dist=str(tmp_path / "dist")), base_url="http://127.0.0.1:8000")
    client.put("/api/papers/vault", json={"path": vault}, headers=H)
    monkeypatch.setattr(papers, "_get", _fetch())
    monkeypatch.setattr(papers, "add_arxiv", lambda url, _f=papers.add_arxiv: _f(url, fetch=_fetch()))
    assert client.post("/api/papers/arxiv", json={"url": "nope"}, headers=H).status_code == 400
    r = client.post("/api/papers/arxiv", json={"url": "https://arxiv.org/abs/1706.03762"}, headers=H)
    assert r.status_code == 200 and r.json()["created"]
    r = client.put("/api/papers/pdf?name=my paper.pdf", content=b"%PDF-1.4 x", headers={**H, "Content-Type": "application/octet-stream"})
    assert r.status_code == 200 and r.json()["id"] == "my paper"
    assert client.get("/api/papers/my paper/pdf").content == b"%PDF-1.4 x"
    assert client.get("/api/papers/LoRA/pdf").status_code == 404


# --- 라이브러리에 묻기 ------------------------------------------------------------


def _fake_agent(answer):
    from claude_agent_sdk import ResultMessage

    seen = {}

    async def run(opts, prompt):
        seen["opts"], seen["prompt"] = opts, prompt
        yield ResultMessage(
            subtype="success", duration_ms=1, duration_api_ms=1, is_error=False, num_turns=1,
            session_id="s", structured_output=answer,
        )

    run.seen = seen
    return run


def test_묻기_읽기_전용과_근거_정리(vault, monkeypatch):
    import asyncio

    from app import library
    from app.agents import claude as claude_mod

    papers.set_vault(vault)
    monkeypatch.setattr(claude_mod, "cli_path", lambda: "/usr/bin/true")
    run = _fake_agent({"answer": "LoRA 는 저랭크 어댑터예요.", "sources": [
        {"paper": "LoRA", "why": "초록"},
        {"paper": "Papers/LoRA.md", "why": "중복"},
        {"paper": "Attention Is All You Need", "why": "제목으로 적음"},
        {"paper": "없는 논문", "why": "지어냄"},
    ]})

    async def go():
        got = library.start("LoRA 가 뭐야?", [{"role": "user", "text": "앞 질문"}], query_fn=run)
        assert got["state"] == "running"
        with pytest.raises(library.AskError, match="답하는 중"):
            library.start("또", query_fn=run)
        for _ in range(50):
            await asyncio.sleep(0.01)
            if library.job(got["id"])["state"] != "running":
                break
        return library.job(got["id"])

    done = asyncio.run(go())
    assert done["state"] == "done" and "저랭크" in done["answer"]
    assert [s["paperId"] for s in done["sources"]] == ["LoRA", "Transformer"]
    opts = run.seen["opts"]
    assert opts.permission_mode == "plan" and opts.tools == ["Read", "Glob", "Grep"]
    assert os.path.realpath(opts.cwd) == os.path.realpath(vault)
    assert "LoRA · LoRA: Low-Rank Adaptation" in run.seen["prompt"] and "[질문] 앞 질문" in run.seen["prompt"]


def test_묻기_거절(vault, monkeypatch, tmp_path):
    from app import library

    with pytest.raises(library.AskError, match="질문을"):
        library.start("  ")
    papers.set_vault(vault)
    monkeypatch.setattr(papers, "vault_path", lambda: str(tmp_path / "없음"))
    with pytest.raises(library.AskError, match="vault 폴더가 없어요"):
        library.start("x")


# --- 휴지통 · 모음 · BibTeX · 참고문헌 보관 -----------------------------------------


def test_휴지통은_lab_remote_에서만(vault):
    papers.set_vault(vault)
    before = sorted(os.listdir(os.path.join(vault, "Papers")))
    papers.set_trashed("LoRA", True)
    assert "LoRA" not in {p["id"] for p in papers.list_papers()}
    assert [p["id"] for p in papers.list_papers(trash=True)] == ["LoRA"]
    assert "LoRA" not in {n["id"] for n in papers.graph()["nodes"]}
    assert sorted(os.listdir(os.path.join(vault, "Papers"))) == before  # vault 그대로
    papers.set_trashed("LoRA", False)
    assert "LoRA" in {p["id"] for p in papers.list_papers()}
    with pytest.raises(papers.PapersError):
        papers.set_trashed("없음", True)


def test_모음(vault):
    papers.set_vault(vault)
    assert papers.add_collection("읽을 것") == [{"name": "읽을 것", "count": 0}]
    with pytest.raises(papers.PapersError):
        papers.add_collection("읽을 것")
    with pytest.raises(papers.PapersError):
        papers.add_collection("a/b")
    papers.set_in_collection("읽을 것", ["LoRA", "Transformer"], True)
    assert {p["id"]: p["collections"] for p in papers.list_papers()}["LoRA"] == ["읽을 것"]
    papers.set_in_collection("읽을 것", ["LoRA"], False)
    assert papers.collections() == [{"name": "읽을 것", "count": 1}]
    papers.remove_collection("읽을 것")
    assert papers.collections() == []


def test_BibTeX(vault):
    papers.set_vault(vault)
    text = papers.bibtex(["LoRA", "없음"])
    assert text.startswith("@article{hu2021lora,") and "author        = {Hu and Shen and Wallis and Allen-Zhu}" in text
    assert "eprint        = {2106.09685}" in text and "booktitle     = {ICLR 2022}" in text


def test_참고문헌_보관(vault):
    papers.set_vault(vault)
    got = papers.add_reference("Long Short-Term Memory", "Hochreiter & Schmidhuber", "1997", "Neural Computation")
    assert got["created"] and got["id"] == "Long Short-Term Memory"
    row = {p["id"]: p for p in papers.list_papers()}[got["id"]]
    assert row["authors"] == "Hochreiter, Schmidhuber · 1997"
    assert papers.add_reference("long short-term memory")["created"] is False


def test_하이라이트_주석_서버_저장(tmp_path):
    client = TestClient(main.create_app(web_dist=str(tmp_path / "dist")), base_url="http://127.0.0.1:8000")
    base = "/api/papers/QLoRA (2)/annotations"
    r = client.post(base, json={"kind": "highlight", "text": "4-bit", "source": "4-bit", "sectionId": "o1", "page": 1, "boxes": [[1, 2, 3, 4]]}, headers=H)
    assert r.status_code == 200, r.text
    made = r.json()
    assert made["id"].startswith("u-") and made["boxes"] == [[1.0, 2.0, 3.0, 4.0]]
    assert client.post(base, json={"kind": "x", "text": "a"}, headers=H).status_code == 400
    note = client.post(base, json={"kind": "note", "text": "메모", "source": "4-bit", "page": 1}, headers=H).json()
    assert client.patch(f"{base}/{note['id']}", json={"text": "고친 메모"}, headers=H).json()["text"] == "고친 메모"
    assert [a["id"] for a in client.get(base).json()] == [note["id"], made["id"]]
    assert client.delete(f"{base}/{made['id']}", headers=H).status_code == 200
    # 되돌리기 — 같은 id · 시각으로
    assert client.post(base, json=made, headers=H).json()["id"] == made["id"]
    assert client.delete(f"{base}/없음", headers=H).status_code == 404


# --- AI 요약 (vault 에 새 파일) ----------------------------------------------------


def test_요약_만들기(vault, monkeypatch):
    import asyncio

    from app import summaries
    from app.agents import claude as claude_mod

    papers.set_vault(vault)
    monkeypatch.setattr(claude_mod, "cli_path", lambda: "/usr/bin/true")
    os.makedirs(os.path.join(vault, "Papers", "pdf"), exist_ok=True)
    with open(os.path.join(vault, "Papers", "pdf", "LoRA.pdf"), "wb") as fh:
        fh.write(b"%PDF-1.4 x")
    note = os.path.join(vault, "Papers", "LoRA.md")
    text = open(note, encoding="utf-8").read().replace("aliases: [LoRA]", "aliases: [LoRA]\npdf: Papers/pdf/LoRA.pdf")
    open(note, "w", encoding="utf-8").write(text)
    before = open(note, encoding="utf-8").read()
    run = _fake_agent({
        "lines": [{"text": "저랭크 어댑터", "page": 2}, {"text": "B", "page": 0}, {"text": "C", "page": 5}],
        "field": "NLP", "baseModel": "GPT-3 175B", "code": "", "method": "ΔW = BA", "methodPage": 4,
        "result": "파라미터 1/10000", "resultPage": 7, "limitation": "",
    })

    async def go():
        assert summaries.start("LoRA", query_fn=run)["state"] == "running"
        with pytest.raises(summaries.SummaryError):
            summaries.start("LoRA", query_fn=run)
        assert {p["id"]: p for p in papers.list_papers()}["LoRA"]["summaryState"] == "running"
        for _ in range(50):
            await asyncio.sleep(0.01)
            if summaries.job("LoRA")["state"] != "running":
                break
        return summaries.job("LoRA")

    assert asyncio.run(go())["state"] == "done", summaries.job("LoRA")
    # 원래 노트는 그대로, 요약은 새 파일
    assert open(note, encoding="utf-8").read() == before
    md = open(os.path.join(vault, "Papers", "LoRA 요약.md"), encoding="utf-8").read()
    assert 'summary_of: "[[LoRA]]"' in md and "1. 저랭크 어댑터 ([[Papers/pdf/LoRA.pdf#page=2|p.2]])" in md
    assert "2. B (p.[쪽])" in md and "## Limitation" not in md
    # 요약 파일은 논문으로 세지 않는다
    assert "LoRA 요약" not in {p["id"] for p in papers.list_papers()}
    s = summaries.load_all()["LoRA"]
    assert s["lines"][0] == {"text": "저랭크 어댑터", "ref": "p.2"} and s["file"] == "LoRA.pdf"
    assert {f["label"] for f in s["fields"]} == {"Field", "Base Model", "Paper URL"}
    assert {p["id"]: p for p in papers.list_papers()}["LoRA"]["summaryState"] == "done"
    # 수정은 요약 파일만, None 이면 되돌리기
    summaries.save_markdown("LoRA", "고친 요약")
    assert summaries.markdown_of("LoRA") == "고친 요약"
    summaries.save_markdown("LoRA", None)
    assert "summary_of" in summaries.markdown_of("LoRA")
    assert open(note, encoding="utf-8").read() == before


def test_같은_이름의_다른_파일은_덮지_않는다(vault, monkeypatch):
    from app import summaries

    papers.set_vault(vault)
    other = os.path.join(vault, "Papers", "LoRA 요약.md")
    open(other, "w", encoding="utf-8").write("내가 쓴 노트\n")
    with pytest.raises(summaries.SummaryError):
        summaries.save_markdown("LoRA", "x")
    assert open(other, encoding="utf-8").read() == "내가 쓴 노트\n"
