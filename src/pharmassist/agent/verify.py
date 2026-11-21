"""Answer checks for the agent: claim by claim, against the evidence its tools returned.

The agent submits atomic, self-contained claims (exactly one direct answer), each naming its program,
with its own citations and a type. Every claim is checked synchronously and deterministically against
only the pages or rows it cites, never against outside knowledge, and gets a label:
- verified: the claim's assertion was compared field to field: a PDL preferred/non-preferred status,
  a VA formulary Restriction (PA) or formulary status, with polarity, against the returned lookup row;
- values_checked: its critical elements (drug names, doses and strengths, thresholds, dates, phone
  numbers with a word-overlap purpose check, billing codes, legal wording) were found on its cited
  pages, but the relation between them can't be checked deterministically;
- unchecked: nothing in it is checkable (absence statements are always unchecked).
A claim fails when an element isn't on its own cited pages (citation_only if another returned page
has it, else evidence_failure), when a status contradicts its lookup row, or when it is malformed
(schema_rejection: dependent opening, no program, no citation, a source-precedence claim, global
absence wording, an absence claim as the direct answer to a question that isn't about what the
documents contain). A retrieval miss is never a confirmed negative: absence claims are unchecked.
assemble() builds the whole response in code (numbered steps from the claims' step numbers, a
coverage table from returned lookup rows only, each claim's label in its configured short form);
audit_claims() is the optional offline model audit, never called while answering.
"""

import json
import re
from dataclasses import dataclass, field
from functools import cache

CLAIM_TYPES = ("dose", "threshold", "phone_number", "coverage_rule", "billing_instruction",
               "legal_characterization", "corpus_absence", "other")
TYPE_LABELS = {"dose": "a dose", "threshold": "a threshold", "phone_number": "a phone number",
               "coverage_rule": "a coverage rule", "billing_instruction": "a billing instruction",
               "legal_characterization": "a legal characterization", "corpus_absence": "an absence statement",
               "other": "a statement"}
COULD_NOT_VERIFY = "I could not verify {label} from the provided documents."
MAX_CLAIM_WORDS = 35      # defaults; agent.verification sets them
MAX_SUPPORTING = 4
NO_PROGRAM = "Coverage program not specified"
# program names and aliases a question may use; matched deterministically, in this order of display
PROGRAM_ALIASES = {
    # the abbreviation is case-sensitive ("VA", not "via"/"VALID"); the rest aren't
    "VA": r"\bV\.?A\.?(?![A-Za-z])|(?i:\bveterans?\b|\bveterans affairs\b|\bVHA\b|\bVANF\b)",
    "Medicare Part D": r"\bMedicare\b|\bPart D\b|\bPDPs?\b|\bMA-PDs?\b",
    "NY Medicaid": r"\bNYRx\b|\bN\.?Y\.?S?\.? Medicaid\b|\bNew York (?:State )?Medicaid\b|\bMedicaid\b",
}
ABSTAIN = ("I could not verify an answer to this question from the provided documents. "
           "Please have a pharmacist review it before acting.")
OUT_OF_SCOPE = "This question is outside the pharmacy documents this assistant answers from."
# a claim opening with one of these leans on another claim (a pre-check; the claim check judges the rest)
DEPENDENT_START = re.compile(
    r"^\W*(it|its|this|that|these|those|they|them|their|such|therefore|thus|hence|however|also|"
    r"otherwise|instead|then|both|the former|the latter|the same|which|supersedes|superseded|"
    r"in that case|in this case|if so|if not|as above|as noted|as a result|because of this)\b", re.I)

# abbreviations the requirements say to use freely, and names of the programs and their documents
COMMON_TERMS = {"pa", "ql", "st", "daw", "mme", "pdl", "bltg", "va", "cms", "ny", "nyrx", "dod", "pbm",
                "cpg", "vanf", "us", "usa", "rx", "otc", "fda", "md", "rph", "ok", "id", "faq", "pdf", "url",
                "medicare", "medicaid", "part", "ii", "iii", "iv"}
EXPANSIONS = {"pa": "prior authorization", "e&o": "education outreach", "eo": "education outreach",
              "tpl": "third party liability", "dme": "durable medical equipment", "dmp": "drug management program",
              "mat": "medication assisted treatment", "oud": "opioid use disorder", "ql": "quantity limit",
              "cc": "call center"}
STOP = set("""a an the and or of to in on for at by with from as is are be been was were it its this that these those
which who whom what when where how than then there their they them you your we our us not no nor can may might
must should will would shall do does did done has have had having if but so such any all each every per via into
onto over under about after before also only just more most less least very same other another both either""".split())
GENERIC = set("""call calls calling contact contacted phone number numbers fax email line center centre available
reach use used using get submit start starting before check confirm need needs needed required require requires
patient patients prescriber prescribers pharmacy pharmacist pharmacists plan plans claim claims""".split())
UNIVERSAL = re.compile(r"\b(any|all|every|always|never|automatically)\b", re.I)
LEGAL = re.compile(r"\b(fraud\w*|illegal\w*|unlawful\w*|criminal\w*|felon\w*|kickback\w*|"
                   r"violat\w* (?:of )?(?:federal |state )?law|prohibited by law|against the law)\b", re.I)

UNITS = (r"mg/kg/day|mg/kg|mg/day|mg/d|mcg/hr|mcg/h|mcg|mg|ml/min/1\.73\s?m2|ml/min/1\.73\s?m²|ml/min|ml|g|units?|"
         r"tablets?|tabs?|capsules?|caps?|patch(?:es)?|films?|doses?|days?|weeks?|months?|years?|hours?|hrs?|"
         r"refills?|fills?|mme|%|percent")
NUMBER = re.compile(r"(?<![\w/.-])(\$\s?)?(\d{1,3}(?:,\d{3})+|\d+)(\.\d+)?\s?(" + UNITS + r")?(?![\w])", re.I)
PHONE = re.compile(r"(?<!\d)(?:1[-. ]?)?\(?(\d{3})\)?[-. ]?(\d{3})[-. ]?(\d{4})(?!\d)")
MONTHS = {m: i for i, m in enumerate(["jan", "feb", "mar", "apr", "may", "jun", "jul", "aug", "sep", "oct",
                                       "nov", "dec"], 1)}
DATE_NUM = re.compile(r"(?<!\d)(\d{1,2})/(\d{1,2})/(\d{2}|\d{4})(?!\d)")
DATE_ISO = re.compile(r"(?<!\d)(\d{4})-(\d{2})-(\d{2})(?!\d)")
DATE_TEXT = re.compile(r"\b(jan|feb|mar|apr|may|jun|jul|aug|sep|sept|oct|nov|dec)[a-z]*\.?\s+(\d{1,2}),?\s+(\d{4})\b", re.I)
TECH = re.compile(r"\b[A-Za-z]*(?:[A-Z][A-Za-z0-9]*[A-Z0-9]|[a-z][A-Z]+[a-z]*[A-Z0-9]*)[A-Za-z0-9]*(?:-\d+)?\b")


