"""NYRx PDL drug rows, extracted with a fixed-column pdfplumber reader for this document only.

Why not the generic parser or Docling (see reports/PDL_EXTRACTION.md): both recover the grid, but
neither keeps what tells drugs apart inside a cell. A wrapped drug name continues on a line indented
~8 pt, and the effective-date markers 1 and 2 are set at 6.96 pt like the ® sign, against 11.04 pt
text. So the grid comes from pdfplumber's find_tables(), and each drug cell's lines are rebuilt from
word positions and font sizes.

Pages 4–60 are the Preferred Drug Program (three columns: Preferred Drugs, Non-Preferred Drugs,
Coverage Parameters). Later pages use other layouts and stay in text search.
"""

import json
import re
from dataclasses import asdict, dataclass, field
from datetime import datetime
from functools import cache
from pathlib import Path

import pdfplumber

from pharmassist.catalog import docs_dir, load_catalog
from pharmassist.tables import match

DOC_ID = "ny_medicaid_pdl"
PDP_PAGES = range(4, 61)
METHOD = "pdfplumber fixed-column (find_tables grid + word size/indent)"
SMALL_PT = 9.0     # ®, ™ and the 1/2 markers are 6.96 pt; body text is 11.04 pt
INDENT_PT = 4.0    # a wrapped name's next line starts ~8 pt right of the cell's drug lines
LINE_GAP_PT = 5.0  # lines are ~12.5 pt apart; words within this of a line's top belong to it
SECTION = re.compile(r"^[IVX]+\.\s")
LEGEND = re.compile(r"(\d)\s*=\s*(Preferred|Non-Preferred)\s+as\s+of\s+(\d{1,2})/(\d{1,2})/(\d{4})")
# flags printed after a drug or class name, with where the PDL defines each (None: it doesn't)
FLAGS = {
    "CC": "Clinical Criteria: see the class's Coverage Parameters",
    "ST": "Step Therapy: see the class's Coverage Parameters",
    "F/Q/D": "Frequency/Quantity/Duration limits: see the class's Coverage Parameters",
    "DO": "Dose Optimization Program (PDL pages 80–84)",
    "BLTG": "Brand Less Than Generic Program (PDL pages 77–78)",
    "MR": None,
}


@dataclass
class Row:
    row_id: str                 # {doc_id}#p{page}#row-{n}, n counts drug rows on the page
    page: int
    drug_name: str              # as printed, wrapped lines joined
    drug_name_norm: str
    generic_of: str | None      # "(gen Victoza®)" -> "victoza": the brand this generic is stated to be
    section: str
    drug_class: str
    class_flags: list[str]
    status: str                 # "preferred" or "non-preferred": the column the drug is listed in
    flags: list[str]
    marker: dict | None         # {"code", "meaning", "becomes", "effective_date"}
    coverage_parameters: str    # the class's Coverage Parameters text (all its parts)
    coverage_pages: list[int]
    class_start_page: int
    continued_from_page: int | None   # set when this page continues the previous page's class
    extraction_method: str = METHOD
    name_base: str = field(default="")  # normalized name without "(gen ...)"


def _path():
    entry = next(e for e in load_catalog() if e["id"] == DOC_ID)
    return docs_dir() / entry["file"]


def _legend(text: str) -> dict:
    out = {}
    for code, status, m, d, y in LEGEND.findall(text):
        out[code] = {"code": code, "meaning": f"{status} as of {m}/{d}/{y}",
                     "becomes": status.lower(), "effective_date": f"{y}-{int(m):02d}-{int(d):02d}"}
    return out


def _split_flags(text: str) -> tuple[str, list[str]]:
    """'Victoza® BLTG' -> ('Victoza®', ['BLTG']); 'Nurtec® ODT CC, ST' -> ('Nurtec® ODT', ['CC', 'ST'])."""
    words = text.split()
    flags = []
    while words and words[-1].rstrip(",") in FLAGS:
        flags.insert(0, words.pop().rstrip(","))
    return " ".join(words).rstrip(", "), flags


def _in_cell(words: list[dict], bbox) -> list[dict]:
    """Words whose center lies in the cell. (within_bbox drops words that overhang a cell edge by
    a fraction of a point, which loses whole drug names.)"""
    x0, top, x1, bottom = bbox
    return [w for w in words if x0 <= (w["x0"] + w["x1"]) / 2 <= x1
            and top <= (w["top"] + w["bottom"]) / 2 <= bottom]


