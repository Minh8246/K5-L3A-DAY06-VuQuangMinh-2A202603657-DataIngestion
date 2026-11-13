"""Summarize the hand-filled audit sheets into results/audit_summary.json.

Run from starter/ after filling results/audit_*.csv:
    python scripts/summarize_audit.py
Reports, per strategy: coherence mean /2 (n), metadata all-correct n/N with the list of
errors, grounding counts of 0/1/2 and mean /2. Unfilled rows are counted as missing.
"""
import csv
import json
import sys
from pathlib import Path

RESULTS = Path(__file__).resolve().parents[1] / "results"
sys.stdout.reconfigure(encoding="utf-8")


def read(name: str) -> list[dict]:
    with open(RESULTS / name, encoding="utf-8-sig") as f:
        return list(csv.DictReader(f))


def scores(rows: list[dict]) -> tuple[list[int], int]:
    filled = [r["score_0_1_2"].strip() for r in rows if r["score_0_1_2"].strip()]
    bad = [s for s in filled if s not in {"0", "1", "2"}]
    if bad:
        raise SystemExit(f"invalid scores {bad}: use 0, 1 or 2")
    return [int(s) for s in filled], len(rows) - len(filled)


def main() -> None:
    summary = {}
    for strategy in ("A", "B", "C"):
        coh, coh_missing = scores([r for r in read("audit_coherence.csv") if r["strategy"] == strategy])
        gro_rows = [r for r in read("audit_grounding.csv") if r["strategy"] == strategy]
        gro, gro_missing = scores(gro_rows)
        meta = [r for r in read("audit_metadata.csv") if r["strategy"] == strategy]
        meta_filled = [r for r in meta if r["all_correct_YN"].strip()]
        meta_ok = sum(r["all_correct_YN"].strip().upper() == "Y" for r in meta_filled)
        summary[strategy] = {
            "coherence_mean_of_2": round(sum(coh) / len(coh), 2) if coh else None,
            "coherence_n": len(coh), "coherence_missing": coh_missing,
            "metadata_all_correct": f"{meta_ok}/{len(meta_filled)}",
            "metadata_missing": len(meta) - len(meta_filled),
            "metadata_errors": [f"{r['id']} #{r['rank']} {r['chunk_id']}: {r['error_note']}"
                                for r in meta_filled if r["all_correct_YN"].strip().upper() != "Y"],
            "grounding_counts": {s: gro.count(s) for s in (0, 1, 2)},
            "grounding_mean_of_2": round(sum(gro) / len(gro), 2) if gro else None,
            "grounding_missing": gro_missing,
        }
    (RESULTS / "audit_summary.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2),
                                                encoding="utf-8")
    print(json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