NUMBER_WORDS = {w: str(i) for i, w in enumerate(
    "zero one two three four five six seven eight nine ten eleven twelve".split())}
# en/em dash, >=, <=, no-break space, curly apostrophe
SYMBOLS = str.maketrans({"\u2013": "-", "\u2014": "-", "\u2265": ">=", "\u2264": "<=", "\u00a0": " ",
                         "\u2019": "'", "*": ""})


def norm(text: str) -> str:
    """Lowercase and unify symbols, spacing, number words and 'per day' forms, so formatting
    differences don't matter."""
    t = text.lower().translate(SYMBOLS)
    t = re.sub(r"(?<=[a-z0-9])-(iv|iii|ii)\b", lambda m: "-" + {"iv": "4", "iii": "3", "ii": "2"}[m.group(1)], t)
    t = re.sub(r"(?<=[a-z])-(?=[a-z])", "", t)              # co-pay -> copay
    t = re.sub(r"\b(" + "|".join(NUMBER_WORDS) + r")\b", lambda m: NUMBER_WORDS[m.group()], t)
    t = re.sub(r"\s*\bper\s+(day|hour|hr|week|month)\b", lambda m: "/" + {"hour": "hr"}.get(m.group(1), m.group(1)), t)
    t = re.sub(r"/\s+", "/", t)
    return re.sub(r"\s+", " ", t)


def words(text: str) -> set[str]:
    t = norm(text)
    for short, full in EXPANSIONS.items():
        t = re.sub(rf"(?<![\w&]){re.escape(short)}(?![\w&])", f"{short} {full}", t)
    return {w for w in re.findall(r"[a-z0-9]+", t) if len(w) > 2 and w not in STOP}


def _canon_number(whole: str, frac: str | None) -> str:
    n = whole.replace(",", "") + (frac or "")
    return re.sub(r"\.0+$", "", n) if "." in n else n


def _canon_unit(u: str | None) -> str | None:
    if not u:
        return None
    u = norm(u).replace(" ", "")
    for full, short in (("percent", "%"), ("tablets", "tablet"), ("tabs", "tablet"), ("tab", "tablet"),
                        ("capsules", "capsule"), ("caps", "capsule"), ("cap", "capsule"), ("units", "unit"),
                        ("days", "day"), ("weeks", "week"), ("months", "month"), ("years", "year"),
                        ("hours", "hour"), ("hrs", "hour"), ("hr", "hour"), ("refills", "refill"),
                        ("fills", "fill"), ("doses", "dose"), ("films", "film"), ("patches", "patch"),
                        ("mg/d", "mg/day"), ("mcg/h", "mcg/hr"), ("ml/min/1.73m²", "ml/min/1.73m2")):
        if u == full:
            return short
    return u


def dates_in(text: str) -> set[str]:
    """Every date in the text as YYYY-MM-DD."""
    out = set()
    for m, d, y in DATE_NUM.findall(text):
        y = int(y) + (2000 if len(y) == 2 else 0)
        if 1 <= int(m) <= 12 and 1 <= int(d) <= 31:
            out.add(f"{y:04d}-{int(m):02d}-{int(d):02d}")
    for y, m, d in DATE_ISO.findall(text):
        out.add(f"{y}-{m}-{d}")
    for mon, d, y in DATE_TEXT.findall(text):
        out.add(f"{y}-{MONTHS[mon.lower()[:3]]:02d}-{int(d):02d}")
    return out


def phones_in(text: str) -> list[tuple[str, int, int]]:
    return [("".join(m.groups()), m.start(), m.end()) for m in PHONE.finditer(text)]


@dataclass
class Value:
    raw: str
    kind: str              # number | money | percent | year | date | phone
    canon: str
    unit: str | None = None
    anchors: set[str] = field(default_factory=set)
    context: set[str] = field(default_factory=set)   # words around it (phone purpose)
    range_end: str | None = None   # "16" in "16-24 mg/day": the evidence must state the range


def extract_values(text: str) -> list[Value]:
    """Critical values in an answer: dates, phone numbers, and numbers with their unit and the
    words just before them (the anchor that ties '20' to 'eGFR')."""
    values, taken = [], []
    for m in list(DATE_NUM.finditer(text)) + list(DATE_ISO.finditer(text)) + list(DATE_TEXT.finditer(text)):
        canon = next(iter(dates_in(m.group())), None)
        if canon:
            values.append(Value(m.group(), "date", canon))
            taken.append((m.start(), m.end()))
    for digits, s, e in phones_in(text):
        if any(a <= s < b for a, b in taken):
            continue
        line_start = text.rfind("\n", 0, s) + 1
        line_end = text.find("\n", e)
        line = text[line_start: line_end if line_end != -1 else len(text)]
        ctx = words(line[max(0, s - line_start - 80): e - line_start + 60]) - GENERIC
        values.append(Value(text[s:e], "phone", digits, context=ctx))
        taken.append((s, e))
    matches = list(NUMBER.finditer(text))
    for i, m in enumerate(matches):
        if any(a <= m.start() < b for a, b in taken):
            continue
        dollar, whole, frac, unit = m.groups()
        canon = _canon_number(whole, frac)
        if (not unit and i + 1 < len(matches)
                and re.fullmatch(r"\s*(?:-|–|to)\s*", text[m.end():matches[i + 1].start()])):
            nxt = matches[i + 1]
            values.append(Value(m.group().strip(), "number", canon,
                                range_end=_canon_number(nxt.group(2), nxt.group(3))))
            continue
        if not dollar and not unit and len(canon) == 1 and not re.search(r"[<>=≥≤]\s*$", text[:m.start()]):
            continue  # a bare single digit (list numbering, "1 of 2") isn't a critical value
        kind = ("money" if dollar else "percent" if unit and _canon_unit(unit) == "%" else
                "year" if not unit and re.fullmatch(r"(19[89]|20[0-4])\d", canon) else "number")
        before = re.split(r"[.;:\n(]", text[max(0, m.start() - 50): m.start()])[-1]
        after = re.split(r"[.;:\n)]", text[m.end(): m.end() + 50])[0]
        anchors = {norm(w) for w in _content(before)[-3:] + _content(after)[:3]}
        values.append(Value(m.group().strip(), kind, canon, _canon_unit(unit), anchors))
    return values


def _content(part: str) -> list[str]:
    return [w.lower() for w in re.findall(r"[A-Za-z][A-Za-z0-9-]+", part)
            if w.lower() not in STOP and w.lower() not in GENERIC and len(w) > 2]


