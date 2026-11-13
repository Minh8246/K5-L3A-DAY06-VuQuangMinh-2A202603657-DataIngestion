"""Render chunks A and B side by side, page by page, as one local HTML file.

Run from starter/ after scripts/build_chunks.py:
    python scripts/view_chunks.py
Then open results/chunks_view.html in a browser (no server, no internet needed).
"""
import html
import json
from collections import defaultdict
from pathlib import Path

RESULTS = Path(__file__).resolve().parents[1] / "results"


def load(strategy: str) -> dict[tuple[str, int], list[dict]]:
    by_page = defaultdict(list)
    for line in (RESULTS / f"chunks_{strategy}.jsonl").read_text(encoding="utf-8").splitlines():
        if line.strip():
            c = json.loads(line)
            by_page[(c["document_id"], c["page"])].append(c)
    return by_page


def card(c: dict) -> str:
    text = html.escape(c["text"])
    if c["text"].startswith("[Điều"):
        end = text.find("]") + 1
        text = f'<span class="hdr">{text[:end]}</span>{text[end:]}'
    m = c["metadata"]
    return (f'<div class="card"><div class="meta"><b>{html.escape(c["chunk_id"])}</b>'
            f'<span>{html.escape(m.get("article") or "-")}</span><span>{len(c["text"])} ký tự</span>'
            f'<span>chars {m["char_start"]}–{m["char_end"]}</span></div><p>{text}</p></div>')


def main() -> None:
    a, b = load("A"), load("B")
    pages = sorted(set(a) | set(b), key=lambda k: (k[0], k[1]))
    options = "".join(f'<option value="{d}:{p}">{d} — trang {p} (A {len(a[(d, p)])} / B {len(b[(d, p)])})</option>'
                      for d, p in pages)
    sections = "".join(
        f'<section data-page="{d}:{p}"><div class="col"><h2>A · cố định 500/50</h2>'
        f'{"".join(card(c) for c in a[(d, p)])}</div><div class="col"><h2>B · theo cấu trúc</h2>'
        f'{"".join(card(c) for c in b[(d, p)])}</div></section>'
        for d, p in pages)
    page = f"""<!doctype html><html lang="vi"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1"><title>Chunks A vs B</title>
<style>
:root{{--bg:#f6f7f9;--card:#fff;--text:#1d2330;--muted:#5b6475;--line:#d9dde5;--hdr:#fff3c4}}
@media (prefers-color-scheme:dark){{:root{{--bg:#14171c;--card:#1d2129;--text:#e6e8ec;--muted:#9aa3b2;--line:#323844;--hdr:#4a3f12}}}}
body{{margin:0;font:15px/1.55 system-ui,sans-serif;background:var(--bg);color:var(--text)}}
header{{position:sticky;top:0;background:var(--bg);border-bottom:1px solid var(--line);padding:12px 16px;display:flex;gap:12px;align-items:center;flex-wrap:wrap}}
select,button{{font:inherit;padding:6px 10px;border:1px solid var(--line);border-radius:6px;background:var(--card);color:var(--text)}}
section{{display:none;grid-template-columns:1fr 1fr;gap:16px;padding:16px}} section.on{{display:grid}}
@media (max-width:800px){{section.on{{grid-template-columns:1fr}}}}
h2{{font-size:15px;margin:0 0 8px;color:var(--muted)}}
.card{{background:var(--card);border:1px solid var(--line);border-radius:8px;padding:10px 12px;margin-bottom:10px}}
.meta{{display:flex;gap:10px;flex-wrap:wrap;font-size:12px;color:var(--muted);margin-bottom:6px}}
.card p{{margin:0;white-space:pre-wrap;overflow-wrap:anywhere}} .hdr{{background:var(--hdr);border-radius:3px}}
</style></head><body>
<header><button id="prev">◀</button><select id="sel">{options}</select><button id="next">▶</button>
<span style="color:var(--muted);font-size:13px">Nền vàng = tiêu đề Điều do chiến lược B chèn thêm</span></header>
{sections}
<script>
const sel=document.getElementById('sel'),secs=[...document.querySelectorAll('section')];
function show(){{secs.forEach(s=>s.classList.toggle('on',s.dataset.page===sel.value));}}
sel.onchange=show;
document.getElementById('prev').onclick=()=>{{if(sel.selectedIndex>0){{sel.selectedIndex--;show();}}}};
document.getElementById('next').onclick=()=>{{if(sel.selectedIndex<sel.options.length-1){{sel.selectedIndex++;show();}}}};
show();
</script></body></html>"""
    out = RESULTS / "chunks_view.html"
    out.write_text(page, encoding="utf-8")
    print(f"Wrote {out} ({len(pages)} pages)")


if __name__ == "__main__":
    main()
