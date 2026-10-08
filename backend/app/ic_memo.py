"""The IC memo (docs/specs/verdict-and-memo.md section 7, method A11).

A pure module: it is handed the register, the verdict, the stored results, the audit, the stored narratives and the usage,
and returns Markdown, or refuses and says why. It imports nothing from `app.llm`, calls no model, stores nothing and
generates no narrative. Python never rates: the two assessed rows carry the analyst's rating, the other four say "Not
assessed". Every number is checked against the stored data before the text is returned (section 7.4).
"""
from __future__ import annotations

import io
import math
import re
from decimal import ROUND_HALF_UP, Decimal
from typing import Dict, Iterable, List, Optional, Tuple

from app import claim_matching as cm
from app import disclosure
from app import formatting as fmt
from app import verdict as vd
from schemas import metrics as contract

WORD_LIMIT = 1500
FIXED_NUMERALS = (5, 7, 12)             # the top 5, the 7 evidence categories, the 12-month window (section 7.4 g)

# Screen wording W15-W19 (section 11), as approved.
TITLE = "Investment committee memo: {company}"
HEADINGS = ("Summary", "Deal thesis", "Scorecard", "Key gates and deal terms", "Worth flagging", "Data gaps and requests")
APPENDICES = ("Appendix A – Claim register and gates", "Appendix B – Data gaps and data request list",
              "Appendix C – Detailed analysis tables", "Appendix D – Source key list and value-at-risk de-duplication")
W16_VALUE_AT_RISK = ("Value at risk: ARR not yet computed (ARR bridge not run); cash not yet computed (no cash analysis). "
                     "Overlapping claims are counted once, at the largest value in their group.")
W17_NOT_ASSESSED = (
    ("Strategic coherence", "Not assessed – strategy documents not ingested"),
    ("Forecast track record", "Not assessed – past budgets and forecasts not ingested"),
    ("Execution capacity", "Not assessed – hiring plan and organisation data not ingested"),
    ("Defensibility", "Not assessed – market and competitor data not ingested"),
)
S17 = ("Narrative could not be generated. The computed metrics below are unaffected — they come from the calculation "
       "engine, not the narrative.")
W19_PREFIX = "Memo not exported: "
W19_WORDS = W19_PREFIX + "{n} words; the limit is 1,500."
W19_NUMBERS = W19_PREFIX + "{n} numbers are not in the stored results: {list}."
W19_BLOCKED = W19_PREFIX + "the verdict is blocked."
W19_KEY_GATES = W19_PREFIX + "mark 3 to 5 key gates."
W19_RATE = W19_PREFIX + "rate {rows}."
W19_CONTRACT = W19_PREFIX + "the stored results fail the contract: {fields}."
CONTRACT_NO_VERDICT = "No verdict: the stored results fail the contract: {fields}."
W19_TOP5 = W19_PREFIX + vd.W23_MEMO
# Not in W1-W25 (reported under "Decisions for you"): the refusals for a missing thesis and for no verdict at all.
WORDING_NOT_IN_W = {
    "thesis": W19_PREFIX + "write the deal thesis: {parts}.",
    "no_verdict": W19_PREFIX + "{message}",
}

RATING_LABELS = {"data_reliability": "Data reliability", "growth_engine": "Growth engine"}
THESIS_LABELS = {"plan": "Plan", "evidence": "Evidence", "condition": "Condition"}

CATEGORIES = (
    ("Monthly revenue by customer", "revenue", None),
    ("CRM export", "crm", None),
    ("P&L and budget vs actuals", "pnl", "budget vs actuals is not ingested"),
    ("Headcount history and hiring plan", None, "not ingested by the app"),
    ("Product usage data", None, "not ingested by the app"),
    ("Board decks, last 6–8 quarters", "decks", "the app does not check which quarters the decks cover"),
    ("Roadmap and hiring budget by segment/product", None, "not ingested by the app"),
)


class MemoRefused(Exception):
    """The memo is not exported. `code` is the closed reason for the log; `message` is what the analyst reads."""

    def __init__(self, code: str, message: str, words: Optional[int] = None, unmatched: Optional[List[str]] = None):
        super().__init__(message)
        self.code, self.message, self.words, self.unmatched = code, message, words, unmatched or []