def _number_supported(v: Value, evidence: str) -> bool:
    """The number occurs in the evidence with the same unit (if any) and one of its anchor words
    nearby; '1,000' and '1000', '$1' and '$1.00' match."""
    e = norm(evidence)
    variants = [v.canon]
    if len(v.canon) > 3 and "." not in v.canon:
        variants.append(f"{int(v.canon):,}")
    if v.range_end:
        return re.search(r"(?<![\w.,])" + re.escape(v.canon) + r"\s*(?:-|to)\s*" + re.escape(v.range_end)
                         + r"(?!\d)", e) is not None
    for canon in variants:
        for m in re.finditer(r"(?<![\w.,])" + re.escape(canon) + r"(?:\.0+)?(?!\d|[.,]\d)", e):
            after = e[m.end(): m.end() + 16].lstrip().replace(" ", "")
            if v.unit and not (after.startswith(v.unit) or (v.unit == "%" and after.startswith("percent"))):
                continue
            if v.kind == "money" and "$" not in e[max(0, m.start() - 2): m.start()]:
                continue
            if v.unit or v.kind in ("money", "year"):
                return True  # a value with its unit (or a year) is specific enough
            # a bare number needs one of its neighbouring words nearby (so '20' near 'eGFR')
            window = e[max(0, m.start() - 120): m.end() + 120]
            if not v.anchors or any(a in window for a in v.anchors):
                return True
    return False


def supported(v: Value, evidence: str) -> bool:
    if not evidence:
        return False
    if v.kind == "date":
        return v.canon in dates_in(evidence)
    if v.kind == "phone":
        return any(d == v.canon for d, _, _ in phones_in(evidence))
    return _number_supported(v, evidence)


def phone_purpose_ok(v: Value, evidence: str) -> bool:
    """The words around the number in the answer share a purpose word with the words the evidence
    puts with that number (PA and prior authorization count as the same). The evidence's words for a
    number stop at the previous number and at sentence ends, so a neighbouring line's purpose
    doesn't count."""
    if not v.context:
        return True
    phones = phones_in(evidence)
    for i, (d, s, e) in enumerate(phones):
        if d != v.canon:
            continue
        lo = max(phones[i - 1][2] if i else 0, s - 160)
        before = re.split(r"(?<=[.!?])\s+", evidence[lo:s])[-1]
        hi = min(phones[i + 1][1] if i + 1 < len(phones) else len(evidence), e + 80)
        after = re.split(r"(?<=[.!?])\s+", evidence[e:hi])[0]
        if v.context & (words(before + " " + after) - GENERIC):
            return True
    return False


def given_values(question: str, today) -> set[str]:
    """Canonical values a claim may repeat without evidence: those in the question, and today."""
    vals = {v.canon for v in extract_values(question)}
    if today is not None:
        vals |= {today.isoformat(), str(today.year)}
    return vals


@dataclass
class Problem:
    kind: str          # what failed (dependent_start, unsupported_value, status_mismatch, ...)
    text: str          # the offending element (for the trace; never shown to staff)
    detail: str
    cause: str = "evidence_failure"   # schema_rejection | citation_only | evidence_failure
    locators: list[str] = field(default_factory=list)

    def message(self) -> str:
        return f"{self.detail}" + (f" (stated on: {', '.join(self.locators)})" if self.locators else "")

    def record(self) -> dict:
        return {"kind": self.kind, "cause": self.cause, "detail": self.message()}


def _sentences(text: str) -> list[str]:
    out = []
    for line in text.split("\n"):
        out += [s for s in re.split(r"(?<=[.!?])\s+", line) if s.strip()]
    return out


def locators_of(claim: dict) -> list[str]:
    from pharmassist.agent.tools import locator
    return list(dict.fromkeys(locator(c.get("doc_id"), c.get("page"), c.get("row"))
                              for c in claim.get("citations") or []))


# a document identifier's shape: "IB 10-1775", "Version 6.0", "CY 2019"
DOC_IDENT = re.compile(r"\b[A-Z]{1,5} ?\d+(?:[-.]\d+)+\b|\bVersion \d+(?:[-.]\d+)*\b|\bCY ?\d{4}\b")


@cache
def catalog_identifiers() -> frozenset[str]:
    """Identifiers that appear in the catalog's document titles and ids (what list_documents
    returns), whitespace-normalized."""
    from pharmassist.agent.tools import catalog
    found = set()
    for doc_id, e in catalog().items():
        for m in DOC_IDENT.finditer(f"{e.get('title', '')} {doc_id}"):
            found.add(re.sub(r"\s+", " ", m.group()))
    return frozenset(found)


def mask_document_identifiers(text: str) -> str:
    """Blank out document identifiers that match the catalog, so their numbers aren't read as
    claim values; any other number, including one shaped like an identifier, stays."""
    known = catalog_identifiers()
    return DOC_IDENT.sub(lambda m: " " * len(m.group()) if re.sub(r"\s+", " ", m.group()) in known
                         else m.group(), text)


def text_problems(text: str, scope: str, evidence: dict[str, str], question: str,
                  today) -> tuple[list[Problem], list[dict], list[str]]:
    """Values, phone purposes and legal wording in `text`, checked against `scope` (the evidence the
    text cites). A value found only on another returned page is a citation-only failure, reported
    with that page. Technical terms missing from `scope` come back as hints (recorded, not failures)."""
    given = given_values(question, today)
    problems, record = [], []
    for v in extract_values(mask_document_identifiers(text)):
        entry = {"value": v.raw, "kind": v.kind}
        if supported(v, scope):
            entry["source"] = "cited evidence"
            if v.kind == "phone" and not phone_purpose_ok(v, scope):
                entry["source"] = "cited evidence, different purpose"
                problems.append(Problem("phone_purpose", v.raw, f"{v.raw}: the cited evidence gives this number "
                                                                 f"for a different purpose"))
        elif v.canon in given:
            entry["source"] = "question or today's date"
        else:
            found = sorted(l for l, t in evidence.items() if supported(v, t))
            entry["source"] = "uncited returned evidence" if found else "unsupported"
            problems.append(Problem("uncited_support", v.raw, f"{v.raw} is not on the pages cited for it; cite "
                                                              f"the returned page that states it", "citation_only",
                                    found[:3])
                            if found else
                            Problem("unsupported_value", v.raw, f"{v.raw} does not appear in any evidence returned "
                                                                f"for this question"))
        record.append(entry)

    for sent in _sentences(text):
        for m in LEGAL.finditer(sent):
            stem = m.group()[:5].lower()
            ev_sents = [s for s in re.split(r"(?<=[.!?])\s+|\n", scope) if stem in s.lower()]
            ctx = words(sent) - words(m.group()) - GENERIC
            best = max(ev_sents, key=lambda s: len(ctx & (words(s) - GENERIC)), default=None)
            overlap = len(ctx & (words(best) - GENERIC)) if best else 0
            widened = best is not None and UNIVERSAL.search(sent) and not UNIVERSAL.search(best)
            if best is None or overlap < 2 or widened:
                why = ("isn't used in the cited evidence" if best is None else
                       "is widened beyond the situation the evidence describes" if widened else
                       "is used in the cited evidence only for a different situation")
                problems.append(Problem("legal", sent.strip(), f"{m.group()!r} {why}"))
                record.append({"value": m.group(), "kind": "legal", "source": "failed"})
            else:
                record.append({"value": m.group(), "kind": "legal", "source": "cited evidence"})

    hints = []
    ev_norm, q_norm = norm(scope), norm(question)
    ev_flat = ev_norm.replace("-", "").replace(" ", "")
    for term in dict.fromkeys(TECH.findall(text)):
        t = norm(term)
        if t in COMMON_TERMS or t.rstrip("s") in COMMON_TERMS or len(t) < 2:
            continue
        forms = {t, t[:-1] if t[-1] in "si" and len(t) >= 3 else t}
        found = any(re.search(r"(?<![a-z0-9])" + re.escape(f), ev_norm) or f.replace("-", "") in ev_flat
                    for f in forms)
        if not found and t not in q_norm:
            hints.append(term)
    return problems, record, hints


