"""Name normalization and the result labels shared by the drug lookups.

Normalizing only trims, lowercases, collapses whitespace and drops trademark symbols. Strengths,
units, dosage forms and markers such as (OTC) stay intact, so "humalog 200 u/ml" never matches
"humalog 100 u/ml" by accident.
"""

import difflib
import re

# result labels, in the words the agent sees
EXACT = "exact_match"                  # one row matched the name exactly
MULTIPLE = "multiple_matches"          # several rows matched; all are returned
FORM_NOT_LISTED = "dosage_form_not_listed"  # VA only: the drug is listed, but not in that dosage form
CLASS = "class_match"                  # NY only: the query names a drug class, not a drug
FUZZY = "fuzzy_suggestion"             # no match; close names offered, none of them is a match
NO_MATCH = "no_matching_row"           # nothing matched; this never means "not covered"
FAILURE = "lookup_failure"             # the structured source couldn't be read

STRENGTH = re.compile(
    r"\b\d+(?:[.,]\d+)?\s?(?:mg|mcg|g|ml|units?|u|%|meq|iu)"
    r"(?:\s?/\s?\d*(?:\.\d+)?\s?(?:mg|mcg|g|ml|units?|u|hr|h|actuation|dose))?(?![a-z])", re.I)


def norm(s: str | None) -> str:
    """Trim, lowercase, collapse whitespace; drop ® and ™ (typography, not part of the name)."""
    if not s:
        return ""
    s = s.replace("\xa0", " ").replace("®", " ").replace("™", " ")
    s = s.replace("–", "-").replace("—", "-").replace("‑", "-")
    return " ".join(s.lower().split())


def split_strengths(q: str) -> tuple[str, list[str]]:
    """'buprenorphine 8 mg' -> ('buprenorphine', ['8 mg'])."""
    strengths = [m.group(0) for m in STRENGTH.finditer(q)]
    return " ".join(STRENGTH.sub(" ", q).split()), strengths


def fuzzy(q: str, names: list[str], n: int = 3, cutoff: float = 0.82) -> list[str]:
    """Close names for a query that matched nothing. Conservative cutoff: these are offered as
    suggestions to check, never used as a match."""
    return difflib.get_close_matches(q, sorted(set(names)), n=n, cutoff=cutoff)


def tokens(s: str) -> list[str]:
    return re.findall(r"[a-z0-9][a-z0-9./%-]*", s)


def starts_with_words(name: str, q: str) -> bool:
    """'humalog 200 u/ml' starts with the words 'humalog'; 'humalogx' doesn't."""
    return name == q or name.startswith(q + " ") or name.startswith(q + ",")
