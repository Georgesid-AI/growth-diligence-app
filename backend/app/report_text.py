"""Report text built from the stored map, not from templates (PR 4f; docs/design/read-check-review.md section 16).

A pure module shared by the memo, the report page's data and the Excel export: no database, no model, no file. It reads the role table of the
audit's stored readings (`role_engine.build_table`) and the engine's result status, and writes:

    missing_reason(...)   why a metric is not computed, from what the map holds for each role it needs (four rules, in order)
    apply_reasons(...)    a copy of the results whose missing-metric reasons are those sentences
    unmapped_roles(...)   the roles no file maps at all: the only roles a data request may name
    anomaly_rows(...)     the anomaly flags with "Not applicable" for a check whose input file or data kind is absent
    file_kinds(...)       what each read file is, for Appendix D

It changes no engine output and decides nothing about a row: it describes the table the engine already read.
"""
import copy
import re
from typing import Dict, Iterable, List, Optional

from . import role_engine

# A role by its plain name, as a person writes it in a sentence ("needs a sales and marketing row").
PLAIN = {
    "revenue": "revenue", "bookings": "bookings", "arr": "ARR", "mrr": "MRR", "churn_rate": "churn rate", "customers": "customers",
    "forecast": "plan", "cost_of_revenue": "cost of revenue", "sales_marketing": "sales and marketing", "rnd": "R&D", "ga": "G&A",
    "opex": "operating expenses", "ebitda": "EBITDA", "cash": "cash", "headcount": "headcount",
}
SHORT = {"sales_marketing": "S&M", "rnd": "R&D", "ga": "G&A"}      # the cost splits, as the P&L writes them
OPEX_TOTAL = "OPEX total"
NOT_APPLICABLE = "Not applicable"
AN_NAMES = ("MRR", "R&D")        # read letter by letter: "an MRR row", "an R&D row"; a vowel starts the rest ("an ARR row", "an EBITDA row")
_NEEDS = re.compile(r"needs an? ([a-z_]+) row")


def plain(role: str) -> str:
    return PLAIN.get(role, role.replace("_", " "))


def article(name: str) -> str:
    return "an" if name[:1].lower() in "aeiou" or name in AN_NAMES else "a"


def needs_row(role: str) -> str:
    return f"{article(plain(role))} {plain(role)} row"


def rows_without_series(files: List[dict]) -> List[dict]:
    """The rows of the files' maps that have a role and no series (the engine's table skips them): records with empty `actual` and `plan` and
    `no_series` set, so the report text sees that the role is mapped. A row the checks rejected is no input and is left out, as in the engine."""
    out = []
    for f in files:
        rejected = set(f.get("rejected") or ())
        for smap in (f.get("file_map") or {}).get("sheets") or []:
            for row in smap.get("rows") or []:
                if f"row:{smap['sheet']}:{row['row']}" in rejected or not row.get("role"):
                    continue
                if any(row.get(k) for k in ("series", "plan_series")):
                    continue
                out.append({"file": f.get("file"), "file_hash": f.get("file_hash"), "sheet": smap["sheet"], "row": row["row"], "role": row["role"], "metric": row.get("metric"),
                            "label": (f.get("labels") or {}).get(f"{smap['sheet']}:{row['row']}"), "basis": row.get("basis"),
                            "actual_plan": row.get("actual_plan"), "granularity": smap.get("granularity"),
                            "segment": (row.get("segment") or "").strip() or None, "actual": {}, "plan": {}, "cells": row.get("cells"),
                            "no_series": True})
    return out


def _recs(table: List[dict], role: str) -> List[dict]:
    """The role's rows that hold a series."""
    return [r for r in table if r["role"] == role and not r.get("no_series")]


def _unread(table: List[dict], role: str) -> List[dict]:
    return [r for r in table if r["role"] == role and r.get("no_series")]


def role_state(table: List[dict], role: str) -> str:
    """How the map holds a role: "unmapped" (no row), "no_values" (rows mapped, no series in them), "segments" (segment rows only, no unsegmented total), "plan_only" (total rows that hold no
    actual value) or "mapped" (a total row with actuals)."""
    recs = _recs(table, role)
    if not recs:
        return "no_values" if _unread(table, role) else "unmapped"
    totals = [r for r in recs if r["segment"] is None]
    if not totals:
        return "segments"
    if not any(r["actual"] and r.get("actual_plan") != "plan" for r in totals):
        return "plan_only"
    return "mapped"