# --- numbers (section 7.4) --------------------------------------------------------------------------------------------------

_DATE = re.compile(r"\d{4}-\d{2}(?:-\d{2})?(?![\d])|\d{4}-Q[1-4]|\bQ[1-4]\b|\[\^\d+\]:?")
_NUMBER = re.compile(r"(?<![\w.])-?\d[\d,]*(?:\.\d+)?")


def _decimal(token: str) -> Decimal:
    return Decimal(token.replace(",", "")).copy_abs()


def _quantized(d: Decimal, places: Iterable[int]) -> Iterable[Tuple[int, Decimal]]:
    for p in places:
        yield p, d.quantize(Decimal(1).scaleb(-p), rounding=ROUND_HALF_UP)


# The places a figure is written with, by its kind (app/formatting.py): a percent is its fraction times 100, whole or to
# two places (a gap of 69.61%); currency whole or to the cent; days rounded up; months to one or two places; ratios to two.
_PLACES = {fmt.PCT: (0, 1, 2), fmt.CURRENCY: (0, 2), fmt.COUNT: (0,), fmt.COUNT_UP: (0,), fmt.DAYS: (0, 1), fmt.MONTHS: (1, 2),
           fmt.RATIO: (2,), fmt.PLAIN: (0,)}


def _keys(value, kind: Optional[str] = None, places: Iterable[int] = (0, 1, 2), percent: bool = False) -> Iterable[Tuple[int, Decimal]]:
    """Every way a stored number may be written: by its kind when it has one, else rounded to `places`; a fraction also as a
    percent; days also rounded up."""
    try:
        d = Decimal(str(value)).copy_abs()
    except Exception:
        return
    if not d.is_finite():
        return
    if kind:
        places = _PLACES.get(kind, places)
        percent = kind == fmt.PCT
    for scaled in ((d * 100,) if percent else (d,)):
        yield from _quantized(scaled, places)
        if kind in (fmt.DAYS, None):
            yield 0, Decimal(math.ceil(scaled))
    yield from _quantized(d, (0,)) if percent else ()


class Allowed:
    """The numbers the memo may state."""

    def __init__(self):
        self.keys: set = set()
        self.words: set = set()

    def number(self, value, kind: Optional[str] = None, **kw) -> "Allowed":
        if isinstance(value, (int, float)) and not isinstance(value, bool):
            self.keys.update(_keys(value, kind, **kw))
            self.words.add(str(value))
        return self

    def text(self, value) -> "Allowed":
        for token in _tokens(str(value)):
            self.words.add(token)
            self.keys.update(_quantized(_decimal(token), range(0, 7)))
        return self

    def tree(self, node, percent_keys: Iterable[str] = ("gap_normalised", "shortfall")) -> "Allowed":
        """Every number, every number inside a text, every numeric key and the length of every list of a structure of the
        register, the audit or the cost log (a number written as it is, to up to two places)."""
        if isinstance(node, dict):
            for k, v in node.items():
                self.text(k) if isinstance(k, str) else self.number(k)
                if k in percent_keys:
                    self.number(v, percent=True)
                self.tree(v, percent_keys)
            self.number(len(node))
        elif isinstance(node, (list, tuple)):
            self.number(len(node))
            for v in node:
                self.tree(v, percent_keys)
        elif isinstance(node, str):
            self.text(node)
        else:
            self.number(node)
        return self

    def results(self, payload, results) -> "Allowed":
        """The stored results, each figure read with its kind (schemas/metrics.py); the texts, the numeric keys and the length of
        every list are stored data too. Row numbers of a citation are bookkeeping, not figures."""
        for path, unit, value in contract.iter_figures(payload):
            if "row_numbers" not in path:
                self.number(value, unit.kind)
        self._strings(results)
        return self

    def _strings(self, node) -> None:
        if isinstance(node, dict):
            for k, v in node.items():
                if k != "row_numbers":
                    self.text(k)
                    self._strings(v)
            self.number(len(node))
        elif isinstance(node, (list, tuple)):
            self.number(len(node))
            for v in node:
                self._strings(v)
        elif isinstance(node, str):
            self.text(node)

    def derived_cells(self, rows: List[List[str]]) -> "Allowed":
        """Allow a cell that is a sum or a difference of two stored cells of the same row (one unit of the last place of slack
        per operand, since the cells are rounded)."""
        for row in rows:
            tokens = [t for cell in row for t in _tokens(str(cell))]
            stored = [t for t in tokens if self.ok(t)]
            for token in tokens:
                if token in stored or self.ok(token):
                    continue
                d = _decimal(token)
                places = max(0, -d.as_tuple().exponent)
                slack = 2 * Decimal(1).scaleb(-places)
                values = [_decimal(t) for t in stored]
                if any(abs(a + b - d) < slack or abs(abs(a - b) - d) < slack for i, a in enumerate(values) for b in values[i + 1:]):
                    self.words.add(token.replace(",", "").lstrip("-"))
                    self.words.add(token)
        return self

    def ok(self, token: str) -> bool:
        clean = token.replace(",", "").lstrip("-")
        if clean in self.words or token in self.words:
            return True
        d = _decimal(token)
        places = max(0, -d.as_tuple().exponent)
        return (min(places, 6), d.quantize(Decimal(1).scaleb(-min(places, 6)), rounding=ROUND_HALF_UP)) in self.keys


