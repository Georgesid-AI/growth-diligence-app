"""Claim groups and conflicts: how register rows relate, computed on read.

Spec: docs/specs/claim-groups.md (docs/design/claim-review-simplified-design.md sections 1 and 2). A pure module like claim_matching: it reads the
register's rows and the analyst's saved choices, never a model, and stores nothing. Every claim stays a claim; a relationship is a presentation
of claims that match in metric definition, entity or segment, currency, unit, calendar and actual/forecast scenario. Only an explicit analyst
decision is persisted, as a hash bound to the whole context and to the identity of every candidate (`context_hash`), never as deck text.
"""
from __future__ import annotations

import hashlib
from decimal import Decimal
from typing import Dict, Iterable, List, NamedTuple, Optional, Tuple

from . import claim_matching as cm

TOLERANCE = Decimal("0.02")         # provisional (design note section 1): abs(parts - total) <= 2% of abs(total); a zero total needs equality
TOLERANCE_TEXT = "±2%"
ANNUAL = 12                          # months in an annual total
FLOW_TYPES = ("revenue", "costs", "gross_profit", "ebitda", "net_profit")        # an amount over a period: the parts add up
BALANCE_TYPES = ("arr", "mrr", "cash", "customers", "users")                     # a level at a date: the year-end observation stands for the year
BALANCE_METRICS = ("ARR", "MRR", "Customer count")     # the metric the register tests the claim against decides its kind when it has one
FLOW_METRICS = ("Revenue",)
FLOW, BALANCE = "flow", "balance"
PARTITIONS = (("month", 1), ("quarter", 3), ("half", 6))      # a flow's parts: one granularity at a time, never mixed
YEAR_END = "year-end"
PART_WORDS = {"month": "months", "quarter": "quarters", "half": "halves", YEAR_END: "year-end observation"}
BASES = ("actual", "projection", "scenario")

TOTAL, PART = "total", "part"
CANDIDATE, ALTERNATIVE = "candidate", "alternative"      # an annual figure in a conflict: none chosen yet, or passed over for the preferred one
KIND_TOTAL, KIND_PARTITION = "total", "partition"           # what a review asks: which total, or which set of parts

NOTE_TOTAL = "Annual total: {parts} reconcile with it ({sum} against {total}, within " + TOLERANCE_TEXT + ")"
NOTE_PART = "Part of the annual total for {period}"
NOTE_REPEAT = "States the same figure as the {role} of its group again; kept as a claim of its own"
NOTE_DIFFERS = "{parts} sum to {sum}, outside " + TOLERANCE_TEXT + " of {total}; kept as independent claims"
NOTE_PARTIAL = "{parts}: {have} of {need} stated; kept as independent claims"
NOTE_AMBIGUOUS = "{parts}: a period is stated with figures that differ; kept as independent claims"
NOTE_TAKEN = "Its parts belong to another annual total; kept as independent claims"
NOTE_CONFLICT = "Unresolved conflict: another annual figure for the same period differs ({values})"
NOTE_ALTERNATIVE = "Unresolved conflict with the preferred annual figure for the same period ({values}); not a segment"
NOTE_CHOOSE = "Several annual figures for the same period: choose the one to use (Needs your attention)"
NOTE_SEVERAL = "Several sets of parts reconcile with it ({sets}): choose one (Needs your attention)"
REASON_TOTAL = "Several annual figures are stated for the same period. Choose the one to use; the others stay as claims until corrected, scoped or excluded."
REASON_PARTITION = "More than one set of parts reconciles with this annual total. Choose the set to show; the others stay as claims."
VAS_IN_TOTAL = "counted in the annual total: its parts add no separate exposure"


class _Fig(NamedTuple):
    row: dict
    key: tuple
    start: int
    end: int
    value: Decimal
    identity: str
    index: int


def _digest(*parts) -> str:
    return hashlib.sha256("|".join(str(p) for p in parts).encode("utf-8")).hexdigest()[:16]


def _decimal(value) -> Decimal:
    return Decimal(str(value))      # str of a float is its shortest repr: 0.1 and 0.2 stay 0.1 and 0.2, so 0.1 + 0.2 - 0.3 is exactly 0


def _plain(value) -> str:
    """A figure as text, the same for 250000 and 250000.0 (an edited value comes back a float)."""
    return format(_decimal(value).normalize(), "f")


def within(parts: Decimal, total: Decimal) -> bool:
    """The reconciliation test of the design note: abs(parts - total) <= 2% of abs(total). A zero total accepts only equality (no
    rounding allowance is documented). It identifies a relationship; it verifies neither figure against company data."""
    return abs(parts - total) <= TOLERANCE * abs(total)


