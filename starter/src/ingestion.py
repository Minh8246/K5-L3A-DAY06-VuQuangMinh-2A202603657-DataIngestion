"""Read and normalize the corpus PDFs, keeping every chunk traceable to its physical page."""
import csv
import logging
import re
import unicodedata
from pathlib import Path
from typing import Any

from pypdf import PdfReader

from .models import DocumentPage

# pypdf logs a fontTools warning for every page of these PDFs; it does not change the text.
logging.getLogger("pypdf").setLevel(logging.ERROR)

# Same counting rule as scripts/build_manifest.py: a page is content when its NFC text,
# trimmed, has at least this many characters. Pages below it are logged and skipped.
MIN_CONTENT_CHARS = 200

# Printed page number alone on the first line, e.g. "11".
_PAGE_NUMBER = re.compile(r"^\d{1,3}$")
# QD43 footnotes: "7 Điều này được sửa đổi theo ... Thông tư số 57/2012/TT-BGDĐT".
# Requiring "sửa đổi"/"bổ sung" on the same line avoids body lines such as
# "3 Điều này, còn áp dụng cho ..." (QD43 p14), which is real content.
_FOOTNOTE_START = re.compile(
    r"^(\d{1,2}) (?:Điều|Khoản|Điểm|Cụm từ)\b.*(?:được sửa đổi|được bổ sung|sửa đổi bởi)"
)
# Article heading at the start of a line: "Điều 15. Nghỉ học tạm thời, thôi học".
ARTICLE_HEADING = re.compile(r"^Điều (\d+[a-z]?)\.\s*(.*)$", re.MULTILINE)


def normalize_text(text: str) -> str:
    """NFC-normalize and clean whitespace while keeping one line per extracted line.

    Line breaks are kept because structure-aware chunking needs to see lines that
    start with "Chương", "Điều 15.", "1." or "a)". Spaces inside words that pypdf
    inserted ("Thông t ư") are NOT repaired: there is no safe general rule.
    """
    text = unicodedata.normalize("NFC", text)
    text = text.replace(" ", " ").replace("\t", " ").replace("\r", "\n")
    lines = (re.sub(r" {2,}", " ", line).strip() for line in text.split("\n"))
    return "\n".join(line for line in lines if line)


def strip_page_number(text: str) -> tuple[str, str]:
    """Remove the printed page number line at the top; return (text, printed_page)."""
    first, _, rest = text.partition("\n")
    if _PAGE_NUMBER.match(first):
        return rest, first
    return text, ""


def strip_footnotes(text: str) -> tuple[str, list[str]]:
    """Remove the amendment footnote block at the bottom of a QD43 page.

    Footnote markers glued to the body ("buộc thôi học7", "1.3 Khi", "c)5 Không")
    are removed only for the footnote numbers found on this page, so ordinary
    numbers such as "cao đẳng 2" stay untouched.
    """
    lines = text.split("\n")
    start = next((i for i, line in enumerate(lines) if _FOOTNOTE_START.match(line)), None)
    if start is None:
        return text, []
    footnotes = "\n".join(lines[start:])
    numbers = sorted({m.group(1) for line in lines[start:]
                      if (m := _FOOTNOTE_START.match(line))}, key=len, reverse=True)
    body = "\n".join(lines[:start])
    for n in numbers:
        body = re.sub(rf"(?<=[^\d\s]){n}$", "", body, flags=re.MULTILINE)      # "học phần1"
        body = re.sub(rf"^(\d{{1,2}}\.){n}(?= )", r"\1", body, flags=re.MULTILINE)  # "1.3 Khi"
        body = re.sub(rf"^([a-zđ]\)){n}(?= )", r"\1", body, flags=re.MULTILINE)     # "c)5 Không"
    return body, [f for f in footnotes.split("\n") if f]


def load_pdf(path: Path, document_id: str, source: str) -> list[DocumentPage]:
    """Extract every physical page (1-based) and record why a page is not usable.

    All pages are returned so the caller can log them; metadata["status"] is
    "ok", "no_text_layer" (scan without OCR) or "too_short".
    """
    pages = []
    for number, pdf_page in enumerate(PdfReader(path).pages, start=1):
        raw = pdf_page.extract_text() or ""
        raw_chars = len(unicodedata.normalize("NFC", raw).strip())
        if raw_chars == 0:
            status = "no_text_layer"
        elif raw_chars < MIN_CONTENT_CHARS:
            status = "too_short"
        else:
            status = "ok"

        text = normalize_text(raw)
        text, printed_page = strip_page_number(text)
        text, footnotes = strip_footnotes(text)
        pages.append(DocumentPage(
            document_id=document_id,
            source=source,
            page=number,
            text=text,
            metadata={
                "status": status,
                "raw_chars": raw_chars,
                "clean_chars": len(text),
                "printed_page": printed_page,
                "footnotes_removed": len(footnotes),
            },
        ))
    return pages


def load_corpus(manifest_path: Path, base_dir: Path) -> tuple[list[DocumentPage], list[dict[str, Any]]]:
    """Load every document listed in the manifest.

    Returns (content_pages, log_rows). Content pages carry filter metadata from the
    manifest (issued_year, document_type) and the article in force at the top of the
    page, so a chunk that starts mid-article can still be traced to "Điều N".
    log_rows has one row per physical page, including skipped ones.
    """
    content, log_rows = [], []
    with open(manifest_path, encoding="utf-8") as f:
        documents = list(csv.DictReader(f))

    for doc in documents:
        current_article: dict[str, str] | None = None
        for page in load_pdf(base_dir / doc["local_path"], doc["source_id"], doc["local_path"]):
            page.metadata.update({
                "issued_year": int(doc["issued_year"]),
                "document_type": doc["document_type"],
                "article_at_start": current_article,
            })
            headings = ARTICLE_HEADING.findall(page.text)
            if headings:
                number, title = headings[-1]
                current_article = {"article": f"Điều {number}", "title": title.strip()}

            log_rows.append({
                "page_id": f"{page.document_id}:p{page.page:02d}",
                "document_id": page.document_id,
                "page": page.page,
                "printed_page": page.metadata["printed_page"],
                "status": page.metadata["status"],
                "raw_chars": page.metadata["raw_chars"],
                "clean_chars": page.metadata["clean_chars"],
                "footnotes_removed": page.metadata["footnotes_removed"],
                "articles_starting": ";".join(f"Điều {n}" for n, _ in headings),
            })
            if page.metadata["status"] == "ok":
                content.append(page)
    return content, log_rows