# ---- structured rows: what the lookups returned, parsed back from their tool results ----

def structured_rows(parts: dict[str, list[str]]) -> list[dict]:
    """Every lookup row any tool returned, from the lookup results (JSON) recorded as evidence:
    {"source", "locator", "names", plus the row's own fields}. Rows are only ever read here."""
    from pharmassist.agent.tools import locator
    from pharmassist.tables import match
    rows, seen = [], set()
    for texts in parts.values():
        for text in texts:
            try:
                res = json.loads(text)
            except (ValueError, TypeError):
                continue
            if not isinstance(res, dict):
                continue
            for r in res.get("rows") or []:                         # VA formulary
                key = ("va", r.get("row"))
                if key in seen or r.get("row") is None:
                    continue
                seen.add(key)
                generic = r.get("Generic", "")
                names = {match.norm(re.sub(r"\(.*?\)", " ", generic))} | {
                    match.norm(b) for g in re.findall(r"EQV-([^)]+)\)", generic) for b in re.split(r"/| and ", g)}
                rows.append({"source": "va", "locator": locator(r["cite"]["doc_id"], row=r["row"]),
                             "names": {n for n in names if n}, "restriction": (r.get("Restriction") or "").strip(),
                             "result": res.get("result"), "row_id": r.get("row_id"),
                             "doc_id": r["cite"]["doc_id"], "stored": r})
            for c in res.get("classes") or []:                      # NY PDL
                for r in c.get("rows") or []:
                    key = ("ny", r.get("row_id"))
                    if key in seen:
                        continue
                    seen.add(key)
                    name = match.norm(re.sub(r"\(.*?\)|®|™", " ", r.get("drug_name", "")))
                    rows.append({"source": "ny", "locator": locator(r["cite"]["doc_id"], r["cite"]["page"]),
                                 "names": {name, name.split()[0]} if name else set(),
                                 "listed_as": r.get("listed_as"), "row_id": r.get("row_id"),
                                 "doc_id": r["cite"]["doc_id"], "stored": r})
    return rows


# status wording in a claim, and its polarity
NON_PREFERRED = re.compile(r"\bnon-?\s?preferred\b|\bnot (?:listed as )?preferred\b", re.I)
PREFERRED = re.compile(r"\bpreferred\b", re.I)
PA_WORD = re.compile(r"\b(?:PA|prior auth\w*|PA-[FNV])\b", re.I)
PA_NOT = re.compile(r"\b(?:no|not|without|doesn'?t|does not|isn'?t|is not|never)\b[^.;]{0,40}\b(?:PA|prior auth\w*)\b|"
                    r"\b(?:PA|prior auth\w*)\b[^.;]{0,25}\b(?:not required|isn'?t required|is not required|not needed)\b", re.I)
PA_YES = re.compile(r"\b(?:requires?|required|needs?|need|subject to)\b[^.;]{0,25}\b(?:PA|prior auth\w*)\b|"
                    r"\b(?:PA|prior auth\w*)\b[^.;]{0,15}\b(?:is |are )?required\b|\bPA-[FNV]\b", re.I)
CONDITIONAL = re.compile(r"\b(?:if|when|unless|only|except|for patients|concurrent\w*)\b", re.I)
NON_FORMULARY = re.compile(r"\bnon-?\s?formulary\b|\bnot on the (?:VA )?(?:national )?formulary\b", re.I)
ON_FORMULARY = re.compile(r"\b(?:is|are|listed) (?:on the )?(?:VA )?(?:national )?formulary\b|\bformulary\b", re.I)


# status words used generically, of no drug: "preferred/non-preferred status", "formulary status"
GENERIC_STATUS = re.compile(
    r"\b(?:non-?\s?)?preferred\s*(?:/|or|and)\s*(?:non-?\s?)?preferred\b(?:\s+status(?:es)?)?|"
    r"\b(?:formulary|non-?\s?formulary|PDL|preferred|non-?\s?preferred|PA|coverage)\s+status(?:es)?\b", re.I)
DOSAGE_FORM = re.compile(r"\b(?:tablets?|capsules?|films?|patch(?:es)?|pens?|injections?|injectables?|solutions?|"
                         r"suspensions?|formulations?|dosage forms?|sublingual|buccal|transdermal|extended-release|"
                         r"oral)\b", re.I)
CLAUSE_SPLIT = re.compile(r"[;:]|(?<=[.!?])\s+|,\s*(?:and|but|while|whereas|so)\s+")


def status_assertions(text: str) -> list[tuple[str, str | None]]:
    """(kind, polarity) for each status the claim asserts of a named drug: kind preferred | pa |
    formulary; polarity a value to compare field to field, or None when the wording (a condition, a
    hedge) can't be compared. A status word counts only in a clause that names a drug or a dosage
    form; field descriptions ("preferred/non-preferred status", "formulary status", "PA status")
    assert nothing, and no polarity is read from them."""
    out = []
    for clause in CLAUSE_SPLIT.split(GENERIC_STATUS.sub(" ", text)):
        if clause and (drug_names(clause) or DOSAGE_FORM.search(clause)):
            for a in _clause_status(clause):
                if a not in out:
                    out.append(a)
    return out


def _clause_status(text: str) -> list[tuple[str, str | None]]:
    out = []
    if NON_PREFERRED.search(text):
        out.append(("preferred", "non-preferred"))
    elif PREFERRED.search(text):
        out.append(("preferred", "preferred"))
    if PA_WORD.search(text):
        if CONDITIONAL.search(text):
            out.append(("pa", None))
        elif PA_NOT.search(text):
            out.append(("pa", "not_required"))
        elif PA_YES.search(text):
            out.append(("pa", "required"))
        else:
            out.append(("pa", None))
    if NON_FORMULARY.search(text):
        out.append(("formulary", "non-formulary"))
    elif ON_FORMULARY.search(text) and re.search(r"\bVA\b", text):
        out.append(("formulary", "formulary"))
    return out


