"""The VA National Formulary spreadsheet as rows, and the lookup over them.

The header row is found by its labels, not assumed. Each row keeps its original cell values, the
sheet name and its spreadsheet row number (1-based, as Excel shows it), plus normalized search
fields. The notes above the header (dosage-form rule, PA levels, U/E) are kept with their rows so
results can cite them.
"""

import json
import re
from dataclasses import dataclass
from datetime import datetime
from functools import cache
from pathlib import Path

import pandas as pd

from pharmassist.catalog import docs_dir, load_catalog
from pharmassist.tables import match

DOC_ID = "va_national_formulary_2026_09"
SHEET = "Formulary"
HEADER = ["VA Class", "Restriction", "Generic", "Dosage Form", "Comments", "U/E Formulary",
          "Clinical Guidance"]
FIELDS = ["va_class", "restriction", "generic", "dosage_form", "comments", "ue_formulary",
          "clinical_guidance"]
# words people use for a dosage form, mapped to the formulary's abbreviations
FORM_WORDS = {"tablet": "tab", "tablets": "tab", "tabs": "tab", "capsule": "cap", "capsules": "cap",
              "caps": "cap", "injection": "inj", "injectable": "inj", "solution": "soln",
              "patches": "patch", "transdermal": "patch", "sl": "sublingual", "films": "film",
              "suspension": "susp", "cream": "cream", "ointment": "oint", "pen": "inj"}


@dataclass
class Formulary:
    rows: pd.DataFrame            # one row per drug row; index = spreadsheet row number
    header_row: int
    notes: dict[int, str]         # spreadsheet row -> note text, for the rows above the header
    rule_row: int                 # the dosage-form-specific rule
    pa_row: int                   # the PA-N / PA-V / PA-F definitions


def locator(row: int) -> str:
    return f"{DOC_ID}:r{row}"


def row_id(row: int) -> str:
    return f"{DOC_ID}#{SHEET}#row-{row}"


def _path():
    entry = next(e for e in load_catalog() if e["id"] == DOC_ID)
    return docs_dir() / entry["file"]


def _brands(generic: str) -> list[str]:
    """Brand names the row itself states, e.g. 'SEMAGLUTIDE (EQV-OZEMPIC)' -> ['ozempic']."""
    out = []
    for group in re.findall(r"EQV-([^)]+)\)", generic):
        out += [match.norm(b) for b in re.split(r"/| and ", group) if b.strip()]
    return out


def _base(generic: str) -> str:
    """The name without parenthetical notes: 'SEMAGLUTIDE (EQV-OZEMPIC)' -> 'semaglutide'."""
    return match.norm(re.sub(r"\([^)]*\)", " ", generic))


# salt words dropped only from the end of a single-ingredient name: 'metformin hcl' -> 'metformin'
SALTS = {"hcl", "hydrochloride", "sodium", "potassium", "calcium", "so4", "sulfate", "mesylate",
         "maleate", "tartrate", "succinate", "besylate", "citrate", "acetate", "phosphate", "bitartrate"}


def _without_salt(base: str) -> str:
    words = base.split()
    while len(words) > 1 and words[-1] in SALTS:
        words.pop()
    return " ".join(words)


def artifact_path():
    from pharmassist.config import project_path
    return project_path("index") / "tables" / "va_formulary_cells.json"


def _read_sheet(path=None) -> pd.DataFrame:
    raw = pd.read_excel(path or _path(), sheet_name=SHEET, header=None, dtype=str, usecols="A:G").fillna("")
    raw.index = raw.index + 1  # spreadsheet row numbers
    return raw


def build(path=None) -> dict:
    """Save the sheet's cells (with spreadsheet row numbers) so lookups never read the xlsx while
    answering. The ingestion worker calls this with the copy it downloaded."""
    import hashlib
    src = Path(path) if path else _path()
    raw = _read_sheet(src)
    out = artifact_path()
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps({"sheet": SHEET, "rows": {str(i): r.tolist() for i, r in raw.iterrows()}},
                              ensure_ascii=False))
    manifest = {"source": src.name, "sha256": hashlib.sha256(src.read_bytes()).hexdigest(),
                "rows": len(raw), "built_at": datetime.now().isoformat(timespec="seconds")}
    out.with_suffix(".manifest.json").write_text(json.dumps(manifest, indent=2) + "\n")
    load.cache_clear()
    return manifest


def _cells() -> pd.DataFrame:
    """The saved cells when the artifact exists, else the spreadsheet itself."""
    path = artifact_path()
    if not path.exists():
        return _read_sheet()
    rows = json.loads(path.read_text())["rows"]
    return pd.DataFrame.from_dict({int(i): v for i, v in rows.items()}, orient="index").sort_index()


@cache
def load() -> Formulary:
    return from_cells(_cells())


def from_cells(raw: pd.DataFrame) -> Formulary:
    """A Formulary from the sheet's cells (index = spreadsheet row number, 7 string columns A:G),
    wherever they came from: the local artifact, the xlsx, or the store's table rows (v2)."""
    header_row = next(i for i, r in raw.iterrows() if [v.strip() for v in r.tolist()] == HEADER)
    notes = {i: raw.at[i, 0].strip() for i in raw.index[raw.index < header_row] if raw.at[i, 0].strip()}
    rule_row = next(i for i, t in notes.items() if "dosage form specific" in t)
    pa_row = next(i for i, t in notes.items() if "PA-F" in t)

    rows = raw[raw.index > header_row].copy()
    rows.columns = FIELDS
    rows = rows[(rows != "").any(axis=1)]
    rows["generic_norm"] = rows["generic"].map(match.norm)
    rows["name_base"] = rows["generic"].map(_base)
    rows["name_no_salt"] = rows["name_base"].map(lambda b: b if "/" in b else _without_salt(b))
    rows["components"] = rows["name_base"].map(lambda b: [c.strip() for c in b.split("/") if c.strip()])
    rows["brands"] = rows["generic"].map(_brands)
    rows["form_norm"] = rows["dosage_form"].map(match.norm)
    rows["form_tokens"] = rows["form_norm"].map(lambda f: set(re.split(r"[\s,/]+", f)) - {"", "or"})
    return Formulary(rows, header_row, notes, rule_row, pa_row)