def _tokens(text: str) -> List[str]:
    return _NUMBER.findall(_DATE.sub(" ", text))


def unmatched(text: str, allowed: Allowed) -> List[str]:
    """The numeric tokens of `text` that are not allowed, in order of appearance, once each. Dates, months, quarters and footnote
    markers are not numbers."""
    seen, out = set(), []
    for token in _tokens(text):
        if token not in seen and not allowed.ok(token):
            seen.add(token)
            out.append(token)
    return out


def count_words(text: str) -> int:
    """Whitespace-separated tokens that hold a letter or a digit (section 7.5). Table pipes and heading marks are not words."""
    return sum(1 for t in text.split() if re.search(r"[^\W_]", t))


# --- the export's tables (Appendix C) -----------------------------------------------------------------------------------------

SKIPPED_SHEETS = ("Missing Data", "Glossary")        # Missing Data is in Appendix B; the glossary is not a data table
SHEET_BLOCKS = {
    "Headline": ("arr", "nrr", "gross_churn", "cac_payback", "sales_cycle", "win_rate"),
    "By Segment": ("nrr", "sales_cycle", "acv_path"), "NRR by Cohort": ("nrr",), "NRR Series": ("nrr",),
    "CAC by Quarter": ("cac_payback",), "Path to Plan": ("acv_path",), "ACV Bands": ("acv_path",),
    "Segment Base": ("segment_paths",), "Segment Mix": ("segment_paths",), "Segment Mix Detail": ("segment_paths",),
    "Anomalies": ("anomalies",),
}


def render_cell(value, number_format: str = "General") -> str:
    """A workbook cell as the app writes it on screen: by its Excel number format (app/formatting.py)."""
    if value is None:
        return ""
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return str(value)
    if number_format == fmt.XLSX_NUMBER_FORMAT[fmt.PCT]:
        return fmt.fmt_pct(value)
    if number_format == fmt.XLSX_NUMBER_FORMAT[fmt.MONTHS]:
        return fmt.fmt_months(value).removesuffix(" months")
    if number_format == fmt.XLSX_NUMBER_FORMAT[fmt.RATIO]:
        return fmt.fmt_ratio(value)
    if number_format == fmt.XLSX_NUMBER_FORMAT[fmt.CURRENCY]:
        return fmt.fmt_count(value)
    if number_format == fmt.XLSX_NUMBER_FORMAT[fmt.PLAIN]:
        return fmt.fmt_plain(value)
    return str(value)