def _cell_lines(page_words: list[dict], bbox) -> list[dict]:
    """Lines in a cell: x0 of the first full-size word, the text, and any small 1/2 marker."""
    # a lone dash or bullet glyph in a drug cell is a stray mark (e.g. p45, beside Olumiant)
    words = [w for w in _in_cell(page_words, bbox)
             if w["size"] > 2 and w["text"].strip() and w["text"].strip() not in ("−", "–", "-", "•")]
    lines = []
    for w in sorted(words, key=lambda w: (round(w["top"]), w["x0"])):
        if lines and abs(w["top"] - lines[-1]["top"]) <= LINE_GAP_PT:
            lines[-1]["words"].append(w)
        else:
            lines.append({"top": w["top"], "words": [w]})
    out = []
    for line in lines:
        ws = sorted(line["words"], key=lambda w: w["x0"])
        full = [w for w in ws if w["size"] >= SMALL_PT]
        if not full:
            # a line of small text only: keep it when it's flags (e.g. 'MR' wrapped onto its own line)
            if all(w["text"].rstrip(",") in FLAGS for w in ws):
                out.append({"x0": ws[0]["x0"], "text": " ".join(w["text"] for w in ws), "marker": None})
            continue
        text, marker = "", None
        for w in ws:
            small = w["size"] < SMALL_PT
            if small and w["text"] in ("1", "2"):
                marker = w["text"]
            elif small and w["text"] in ("®", "™"):   # attach to the word before
                text = text.rstrip() + w["text"]
            elif small and w["text"].startswith(("®", "™")):  # e.g. '®BLTG': the sign, then a small flag
                text = text.rstrip() + w["text"][0] + " " + w["text"][1:]
            else:                  # full-size words, and small flags such as BLTG
                text += (" " if text and not text.endswith(" ") else "") + w["text"]
        out.append({"x0": full[0]["x0"], "text": " ".join(text.split()), "marker": marker})
    return out


def _left_edge(words: list[dict], x0: float, x1: float, top: float, bottom: float) -> float:
    """Where a column's unindented text starts: the leftmost full-size word in it."""
    xs = [w["x0"] for w in words if w["size"] >= SMALL_PT and x0 <= w["x0"] < x1
          and top <= w["top"] <= bottom]
    return min(xs) if xs else x0


def _entries(lines: list[dict], left: float) -> list[dict]:
    """Join wrapped lines: a line indented past the column's left text edge continues the previous
    name. `left` is measured over the whole column, so a one-line cell can still be a wrap."""
    entries = []
    for l in lines:
        flags_only = all(w.rstrip(",") in FLAGS for w in l["text"].split())
        if entries and (l["x0"] > left + INDENT_PT or flags_only):
            entries[-1]["text"] += " " + l["text"]
            entries[-1]["marker"] = entries[-1]["marker"] or l["marker"]
            entries[-1]["continued"] = True
        else:
            entries.append({**l, "continued": False,
                            "indented": l["x0"] > left + INDENT_PT or flags_only})
    return entries


def _cell_text(page_words: list[dict], bbox) -> str:
    """A coverage cell's text, line by line (® and ™ kept attached)."""
    return "\n".join(l["text"] for l in _cell_lines(page_words, bbox))


