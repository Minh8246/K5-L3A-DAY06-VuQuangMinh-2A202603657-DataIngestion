"""Fixed-size (strategy A) and structure-aware (strategy B/C) chunking.

Both work page by page, so `page` metadata is always exact. Trade-off: an article
that continues onto the next page is cut at the page break.
"""
import re
from typing import Any

from .ingestion import ARTICLE_HEADING
from .models import Chunk, DocumentPage

# A new paragraph starts at a chapter, an article, a clause "1." or a point "a)".
# Any other line is a hard-wrapped continuation of the previous one.
_PARAGRAPH_START = re.compile(r"^(?:Chương [IVXLC]+\b|Điều \d+[a-z]?\.|\d{1,2}\.\s|[a-zđ]\)\s)")
_STRUCTURAL_BREAK = re.compile(r"^(?:Chương [IVXLC]+\b|Điều \d+[a-z]?\.)")
_SENTENCE_END = re.compile(r"(?<=[.;:]) ")


def _article_at(page: DocumentPage, offset: int) -> dict[str, str] | None:
    """Article in force at a character offset of page.text."""
    article = page.metadata.get("article_at_start")
    for m in ARTICLE_HEADING.finditer(page.text):
        if m.start() > offset:
            break
        article = {"article": f"Điều {m.group(1)}", "title": m.group(2).strip()}
    return article


def _make_chunk(page: DocumentPage, strategy: str, index: int, text: str,
                start: int, end: int, extra: dict[str, Any]) -> Chunk:
    probe = start
    if page.text.startswith("Chương", start):
        # A chunk "Chương II ... Điều 6. ..." belongs to the article it introduces.
        first = ARTICLE_HEADING.search(page.text, start, end)
        probe = first.start() if first else start
    article = _article_at(page, probe)
    return Chunk(
        chunk_id=f"{page.document_id}:p{page.page:02d}:{strategy}:{index:03d}",
        document_id=page.document_id,
        source=page.source,
        page=page.page,
        text=text,
        metadata={
            "issued_year": page.metadata["issued_year"],
            "document_type": page.metadata["document_type"],
            "article": article["article"] if article else None,
            "strategy": strategy,
            "char_start": start,
            "char_end": end,
            **extra,
        },
    )


def fixed_size(page: DocumentPage, size: int, overlap: int) -> list[Chunk]:
    """Strategy A: character windows of `size` with `overlap`, ignoring structure.

    Line breaks become spaces (same length, so offsets still match page.text).
    Windows may cut words and sentences; that is the point of the baseline.
    """
    if not 0 <= overlap < size:
        raise ValueError("need 0 <= overlap < size")
    flat = page.text.replace("\n", " ")
    step = size - overlap
    chunks = []
    for index, start in enumerate(range(0, len(flat), step)):
        end = min(start + size, len(flat))
        chunks.append(_make_chunk(page, "A", index, flat[start:end].strip(), start, end,
                                  {"size": size, "overlap": overlap}))
        if end == len(flat):
            break
    return chunks


def _paragraphs(text: str) -> list[tuple[int, int, str]]:
    """Join hard-wrapped lines into paragraphs; return (start, end, text) per paragraph.

    Offsets index page.text; the paragraph text has line breaks replaced by spaces.
    """
    paragraphs, start, pos = [], 0, 0
    for line in text.split("\n"):
        if _PARAGRAPH_START.match(line) and pos > start:
            paragraphs.append((start, pos - 1, text[start:pos - 1].replace("\n", " ")))
            start = pos
        pos += len(line) + 1
    if pos - 1 > start:
        paragraphs.append((start, pos - 1, text[start:pos - 1].replace("\n", " ")))
    return paragraphs


def _split_long(start: int, text: str, max_size: int) -> list[tuple[int, str]]:
    """Split one oversized paragraph at sentence ends; hard-cut a sentence still too long."""
    pieces: list[tuple[int, str]] = []
    buf, buf_start, pos = "", start, start
    for sentence in _SENTENCE_END.split(text):
        if buf and len(buf) + 1 + len(sentence) > max_size:
            pieces.append((buf_start, buf))
            buf, buf_start = "", pos
        buf = f"{buf} {sentence}" if buf else sentence
        pos += len(sentence) + 1
    if buf:
        pieces.append((buf_start, buf))
    return [(s + i, piece[i:i + max_size]) for s, piece in pieces
            for i in range(0, len(piece), max_size)]


def by_paragraph(page: DocumentPage, max_size: int, with_header: bool = True) -> list[Chunk]:
    """Strategy B: pack whole paragraphs (clauses "1.", points "a)") of one article.

    - "Chương"/"Điều" headings always start a new chunk, so a chunk never mixes two
      articles; a chapter heading stays attached to the article right after it.
    - Within an article, paragraphs are packed until `max_size` characters.
    - A paragraph longer than `max_size` is split at sentence ends.
    - With `with_header`, a chunk that starts mid-article gets the prefix
      "[Điều N. title] " so it is understandable on its own (counts toward max_size).
    """
    chunks: list[Chunk] = []
    buf: list[str] = []
    buf_start = buf_end = 0

    def header_for(offset: int) -> str:
        article = _article_at(page, offset)
        # No header when the chunk already opens with its own "Chương ..."/"Điều N." heading.
        if (not with_header or not article or page.text.startswith("Chương", offset)
                or page.text.startswith(article["article"] + ".", offset)):
            return ""
        return f"[{article['article']}. {article['title']}] "

    def emit(start: int, end: int, body: str) -> None:
        chunks.append(_make_chunk(page, "B", len(chunks), header_for(start) + body, start, end,
                                  {"max_size": max_size, "with_header": with_header}))

    for p_start, p_end, para in _paragraphs(page.text):
        chapter_only = len(buf) == 1 and buf[0].startswith("Chương")
        starts_new_unit = _STRUCTURAL_BREAK.match(para) and not (chapter_only and para.startswith("Điều"))
        too_big = buf and len(header_for(buf_start)) + len(" ".join(buf)) + 1 + len(para) > max_size
        if buf and (starts_new_unit or too_big):
            emit(buf_start, buf_end, " ".join(buf))
            buf = []

        if not buf:
            buf_start = p_start
            budget = max_size - len(header_for(p_start))
            if len(para) > budget:
                for piece_start, piece in _split_long(p_start, para, budget):
                    emit(piece_start, piece_start + len(piece), piece)
                continue
        buf.append(para)
        buf_end = p_end

    if buf:
        emit(buf_start, buf_end, " ".join(buf))
    return chunks
