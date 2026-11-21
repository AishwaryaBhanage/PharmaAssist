"""Parse every catalog PDF with Docling (cached by source hash + options) and report what was found.

Run: python scripts/parse_docs.py [--doc <doc_id>]
Writes reports/parsing/PARSE_REPORT.json with per-document timings, tables and the figure inventory.
"""

import argparse
import json
import time
from collections import Counter

from pharmassist.catalog import docs_dir, load_catalog
from pharmassist.config import PROJECT_ROOT
from pharmassist.parsers.docling_parser import parse_cached


def main():
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--doc", action="append", help="only these doc ids")
    args = ap.parse_args()
    report = {}
    for e in load_catalog():
        if not e["file"].lower().endswith(".pdf") or (args.doc and e["id"] not in args.doc):
            continue
        t0 = time.perf_counter()
        r = parse_cached(docs_dir() / e["file"], e["id"])
        kinds = Counter(b["type"] for b in r["blocks"])
        report[e["id"]] = {"pages": r["pages"], "convert_seconds": r["seconds"],
                           "this_run_seconds": round(time.perf_counter() - t0, 1),
                           "blocks": dict(kinds), "figures": len(r["figures"]),
                           "figures_by_source": dict(Counter(f["source"] for f in r["figures"]))}
        print(f"{e['id']:<36} {r['pages']:>4} pp  {dict(kinds)}  figures {len(r['figures'])}"
              f"  ({r['seconds']}s convert)", flush=True)
    out = PROJECT_ROOT / "reports" / "parsing" / "PARSE_REPORT.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    old = json.loads(out.read_text()) if out.exists() else {}
    out.write_text(json.dumps({**old, **report}, indent=1) + "\n")


if __name__ == "__main__":
    main()
