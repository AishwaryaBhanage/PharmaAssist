"""Decide every parsed image (decorative or vision), run vision extraction on the rest, check it.

Run after scripts/parse_docs.py:  python scripts/extract_figures.py [--dry-run]
--dry-run lists the decisions and the estimated vision cost without calling any model.

Writes storage/figures/records.json (read by the docling index build) and
reports/parsing/FIGURES.json (the inventory: every image, its decision, checks and status).
"""

import argparse
import json
from collections import Counter

from pharmassist.catalog import docs_dir, load_catalog
from pharmassist.config import PROJECT_ROOT, load_config
from pharmassist.parsers import figures as F
from pharmassist.parsers.docling_parser import parse_cached

EST_IN, EST_OUT = 2500, 4000   # tokens per figure, for the dry-run estimate


def main():
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()
    cfg = load_config()["figures"]
    price = cfg["prices_per_mtok"]
    spent, inventory, records = 0.0, [], {}
    todo = []
    for e in load_catalog():
        if not e["file"].lower().endswith(".pdf"):
            continue
        r = parse_cached(docs_dir() / e["file"], e["id"])
        for fig in r["figures"]:
            if F.expand_to_image(fig, docs_dir() / e["file"]):
                print(f"  {fig['figure_id']}: crop expanded to the full embedded image")
            d = F.decide(fig)
            inventory.append({**fig, "doc_id": e["id"], "decision": d,
                              "decorative_reason": (f"docling class {fig['classes'][0][0]}" if fig.get("classes")
                                                    else f"pdf image covering {fig.get('frac', 0):.1%} of the page")
                              if d == "decorative" else None})
            if d == "vision":
                todo.append((e, fig, inventory[-1]))

    est = len(todo) * (EST_IN * price["input"] + EST_OUT * price["output"]) / 1e6
    print(f"{len(inventory)} images: {dict(Counter(i['decision'] for i in inventory))}; "
          f"vision for {len(todo)} (est. ${est:.2f} if none cached)")
    if args.dry_run:
        for _, fig, _ in todo:
            print(f"  {fig['figure_id']:<44} {fig['source']:<9} {fig['classes'][:1]}")
        return

    if est > cfg["max_spend_usd"]:
        raise SystemExit(f"stopping: estimate ${est:.2f} is over max_spend_usd ${cfg['max_spend_usd']}")
    from concurrent.futures import ThreadPoolExecutor
    with ThreadPoolExecutor(max_workers=6) as pool:   # cached figures return immediately
        results = list(pool.map(lambda t: F.extract(t[1], t[0]), todo))
    for (e, fig, inv), res in zip(todo, results):
        u = res["usage"]
        cost = (u["input_tokens"] * price["input"] + u["output_tokens"] * price["output"]) / 1e6
        if not res["cached"]:
            spent += cost
        rec = res["record"]
        ocr = fig.get("ocr_text") or []
        if not ocr and rec.get("kind") != "decorative":
            ocr = F.ocr_crop(PROJECT_ROOT / fig["crop"])   # independent OCR of the crop for the checks
        rec = dict(rec)
        title_ok = F.title_supported(rec.get("title") or "", ocr, fig.get("caption"))
        if not title_ok:   # a title the image doesn't show was supplied by the model: don't index it
            rec["title"] = fig.get("caption") or ""
        chk = F.check(rec, ocr)
        status = F.status_for(fig["figure_id"], chk)
        indexed = rec.get("kind") != "decorative"
        inv.update({"vision_kind": rec.get("kind"), "title": rec.get("title"), "title_in_image": title_ok,
                    "checks": chk, "status": status,
                    "indexed": indexed, "vision_model": res["model"], "vision_cost_usd": round(cost, 4),
                    "unreadable": rec.get("unreadable") or [],
                    "decision": "vision" if indexed else "decorative",
                    "decorative_reason": rec.get("decorative_reason") if not indexed else None})
        if indexed:
            records[fig["figure_id"]] = {"record": rec, "status": status, "page": fig["page"],
                                         "bbox": fig["bbox"], "crop": fig["crop"], "doc_id": e["id"],
                                         "model": res["model"], "checks": chk}
        print(f"  {fig['figure_id']:<44} {rec.get('kind'):<12} {status:<20} "
              f"{'' if chk['passed'] else '; '.join(chk['problems'])[:120]}")

    out = PROJECT_ROOT / "storage" / "figures" / "records.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(records, indent=1))
    total_cost = sum(i.get("vision_cost_usd") or 0 for i in inventory)
    summary = {"images": len(inventory), "decisions": dict(Counter(i["decision"] for i in inventory)),
               "indexed_by_kind": dict(Counter(r["record"]["kind"] for r in records.values())),
               "status": dict(Counter(r["status"] for r in records.values())),
               "vision_cost_usd_all_figures": round(total_cost, 4), "spent_this_run_usd": round(spent, 4)}
    rep = PROJECT_ROOT / "reports" / "parsing" / "FIGURES.json"
    rep.write_text(json.dumps({"summary": summary, "figures": inventory}, indent=1) + "\n")
    print(json.dumps(summary, indent=1))


if __name__ == "__main__":
    main()