def extract(pages=PDP_PAGES, path=None) -> list[Row]:
    """All drug rows on the given PDL pages, in reading order. `path` overrides the catalog's file
    (the ingestion worker passes the copy it downloaded)."""
    rows: list[Row] = []
    classes: dict[tuple, dict] = {}   # (start page, class name) -> coverage parts
    current = None                    # the open class: carried to the next page only as a continuation
    with pdfplumber.open(path or _path()) as pdf:
        for pno in pages:
            page = pdf.pages[pno - 1]
            legend = _legend(page.extract_text() or "")
            words = page.extract_words(extra_attrs=["size"])
            n_on_page = 0
            seen_class_on_page = False
            section_on_page = None
            for table in page.find_tables():
                texts = table.extract()
                if not texts or (texts[0][0] or "").strip() != "Preferred Drugs":
                    continue  # not a PDP table
                head = table.rows[0].cells
                pref_x = (head[0][0], head[0][2])
                nonpref_x = (head[1][0], head[1][2])
                cov_x0 = head[2][0]
                below = (head[0][3], table.bbox[3])
                left = {"preferred": _left_edge(words, *pref_x, *below),
                        "non-preferred": _left_edge(words, *nonpref_x, *below)}
                for trow, text in zip(table.rows[1:], texts[1:]):
                    cells = trow.cells
                    first = " ".join((text[0] or "").split())
                    # a section or class heading spans the table; a drug cell ends at its column
                    spanning = cells[0] is not None and cells[0][2] > nonpref_x[1] + 3
                    if first and spanning:
                        if SECTION.match(first):
                            section_on_page = first
                            continue
                        name, cflags = _split_flags(first)
                        current = {"name": name, "flags": cflags, "section": section_on_page or "",
                                   "start": pno, "key": (pno, name), "cov_x0": cov_x0}
                        classes[current["key"]] = {"parts": [], "pages": []}
                        seen_class_on_page = True
                        continue
                    continued_from = None
                    if not seen_class_on_page:
                        # drug rows before any class heading: join the previous page's class only
                        # when the continuation is clear (same section, same columns)
                        clear = (current is not None and current["start"] < pno
                                 and current["section"] == (section_on_page or "")
                                 and abs(current["cov_x0"] - cov_x0) < 3)
                        if clear:
                            continued_from = current["start"]
                        else:
                            current = {"name": "(class heading not on this page)", "flags": [],
                                       "section": section_on_page or "", "start": pno,
                                       "key": (pno, "(unlabeled)"), "cov_x0": cov_x0}
                            classes.setdefault(current["key"], {"parts": [], "pages": []})
                        seen_class_on_page = True  # later rows on this page belong to it too
                    cov = [_cell_text(words, c) for c in cells if c and c[0] >= cov_x0 - 2]
                    cov = "\n".join(t for t in cov if t)
                    if cov:
                        classes[current["key"]]["parts"].append(cov)
                        classes[current["key"]]["pages"].append(pno)
                    for status, (x0, x1) in (("preferred", pref_x), ("non-preferred", nonpref_x)):
                        cell = next((c for c in cells if c and abs(c[0] - x0) < 3 and c[2] <= x1 + 3), None)
                        if cell is None:
                            continue
                        for e in _entries(_cell_lines(words, cell), left[status]):
                            # a wrap that crossed into the next table row: join the same column's last drug
                            prev = next((r for r in reversed(rows) if r.page == pno and r.status == status
                                         and r._key == current["key"]), None)
                            if e["indented"] and prev is not None:
                                prev.drug_name += " " + e["text"]
                                if e["marker"] and not prev.marker:
                                    prev.marker = legend.get(e["marker"])
                                continue
                            n_on_page += 1
                            name, flags = _split_flags(e["text"])
                            rows.append(Row(
                                row_id=f"{DOC_ID}#p{pno}#row-{n_on_page}", page=pno, drug_name=name,
                                drug_name_norm="", generic_of=None, section=current["section"],
                                drug_class=current["name"], class_flags=current["flags"], status=status,
                                flags=flags, marker=legend.get(e["marker"]) if e["marker"] else None,
                                coverage_parameters="", coverage_pages=[], class_start_page=current["start"],
                                continued_from_page=continued_from))
                            rows[-1]._key = current["key"]
            page.close()

    for r in rows:
        name, flags = _split_flags(r.drug_name)   # flags after a wrapped name end up at the end
        r.drug_name, r.flags = name, r.flags + [f for f in flags if f not in r.flags]
        r.drug_name_norm = match.norm(r.drug_name)
        gen = re.search(r"\(gen ([^)]*)\)", r.drug_name)
        r.generic_of = match.norm(gen.group(1)) if gen else None
        r.name_base = match.norm(re.sub(r"\(gen [^)]*\)", " ", r.drug_name))
        c = classes[r._key]
        r.coverage_parameters = "\n".join(c["parts"])
        r.coverage_pages = sorted(set(c["pages"]))
        del r._key
    return rows


# ---- the cached artifact: extraction takes ~1 min, lookups need it in milliseconds ----

def artifact_path():
    from pharmassist.config import project_path
    return project_path("index") / "tables" / "ny_pdl_rows.jsonl"


def build(path=None) -> dict:
    import hashlib
    src = Path(path) if path else _path()
    rows = extract(path=src)
    out = artifact_path()
    out.parent.mkdir(parents=True, exist_ok=True)
    with out.open("w") as f:
        for r in rows:
            f.write(json.dumps(asdict(r), ensure_ascii=False) + "\n")
    manifest = {"source": src.name, "sha256": hashlib.sha256(src.read_bytes()).hexdigest(),
                "pages": [PDP_PAGES.start, PDP_PAGES.stop - 1], "rows": len(rows), "method": METHOD,
                "built_at": datetime.now().isoformat(timespec="seconds")}
    out.with_suffix(".manifest.json").write_text(json.dumps(manifest, indent=2) + "\n")
    load.cache_clear()
    return manifest


@cache
def load() -> list[dict]:
    path = artifact_path()
    if not path.exists():
        raise FileNotFoundError(f"no PDL rows at {path}; run: python scripts/build_tables.py")
    return [json.loads(line) for line in path.open()]


# ---- lookup ----

RULES_PAGE = 1
RULES = ("Non-preferred drugs in these classes require prior authorization (PA), unless indicated "
         "otherwise. Preferred drugs that require PA are indicated by footnote. Not all drugs covered "
         "by NYRx are subject to programs included in this document.")


def _flag_meanings(flags: list[str]) -> dict:
    return {f: FLAGS.get(f) or "printed in the PDL; the PDL doesn't define it" for f in flags}


