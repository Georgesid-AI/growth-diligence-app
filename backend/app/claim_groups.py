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
ALSO = "also"            # a part of a coarser set that reconciles with the total too: under the total's Details beside the finer set
REPEAT = "repeat"        # the same figure stated again: folded into the row of its first statement, both sources under Details
PENDING = "pending_part"    # a part of a candidate's reconciling set while the annual conflict is open: no top-five slot, no exposure of its own
CANDIDATE, ALTERNATIVE = "candidate", "alternative"      # an annual figure in a conflict: none chosen yet, or passed over for the preferred one
KIND_TOTAL = "total"           # what a review asks: which total
SUBORDINATE = (PART, ALSO, REPEAT)      # shown under another row's Details, never an item of their own

NOTE_TOTAL = "Annual total: {parts} reconcile with it ({sum} against {total}, within " + TOLERANCE_TEXT + ")"
NOTE_PART = "Part of the annual total for {period}"
NOTE_REPEAT = "Same figure as #{rank} ({page}); counted once"
NOTE_ALSO = "{parts} also reconcile with this total; shown under its Details"
NOTE_PENDING = "Part of a set that reconciles with one of the annual figures still in conflict; no exposure of its own until one is chosen"
NOTE_DIFFERS = "{parts} sum to {sum}, outside " + TOLERANCE_TEXT + " of {total}; kept as independent claims"
NOTE_PARTIAL = "{parts}: {have} of {need} stated; kept as independent claims"
NOTE_AMBIGUOUS = "{parts}: a period is stated with figures that differ; kept as independent claims"
NOTE_TAKEN = "Its parts belong to another annual total; kept as independent claims"
NOTE_CONFLICT = "Unresolved conflict: another annual figure for the same period differs ({values})"
NOTE_ALTERNATIVE = "Unresolved conflict with the preferred annual figure for the same period ({values}); not a segment"
NOTE_CHOOSE = "Several annual figures for the same period: choose the one to use (Needs your attention)"
REASON_TOTAL = "Several annual figures are stated for the same period. Choose the one to use; the others stay as claims until corrected, scoped or excluded."
VAS_IN_TOTAL = "counted in the annual total: its parts add no separate exposure"
VAS_PENDING = "waiting for the choice of the annual figure: its parts add no separate exposure"
VAS_REPEAT = "the same figure as another claim: counted once"


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


def has_open_question(row: dict) -> bool:
    """A row the analyst still has to answer (Definition check, turnover, growth basis, a period or field the claim editor asks for). Such a row
    is not related to others until it is answered: its control stays on its own row, never hidden under a total's Details."""
    return row.get("definition_check") == cm.DEFINITION_ASK or row.get("turnover_state") == "ask" or row.get("growth_basis") == "unknown" \
        or bool(row.get("required_unknown")) or cm.asks_analyst(row)


def _scope(row: dict) -> Optional[tuple]:
    """The scope key a row groups under, or None when the row cannot be related: an unknown part of the scope is never assumed equal to
    another row's, and a row with an open question waits for its answer. The metric decides what the figure is (the claim type only when the
    row has no metric), then population, segment, currency, unit, figure type, basis and case; the fiscal calendar is the audit's own,
    applied when the period was resolved (dates-and-periods.md)."""
    kind = _kind(row)
    if kind is None or cm.is_untested(row) or row.get("claimed_value") is None or row.get("claimed_high") is not None:
        return None
    if has_open_question(row) or row.get("figure_type") not in ("actual", "target"):
        return None
    if row.get("claim_type") in cm.MONEY_TYPES and not row.get("currency"):
        return None
    return (kind, row.get("metric") or row["claim_type"], row.get("population"), row.get("segment"), row.get("currency") or "",
            row.get("unit") or "", row["figure_type"], row.get("basis") or "", row.get("scenario") or "none")


def scope_period(row: dict) -> Optional[tuple]:
    """What two statements of one figure share: the scope and the period. None for a row that cannot be related."""
    key = _scope(row)
    return None if key is None else (key, row.get("period_start"), row.get("period_end"))


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