def row_text(row: int) -> str:
    """One row as 'column: value' lines, for the groundedness judge."""
    f = load()
    if row in f.notes:
        return f"Note row {row}: {f.notes[row]}"
    if row == f.header_row:
        return "Header row: " + " | ".join(HEADER)
    r = f.rows.loc[row]
    return "\n".join(f"{h}: {r[k].strip()}" for h, k in zip(HEADER, FIELDS))


def _form_tokens(form: str) -> set[str]:
    words = re.split(r"[\s,/]+", match.norm(form))
    return {FORM_WORDS.get(w, w) for w in words if w}


def _row_out(f: Formulary, row: int, matched_on: str, strengths: list[str]) -> dict:
    r = f.rows.loc[row]
    out = {"row_id": row_id(row), "cite": {"doc_id": DOC_ID, "row": int(row)},
           "sheet": SHEET, "row": int(row), "matched_on": matched_on}
    out.update({h: r[k].strip() for h, k in zip(HEADER, FIELDS)})
    restriction = r["restriction"].strip()
    out["Restriction meaning"] = (f"{restriction}: prior authorization required (see row {f.pa_row})"
                                  if restriction else "no restriction listed")
    ue = r["ue_formulary"].strip()
    if ue.startswith("http"):
        out["U/E Formulary"] = "(the cell holds a link, not a Yes/No value)"
    if strengths:
        text = match.norm(" ".join([r["generic"], r["comments"], r["ue_formulary"]])).replace(" ", "")
        # '8mg' must stand alone: '8mg/2mg' is a combination strength, not 8 mg
        found = [s for s in strengths
                 if re.search(rf"(?<![\d./]){re.escape(match.norm(s).replace(' ', ''))}(?![\d/])", text)]
        out["strength"] = (f"{', '.join(found)} stated in this row" if found else
                           f"{', '.join(strengths)} not stated in this row; the formulary lists "
                           "products by dosage form, not strength")
    return out


def lookup(drug: str, dosage_form: str | None = None, formulary: Formulary | None = None) -> dict:
    """Formulary rows for a drug name (generic, or a brand the formulary states as EQV-),
    optionally narrowed to a dosage form. Never picks a fuzzy match. `formulary` overrides the
    locally loaded sheet (the v2 agent passes one built from the store's rows)."""
    f = formulary if formulary is not None else load()
    q, strengths = match.split_strengths(match.norm(drug))
    rows = f.rows

    exact = rows.index[(rows["generic_norm"] == q) | (rows["name_base"] == q)
                       | (rows["name_no_salt"] == _without_salt(q))
                       | rows["brands"].map(lambda b: q in b)]
    combos = rows.index[rows["components"].map(lambda c: len(c) > 1 and q in c)].difference(exact)

    def why(i):
        if i in combos:
            return f"combination product containing {q}"
        named = q in (rows.at[i, "name_base"], rows.at[i, "generic_norm"])
        if not named and q in rows.at[i, "brands"]:
            return f"brand stated in the row ({rows.at[i, 'generic'].strip()})"
        if not named:
            return f"same drug, salt named in the row ({rows.at[i, 'generic'].strip()})"
        return "generic name"

    result = {"source": f"VA National Formulary, sheet {SHEET} (header row {f.header_row})",
              "query": {"drug": drug, "dosage_form": dosage_form},
              "rule": {"cite": {"doc_id": DOC_ID, "row": f.rule_row}, "text": f.notes[f.rule_row]},
              "pa_levels": {"cite": {"doc_id": DOC_ID, "row": f.pa_row}, "text": f.notes[f.pa_row]}}
    found = list(exact) + list(combos)
    if not found:
        names = list(rows["name_base"]) + [b for bs in rows["brands"] for b in bs]
        suggestions = match.fuzzy(q, names)
        if suggestions:
            result.update(result=match.FUZZY, suggestions=suggestions,
                          note="No row matches this name. These are close names, not matches: "
                               "confirm the intended drug before relying on any of them.")
        else:
            result.update(result=match.NO_MATCH,
                          note="No row matches this name. That doesn't mean the drug is non-formulary "
                               "or not covered: the name may be spelled or listed differently.")
        return result

    if dosage_form:
        wanted = _form_tokens(dosage_form)
        in_form = [i for i in found if wanted <= rows.at[i, "form_tokens"]]
        if not in_form:
            result.update(
                result=match.FORM_NOT_LISTED,
                note=f"{drug} is listed, but not as {dosage_form}. Per row {f.rule_row}, the formulary "
                     "is dosage-form specific: a dosage form that isn't listed is non-formulary, even "
                     "when other forms of the same drug are formulary. The listed forms follow.",
                rows=[_row_out(f, i, why(i), strengths) for i in found])
            return result
        found = in_form

    result.update(result=match.EXACT if len(found) == 1 else match.MULTIPLE,
                  rows=[_row_out(f, i, why(i), strengths) for i in found])
    if len(found) > 1:
        result["note"] = ("Several rows match. List the relevant ones, or state which one you "
                          "assumed; each dosage form is a separate formulary entry.")
    return result