def has_name(name: str, normed: str) -> bool:
    """`name` occurs in `normed` (both match.norm'ed, so lowercase) as whole tokens: punctuation,
    parentheses and slashes are boundaries; a longer token containing it is not a match."""
    return bool(name) and name in normed and re.search(
        r"(?<![a-z0-9])" + re.escape(name) + r"(?![a-z0-9])", normed) is not None


def _rows_for(claim_text: str, rows: list[dict], locs: list[str]) -> list[dict]:
    """The returned lookup rows on the claim's cited pages/rows for a drug the claim names."""
    from pharmassist.tables import match
    t = match.norm(claim_text)
    return [r for r in rows if r["locator"] in locs and any(has_name(n, t) for n in r["names"] if n)]


def _check_status(kind: str, polarity: str | None, rows: list[dict]) -> tuple[str, str | None]:
    """('verified' | 'values_checked' | 'mismatch', why)."""
    if polarity is None:
        return "values_checked", f"{kind} wording can't be compared field to field"
    if kind == "preferred":
        ny = [r for r in rows if r["source"] == "ny" and r.get("listed_as")]
        if not ny:
            return "values_checked", "no NY PDL row for this drug on the cited pages"
        got = {r["listed_as"] for r in ny}
        return ("verified", None) if got == {polarity} else ("mismatch", f"the PDL row lists it as {sorted(got)}")
    if kind == "pa":
        va = [r for r in rows if r["source"] == "va"]
        if not va:
            # the NY PDL rows have no per-row PA field
            return "values_checked", "no structured row with a PA field for this drug on the cited rows"
        got = {"required" if r["restriction"] else "not_required" for r in va}
        return ("verified", None) if got == {polarity} else ("mismatch", f"the formulary Restriction field says {sorted(got)}")
    if kind == "formulary":
        va = [r for r in rows if r["source"] == "va"]
        if not va:
            return "values_checked", "no VA formulary row for this drug on the cited rows"
        got = {"non-formulary" if r["result"] == "dosage_form_not_listed" else "formulary" for r in va}
        return ("verified", None) if got == {polarity} else ("mismatch", f"the formulary lookup says {sorted(got)}")
    return "values_checked", None


# billing codes: NCPDP field ids (420-DK), DAW and SCC codes, reject codes
CODES = re.compile(r"\b\d{3}-[A-Z][A-Z0-9]\b|\bDAW\s?\d\b|\bSCC\s?\d{1,2}\b|\breject(?:ion)?\s+(?:code\s+)?\d{1,5}\b", re.I)
GOVERNS = re.compile(r"\bsupersed\w*|\bgovern\w*|\btakes? precedence\b|\bprevail\w*|\bno longer applies\b|"
                     r"\boutdated\b|\bis replaced by\b", re.I)
ABSENCE_OK = re.compile(r"^I (?:did not|didn'?t|could not|couldn'?t) find\b.+\bin the retrieved\b.+\b(?:evidence|documents|pages)\b", re.I)
# a question about what the documents themselves contain, the only case an absence claim may answer
DOCS_QUESTION = re.compile(
    r"\b(?:do|does|did|is|are)\s+(?:the\s+)?(?:[\w-]+\s+){0,4}?(?:documents?|manuals?|pdl|guidelines?|guidance|"
    r"guides?|polic(?:y|ies)|sources?|corpus)\s+(?:\w+\s+)?(?:say|mention|contain|include|address|cover|list|state|"
    r"specify|discuss|define)\b|"
    r"\b(?:is|are) there\b[^?]*\b(?:in|from) the (?:[\w-]+\s+){0,3}?(?:documents?|manuals?|pdl|guidelines?|"
    r"guidance|polic(?:y|ies))\b", re.I)
ABSENCE_GLOBAL = re.compile(r"\b(?:has|have|contains?|there (?:is|are)) no\b|\bno\b[^.]{0,40}\bexists?\b|"
                            r"\bdoes(?: not|n'?t) (?:have|exist|include|contain)\b|\bdo(?: not|n'?t) contain\b", re.I)


@cache
def _vocabulary() -> frozenset[str]:
    """Normalized drug names from the structured sources (VA generics and brands, NY PDL names),
    without numbers or stop words."""
    from pharmassist.tables import match, ny_pdl, va_formulary
    names = set()
    try:
        f = va_formulary.load()
        for base, brands in zip(f.rows["name_no_salt"], f.rows["brands"]):
            names.add(base)
            names.update(brands)
        for r in ny_pdl.load():
            n = match.norm(re.sub(r"\(.*?\)|®|™", " ", r["drug_name"]))
            if n:
                names.add(n.split()[0])
                names.add(" ".join(n.split()[:2]))
    except Exception:
        pass
    return frozenset(n for n in names if len(n) >= 4 and not re.search(r"\d", n) and n not in STOP)


def drug_names(text: str) -> list[str]:
    from pharmassist.tables import match
    t = match.norm(text)
    names = [n for n in _vocabulary() if has_name(n, t)]
    return [n for n in names if not any(n != m and n in m for m in names)]   # longest form only


@dataclass
class Context:
    evidence: dict[str, str]            # locator -> text the tools returned for it
    parts: dict[str, list[str]]         # locator -> each tool result separately (lookup JSON among them)
    question: str
    today: object = None
    queries: list[str] = field(default_factory=list)   # every search query run for the question
    rows: list[dict] = field(default_factory=list)
    max_words: int = MAX_CLAIM_WORDS

    def __post_init__(self):
        if not self.rows:
            self.rows = structured_rows(self.parts)


ABBREVIATIONS = {"e.g.", "i.e.", "vs.", "etc.", "approx.", "dr.", "mr.", "ms.", "no.", "st.", "inc.", "jr.",
                 "al.", "fig.", "p.", "pp.", "ca.", "sec.", "min.", "max.", "u.s."}
# a predicate: what makes a clause an independent assertion (a deterministic approximation)
PREDICATE = re.compile(
    r"\b(?:is|are|was|were|isn'?t|aren'?t|must|should|may|might|can|cannot|can'?t|will|would|shall|does|do|did|"
    r"doesn'?t|don'?t|has|have|had|requires?|needs?|says?|lists?|applies|covers?|states?|recommends?|allows?|"
    r"permits?|limits?|provides?|includes?|excludes?|exempts?)\b", re.I)
# verbs that report what a source says: on their own they don't complete the clause they introduce
REPORTING = re.compile(r"\b(?:says?|said|states?|stated|lists?|listed|notes?|noted|recommends?|calls?|describes?|"
                       r"shows?|advises?)\b", re.I)
