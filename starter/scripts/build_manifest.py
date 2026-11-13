"""Measure the corpus PDFs and write data/manifest.csv + data/manifest_pages.csv.

Corpus utility, not the ingestion pipeline. Run from starter/:
    python scripts/build_manifest.py

Descriptive fields (title, URL, license, notes) are maintained by hand in SOURCES;
page counts, character counts and hashes are measured from the PDF files.
"""
import csv
import hashlib
import re
import unicodedata
from pathlib import Path

import pypdf
from pypdf import PdfReader

DATA = Path(__file__).resolve().parents[1] / "data"
ACCESSED_AT = "2026-11-13"
# A page counts as content when its extracted, NFC-normalized and trimmed text has at
# least this many characters. Scanned pages without a text layer give 0.
MIN_CONTENT_CHARS = 200
LICENSE = (
    "Văn bản quy phạm pháp luật / văn bản hành chính: không thuộc phạm vi bảo hộ "
    "quyền tác giả (khoản 2 Điều 15 Luật Sở hữu trí tuệ)"
)

SOURCES = [
    {
        "source_id": "tt08-2021",
        "title": "Quy chế đào tạo trình độ đại học (ban hành kèm theo Thông tư 08/2021/TT-BGDĐT)",
        "document_type": "thong_tu",
        "issued_date": "2021-03-18",
        "issued_year": 2021,
        "file": "tt08_2021_quy_che_dao_tao_dai_hoc.pdf",
        "source_url": "https://spnttw.edu.vn/wp-content/uploads/2021/05/thong-tu-08-1-da-gop.pdf",
        "notes": (
            "Bản sao do spnttw.edu.vn đăng, không phải cổng chính thức. "
            "Trang vật lý 1-2 là ảnh scan phần Thông tư (không có lớp chữ, chưa OCR). "
            "Trang vật lý 3-22 tương ứng trang in 1-20 của Quy chế."
        ),
    },
    {
        "source_id": "qd43-2007",
        "title": (
            "Quy chế đào tạo đại học và cao đẳng hệ chính quy theo hệ thống tín chỉ "
            "(Quyết định 43/2007/QĐ-BGDĐT, đã cập nhật sửa đổi theo Thông tư 57/2012/TT-BGDĐT)"
        ),
        "document_type": "quyet_dinh",
        "issued_date": "2007-08-15",
        "issued_year": 2007,
        "file": "qd43_2007_quy_che_tin_chi_sua_doi_2012.pdf",
        "source_url": "https://ins.htu.edu.vn/attachments/article/17/qd.pdf",
        "notes": (
            "Bản hợp nhất không chính thức do ins.htu.edu.vn đăng; chú thích cuối trang ghi "
            "điều khoản được sửa theo Thông tư 57/2012/TT-BGDĐT (hiệu lực 10/02/2013). "
            "Chưa đối chiếu với Văn bản hợp nhất 17/VBHN-BGDĐT."
        ),
    },
]


def page_ranges(pages: list[int]) -> str:
    """Compress [3, 4, 5, 9] into '3-5;9'."""
    out, start = [], None
    for i, p in enumerate(pages):
        if start is None:
            start = p
        if i == len(pages) - 1 or pages[i + 1] != p + 1:
            out.append(f"{start}-{p}" if start != p else str(p))
            start = None
    return ";".join(out)


def main() -> None:
    extractor = f"pypdf {pypdf.__version__}"
    doc_rows, page_rows = [], []
    for src in SOURCES:
        path = DATA / src["file"]
        reader = PdfReader(path)
        counted, excluded, counted_chars = [], [], 0
        for number, page in enumerate(reader.pages, start=1):
            raw = page.extract_text() or ""
            text = unicodedata.normalize("NFC", raw).strip()
            printed = re.match(r"\s*(\d{1,3})\s", raw)
            is_content = len(text) >= MIN_CONTENT_CHARS
            reason = "" if is_content else ("no_text_layer" if not text else "too_short")
            if is_content:
                counted.append(number)
                counted_chars += len(text)
            else:
                excluded.append(number)
            page_rows.append({
                "source_id": src["source_id"],
                "page_id": f"{src['source_id']}:p{number:02d}",
                "physical_page": number,
                "printed_page": printed.group(1) if printed else "",
                "chars": len(text),
                "counted": int(is_content),
                "exclusion_reason": reason,
            })
        doc_rows.append({
            "source_id": src["source_id"],
            "title": src["title"],
            "document_type": src["document_type"],
            "issued_date": src["issued_date"],
            "issued_year": src["issued_year"],
            "source_path_or_url": src["source_url"],
            "local_path": f"data/{src['file']}",
            "license_or_permission": LICENSE,
            "accessed_at": ACCESSED_AT,
            "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
            "physical_pages": len(reader.pages),
            "counted_pages": len(counted),
            "counted_page_list": page_ranges(counted),
            "excluded_page_list": page_ranges(excluded),
            "counted_chars": counted_chars,
            "extractor": extractor,
            "counting_rule": f"NFC text >= {MIN_CONTENT_CHARS} chars",
            "notes": src["notes"],
        })

    for name, rows in (("manifest.csv", doc_rows), ("manifest_pages.csv", page_rows)):
        with open(DATA / name, "w", encoding="utf-8", newline="") as f:
            writer = csv.DictWriter(f, fieldnames=list(rows[0]))
            writer.writeheader()
            writer.writerows(rows)

    total = sum(r["counted_pages"] for r in doc_rows)
    for r in doc_rows:
        print(f"{r['source_id']}: {r['counted_pages']}/{r['physical_pages']} pages counted "
              f"({r['counted_page_list']}), {r['counted_chars']} chars, excluded: {r['excluded_page_list'] or '-'}")
    print(f"TOTAL counted content pages: {total} (requirement: >= 30)")


if __name__ == "__main__":
    main()