def workbook_tables(workbook: io.BytesIO) -> List[dict]:
    """The export's data tables, read from the workbook the export code built (the same row code): [{sheet, rows}]."""
    import openpyxl

    wb = openpyxl.load_workbook(workbook, data_only=True)
    out = []
    for ws in wb.worksheets:
        if ws.title in SKIPPED_SHEETS:
            continue
        rows = [[render_cell(c.value, c.number_format) for c in row] for row in ws.iter_rows()]
        rows = [r for r in rows if any(r)]
        if rows:
            out.append({"sheet": ws.title, "rows": rows})
    return out


# --- footnotes ------------------------------------------------------------------------------------------------------------------

class Notes:
    """Markdown footnotes: one per distinct source text, numbered in order of first use and resolved in Appendix D."""

    def __init__(self):
        self.texts: List[str] = []

    def add(self, text: str) -> str:
        if text not in self.texts:
            self.texts.append(text)
        return f"[^{self.texts.index(text) + 1}]"

    def source(self, analysis: str, key: str, source: Optional[dict] = None, rule: Optional[str] = None) -> str:
        """analysis · source key · file · sheet · rows · rule"""
        s = source or {}
        parts = [analysis, key, s.get("file"), s.get("sheet"), s.get("rows"), rule or s.get("rule")]
        return self.add(" · ".join(str(p) for p in parts if p))

    def register(self, ranks: Iterable[int] = ()) -> str:
        ranks = sorted(ranks)
        return self.add("claim register" + (", " + ", ".join(f"#{r}" for r in ranks) if ranks else ""))

    def analyst(self) -> str:
        return self.add("set by the analyst")

    def definitions(self) -> str:
        return "\n".join(f"[^{i}]: {t}" for i, t in enumerate(self.texts, 1))


def _cell(text) -> str:
    return re.sub(r"\s+", " ", str(text)).replace("|", "/").strip()


def _table(header: List[str], rows: List[List[str]]) -> str:
    lines = ["| " + " | ".join(_cell(h) for h in header) + " |", "|" + "---|" * len(header)]
    lines += ["| " + " | ".join(_cell(c) for c in r) + " |" for r in rows]
    return "\n".join(lines)


# --- the memo -------------------------------------------------------------------------------------------------------------------

def evidence_categories(files: List[dict], decks: List[dict]) -> List[dict]:
    """Section 7.2: a category is covered when a stored file of its type exists (the app ingests four types)."""
    present = {f["dtype"] for f in files}
    out = []
    for name, kind, note in CATEGORIES:
        covered = bool(decks) if kind == "decks" else kind in present if kind else False
        out.append({"category": name, "covered": covered, "note": note})
    return out


def overlap_groups(rows: List[dict]) -> List[List[int]]:
    """Connected groups of overlapping rows, as ranks (section 2.2); a row that overlaps nothing is in no group."""
    by_id = {r["claim_id"]: r for r in rows}
    seen, groups = set(), []
    for r in rows:
        if r["claim_id"] in seen or not r["overlaps_with"]:
            continue
        stack, group = [r["claim_id"]], []
        while stack:
            i = stack.pop()
            if i in seen or i not in by_id:
                continue
            seen.add(i)
            group.append(by_id[i]["rank"])
            stack.extend(by_id[i]["overlaps_with"])
        groups.append(sorted(group))
    return groups


def anomaly_count(results: dict) -> Optional[int]:
    """The anomaly flags the screen lists, added up (gapLists.js anomalyFlags); None when the engine could not compute them."""
    a = results.get("anomalies")
    if not a:
        return None
    return (len(a.get("negative_mrr_months") or ()) + len(a.get("revenue_gap_then_resume") or ())
            + ((a.get("revenue_missing_customer_id") or {}).get("count") or 0)
            + ((a.get("deals_close_before_created") or {}).get("excluded_count") or 0)
            + len(a.get("date_order_from_data") or ()))


def _growth_narrative(narratives: List[dict]) -> Optional[dict]:
    for n in narratives or ():
        n = n if isinstance(n, dict) else n.model_dump()
        if n.get("step") == "growth_engine" and n.get("narrative_status") == "ok" and n.get("narrative"):
            return n["narrative"]
    return None