def same_figure(a: Decimal, b: Decimal) -> bool:
    """Two figures for one scope and period are the same figure when they are within the tolerance of the larger one (symmetric)."""
    return abs(a - b) <= TOLERANCE * max(abs(a), abs(b))


def _kind(row: dict) -> Optional[str]:
    """Whether the figure is an amount over a period (the parts add up) or a level at a date (the year-end observation stands for the year). The metric
    the register tests it against decides: a claim typed revenue whose words say ARR is a balance. With no metric, the claim type."""
    metric = row.get("metric")
    if metric:
        return BALANCE if metric in BALANCE_METRICS else FLOW if metric in FLOW_METRICS else None
    return FLOW if row.get("claim_type") in FLOW_TYPES else BALANCE if row.get("claim_type") in BALANCE_TYPES else None


def _scope(row: dict) -> Optional[tuple]:
    """The scope key a row groups under, or None when the row cannot be related: an unknown part of the scope is never assumed equal to
    another row's. Metric definition (type, metric, population), segment, currency, unit, figure type, basis and case; the fiscal
    calendar is the audit's own, applied when the period was resolved (dates-and-periods.md)."""
    kind = _kind(row)
    if kind is None or cm.is_untested(row) or row.get("claimed_value") is None or row.get("claimed_high") is not None:
        return None
    if row.get("required_unknown") or row.get("turnover_state") == "ask" or row.get("figure_type") not in ("actual", "target"):
        return None
    if row.get("claim_type") in cm.MONEY_TYPES and not row.get("currency"):
        return None
    return (kind, row["claim_type"], row.get("metric"), row.get("population"), row.get("segment"), row.get("currency") or "",
            row.get("unit") or "", row["figure_type"], row.get("basis") or "", row.get("scenario") or "none")


def identity(row: dict) -> str:
    """What a candidate is, for a saved choice: its source and its stated figure, period and scope. Not the claim id (a page read again
    keeps the identity) and not the rank or the label (a new run does not change what the candidate is)."""
    return _digest(row.get("deck_file"), row.get("page_ref"), _plain(row["claimed_value"]), row.get("currency"), row.get("unit"),
                   row.get("period_start"), row.get("period_end"), row.get("claim_type"), row.get("metric"), row.get("segment"),
                   row.get("basis"), row.get("scenario"), row.get("figure_type"))


def context_hash(kind: str, key: tuple, start: int, end: int, candidates: Iterable[str], fiscal_year_end: Optional[int]) -> str:
    """A saved choice holds only for this: the question, the whole scope, the period, the fiscal calendar and the identity of every
    candidate. A metric-and-period hash alone would keep a choice after the figure it chose, or one it passed over, was edited."""
    return _digest(kind, *key, start, end, fiscal_year_end, *sorted(candidates))


def _slot_id(kind: str, key: tuple, start: int, end: int, anchor: str = "") -> str:
    return _digest("slot", kind, *key, start, end, anchor)


def _figures(rows: List[dict]) -> List[_Fig]:
    out = []
    for i, row in enumerate(rows):
        key, start, end = _scope(row), cm._month_of(row.get("period_start")), cm._month_of(row.get("period_end"))
        if key is not None and start is not None and end is not None and end >= start:
            out.append(_Fig(row, key, start, end, _decimal(row["claimed_value"]), identity(row), i))
    return out


def _clusters(figs: List[_Fig]) -> List[List[_Fig]]:
    """The figures of one scope and period, grouped into the ones that state the same figure; the first of a cluster is its lead."""
    out: List[List[_Fig]] = []
    for fig in figs:
        for cluster in out:
            if same_figure(cluster[0].value, fig.value):
                cluster.append(fig)
                break
        else:
            out.append([fig])
    return out


def _amount(value, row: dict) -> str:
    sign = "-" if value < 0 else ""
    if row.get("currency"):
        return sign + cm._money(float(value), row["currency"])
    text = f"{float(value):,.0f}"
    return f"{text} {row['unit']}" if row.get("unit") else text


def _spans(kind: str, name: str, length: int, start: int, end: int) -> List[Tuple[int, int]]:
    if kind == BALANCE:
        return [(end, end)]
    return [(a, a + length - 1) for a in range(start, end + 1, length)]