def mapped_roles(table: List[dict]) -> set:
    """Every role any file maps, in any columns, any segment, with or without values."""
    return {r["role"] for r in table}


def unmapped_roles(table: List[dict], roles: Iterable[str]) -> List[str]:
    have = mapped_roles(table)
    return [r for r in roles if r not in have]


def _cells(table: List[dict], role: str) -> str:
    """"Report!B10:M10": the cells of the role's row (its longest total row), as a range."""
    from .ic_memo import cell_ranges
    totals = [r for r in _recs(table, role) if r["segment"] is None and r["actual"]]
    if not totals:
        return ""
    rec = max(totals, key=lambda r: len(r["actual"]))
    refs = [cell for _, cell in rec["actual"].values()]
    text = ", ".join(cell_ranges(refs))
    return f"{rec['sheet']}!{text}" if rec.get("sheet") and text else text


def _total_label(table: List[dict]) -> str:
    """The file's own label of the OPEX total row, else "OPEX total"."""
    for rec in _recs(table, "opex"):
        if rec["segment"] is None and (rec.get("label") or "").strip():
            return rec["label"].strip()
    return OPEX_TOTAL


def _capital(text: str) -> str:
    return text[:1].upper() + text[1:]


def _role_name(role: str) -> str:
    return SHORT.get(role) or _capital(plain(role))


def _alternatives(needs) -> List[List[str]]:
    """The metric's needs as groups: a "revenue/arr/mrr" entry is one of."""
    return [[r for r in str(n).split("/")] for n in needs]


def _state_text(table: List[dict], role: str, state: str) -> Optional[str]:
    if state == "no_values":
        rec = _unread(table, role)[0]
        cells = f"{rec['sheet']}!{rec['cells']}" if rec.get("sheet") and rec.get("cells") else rec.get("cells") or ""
        return f"{_role_name(role)} row read ({cells}); not computed: no values in the cells"
    if state == "plan_only":
        return f"{_role_name(role)} split only in plan years; actual years carry {_total_label(table)} only"
    if state == "segments":
        segs = [r for r in _recs(table, role)]
        names = ", ".join(dict.fromkeys(r["segment"] for r in segs if r["segment"]))
        return (f"{_role_name(role)} mapped as {len(segs)} segment rows ({names}); the calculation uses one total row")
    return None


def missing_reason(table: List[dict], needs, engine_reason: Optional[str]) -> Optional[str]:
    """Why a metric is not computed, from the map. For each group of roles the metric needs (the first of a "one of" group that the map holds):
    a) the role is mapped nowhere: "needs a <role> row"; b) mapped only in plan columns; c) mapped as segment rows only; d) mapped with actuals
    but the engine returned no value: "<Role> row read (<cells>); not computed: <engine status>". None when the metric has no role to describe
    (the engine's own reason stays)."""
    groups = _alternatives(needs or ())
    if not groups:
        return None
    absent, partial, read = [], [], []
    for group in groups:
        states = {r: role_state(table, r) for r in group}
        usable = next((r for r in group if states[r] == "mapped"), None)
        if usable:
            read.append(usable)
            continue
        first = next((r for r in group if states[r] == "no_values"), None) or next((r for r in group if states[r] == "plan_only"), None) \
            or next((r for r in group if states[r] == "segments"), None)
        if first:
            partial.append(_state_text(table, first, states[first]))
        else:
            absent.append(group)
    out = []
    if absent:
        out.append("needs " + " and ".join(_row_phrase(g) for g in absent))
    out += partial
    if out:
        return "; ".join(out)
    cells = "; ".join(f"{_role_name(r)} row read ({_cells(table, r)})" for r in read)
    status = (engine_reason or "no value at the as-of month").rstrip(".")
    return f"{cells}; not computed: {status}"


def _row_phrase(group: List[str]) -> str:
    if len(group) == 1:
        return needs_row(group[0])
    names = [plain(r) for r in group]
    return f"{article(names[0])} " + ", ".join(names[:-1]) + f" or {names[-1]} row"