def _fold(out: dict, cluster: List[_Fig], group_id: str) -> None:
    """The same figure stated again folds into the row of its first statement (the lead): each repeat is a subordinate row of the lead's
    group, with a note naming the lead, and adds no exposure. Both sources stay visible under the lead's Details."""
    lead = cluster[0].row
    for fig in cluster[1:]:
        out["roles"][fig.row["claim_id"]] = (group_id, REPEAT)
        out["notes"][fig.row["claim_id"]] = NOTE_REPEAT.format(rank=lead.get("rank"), page=lead.get("page_ref") or _source(lead))
    out["folded"].add(lead["claim_id"])


def relate(rows: List[dict], choices: Optional[dict] = None, fiscal_year_end: Optional[int] = None) -> dict:
    """The relationships between the register's rows.

    Returns `groups` (a reconciled annual total with its parts), `reviews` (the questions that wait: which annual figure; with its candidates,
    sources and reconciliation hint, none selected), `conflicts` (the unresolved material conflicts between annual figures, open or with a
    preferred figure chosen), `roles` {claim_id: (group id, role)} and `notes` {claim_id: relationship text}."""
    choices = choices or {}
    figs = _figures(rows)
    clusters: Dict[tuple, List[List[_Fig]]] = {}
    by_slot: Dict[tuple, List[_Fig]] = {}
    for fig in figs:
        by_slot.setdefault((fig.key, fig.start, fig.end), []).append(fig)
    for slot, members in by_slot.items():
        clusters[slot] = _clusters(members)
    out = {"groups": [], "reviews": [], "conflicts": [], "roles": {}, "notes": {}, "folded": set()}
    taken: set = set()
    annual = sorted((s for s in by_slot if s[2] - s[1] + 1 == ANNUAL), key=lambda s: min(f.index for f in by_slot[s]))
    for key, start, end in annual:
        found = clusters[(key, start, end)]
        total_id = _slot_id(KIND_TOTAL, key, start, end)
        evaluations = [_evaluate(clusters, key, start, end, c[0].value) for c in found]
        preferred, used = None, []
        if len(found) == 1:
            preferred = found[0]
        else:
            # the question is bound to the candidates and to the parts that reconcile with each: an edit to those parts is a new question
            sets = [f"{c[0].identity}:{name}:{'.'.join(p[0].identity for p in e['parts'])}"
                    for c, ev in zip(found, evaluations) for name, e in ev.items() if e["state"] == "reconciles"]
            total_ctx = context_hash(KIND_TOTAL, key, start, end, [f.identity for c in found for f in c] + sets, fiscal_year_end)
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
                for ev in evaluations:       # the parts of every candidate's reconciling set wait with the question: no slot, no exposure
                    for e in ev.values():
                        if e["state"] == "reconciles":
                            for cluster in e["parts"]:
                                for fig in cluster:
                                    out["roles"][fig.row["claim_id"]] = (total_id, PENDING)
                                    out["notes"][fig.row["claim_id"]] = NOTE_PENDING
                continue
        evaluation = evaluations[found.index(preferred)]
        total = preferred[0]
        reconciling = [name for name, e in evaluation.items() if e["state"] == "reconciles"]
        if not reconciling:
            note = _why_not(evaluation, total)
            if note:
                out["notes"][total.row["claim_id"]] = note
            continue
        name, others = reconciling[0], reconciling[1:]       # the finer set is the group (months, quarters, halves); the coarser ones go under Details
        part_clusters = evaluation[name]["parts"]
        also_clusters = [c for n in others for c in evaluation[n]["parts"]]
        members = [c[0].row["claim_id"] for c in [preferred] + part_clusters + also_clusters]
        if taken & set(members):
            out["notes"][total.row["claim_id"]] = NOTE_TAKEN
            continue
        taken |= set(members)
        group_id = _digest("group", *key, start, end, total.identity)
        e = evaluation[name]
        period = total.row.get("period")
        out["groups"].append({
            "id": group_id, "kind": key[0], "partition": name, "total": total.row["claim_id"], "period": period,
            "parts": [c[0].row["claim_id"] for c in part_clusters], "other_partitions": others,
            "other_parts": [c[0].row["claim_id"] for c in also_clusters],
            "total_value": float(total.value), "parts_value": float(e["sum"]), "difference": float(e["sum"] - total.value),
            "tolerance": float(TOLERANCE), "metric": total.row.get("metric"), "segment": total.row.get("segment"),
            "currency": total.row.get("currency"), "unit": total.row.get("unit"), "chosen": used})
        out["roles"][total.row["claim_id"]] = (group_id, TOTAL)
        out["notes"][total.row["claim_id"]] = NOTE_TOTAL.format(parts=PART_WORDS[name], sum=_amount(e["sum"], total.row),
                                                                total=_amount(total.value, total.row))
        for c in part_clusters:
            out["roles"][c[0].row["claim_id"]] = (group_id, PART)
            out["notes"][c[0].row["claim_id"]] = NOTE_PART.format(period=period or "the year")
        for n in others:
            for c in evaluation[n]["parts"]:
                out["roles"][c[0].row["claim_id"]] = (group_id, ALSO)
                out["notes"][c[0].row["claim_id"]] = NOTE_ALSO.format(parts=PART_WORDS[n].capitalize())
        for c in [preferred] + part_clusters + also_clusters:
            _fold(out, c, group_id)
    for slot in annual:               # an annual figure stated twice folds also when no group forms and for the candidates of a conflict
        for cluster in clusters[slot]:
            if len(cluster) > 1 and cluster[0].row["claim_id"] not in out["folded"]:
                same = _digest("same", *slot[0], slot[1], slot[2], cluster[0].identity)
                lead = cluster[0].row["claim_id"]
                out["roles"][lead] = (same, out["roles"].get(lead, (None, None))[1])
                _fold(out, cluster, same)
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