def _evaluate(clusters: Dict[tuple, List[List[_Fig]]], key: tuple, start: int, end: int, total: Decimal) -> Dict[str, dict]:
    """For each way of splitting the year (months, quarters or halves of a flow; the year-end observation of a balance): whether the parts are
    complete and one figure each, and whether they reconcile with `total`. A partition holds one granularity only."""
    kind = key[0]
    options = (((YEAR_END, 1),) if kind == BALANCE else PARTITIONS)
    out = {}
    for name, length in options:
        spans = _spans(kind, name, length, start, end)
        found = [clusters.get((key, a, b)) for a, b in spans]
        have = sum(1 for f in found if f)
        if have < len(spans):
            out[name] = {"state": "partial", "have": have, "need": len(spans)}
        elif any(len(f) > 1 for f in found):
            out[name] = {"state": "ambiguous", "have": have, "need": len(spans)}
        else:
            parts = [f[0] for f in found]
            added = sum((c[0].value for c in parts), Decimal(0))
            out[name] = {"state": "reconciles" if within(added, total) else "differs", "have": have, "need": len(spans),
                         "sum": added, "parts": parts}
    return out


def _conflict_text(found: List[List[_Fig]], preferred: Optional[List[_Fig]]) -> str:
    """The conflict as one line for the conclusion and the memo: the claim, then each figure with its source; the preferred one is named."""
    lead = found[0][0].row
    figures = " against ".join(f"{_amount(c[0].value, c[0].row)} ({_source(c[0].row)})" for c in found)
    tail = f" Preferred: {_amount(preferred[0].value, preferred[0].row)}." if preferred is not None else " No figure chosen."
    return f"{cm.claim_name(lead)}: {figures}.{tail}"


def _source(row: dict) -> str:
    return " ".join(str(x) for x in (row.get("deck_file"), row.get("page_ref")) if x)


def _candidate(cluster: List[_Fig], evaluation: Dict[str, dict], chosen: bool) -> dict:
    lead = cluster[0]
    reconciling = [name for name, e in evaluation.items() if e["state"] == "reconciles"]
    hint = None
    if reconciling:
        e = evaluation[reconciling[0]]
        hint = f"{PART_WORDS[reconciling[0]]} sum to {_amount(e['sum'], lead.row)}, within {TOLERANCE_TEXT}"
    return {"claim_id": lead.row["claim_id"], "claim_ids": [f.row["claim_id"] for f in cluster], "identity": lead.identity,
            "value": float(lead.value), "currency": lead.row.get("currency"), "unit": lead.row.get("unit"),
            "period": lead.row.get("period"), "source": _source(lead.row), "hint": hint, "chosen": chosen}


def _saved(choices: dict, slot: str, context: str) -> Optional[str]:
    """The analyst's choice for a question, only while its context still holds."""
    got = (choices or {}).get(slot)
    return got.get("chosen") if isinstance(got, dict) and got.get("context") == context else None