def request_roles(table: List[dict], needs) -> List[str]:
    """The roles a data request for this metric may name: those no file maps (in any columns, any segment); the first of a "one of" group."""
    out = []
    for group in _alternatives(needs or ()):
        if not any(r in mapped_roles(table) for r in group) and group[0] not in out:
            out.append(group[0])
    return out


def request_line(roles: Iterable[str]) -> Optional[str]:
    """"A file with a revenue row and an R&D row": None when no role is unmapped."""
    rows = [needs_row(r) for r in dict.fromkeys(roles)]
    if not rows:
        return None
    return "A file with " + (", ".join(rows[:-1]) + " and " + rows[-1] if len(rows) > 1 else rows[0])


def _yearly_reason(table: List[dict], reason: Optional[str]) -> Optional[str]:
    """A yearly-table reason that reads "needs a <role> row" (engine wording, role key) rewritten from the map; any other reason is kept."""
    if not reason:
        return reason
    roles = _NEEDS.findall(reason)
    if not roles or not reason.startswith("needs "):
        return reason
    return missing_reason(table, roles, reason) or reason


def apply_reasons(results: Optional[dict], table: List[dict]) -> Optional[dict]:
    """The results with each missing metric's reason, and each yearly-table reason, written from the map (rules a-d of `missing_reason`).
    A copy; the stored results are not touched. Without a role table the engine's reasons stay."""
    if not results or not table:
        return results
    out = copy.deepcopy(results)
    for m in ((out.get("role_metrics") or {}).get("metrics")) or ():
        if m["status"] == "computed" or m["metric"] == "reconciliation" or str(m.get("reason") or "").startswith(role_engine.NO_ESTIMATE):
            continue            # an estimate's own closed reason (a failed check, a missing plan input) stays as the engine wrote it
        reason = missing_reason(table, m.get("needs"), m.get("reason"))
        if reason:
            m["reason"] = reason
    for y in ((out.get("yearly_basis") or {}).get("years")) or ():
        for key in ("cac_payback_reason", "cac_payback_net_new_arr_reason"):
            if key in y:
                y[key] = _yearly_reason(table, y.get(key))
    return out


# --- the anomaly flags -----------------------------------------------------------------------------------------------------------------------

def anomaly_scope(a: Optional[dict]) -> Dict[str, bool]:
    """Which kinds of input the flags had: revenue lines (the flags' source rows exist) and CRM deals (the CRM source exists)."""
    a = a or {}
    return {"revenue": bool((a.get("source") or {}).get("row_numbers")), "crm": bool(a.get("deals_source"))}


def anomaly_rows(a: Optional[dict]) -> List[dict]:
    """[{"key", "label", "count", "detail"}] for the flags the Dashboard and the export list. `count` is None, "Not applicable", for a flag whose
    input is absent (no revenue lines, no CRM file); never 0 for a check that did not run."""
    if not a:
        return []
    scope = anomaly_scope(a)
    any_input = scope["revenue"] or scope["crm"]

    def row(key, label, count, detail, kind):
        return {"key": key, "label": label, "count": count if (scope[kind] if kind in scope else any_input) else None, "detail": detail if (scope[kind] if kind in scope else any_input) else ""}

    dates = a.get("date_order_from_data") or []
    rows = [
        row("negative_mrr_months", "Months with negative MRR", len(a.get("negative_mrr_months") or []), ", ".join(a.get("negative_mrr_months") or []), "revenue"),
        row("revenue_gap_then_resume", "Customers with gaps > 2 months then resume", len(a.get("revenue_gap_then_resume") or []),
            ", ".join((a.get("revenue_gap_then_resume") or [])[:50]), "revenue"),
        row("revenue_missing_customer_id", "Revenue lines missing customer ID", (a.get("revenue_missing_customer_id") or {}).get("count"), "", "revenue"),
        row("deals_close_before_created", "Deals close-before-created (excluded)", (a.get("deals_close_before_created") or {}).get("excluded_count"), "", "crm"),
    ]
    if a.get("deals_duplicate_id"):
        rows.append(row("deals_duplicate_id", "CRM rows sharing a deal ID", a["deals_duplicate_id"].get("collapsed"),
                        f"{a['deals_duplicate_id'].get('distinct_ids')} distinct deal IDs", "crm"))
    rows.append(row("date_order_from_data", "Date columns with day/month order set from the data", len(dates),
                    "; ".join(f"{n['field']} ({n['dataset']}): {n['order']}, {n['rows']} rows" for n in dates), "any"))
    return rows