def _needs(ic: dict, rows: List[dict], key: dict) -> None:
    missing = [RATING_LABELS[k] for k in vd.RATED_ROWS if (ic.get("ratings") or {}).get(k) not in vd.RATINGS]
    if missing:
        raise MemoRefused("inputs", W19_RATE.format(rows=", ".join(missing)))
    absent = [THESIS_LABELS[k] for k in vd.THESIS_PARTS if not (ic.get("thesis") or {}).get(k)]
    if absent:
        raise MemoRefused("inputs", WORDING_NOT_IN_W["thesis"].format(parts=", ".join(absent)))


def _build(*, audit, results, rows, ver, key, gaps, ic, blockers, narratives, usage, files, decks, tables, today,
           thesis: Dict[str, str]) -> Tuple[str, str]:
    """(sections 1-6 with the title, the whole text) for one view of the thesis."""
    notes = Notes()
    ccy = results.get("reporting_currency")
    by_id = {r["claim_id"]: r for r in rows}
    five = [by_id[f["claim_id"]] for f in ver["five"]]
    top_ranks = [r["rank"] for r in five]
    counts = cm.label_counts(rows)
    categories = evidence_categories(files, decks)
    covered = sum(1 for c in categories if c["covered"])
    narrative = _growth_narrative(narratives)
    out: List[str] = [f"# {TITLE.format(company=audit.get('company_name') or 'audit')}", f"Date: {today}", ""]

    # 1. Summary
    out += [f"## {HEADINGS[0]}", f"Verdict: {ver['outcome']} – {ver['rule']}{notes.register(top_ranks)}", vd.W24_STATEMENT, ""]
    out += [f"Files reviewed: {len(files)} data {'file' if len(files) == 1 else 'files'} and {len(decks)} {'deck' if len(decks) == 1 else 'decks'}.{notes.add('files by evidence category, Appendix D')}",
            f"Evidence categories covered: {covered} of 7.{notes.add('files by evidence category, Appendix D')}",
            "Claims: " + ", ".join(f"{counts.get(label, 0)} {label}" for label in ("Contradicted", "Unsupported", "Unverified"))
            + f" of {len(rows)} in the register.{notes.register()}", W16_VALUE_AT_RISK, ""]

    # 2. Deal thesis
    out += [f"## {HEADINGS[1]}"]
    out += [f"{THESIS_LABELS[k]}: {thesis.get(k, '')}{notes.analyst()}" for k in vd.THESIS_PARTS]
    out += [""]

    # 3. Scorecard
    rec = results.get("revenue_reconciliation") or {}
    flags = anomaly_count(results)
    verified = counts.get("Verified", 0)
    if rec.get("available"):
        pct = "—" if rec.get("gap_pct") is None else f"{abs(rec['gap_pct']) * 100:g}"
        src = rec.get("source") or {}
        side = src.get("revenue_file") or {}
        recon = (f"Revenue file and P&L differ by {pct}% over {rec.get('first')}–{rec.get('last')}"
                 f"{notes.source('Revenue reconciliation', 'revenue_reconciliation.gap_pct', side, (src.get('pnl') or {}).get('rule'))}")
    else:
        recon = "no P&L to reconcile"
    anomalies = (f"{flags} anomaly flags{notes.source('Anomaly Flags', 'anomalies', (results.get('anomalies') or {}).get('source'))}"
                 if flags is not None else "anomaly flags not computed")
    reliability = f"{recon}; {anomalies}; {verified} of {len(rows)} claims Verified{notes.register()}."
    if narrative:
        growth = f"{narrative['headline']}{notes.add('growth-engine narrative, AI call log')}"
    else:
        arr, nrr, churn = results.get("arr") or {}, results.get("nrr") or {}, results.get("gross_churn") or {}
        growth = (f"ARR {fmt.fmt_currency(arr.get('value'), ccy)}{notes.source('Monthly MRR by Segment', 'arr.value', arr.get('source'))}, "
                  f"NRR {fmt.fmt_pct(nrr.get('overall_pct'))}{notes.source('NRR', 'nrr.overall_pct', nrr.get('source'))}, "
                  f"gross revenue churn {fmt.fmt_pct(churn.get('overall_pct'))}"
                  f"{notes.source('Gross revenue churn', 'gross_churn.overall_pct', churn.get('source'))}. {S17}")
    ratings = ic.get("ratings") or {}
    score = [["Data reliability", ratings["data_reliability"], reliability, "revenue_reconciliation, anomalies, claim register"],
             ["Growth engine", ratings["growth_engine"], growth, "arr, nrr, gross_churn, cac_payback, acv_path"]]
    score += [[name, text, "", ""] for name, text in W17_NOT_ASSESSED]
    out += [f"## {HEADINGS[2]}", _table(["Area", "Rating", "Headline", "Key evidence"], score), ""]

    # 4. Key gates and deal terms
    out += [f"## {HEADINGS[3]}"]
    if key["note"]:
        out += [key["note"]]
    out += [f"- {g['gate_sentence']}{notes.add('claim register, #%d; set by the analyst' % g['rank'])}" for g in key["gates"]]
    out += [vd.W13_DEAL_TERMS, ""]

    # 5. Worth flagging
    out += [f"## {HEADINGS[4]}"]
    flagged = []
    for b in blockers:
        if b.get("kind") == "claim_contradicted" and b.get("claim_id") in by_id:
            flagged.append(f"{b['text']}{notes.register([by_id[b['claim_id']]['rank']])}")
        elif b.get("kind") == "revenue_reconciliation":
            flagged.append(f"{b['text']}{notes.source('Revenue reconciliation', 'revenue_reconciliation', (b.get('citation') or {}).get('revenue_file'))}")
        else:
            flagged.append(b["text"])
    if narrative:
        flagged += [f"{item}{notes.add('growth-engine narrative, AI call log')}" for item in narrative.get("worth_flagging") or ()]
    elif not narrative:
        flagged.append(S17)
    out += [f"- {f}" for f in flagged] + [""]

    # 6. Data gaps and requests
    out += [f"## {HEADINGS[5]}"]
    for g in gaps[:5]:
        date = f" Target date: {g['target_date']}." if g["target_date"] else ""
        out += [f"- {g['item']}: {g['why']} Requested: {str(g['requested']).rstrip('.')}.{date}{notes.source('Missing Data', 'missing_data')}"]
    if len(gaps) > 5:
        out += [f"and {len(gaps) - 5} more in Appendix B{notes.source('Missing Data', 'missing_data')}"]
    out += [f"- {q}{notes.source('Questions for management', 'questions_for_management')}" for q in vd.management_questions(results)]
    head = "\n".join(out).rstrip() + "\n"

    # Appendices
    app: List[str] = []
    app += [f"## {APPENDICES[0]}"]
    reg = [[f"#{r['rank']}", vd.claim_name(r) + f" – {vd.claimed_text(r, results.get('reporting_currency'))}", r["evidence_label"],
            "not yet computed" + (f" · shortfall {r['shortfall'] * 100:.1f}%" if r["shortfall"] is not None else ""),
            ", ".join(f"#{by_id[o]['rank']}" for o in r["overlaps_with"] if o in by_id) or "—",
            f"{r['evidence_analysis']} · {r['evidence_source_key']} ({r['observed_at']})" if r["evidence_analysis"] and r["observed_at"]
            else (f"{r['evidence_analysis']} · {r['evidence_source_key']}" if r["evidence_analysis"] else r["reason"]),
            r["gate_sentence"] or (vd.W4_GATE_NEEDED if r["gate_needed"] else "—"),
            "key" if r["claim_id"] in {g["claim_id"] for g in key["gates"]} else "", "top 5" if r["claim_id"] in {f["claim_id"] for f in ver["five"]} else ""]
           for r in rows]
    app += [_table(["#", "Claim", "Label", "Value at stake", "Overlaps with", "Evidence", "Gate", "Key gate", "Top 5"], reg), ""]

    review = ic.get("first_quarterly_review")
    app += [f"## {APPENDICES[1]}", f"First quarterly review: {review or '—'}", ""]
    app += [_table(["What the company cannot measure", "Why it matters", "Requested", "Target date"],
                   [[g["item"], g["why"], g["requested"] or "", g["target_date"] or "—"] for g in gaps]) if gaps else "No data gaps.", ""]
    asks = [f"- {g['requested']}" for g in gaps if g["requested"]] + [f"- {q}" for q in vd.management_questions(results)]
    asks += [f"- {o['item']}: {o['requested']}" for o in vd.other_requests(results) if o["requested"]]
    app += ["Requests", *asks, ""]

    app += [f"## {APPENDICES[2]}"]
    for t in tables:
        block = SHEET_BLOCKS.get(t["sheet"], ())
        cite = "".join(notes.source(t["sheet"], b, (results.get(b) or {}).get("source")) for b in block if (results.get(b) or {}).get("source"))
        width = max(len(r) for r in t["rows"])
        rows_ = [r + [""] * (width - len(r)) for r in t["rows"]]
        app += [f"{t['sheet']}{cite}", _table(rows_[0], rows_[1:]), ""]
    if rec.get("available") and rec.get("by_month"):
        cite = notes.source("Revenue reconciliation", "revenue_reconciliation.by_month", (rec.get("source") or {}).get("revenue_file"))
        app += [f"Revenue reconciliation by month{cite}",
                _table(["Month", "Revenue file", "P&L", "Gap", "Gap %"],
                       [[m["month"], fmt.fmt_currency(m["revenue_file"], ccy), fmt.fmt_currency(m["pnl"], ccy),
                         fmt.fmt_currency(m["gap"], ccy), fmt.fmt_pct(m.get("gap_pct"))] for m in rec["by_month"]]), ""]

    app += [f"## {APPENDICES[3]}", "Files reviewed"]
    app += [_table(["Category", "Covered", "Files", "Note"],
                   [[c["category"], "yes" if c["covered"] else "no",
                     "; ".join(f"{f['file']} ({f['sheet']})" for f in files if f["dtype"] == kind) if kind and kind != "decks"
                     else ("; ".join(d["file"] for d in decks) if kind == "decks" else ""), c["note"] or ""]
                    for c, (_, kind, _) in zip(categories, CATEGORIES)]), ""]
    groups = overlap_groups(rows)
    app += ["Value at risk: de-duplication", W16_VALUE_AT_RISK,
            "Overlap groups: " + ("; ".join(", ".join(f"#{n}" for n in g) for g in groups) if groups else "none"), ""]
    app += ["AI usage and cost (this audit)", _usage_table(usage), ""]
    block = disclosure.build_disclosure([{"step": n["step"] if isinstance(n, dict) else n.step,
                                          "model": (n if isinstance(n, dict) else n.model_dump()).get("model"),
                                          "generated_at": (n if isinstance(n, dict) else n.model_dump()).get("generated_at")}
                                         for n in narratives or ()])
    if block:
        app += [block["text"], ""]
    app += ["Footnotes", notes.definitions()]
    return head, head + "\n" + "\n".join(app) + "\n"