def _row_out(r: dict, matched_on: str) -> dict:
    out = {"row_id": r["row_id"], "cite": {"doc_id": DOC_ID, "page": r["page"]},
           "drug_name": r["drug_name"], "listed_as": r["status"],
           "flags": _flag_meanings(r["flags"]), "matched_on": matched_on}
    if r["marker"]:
        m = r["marker"]
        before = "non-preferred" if m["becomes"] == "preferred" else "preferred"
        out["effective_date_marker"] = (
            f"{m['code']} = {m['meaning']}. The PDL lists the drug in the column it moves to on "
            f"{m['effective_date']}: {m['becomes']} from that date, {before} before it.")
    return out


def _group(rows: list[tuple[dict, str]]) -> list[dict]:
    """Matched rows grouped by class, with each class's coverage parameters given once."""
    classes = {}
    for r, why in rows:
        key = (r["class_start_page"], r["drug_class"])
        c = classes.setdefault(key, {
            "drug_class": r["drug_class"], "section": r["section"],
            "class_flags": _flag_meanings(r["class_flags"]),
            "coverage_parameters": r["coverage_parameters"] or "(none printed)",
            "coverage_pages": r["coverage_pages"], "rows": []})
        if r["continued_from_page"]:
            c["note"] = (f"This class starts on page {r['class_start_page']} and continues onto later "
                         "pages (no new class heading).")
        c["rows"].append(_row_out(r, why))
    return list(classes.values())


def lookup(drug: str, drug_class: str | None = None, rows: list[dict] | None = None) -> dict:
    """PDL rows for a drug name (brand or generic as printed; a brand also finds the generic the PDL
    states as '(gen Brand)'), or for a drug class when no drug matches. Never picks a fuzzy match.
    `rows` (asdict(Row) dicts) overrides the local artifact; the v2 agent passes the store's rows."""
    rows = load() if rows is None else rows
    q = match.norm(drug)
    if drug_class:
        cq = match.norm(drug_class)
        rows = [r for r in rows if cq in match.norm(r["drug_class"])]
    q_tokens = match.tokens(q)

    found = []
    for r in rows:
        name, base = r["drug_name_norm"], r["name_base"]
        if q in (name, base):
            found.append((r, "exact name"))
        elif r["generic_of"] and q == r["generic_of"]:
            found.append((r, f"generic of {drug} (stated in the PDL as '(gen ...)')"))
        elif match.starts_with_words(base, q) or match.starts_with_words(name, q):
            found.append((r, "name plus strength or dosage form"))
        elif q_tokens and match.tokens(base)[:1] == q_tokens[:1] and set(q_tokens) <= set(match.tokens(name)):
            found.append((r, "name plus strength or dosage form"))

    result = {"source": "NYRx Preferred Drug List, Preferred Drug Program pages 4–60",
              "query": {"drug": drug, "drug_class": drug_class},
              "rules": {"cite": {"doc_id": DOC_ID, "page": RULES_PAGE}, "text": RULES}}
    if found:
        exact = [f for f in found if f[1] == "exact name"]
        label = match.EXACT if len(found) == 1 else match.MULTIPLE
        result.update(result=label, classes=_group(found))
        if len(found) > 1:
            result["note"] = ("Several rows match" + (f" ({len(exact)} by exact name)" if exact else "") +
                              ". List the relevant ones, or state which one you assumed.")
        return result

    in_class = [r for r in rows if q and (q in match.norm(r["drug_class"])
                or (q_tokens and set(q_tokens) <= set(match.tokens(match.norm(r["drug_class"])))))]
    if in_class:
        result.update(result=match.CLASS, classes=_group([(r, "drug class") for r in in_class]),
                      note=f"No drug is named '{drug}'; these are the rows of the matching drug class.")
        return result

    names = [r["name_base"] for r in rows] + [match.tokens(r["name_base"])[0] for r in rows
                                                if match.tokens(r["name_base"])]
    suggestions = match.fuzzy(q, names)
    if suggestions:
        result.update(result=match.FUZZY, suggestions=suggestions,
                      note="No row matches this name. These are close names, not matches: confirm the "
                           "intended drug before relying on any of them.")
    else:
        result.update(result=match.NO_MATCH,
                      note="No row in the Preferred Drug Program pages (4–60) matches this name. That "
                           "doesn't mean it isn't on the PDL or isn't covered: this lookup doesn't read "
                           "the PDL's other sections (CDRP, DUR F/Q/D, MAT formulary p76, BLTG, "
                           "mandatory generic, dose and cost optimization; pages 61–86), which "
                           "search_documents does; drugs outside the PDL's classes can still be "
                           "covered by NYRx (page 1); and the name may be listed differently.")
    return result
