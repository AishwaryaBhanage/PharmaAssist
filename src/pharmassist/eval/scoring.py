"""Scores that need no model: retrieval, Recall@k, citations, abstention, assumption, must_include,
length, latency percentiles, and the failure class.

Sources are locators: 'doc:p34' for a PDF page, 'doc:r1697' for a spreadsheet row. Gold formulary
cells ('A1697:G1697') become row locators. Scores come in two forms: over all gold, and over PDF
pages only, which is comparable across setups that can't reach the spreadsheet.
"""

import re

import numpy as np

ABSTAINED = ("not_in_documents", "out_of_scope", "unverified", "no_answer")  # unverified: verification abstained; no_answer: v2's public status
# statuses that give staff no answer: abstentions, plus a refusal or no submission
NON_ANSWERS = ABSTAINED + ("refused", "no_answer")


def useful(answerable: bool, status: str) -> bool:
    """An answerable question that received a non-abstaining answer (whatever its grade)."""
    return bool(answerable) and status not in NON_ANSWERS
# how an answer may name each program when it states its assumption
PROGRAM_NAMES = {"NY Medicaid": ("ny medicaid", "nyrx"), "Medicare Part D": ("part d", "medicare"),
                 "VA": ("va",)}


def gold_locators(gold: list[dict]) -> set[str]:
    """Every gold source: 'doc:pN' for pages; 'doc:rN' for each row a formulary cell range covers."""
    out = set()
    for g in gold:
        if "page" in g:
            out.add(f"{g['doc_id']}:p{g['page']}")
        else:
            rows = [int(n) for n in re.findall(r"\d+", g["cells"])]
            out.update(f"{g['doc_id']}:r{n}" for n in range(min(rows), max(rows) + 1))
    return out


def pages_only(locators: set[str]) -> set[str]:
    return {l for l in locators if re.search(r":p\d+$", l)}


def recall_at_k(gold: set[str], ranked: list[list[str]], k: int) -> float | None:
    """Share of gold pages covered by the top k units a search returned (a unit is a chunk or a
    parent section; each gives the pages it covers)."""
    top = {loc for unit in ranked[:k] for loc in unit}
    return _share(len(gold & top), len(gold))


def majority_grade(grades: list[str]) -> str:
    """The most common grade across judge passes; with no majority, the middle grade (partial)."""
    from collections import Counter
    grade, n = Counter(grades).most_common(1)[0]
    return grade if n > len(grades) / 2 else "partial"


def _share(part: int, whole: int) -> float | None:
    return round(part / whole, 3) if whole else None


def retrieval(gold: set, seen: set) -> dict:
    """Which gold pages any tool returned during the question."""
    found = gold & seen
    return {"found": sorted(found), "missed": sorted(gold - seen), "recall": _share(len(found), len(gold))}


def citation_scores(gold: set, cited: set) -> dict:
    """Precision is a lower bound: a correct citation to a page outside the gold set counts against it."""
    hit = gold & cited
    return {"precision": _share(len(hit), len(cited)), "recall": _share(len(hit), len(gold))}


def abstention_ok(answerable: bool, status: str) -> bool:
    return (status in ABSTAINED) != answerable


def assumed_program(program: str) -> str | None:
    """'unspecified (assumed NY Medicaid)' -> 'NY Medicaid'; None when the question names its program."""
    m = re.match(r"unspecified \(assumed (.+)\)", program)
    return m.group(1) if m else None


def plain(text: str) -> str:
    """Markdown down to words: no emphasis, headings, table rules or pipes."""
    text = re.sub(r"^\s*\|?[\s:|-]*-{3,}[\s:|-]*$", " ", text, flags=re.M)  # table separator rows
    return re.sub(r"[*_#`|>]", " ", text)


NO_PROGRAM_HEADER = "coverage program not specified"


def assumption_ok(program: str, answer: str, assumption: str | None) -> bool | None:
    """For a question without a program: the response header says so (the agent's fixed
    'Coverage program not specified', or an older 'Assuming <program>' opening), and the answer
    names the expected program somewhere (each claim names its program). None (n/a) when the
    question names its program."""
    expected = assumed_program(program)
    if expected is None:
        return None
    text = " ".join(plain(answer).split()).lower()
    names = PROGRAM_NAMES.get(expected, (expected.lower(),))
    header_ok = text.startswith(NO_PROGRAM_HEADER) or (text[:80].startswith("assuming")
                                                       and any(n in text[:80] for n in names))
    return header_ok and any(n in text for n in names)


def over_abstained(answerable: bool, status: str) -> bool:
    """Abstaining (including verification's 'unverified') on a question the documents answer."""
    return answerable and status in ABSTAINED


def _norm(text: str) -> str:
    return " ".join(text.lower().replace("’", "'").replace("‑", "-").split())


def must_include_substring(terms: list[str], answer: str) -> list[bool]:
    """Literal, case-insensitive. Strict: most terms are phrased as ideas, so the judge's
    paraphrase-aware check is the score; this is kept for reference."""
    a = _norm(answer)
    return [_norm(t) in a for t in terms]


def word_count(answer: str) -> int:
    return len(plain(answer).split())


def percentiles(values: list[float]) -> dict:
    if not values:
        return {"n": 0, "p50": None, "p95": None}
    return {"n": len(values), "p50": round(float(np.percentile(values, 50)), 2),
            "p95": round(float(np.percentile(values, 95)), 2)}


# ---- failure classes ----

NOT_INGESTED = "source not ingested"
NOT_RETRIEVED = "ingested but not retrieved"
ANSWERED_WRONG = "retrieved but answered wrong"
CITED_WRONG = "answered right but cited wrong"
AMBIGUOUS = "ambiguous case"


def classify(accuracy: str, gold: set[str], seen: set[str], cited: set[str],
             rows_ingested: bool) -> tuple[str | None, str]:
    """The earliest pipeline stage that explains a miss, by rule. Rows (spreadsheet locators) count
    as ingested only when the setup has the structured lookups; every PDF page is in the index.
    A correct answer with complete citations is not a failure (None)."""
    missing = gold - seen
    not_ingested = sorted(l for l in missing if not rows_ingested and not re.search(r":p\d+$", l))
    if accuracy == "correct":
        uncited = gold - cited
        if gold and uncited:
            return CITED_WRONG, f"correct, but gold not cited: {'; '.join(sorted(uncited))}"
        return None, ""
    if accuracy not in ("partial", "incorrect"):
        return None, ""
    if not_ingested:
        return NOT_INGESTED, f"gold in a source the setup can't read: {'; '.join(not_ingested)}"
    if missing:
        return NOT_RETRIEVED, f"gold never returned by a tool: {'; '.join(sorted(missing))}"
    return ANSWERED_WRONG, "every gold source was returned, but the answer was graded " + accuracy