SUBORDINATOR = re.compile(r"\b(?:when|whenever|if|unless|until|because|since|where|which|that|who|whom|whose|"
                          r"once|after|before|whether)\b", re.I)
CONJUNCTION = re.compile(r",?\s+(?:and|but|while|whereas|yet)\s+|,?\s*\bhowever\b,?\s*", re.I)
def atomicity_problems(text: str) -> list[Problem]:
    """One fact per claim: more than one sentence, or a conjunction joining a second assertion.
    Semicolons are handled in check_claim (a rejection for a supporting claim, a warning for the
    direct claim)."""
    problems = []
    t = text.strip()
    for m in re.finditer(r"[.!?](?=\s+[\"'(]?[A-Z0-9])", t):
        token = re.search(r"\S+$", t[:m.end()]).group().lower().lstrip("(\"'")
        if token in ABBREVIATIONS or re.fullmatch(r"(?:[a-z]\.)+", token):
            continue
        problems.append(Problem("multiple_sentences", text, "the claim has more than one sentence; one fact per claim",
                                "schema_rejection"))
        break
    # "X is preferred and has a $1 copay", "X is preferred, but the documents give no tier": a
    # conjunction with a predicate on both sides joins two assertions; "coverage and billing policy"
    # joins two nouns and is one
    # the left side needs a predicate of its own (not only "says"); the right side needs one in its
    # main clause, before any "when/if/that ..." (so "T2DM and ASCVD even when A1c is at goal" and
    # "says adults with T2DM and ASCVD should ..." are one assertion)
    pieces = CONJUNCTION.split(t)
    for i in range(1, len(pieces)):
        left = REPORTING.sub(" ", " ".join(pieces[:i]))
        right = SUBORDINATOR.split(pieces[i], maxsplit=1)[0]
        if PREDICATE.search(left) and PREDICATE.search(right):
            problems.append(Problem("compound_assertion", text, "a conjunction joins a second independent "
                                    "assertion; one independently checkable fact per claim", "schema_rejection"))
            break
    return problems


def claim_warnings(claim: dict, max_words: int) -> list[dict]:
    """Presentation-quality warnings for one claim. They never change its verdict: a long claim or
    a semicolon in the direct claim is shown when its evidence checks pass."""
    text = claim.get("text") or ""
    out = []
    n = len(text.split())
    if n > max_words:
        out.append({"kind": "length_violation", "detail": f"{n} words; target at most {max_words}"})
    if claim.get("direct_answer") and ";" in text:
        out.append({"kind": "atomicity_warning", "detail": "the direct claim contains a semicolon"})
    return out


def submission_warnings(checked: list[dict], max_supporting: int) -> list[dict]:
    """Presentation-quality warnings for the whole submission (no claim is omitted for them)."""
    n = sum(1 for c in checked if not c.get("direct_answer"))
    return [{"kind": "supporting_claim_count_violation",
             "detail": f"{n} supporting claims; target at most {max_supporting}"}] if n > max_supporting else []


def displayed_text(answer: str, labels: dict) -> str:
    """The answer as staff read it, without labels, citation brackets or the table's row-id column."""
    forms = "|".join(re.escape(v) for v in labels.values() if v)
    out = []
    for line in answer.split("\n"):
        if line.startswith("|"):
            line = "|".join(line.rstrip("|").split("|")[:-1])
        else:
            line = re.sub(r" \[[^\]]*\](?: (?:" + forms + r"))?$", "", line) if forms else \
                re.sub(r" \[[^\]]*\]$", "", line)
        out.append(line)
    return "\n".join(out)


def check_claim(claim: dict, ctx: Context) -> dict:
    """Every critical element of one claim against only its own cited pages and rows. Returns the
    claim with `passed`, `label` (verified | values_checked | unchecked), `problems` and `elements`."""
    text = claim.get("text") or ""
    ctype = claim.get("type") if claim.get("type") in TYPE_LABELS else "other"
    locs = locators_of(claim)
    scope = "\n".join(ctx.evidence.get(l, "") for l in locs)
    problems, elements = [], []

    # structure: self-contained, names its program, cited, no source-precedence claims
    if DEPENDENT_START.match(text):
        problems.append(Problem("dependent_start", text, "the claim opens with a word that depends on another claim",
                                "schema_rejection"))
    if not resolve_program(text)[1]:
        problems.append(Problem("no_program", text, "the claim doesn't name its program", "schema_rejection"))
    if not locs:
        problems.append(Problem("no_citation", text, "the claim cites no page or row", "schema_rejection"))
    if GOVERNS.search(text):
        problems.append(Problem("source_precedence", text, "claims may not say one source governs another; flag "
                                "the conflict instead", "schema_rejection"))
    problems += atomicity_problems(text)
    if ";" in text and not claim.get("direct_answer"):
        problems.append(Problem("semicolon", text, "a supporting claim may not contain a semicolon; one "
                                "independently checkable fact per claim", "schema_rejection"))
    warnings = claim_warnings(claim, ctx.max_words)

    if ctype == "corpus_absence":
        if not ABSENCE_OK.match(text) or ABSENCE_GLOBAL.search(text):
            problems.append(Problem("absence_wording", text, "absence must be worded as 'I did not find ... in the "
                                    "retrieved ... evidence', never as a fact about the documents", "schema_rejection"))
        if claim.get("direct_answer") and not DOCS_QUESTION.search(ctx.question or ""):
            problems.append(Problem("absence_as_direct", text, "a retrieval miss can't be the direct answer: an "
                                    "absence claim answers only a question about what the documents contain",
                                    "schema_rejection"))
        absence = {"queries": list(ctx.queries), "evidence_units": sorted(ctx.evidence)}
        return {**claim, "type": ctype, "passed": not problems, "label": "unchecked", "problems": problems,
                "elements": [], "absence": absence, "warnings": warnings}

    # values, phone purposes, legal wording: on the claim's own pages, else citation-only if elsewhere
    vals, values, hints = text_problems(text, scope, ctx.evidence, ctx.question, ctx.today)
    for p in vals:
        if p.kind == "uncited_support":
            p.cause = "citation_only"
        problems.append(p)
    elements += [{"kind": v["kind"], "value": v["value"], "checked": "presence",
                  "source": v["source"]} for v in values]
    if any(v["kind"] == "phone" for v in values):
        elements += [{"kind": "phone_purpose", "checked": "word overlap"}]

    # billing codes
    s_norm = norm(scope).replace(" ", "")
    for code in dict.fromkeys(m.group() for m in CODES.finditer(text)):
        c = norm(code).replace(" ", "")
        if c in s_norm:
            elements.append({"kind": "code", "value": code, "checked": "presence"})
            continue
        elsewhere = sorted(l for l, t in ctx.evidence.items() if c in norm(t).replace(" ", ""))
        problems.append(Problem("unsupported_code", code, f"{code} is not on the pages cited for it",
                                "citation_only" if elsewhere else "evidence_failure", elsewhere[:3]))

    # drug and product names: in the cited text, or a name of a returned lookup row the claim cites
    from pharmassist.tables import match
    scope_n, question_n = match.norm(scope), match.norm(ctx.question)
    row_names = {n for r in ctx.rows if r["locator"] in locs for n in r["names"]}
    for name in drug_names(text):
        if has_name(name, scope_n) or name in row_names or has_name(name, question_n):
            elements.append({"kind": "drug", "value": name, "checked": "presence"})
            continue
        elsewhere = sorted(l for l, t in ctx.evidence.items() if has_name(name, match.norm(t)))
        problems.append(Problem("unsupported_drug", name, f"{name!r} is not on the pages cited for it",
                                "citation_only" if elsewhere else "evidence_failure", elsewhere[:3]))

    # coverage / preferred / PA status: field to field against the returned lookup rows only
    rows = _rows_for(text, ctx.rows, locs)
    for kind, polarity in status_assertions(text):
        outcome, why = _check_status(kind, polarity, rows)
        if outcome == "mismatch":
            problems.append(Problem("status_mismatch", kind, f"the claim says {polarity}, but {why}"))
        elements.append({"kind": f"status_{kind}", "value": polarity,
                         "checked": "field" if outcome == "verified" else "presence", "note": why})

    passed = not problems
    if not elements:
        label = "unchecked"
    elif all(e["checked"] == "field" for e in elements if e["kind"].startswith("status_")) and \
            any(e["kind"].startswith("status_") for e in elements) and \
            all(e["checked"] == "field" or e["kind"] == "drug" for e in elements):
        # the claim's assertion is a status compared field to field (its drug names are what it's about)
        label = "verified"
    else:
        label = "values_checked"
    return {**claim, "type": ctype, "passed": passed, "label": label, "problems": problems, "elements": elements,
            "term_hints": hints, "warnings": warnings}


