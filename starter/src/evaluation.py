"""Score retrieved chunks against gold evidence and keep a full per-query trace.

Definitions (GUIDE.md section 4):
- A retrieved chunk is a HIT when it comes from a gold (source, page) AND contains the
  whole evidence_quote. Any documented alt_gold counts. Matching ignores whitespace,
  because pypdf inserts spaces inside words ("Thông t ư").
- Hit@1: the top-1 chunk is a hit. Evidence Hit@3: at least one of the top-3 is a hit.
- A chunk on the right page that holds only part of the evidence is NOT a hit; it is
  flagged `page_match` so split-evidence errors can be counted separately.
Coherence and grounding are manual labels and are not inferred here.
"""
import re
import unicodedata
from typing import Any


def _key(text: str) -> str:
    return re.sub(r"\s+", "", unicodedata.normalize("NFC", text))


def gold_list(question: dict[str, Any]) -> list[tuple[str, int, str]]:
    golds = [(question["gold_source_id"], question["gold_page"], question["evidence_quote"])]
    golds += [(g["source_id"], g["page"], g["evidence_quote"]) for g in question.get("alt_gold", [])]
    return golds


def evaluate_query(question: dict[str, Any], hits: list[dict[str, Any]]) -> dict[str, Any]:
    """Label each retrieved chunk and compute hit@1 / hit@3 for one question."""
    golds = gold_list(question)
    gold_pages = {(sid, page) for sid, page, _ in golds}
    wanted = question.get("filter") or {}
    ranked = []
    for rank, hit in enumerate(hits, start=1):
        text = _key(hit["text"])
        on_gold_page = (hit["document_id"], hit["page"]) in gold_pages
        is_hit = any(hit["document_id"] == sid and hit["page"] == page and _key(ev) in text
                     for sid, page, ev in golds)
        ranked.append({
            "rank": rank,
            "chunk_id": hit["chunk_id"],
            "document_id": hit["document_id"],
            "page": hit["page"],
            "article": hit.get("article"),
            "issued_year": hit.get("issued_year"),
            "score": hit["score"],
            "is_hit": is_hit,
            "page_match": on_gold_page,
            "matches_filter": all(hit.get(k) == v for k, v in wanted.items()) if wanted else None,
            "text": hit["text"],
        })
    first_hit = next((r["rank"] for r in ranked if r["is_hit"]), None)
    return {
        "hit@1": first_hit == 1,
        "hit@3": first_hit is not None and first_hit <= 3,
        "first_hit_rank": first_hit,
        "gold_page_in_top3": any(r["page_match"] for r in ranked[:3]),
        "top3_all_match_filter": all(r["matches_filter"] for r in ranked[:3]) if wanted else None,
        "results": ranked,
    }


def summarize(traces: list[dict[str, Any]]) -> dict[str, Any]:
    """Aggregate by strategy and split; report numerator/denominator, not only rates."""
    groups: dict[tuple[str, str], list[dict[str, Any]]] = {}
    for t in traces:
        groups.setdefault((t["strategy"], t["split"]), []).append(t)
    summary = {}
    for (strategy, split), items in sorted(groups.items()):
        n = len(items)
        h1 = sum(t["hit@1"] for t in items)
        h3 = sum(t["hit@3"] for t in items)
        split_evidence = sum(1 for t in items if not t["hit@3"] and t["gold_page_in_top3"])
        filtered = [t for t in items if t["question_filter"]]
        compliant = sum(1 for t in filtered if t["top3_all_match_filter"])
        summary[f"{strategy}/{split}"] = {
            "n": n,
            "hit@1": f"{h1}/{n}", "hit@1_rate": round(h1 / n, 3),
            "hit@3": f"{h3}/{n}", "hit@3_rate": round(h3 / n, 3),
            "miss_but_gold_page_in_top3": split_evidence,
            "filter_questions": len(filtered),
            "filter_compliance_top3": f"{compliant}/{len(filtered)}" if filtered else "N/A",
        }
    return summary
