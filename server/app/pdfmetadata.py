from dataclasses import dataclass
from io import BytesIO
import math
import unicodedata

from pypdf import PdfReader
from pypdf.errors import PdfReadError
from pypdf.generic import DictionaryObject


@dataclass(frozen=True, slots=True)
class _Fragment:
    text: str
    size: float
    x: float
    y: float


def _clean(text: str) -> str:
    return " ".join(unicodedata.normalize("NFKC", text).replace("\x00", "").split())


def _usable(title: str, fallback: str) -> bool:
    folded = title.casefold()
    return (
        4 <= len(title) <= 500
        and sum(c.isalpha() for c in title) >= 3
        and folded not in {fallback.casefold(), "untitled", "untitled document", "document", "paper", "manuscript"}
        and not folded.endswith((".pdf", ".doc", ".docx", ".tex"))
        and not folded.startswith(("arxiv:", "microsoft word", "preprint", "submitted to", "proceedings of", "copyright"))
    )


def title_from_pdf(data: bytes, fallback: str) -> str:
    """Prefer document metadata, then a prominent heading on the first page."""
    try:
        with BytesIO(data) as stream:
            reader = PdfReader(stream)
            if reader.is_encrypted:
                return fallback
            metadata = reader.metadata
            title = _clean(metadata.title or "") if metadata else ""
            if _usable(title, fallback):
                return title
            if not reader.pages:
                return fallback
            page = reader.pages[0]
            fragments: list[_Fragment] = []

            def visit(text: str, cm: list[float], tm: list[float], font: DictionaryObject | None, size: float) -> None:
                text = _clean(text)
                x = tm[4] * cm[0] + tm[5] * cm[2] + cm[4]
                y = tm[4] * cm[1] + tm[5] * cm[3] + cm[5]
                upright = abs(tm[1] * cm[0] + tm[3] * cm[2]) < 0.01
                if text and upright and float(page.mediabox.bottom) + float(page.mediabox.height) * 0.55 < y <= float(page.mediabox.top):
                    fragments.append(_Fragment(text, size * math.hypot(cm[2], cm[3]), x, y))

            page.extract_text(orientations=(0,), visitor_text=visit)
            candidates = [f for f in fragments if _usable(f.text, fallback)]
            if not candidates:
                return fallback
            largest = max(f.size for f in candidates)
            heading = sorted((f for f in candidates if f.size >= largest * 0.95), key=lambda f: (-f.y, f.x))
            lines: list[str] = []
            previous_y = None
            for fragment in heading:
                if previous_y is not None and previous_y - fragment.y > largest * 2:
                    break
                lines.append(fragment.text)
                previous_y = fragment.y
            title = _clean(" ".join(lines))
            return title if _usable(title, fallback) else fallback
    except (PdfReadError, ValueError, RecursionError):
        return fallback