def validate(final: dict) -> list[Problem]:
    """Answer-level structure: exactly one direct claim when the status needs an answer."""
    if final.get("status") == "out_of_scope":
        return []
    n = sum(1 for c in final.get("claims") or [] if c.get("direct_answer"))
    if n != 1:
        return [Problem("direct_count", "", f"{n} claims are marked direct_answer; exactly one must be",
                        "schema_rejection")]
    return []


# ---- source-precedence policy and assembly ----

META = re.compile(r"^(?P<doc>[a-z0-9_]+)(?: page \d+)? \((?P<program>[^,]+), (?P<authority>[^,]+), (?P<date>[^)]+)\)", re.M)


def source_meta(locs: list[str], evidence: dict[str, str]) -> list[dict]:
    """(doc, program, date) for each cited page, from the metadata the tools returned with it."""
    out = []
    for l in locs:
        m = META.search(evidence.get(l, ""))
        if m:
            out.append({"doc": m["doc"], "program": m["program"].strip(), "date": m["date"].strip()})
    return out


SHORT_NAME_WORDS = 6
SHORT_NAME_CUTS = (" for the ", " for ", " in ", " to ", " of ")


def short_title(title: str | None) -> str | None:
    """A readable short name from a document title: no parentheticals, nothing after a colon, no
    leading article, and past SHORT_NAME_WORDS words cut before the first 'for/in/to/of' phrase that
    leaves at least three words. None when there's no title."""
    if not title:
        return None
    t = re.sub(r"\s*\([^)]*\)", "", title).split(": ")[0].strip()
    t = re.sub(r"^(?:A|An|The)\s+", "", t)
    if len(t.split()) > SHORT_NAME_WORDS:
        for cut in SHORT_NAME_CUTS:
            i = t.find(cut)
            if i > 0 and len(t[:i].split()) >= 3:
                t = t[:i]
                break
    return t.strip() or None


def _short_name(doc: str) -> str:
    """The document's short name from its catalog title (what list_documents returns); its id only
    when the catalog has no title for it."""
    from pharmassist.agent.tools import catalog
    return short_title((catalog().get(doc) or {}).get("title")) or doc


def policy_lines(final: dict, checked: list[dict], evidence: dict[str, str], policy: dict | None) -> list[dict]:
    """Policy lines for conflicts the model flagged, when both claims passed, come from different
    documents of the same program, and those documents' dates differ. Documents are named by their
    short names derived from their catalog titles, with their dates."""
    if not policy:
        return []
    out = []
    for f in final.get("conflicts") or []:
        i, j = f.get("first", 0) - 1, f.get("second", 0) - 1
        if not (0 <= i < len(checked) and 0 <= j < len(checked)) or i == j:
            continue
        a, b = checked[i], checked[j]
        if not (a["passed"] and b["passed"]):
            continue
        ma, mb = source_meta(locators_of(a), evidence), source_meta(locators_of(b), evidence)
        if len({m["doc"] for m in ma}) != 1 or len({m["doc"] for m in mb}) != 1:
            continue   # each side must rest on one document
        sa, sb = ma[0], mb[0]
        if sa["doc"] == sb["doc"] or sa["program"] != sb["program"] or sa["date"] == sb["date"]:
            continue
        newer, older = (sa, sb) if sa["date"] > sb["date"] else (sb, sa)
        out.append({"policy_id": policy["id"], "claims": [i + 1, j + 1], "docs": [newer["doc"], older["doc"]],
                    "text": policy["text"].format(newer=f"{_short_name(newer['doc'])}, {newer['date']}",
                                                  older=f"{_short_name(older['doc'])}, {older['date']}")})
    return out


def _cite_label(c: dict) -> str:
    return f"{c['doc_id']} row {c['row']}" if c.get("row") is not None else f"{c['doc_id']} p{c.get('page')}"


def _line(c: dict, labels: dict, mark: str = "-") -> str:
    """One claim, verbatim, with its citations, and its label's short form when `labels` is given."""
    label = labels.get(c["label"])
    return f"{mark} {c['text']} [{'; '.join(_cite_label(x) for x in c.get('citations') or [])}]" + \
        (f" {label}" if label else "")


def step_of(c: dict) -> int | None:
    s = c.get("step")
    return s if isinstance(s, int) and not isinstance(s, bool) and s > 0 else None


def _cell(v) -> str:
    return str(v).replace("|", "\\|").replace("\n", " ").strip()


