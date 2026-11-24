from collections.abc import Iterator
from io import BytesIO
from pathlib import Path
from typing import Final

import pytest
from fastapi.testclient import TestClient
from pypdf import PdfWriter
from pypdf.generic import DecodedStreamObject, DictionaryObject, NameObject

from app import main

HEADERS: Final = {"X-Lab-Remote": "1", "Content-Type": "application/pdf"}
FIRST_PAGE: Final = b"""
BT /F1 20 Tf 0 1 -1 0 20 160 Tm (arXiv:2401.12345v1 [cs.LG]) Tj ET
BT /F1 30 Tf 1 0 0 1 72 745 Tm (arXiv:2401.12345v1 [cs.LG]) Tj ET
BT /F1 10 Tf 1 0 0 1 72 760 Tm (Preprint submitted for review) Tj ET
BT /F1 24 Tf 1 0 0 1 72 700 Tm (Learning Useful Representations) Tj ET
BT /F1 24 Tf 1 0 0 1 72 670 Tm (with Limited Supervision) Tj ET
BT /F1 12 Tf 1 0 0 1 72 620 Tm (Alice Example and Bob Researcher) Tj ET
BT /F1 12 Tf 1 0 0 1 72 560 Tm (Abstract) Tj ET
BT /F1 10 Tf 1 0 0 1 72 540 Tm (We study efficient learning from limited data.) Tj ET
"""


def _pdf(content: bytes = b"", title: str | None = None, password: str = "") -> bytes:
    writer = PdfWriter()
    page = writer.add_blank_page(width=612, height=792)
    font = DictionaryObject({
        NameObject("/Type"): NameObject("/Font"),
        NameObject("/Subtype"): NameObject("/Type1"),
        NameObject("/BaseFont"): NameObject("/Helvetica"),
    })
    page[NameObject("/Resources")] = DictionaryObject({
        NameObject("/Font"): DictionaryObject({NameObject("/F1"): font}),
    })
    stream = DecodedStreamObject()
    stream.set_data(content)
    page[NameObject("/Contents")] = stream
    if title is not None:
        writer.add_metadata({"/Title": title})
    if password:
        writer.encrypt(password)
    with BytesIO() as output:
        writer.write(output)
        return output.getvalue()


@pytest.fixture()
def client(tmp_path: Path) -> Iterator[TestClient]:
    with TestClient(
        main.create_app(web_dist=str(tmp_path / "dist")),
        base_url="http://127.0.0.1:8000",
    ) as api:
        yield api


def test_metadata_title_is_normalized_and_persisted(
    client: TestClient, isolated_data: Path,
) -> None:
    document = _pdf(FIRST_PAGE, "  Efficient\n Models:\t Learning\u00a0with Less  ")

    response = client.put(
        "/api/papers/pdf", params={"name": "2401.12345.pdf"},
        content=document, headers=HEADERS,
    )

    assert response.status_code == 200, response.text
    uploaded = response.json()
    assert [(row["id"], row["title"]) for row in client.get("/api/papers").json()] == [
        (uploaded["id"], "Efficient Models: Learning with Less"),
    ]
    note = (isolated_data / uploaded["path"]).read_text(encoding="utf-8")
    assert 'title: "Efficient Models: Learning with Less"' in note
    assert client.get(f"/api/papers/{uploaded['id']}/pdf").content == document


@pytest.mark.parametrize("title", [None, "", "Untitled", "2401.12345.pdf"])
def test_unhelpful_metadata_uses_multiline_first_page_title(
    client: TestClient, title: str | None,
) -> None:
    document = _pdf(FIRST_PAGE, title)

    response = client.put(
        "/api/papers/pdf", params={"name": "2401.12345.pdf"},
        content=document, headers=HEADERS,
    )

    assert response.status_code == 200, response.text
    assert [row["title"] for row in client.get("/api/papers").json()] == [
        "Learning Useful Representations with Limited Supervision",
    ]


@pytest.mark.parametrize("document", [
    pytest.param(_pdf(), id="blank"),
    pytest.param(_pdf(FIRST_PAGE, "Private Research Title", "secret"), id="encrypted"),
    pytest.param(b"%PDF-1.4 unreadable body", id="unreadable"),
])
def test_unextractable_pdf_keeps_filename_and_upload_succeeds(
    client: TestClient, document: bytes,
) -> None:
    response = client.put(
        "/api/papers/pdf", params={"name": "local manuscript.pdf"},
        content=document, headers=HEADERS,
    )

    assert response.status_code == 200, response.text
    assert [(row["id"], row["title"]) for row in client.get("/api/papers").json()] == [
        ("local manuscript", "local manuscript"),
    ]
    assert client.get("/api/papers/local manuscript/pdf").content == document


def test_duplicate_extracted_titles_preserve_both_notes_and_documents(
    client: TestClient, isolated_data: Path,
) -> None:
    first_pdf = _pdf(FIRST_PAGE, "Shared Research Title")
    second_pdf = _pdf(b"BT /F1 12 Tf 72 700 Td (Second document) Tj ET", "Shared Research Title")
    first = client.put(
        "/api/papers/pdf", params={"name": "first.pdf"},
        content=first_pdf, headers=HEADERS,
    )
    assert first.status_code == 200, first.text
    first_upload = first.json()
    first_note = isolated_data / first_upload["path"]
    original_note = first_note.read_bytes()

    second = client.put(
        "/api/papers/pdf", params={"name": "second.pdf"},
        content=second_pdf, headers=HEADERS,
    )

    assert second.status_code == 200, second.text
    second_upload = second.json()
    assert first_upload["id"] != second_upload["id"]
    assert [row["title"] for row in client.get("/api/papers").json()] == [
        "Shared Research Title", "Shared Research Title",
    ]
    assert first_note.read_bytes() == original_note
    assert (isolated_data / second_upload["path"]).is_file()
    assert client.get(f"/api/papers/{first_upload['id']}/pdf").content == first_pdf
    assert client.get(f"/api/papers/{second_upload['id']}/pdf").content == second_pdf