def _usage_table(usage: dict) -> str:
    labels = {"deck_structure": "Deck structure reading", "column_mapping": "Column mapping"}
    rows = []
    for step, u in (usage.get("by_step") or {}).items():
        name = labels.get(step) or f"Narrative – {step}"
        rows.append([name, u["calls"], u["cache_hits"], fmt.fmt_count(u["input_tokens"]), fmt.fmt_count(u["output_tokens"]),
                     f"{u['estimated_cost_usd']:.2f}"])
    rows.append(["Total", usage.get("calls", 0) + usage.get("structure_calls", 0), usage.get("cache_hits", 0),
                 fmt.fmt_count(usage.get("input_tokens", 0)), fmt.fmt_count(usage.get("output_tokens", 0)),
                 f"{usage.get('estimated_cost_usd', 0):.2f}"])
    return _table(["Step", "Calls", "Cache hits", "Input tokens", "Output tokens", "Cost (USD)"], rows)


def allowed_numbers(audit: dict, results: dict, rows: List[dict], gaps: List[dict], ic: dict, usage: dict, files: List[dict],
                    decks: List[dict], thesis: bool, tables: Optional[List[dict]] = None) -> Allowed:
    """The numbers a memo may state. `thesis=True` is the set for a thesis sentence: (a)-(c) and (e), without the analyst's deal terms."""
    allowed = Allowed().results(contract.MetricsPayload.model_validate(results), results)
    allowed.tree({k: audit.get(k) for k in ("company_name", "target_arr", "target_date", "as_of_month")})
    analyst_fields = ("gate_threshold", "gate_budget_decision", "gate_metric_name", "gate_sentence", "gate_date")
    allowed.tree([{k: v for k, v in r.items() if thesis is False or k not in analyst_fields} for r in rows])
    allowed.tree(gaps).tree(usage).tree([f["file"] for f in files]).tree([d["file"] for d in decks])
    for n in FIXED_NUMERALS:
        allowed.number(n)
    for n in range(0, max(len(rows), len(gaps), len(files) + len(decks), 8) + 1):
        allowed.number(n)                                   # counts of rows, gaps, files, categories and gates the memo states
    if not thesis:
        # Appendix C's cells are the export's own rows. A cell the stored data does not hold is allowed only when it is the sum or
        # the difference of two other cells of its row that it does hold; a ratio or any other derived figure is refused.
        allowed.derived_cells([row for t in tables or () for row in t["rows"]])
        allowed.tree(ic.get("gap_target_dates") or {}).tree(ic.get("first_quarterly_review"))
    return allowed