def relate(rows: List[dict], choices: Optional[dict] = None, fiscal_year_end: Optional[int] = None) -> dict:
    """The relationships between the register's rows.

    Returns `groups` (a reconciled annual total with its parts), `reviews` (the questions that wait: which total, which set of parts; each
    with its candidates, sources and reconciliation hint, none selected), `conflicts` (the unresolved material conflicts between annual
    figures, open or with a preferred figure chosen), `roles` {claim_id: (group id, role)} and `notes` {claim_id: relationship text}."""
    choices = choices or {}
    figs = _figures(rows)
    clusters: Dict[tuple, List[List[_Fig]]] = {}
    by_slot: Dict[tuple, List[_Fig]] = {}
    for fig in figs:
        by_slot.setdefault((fig.key, fig.start, fig.end), []).append(fig)
    for slot, members in by_slot.items():
        clusters[slot] = _clusters(members)
    out = {"groups": [], "reviews": [], "conflicts": [], "roles": {}, "notes": {}}
    taken: set = set()
    annual = sorted((s for s in by_slot if s[2] - s[1] + 1 == ANNUAL), key=lambda s: min(f.index for f in by_slot[s]))
    for key, start, end in annual:
        found = clusters[(key, start, end)]
        total_id = _slot_id(KIND_TOTAL, key, start, end)
        total_ctx = context_hash(KIND_TOTAL, key, start, end, [f.identity for c in found for f in c], fiscal_year_end)
        evaluations = [_evaluate(clusters, key, start, end, c[0].value) for c in found]
        preferred, used = None, []
        if len(found) == 1:
            preferred = found[0]
        else:
            pick = _saved(choices, total_id, total_ctx)
            preferred = next((c for c in found if pick in {f.identity for f in c}), None) if pick else None
            used = [total_id] if preferred is not None else []
            candidates = [_candidate(c, ev, c is preferred) for c, ev in zip(found, evaluations)]
            values = ", ".join(_amount(c[0].value, c[0].row) for c in found)
            review = {"id": total_id, "kind": KIND_TOTAL, "state": "chosen" if preferred is not None else "open", "context": total_ctx,
                      "reason": REASON_TOTAL, "text": _conflict_text(found, preferred),
                      "metric": found[0][0].row.get("metric"), "period": found[0][0].row.get("period"),
                      "segment": found[0][0].row.get("segment"), "candidates": candidates}
            out["conflicts"].append(review)           # a conflict stays listed after a preferred figure is chosen
            if preferred is None:
                out["reviews"].append(review)
            for c in found:
                note = NOTE_CHOOSE if preferred is None else NOTE_CONFLICT if c is preferred else NOTE_ALTERNATIVE
                for fig in c:
                    out["notes"][fig.row["claim_id"]] = note.format(values=values)
                    if preferred is None or c is not preferred:        # a figure the analyst has not chosen is no item of the top five
                        out["roles"][fig.row["claim_id"]] = (total_id, CANDIDATE if preferred is None else ALTERNATIVE)
            if preferred is None:
                continue
        evaluation = evaluations[found.index(preferred)]
        total = preferred[0]
        reconciling = [name for name, e in evaluation.items() if e["state"] == "reconciles"]
        if not reconciling:
            note = _why_not(evaluation, total)
            if note:
                out["notes"][total.row["claim_id"]] = note
            continue
        part_ctx = None
        if len(reconciling) == 1:
            name = reconciling[0]
        else:
            part_id = _slot_id(KIND_PARTITION, key, start, end, total.identity)
            sets = {n: [c[0].identity for c in evaluation[n]["parts"]] for n in reconciling}
            part_ctx = context_hash(KIND_PARTITION, key, start, end, [total.identity] + [i for n in sorted(sets) for i in sets[n]],
                                    fiscal_year_end)
            pick = _saved(choices, part_id, part_ctx)
            name = pick if pick in reconciling else None
            if name is None:
                review = {"id": part_id, "kind": KIND_PARTITION, "state": "open", "context": part_ctx, "reason": REASON_PARTITION,
                          "metric": total.row.get("metric"), "period": total.row.get("period"), "segment": total.row.get("segment"),
                          "candidates": [{"partition": n, "label": PART_WORDS[n], "claim_ids": [c[0].row["claim_id"] for c in evaluation[n]["parts"]],
                                          "sum": float(evaluation[n]["sum"]), "currency": total.row.get("currency"), "unit": total.row.get("unit"),
                                          "total": float(total.value), "hint": f"{PART_WORDS[n]} sum to {_amount(evaluation[n]['sum'], total.row)}, within {TOLERANCE_TEXT}",
                                          "chosen": False} for n in reconciling]}
                out["reviews"].append(review)
                out["notes"][total.row["claim_id"]] = NOTE_SEVERAL.format(sets=", ".join(PART_WORDS[n] for n in reconciling))
                continue
            used.append(part_id)
        part_clusters = [[f for f in c] for c in (clusters[(key, a, b)][0] for a, b in _spans(key[0], name, dict(PARTITIONS).get(name, 1), start, end))]
        members = [c[0].row["claim_id"] for c in [preferred] + part_clusters]
        if taken & set(members):
            out["notes"][total.row["claim_id"]] = NOTE_TAKEN
            continue
        taken |= set(members)
        group_id = _digest("group", *key, start, end, total.identity)
        e = evaluation[name]
        period = total.row.get("period")
        out["groups"].append({
            "id": group_id, "kind": key[0], "partition": name, "total": total.row["claim_id"], "period": period,
            "parts": [c[0].row["claim_id"] for c in part_clusters],
            "total_value": float(total.value), "parts_value": float(e["sum"]), "difference": float(e["sum"] - total.value),
            "tolerance": float(TOLERANCE), "metric": total.row.get("metric"), "segment": total.row.get("segment"),
            "currency": total.row.get("currency"), "unit": total.row.get("unit"), "chosen": used})
        out["roles"][total.row["claim_id"]] = (group_id, TOTAL)
        out["notes"][total.row["claim_id"]] = NOTE_TOTAL.format(parts=PART_WORDS[name], sum=_amount(e["sum"], total.row),
                                                                total=_amount(total.value, total.row))
        for c in part_clusters:
            out["roles"][c[0].row["claim_id"]] = (group_id, PART)
            out["notes"][c[0].row["claim_id"]] = NOTE_PART.format(period=period or "the year")
        for c in [preferred] + part_clusters:         # the same figure stated again is not folded in: it stays a claim of its own, with a note
            for fig in c[1:]:
                out["notes"][fig.row["claim_id"]] = NOTE_REPEAT.format(role="total" if c is preferred else "part")
    out["notes"] = {k: v for k, v in out["notes"].items() if v}
    return out