NO_EXPOSURE = {PART: VAS_IN_TOTAL, ALSO: VAS_IN_TOTAL, PENDING: VAS_PENDING, REPEAT: VAS_REPEAT}      # the roles that add no value at stake of their own


def annotate(rows: List[dict], choices: Optional[dict] = None, fiscal_year_end: Optional[int] = None) -> dict:
    """Sets `group_id`, `group_role` and `relationship` on every row and takes the exposure of a group's parts out of the value at stake (the
    annual headline keeps its own; a part, a repeat and a part waiting for a conflict's choice add none). Returns `relate`'s result for the callers that need the groups and the questions."""
    found = relate(rows, choices, fiscal_year_end)
    for row in rows:
        group_id, role = found["roles"].get(row["claim_id"], (None, None))
        row.update(group_id=group_id, group_role=role, relationship=found["notes"].get(row["claim_id"]))
        if role in NO_EXPOSURE and row.get("value_at_stake_arr") is not None:
            row.update(value_at_stake_arr=None, vas_reason=NO_EXPOSURE[role])
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
    """A part of a reconciled total, a part of a coarser set that reconciles too, or a figure stated again: shown under another row's Details,
    never an item of the top five or of the count."""
    return row.get("group_role") in SUBORDINATE


def is_ineligible(row: dict) -> bool:
    """A row the top five does not take: a subordinate row, a part waiting for a conflict's choice, and an annual figure in an unresolved
    conflict that is not the preferred one. With no figure chosen, none of the candidates can enter the five; the conflict is reported beside
    the conclusion instead."""
    return row.get("group_role") in (*SUBORDINATE, PENDING, CANDIDATE, ALTERNATIVE)


def is_repeat_of_listed(row: dict, rows: List[dict]) -> bool:
    """A figure stated again whose first statement is Contradicted too: the conclusion and the banner list the figure once."""
    if row.get("group_role") != REPEAT:
        return False
    key = scope_period(row)
    return key is not None and any(r.get("evidence_label") == "Contradicted" and r.get("group_role") != REPEAT and scope_period(r) == key
                                   for r in rows)


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