def build_memo(*, audit: dict, results: dict, rows: List[dict], ver: dict, key: dict, gaps: List[dict], ic: dict,
               blockers: List[dict], narratives: List, usage: dict, files: List[dict], decks: List[dict], tables: List[dict],
               today: str) -> str:
    """The IC memo as Markdown, or `MemoRefused` (section 7.1). Built on request from the functions of the register and the verdict;
    nothing is stored."""
    try:
        contract.validate_for_export(results)
    except contract.ContractError as exc:
        raise MemoRefused("contract", W19_CONTRACT.format(fields=exc.log_text)) from exc
    if ver["status"] in ("no_verdict",):
        raise MemoRefused("no_verdict", WORDING_NOT_IN_W["no_verdict"].format(message=ver["message"].removeprefix("No verdict: ")))
    if ver["status"] in ("unconfirmed", "void"):
        raise MemoRefused("top5", W19_TOP5)
    if ver["status"] == "blocked":
        raise MemoRefused("blocked", W19_BLOCKED)
    if not key["ok"]:
        raise MemoRefused("key_gates", W19_KEY_GATES)
    _needs(ic, rows, key)

    common = dict(audit=audit, results=results, rows=rows, ver=ver, key=key, gaps=gaps, ic=ic, blockers=blockers,
                  narratives=narratives, usage=usage, files=files, decks=decks, tables=tables, today=today)
    # A number in a thesis sentence must be in the results, the register or the cost log: checked sentence by sentence.
    strict = allowed_numbers(audit, results, rows, gaps, ic, usage, files, decks, thesis=True)
    bad = [t for part in vd.THESIS_PARTS for t in unmatched(ic["thesis"][part], strict)]
    # Everything else, appendices included, against the full set; the date line is the one line the check skips.
    _, blank = _build(**common, thesis={k: "" for k in vd.THESIS_PARTS})
    checked = "\n".join(line for line in blank.split("\n") if not line.startswith("Date: "))
    bad += [t for t in unmatched(checked, allowed_numbers(audit, results, rows, gaps, ic, usage, files, decks, thesis=False, tables=tables))
            if t not in bad]
    if bad:
        raise MemoRefused("numbers", W19_NUMBERS.format(n=len(bad), list=", ".join(bad)), unmatched=bad)
    head, text = _build(**common, thesis=dict(ic["thesis"]))
    words = count_words(head)
    if words > WORD_LIMIT:
        raise MemoRefused("words", W19_WORDS.format(n=f"{words:,}"), words=words)
    return text


def word_count_of(text: str) -> int:
    """Words of a built memo: from the title to the end of section 6 (appendices are not counted)."""
    return count_words(text.split(f"## {APPENDICES[0]}")[0])