def _why_not(evaluation: Dict[str, dict], total: _Fig) -> Optional[str]:
    """The relationship note of an annual total that no set of parts reconciles with, when it is useful: the complete set that differs, else the
    set closest to complete with two or more parts stated. Nothing for a total with no parts."""
    differs = [(n, e) for n, e in evaluation.items() if e["state"] == "differs"]
    if differs:
        n, e = differs[0]
        return NOTE_DIFFERS.format(parts=PART_WORDS[n].capitalize(), sum=_amount(e["sum"], total.row), total=_amount(total.value, total.row))
    ambiguous = [n for n, e in evaluation.items() if e["state"] == "ambiguous"]
    if ambiguous:
        return NOTE_AMBIGUOUS.format(parts=PART_WORDS[ambiguous[0]].capitalize())
    partial = [(e["have"], n, e) for n, e in evaluation.items() if e["state"] == "partial" and e["have"] >= 2]
    if partial:
        _, n, e = max(partial, key=lambda p: p[0])
        return NOTE_PARTIAL.format(parts=PART_WORDS[n].capitalize(), have=e["have"], need=e["need"])
    return None


def annotate(rows: List[dict], choices: Optional[dict] = None, fiscal_year_end: Optional[int] = None) -> dict:
    """Sets `group_id`, `group_role` and `relationship` on every row and takes the exposure of a group's parts out of the value at stake (the
    annual headline keeps its own; a part adds none). Returns `relate`'s result for the callers that need the groups and the questions."""
    found = relate(rows, choices, fiscal_year_end)
    for row in rows:
        group_id, role = found["roles"].get(row["claim_id"], (None, None))
        row.update(group_id=group_id, group_role=role, relationship=found["notes"].get(row["claim_id"]))
        if role == PART and row.get("value_at_stake_arr") is not None:
            row.update(value_at_stake_arr=None, vas_reason=VAS_IN_TOTAL)
    return found


# --- what the other readers need from a group ----------------------------------------------------------------------------

def members(rows: List[dict]) -> Dict[str, List[dict]]:
    """The rows of each group, by group id."""
    out: Dict[str, List[dict]] = {}
    for row in rows:
        if row.get("group_id"):
            out.setdefault(row["group_id"], []).append(row)
    return out


def is_subordinate(row: dict) -> bool:
    """A part of a reconciled total: shown under the total's Details, never an item of the top five."""
    return row.get("group_role") == PART


def is_ineligible(row: dict) -> bool:
    """A row the top five does not take: a part of a group, and an annual figure in an unresolved conflict that is not the preferred
    one. With no figure chosen, none of the candidates can enter the five; the conflict is reported beside the conclusion instead."""
    return row.get("group_role") in (PART, CANDIDATE, ALTERNATIVE)


def contradicted_members(row: dict, by_group: Dict[str, List[dict]]) -> List[dict]:
    """The Contradicted rows of the group a total stands for (the total itself excluded): a verified annual total cannot hide a contradicted
    quarter. Empty for a row that is not a total."""
    if row.get("group_role") != TOTAL:
        return []
    return [m for m in by_group.get(row["group_id"], ()) if m is not row and m.get("evidence_label") == "Contradicted"]


def effective_label(row: dict, by_group: Dict[str, List[dict]]) -> Optional[str]:
    """The label a group's item carries in the conclusion: Contradicted when any member is, else the total's own."""
    return "Contradicted" if row.get("evidence_label") == "Contradicted" or contradicted_members(row, by_group) else row.get("evidence_label")


def group_shortfall(row: dict, by_group: Dict[str, List[dict]]) -> float:
    """The priority of a group's item: the largest shortfall among its members (the most material unresolved issue), the total's own for a row
    in no group."""
    pool = by_group.get(row.get("group_id") or "", [row]) if row.get("group_role") == TOTAL else [row]
    return max((m.get("shortfall") or 0 for m in pool), default=0)


def counts(rows: List[dict]) -> dict:
    """Items shown against the claims underneath: a reconciled group is one item."""
    return {"items": sum(1 for r in rows if not is_subordinate(r)), "claims": len(rows),
            "groups": sum(1 for r in rows if r.get("group_role") == TOTAL)}