def anomaly_total(a: Optional[dict]) -> Optional[int]:
    """The flags added up, over the applicable checks only; None when the engine could not compute them or no check had an input."""
    rows = anomaly_rows(a)
    counted = [r["count"] for r in rows if r["count"] is not None]
    return sum(counted) if counted else None


# --- the files by evidence kind --------------------------------------------------------------------------------------------------------------

P_AND_L_ROLES = ("cost_of_revenue", "sales_marketing", "rnd", "ga", "opex", "ebitda")
REVENUE_REPORT_ROLES = ("revenue", "arr", "mrr")


def file_kinds(table: List[dict]) -> Dict[str, dict]:
    """{file: {"sheet", "kinds"}} for every file the stored readings map: "pnl" when a cost or profit row is mapped, "revenue_report" when a
    revenue, ARR or MRR row is and no cost row is, "headcount" when a headcount row is. A file with none of them has no kind."""
    out: Dict[str, dict] = {}
    for r in table:
        entry = out.setdefault(r["file"], {"sheet": r["sheet"], "kinds": []})
        for kind, roles in (("pnl", P_AND_L_ROLES), ("revenue_report", REVENUE_REPORT_ROLES), ("headcount", ("headcount",))):
            if r["role"] in roles and kind not in entry["kinds"]:
                entry["kinds"].append(kind)
    for entry in out.values():          # a file with cost or profit rows is a P&L, listed there; it is not also a revenue report
        if "pnl" in entry["kinds"] and "revenue_report" in entry["kinds"]:
            entry["kinds"].remove("revenue_report")
    return out


def read_files(table: List[dict], skip: Iterable[str] = ()) -> List[dict]:
    """The files the stored readings map, as the memo lists them: a file with a cost or profit row is a P&L (dtype "pnl"), any other "reading";
    `kinds` says what else it is (a revenue or ARR report, a headcount file). `skip`: files already listed as stored datasets."""
    skip = set(skip)
    kinds = file_kinds(table)
    out = []
    for name in dict.fromkeys(r["file"] for r in table):
        if name in skip:
            continue
        rows = [r for r in table if r["file"] == name]
        pnl = [r for r in rows if r["role"] in P_AND_L_ROLES]
        out.append({"dtype": "pnl" if pnl else "reading", "file": name, "sheet": (pnl or rows)[0]["sheet"], "kinds": kinds[name]["kinds"]})
    return out


def memo_files(datasets: List[dict], table: List[dict]) -> List[dict]:
    """The one list of data files the memo counts ("Files reviewed") and lists by evidence category (Appendix D). The file records come first, in
    upload order, each joined by file hash (else by name) to what its reading maps: a record is typed "file" and carries no kind of its own, so
    its kind is the reading's (P&L, revenue report, headcount). A stored type (an older dataset: pnl, revenue, crm) is kept. A read file with no
    record is added after them."""
    kinds = file_kinds(table)
    by_hash = {}
    for r in table:
        if r.get("file_hash"):
            by_hash.setdefault(r["file_hash"], r["file"])
    out, seen = [], set()
    for d in datasets:
        name = d.get("file")
        read_as = by_hash.get(d.get("file_hash"), name)
        entry = kinds.get(read_as) or {"sheet": None, "kinds": []}
        stored = d.get("dtype")
        dtype = stored if stored not in (None, "file", "reading") else ("pnl" if "pnl" in entry["kinds"] else "reading")
        out.append({"dtype": dtype, "file": name, "sheet": d.get("sheet") or entry["sheet"], "kinds": list(entry["kinds"])})
        seen.update({name, read_as})
    return out + read_files(table, skip=seen)


__all__ = ["memo_files", "missing_reason", "apply_reasons", "unmapped_roles", "anomaly_rows", "anomaly_total", "file_kinds", "read_files"]