def coverage_table(shown: list[dict], rows: list[dict]) -> tuple[str, list[dict]]:
    """A markdown table built only from lookup rows the tools returned: those on a shown claim's
    cited pages/rows for a drug the claim names. Cells are the rows' stored fields; nothing comes
    from the model. Returns (table, the rows used); ("", []) when there are none."""
    from pharmassist.agent.tools import catalog
    used = []
    for c in shown:
        for r in _rows_for(c.get("text") or "", rows, locators_of(c)):
            if r not in used:
                used.append(r)
    if not used:
        return "", []
    lines = ["| Drug | Program | Status (as stored) | Row |", "|---|---|---|---|"]
    for r in used:
        st, program = r["stored"], (catalog().get(r["doc_id"]) or {}).get("program", r["doc_id"])
        if r["source"] == "ny":
            drug = st.get("drug_name", "")
            status = [f"listed_as: {st.get('listed_as')}"]
            if st.get("flags"):
                status.append("flags: " + ", ".join(st["flags"]))
            if st.get("effective_date_marker"):
                status.append(f"effective_date_marker: {st['effective_date_marker']}")
        else:
            drug = f"{st.get('Generic', '')} {st.get('Dosage Form', '')}"
            status = [f"Restriction: {st.get('Restriction') or '(blank)'}",
                      f"Restriction meaning: {st.get('Restriction meaning', '')}"]
            if r.get("result") == "dosage_form_not_listed":
                status.append("lookup result: dosage_form_not_listed")
        lines.append(f"| {_cell(drug)} | {_cell(program)} | {_cell('; '.join(status))} | {_cell(r['row_id'])} |")
    return "\n".join(lines), used


def assemble(header: str, checked: list[dict], answer_problems: list[Problem], policies: list[dict],
             status: str = "answered", labels: dict | None = None, table: str = "") -> tuple[str, bool]:
    """The whole response, in code: header; the direct claim; passing supporting claims (those
    with a step number as a numbered list in step order, then the rest); the coverage table; policy
    lines; a fixed 'could not verify <type>' line per omitted type. With `labels`, each claim shows
    its label's short form (off on the live path: labels stay in the response metadata). Abstains when the direct claim (or the answer's structure) fails.
    Returns (text, abstained)."""
    labels = labels or {}
    if status == "out_of_scope":
        return f"{header}\n\n{OUT_OF_SCOPE}", False
    direct = [c for c in checked if c.get("direct_answer")]
    if answer_problems or len(direct) != 1 or not direct[0]["passed"]:
        return f"{header}\n\n{ABSTAIN}", True
    support = [c for c in checked if not c.get("direct_answer")]
    passing = [c for c in support if c["passed"]]
    # the model's own step numbers are kept, so an omitted step shows as a gap
    steps = sorted((c for c in passing if step_of(c)), key=step_of)
    rest = [c for c in passing if not step_of(c)]
    omitted = list(dict.fromkeys(c["type"] for c in support if not c["passed"]))
    bullets = [_line(c, labels) for c in rest]
    if steps:   # direct claim, then the numbered steps, then the other supporting claims
        blocks = [header, _line(direct[0], labels),
                  "\n".join(_line(c, labels, f"{step_of(c)}.") for c in steps)] + (["\n".join(bullets)] if bullets else [])
    else:
        blocks = [header, "\n".join([_line(direct[0], labels)] + bullets)]
    if table:
        blocks.append(table)
    if policies:
        blocks.append("\n".join(p["text"] for p in policies))
    if omitted:
        blocks.append(" ".join(COULD_NOT_VERIFY.format(label=TYPE_LABELS[t]) for t in omitted))
    return "\n\n".join(blocks), False


def resolve_program(question: str, program_filter: str | None = None) -> tuple[str, list[str]]:
    """The response header, from trusted inputs only: the programs the question names (by name or
    alias), else a trusted program filter from the request, else the fixed 'not specified' text."""
    named = sorted(((m.start(), prog) for prog, pat in PROGRAM_ALIASES.items()
                    for m in [re.search(pat, question, 0 if prog == "VA" else re.I)] if m), key=lambda x: x[0])
    programs = [p for _, p in named]
    if programs:
        joined = programs[0] if len(programs) == 1 else ", ".join(programs[:-1]) + " and " + programs[-1]
        return f"{joined} (stated in the question)", programs
    if program_filter:
        return f"Assuming {program_filter}", [program_filter]
    return NO_PROGRAM, []


# ---- optional offline audit (never on the live path) ----

AUDIT_SYSTEM = """\
You audit claims written for pharmacy staff against the evidence each one cites. Use only the \
evidence text given; never your own knowledge. For each claim decide supported (its cited evidence \
states it, with every condition and qualifier), partially_supported (the core is stated but a \
value, scope or condition isn't), or unsupported; quote in unsupported_words the claim's words the \
evidence doesn't support (empty if supported); and say whether it is self_contained (understandable \
alone). One sentence of reason each."""

AUDIT_SCHEMA = {
    "type": "object", "additionalProperties": False, "required": ["verdicts"],
    "properties": {"verdicts": {"type": "array", "items": {
        "type": "object", "additionalProperties": False,
        "required": ["claim", "verdict", "unsupported_words", "self_contained", "reason"],
        "properties": {"claim": {"type": "integer"},
                       "verdict": {"type": "string", "enum": ["supported", "partially_supported", "unsupported"]},
                       "unsupported_words": {"type": "string"},
                       "self_contained": {"type": "boolean"},
                       "reason": {"type": "string"}}}}},
}


def audit_claims(client, acfg: dict, claims: list[dict], evidence: dict[str, str], question: str = "") -> dict:
    """One batched model call judging every claim against its cited pages, for eval reports only.
    Never called while answering. Returns {"verdicts", "model", "usage"}."""
    chars = acfg.get("evidence_chars", 6000)
    blocks, locs_used = [], []
    for i, c in enumerate(claims, 1):
        locs = locators_of(c)
        blocks.append(f"Claim {i} [{c.get('type')}]: {c.get('text')}\nCites: {', '.join(locs) or 'nothing'}")
        locs_used += [l for l in locs if l not in locs_used]
    ev = "\n\n".join(f"## {l}\n{evidence.get(l, '(not returned by any tool)')[:chars]}" for l in locs_used)
    user = (f"# Staff question\n{question}\n\n" if question else "") + "# Claims\n" + "\n\n".join(blocks) + \
        "\n\n# Evidence\n" + ev
    resp = client.beta.messages.create(
        model=acfg["model"], max_tokens=acfg.get("max_tokens", 2000), system=AUDIT_SYSTEM,
        messages=[{"role": "user", "content": user}],
        output_config={"format": {"type": "json_schema", "schema": AUDIT_SCHEMA},
                       **({"effort": acfg["effort"]} if acfg.get("effort") else {})},
        timeout=acfg.get("timeout_s", 60))
    if resp.stop_reason != "end_turn":
        raise RuntimeError(f"audit stopped with {resp.stop_reason}")
    u = resp.usage
    usage = {"input": u.input_tokens or 0, "output": u.output_tokens or 0,
             "cache_read": getattr(u, "cache_read_input_tokens", None) or 0,
             "cache_write": getattr(u, "cache_creation_input_tokens", None) or 0}
    return {"verdicts": json.loads("".join(b.text for b in resp.content if b.type == "text"))["verdicts"],
            "model": resp.model, "usage": usage}
