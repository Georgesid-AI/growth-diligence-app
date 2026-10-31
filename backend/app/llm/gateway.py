"""The LLM gateway - the only component permitted to call a model provider.

Data boundary (CLAUDE.md rules 16-18, docs/specs/deck-parser.md section 4)
--------------------------------------------------------------------------
Two paths reach the provider, each with its own fields.

Narrative path: `load_computed_results` projects the calc engine's output field and nothing else,
so uploaded rows, raw file bytes and parsed deck text are never fetched, let alone sent.

Structure path (rule 16, read_structure): selected deck structures (tables, charts with data
labels, KPI panels, roadmaps and timelines, hiring, unit-economics and use-of-funds tables) and
spreadsheet sheet names, title rows and header rows (at most 3 header rows) with, per column, up to 3 sample values (numeric and date
columns only) or a profile (distinct count, typical length, shape pattern) for text columns. Only
after redaction, only with the audit's consent, only as extracted text with cell positions; never
raw files or prose slides (the page_claims step below is the one exception, for pages). For the sheet_structure step only (George, 2026-10-18;
chat-upload.md section 26): every text cell of one sheet (title rows, headers, row labels, indents,
num/blank markers), after redaction and the withhold rule, never a figure, at most 400 rows with
text; checked again here (structures/redact.sheet_text_problem). For the page_claims step only (George, 2026-10-22,
PR #158, decision 1b; the default path since 2026-10-22, DECK_PIPELINE=ai, docs/design/ai-reads-rules-check.md): the text
lines of deck pages whose text holds at least one digit, prose lines included, as `p<page>r<row>c<col>: <text>` lines, at most 5
pages per call, with one PNG of each whole page (docs/design/page-image.md; George, 2026-10-27): pages go as printed, with no
redaction, to a Sonnet or Opus model only (page_reader_problem), read with the `deck_reading` prompt of the store; a page with no
digit in its text is refused (structures/redact.page_text_problem). A page call is exempt from the daily spend cap and counted in the tester's
monthly allowance, as a column mapping is (docs/specs/usage-and-allowance.md section 4). A deck structure's text carries, below its cells, the item
list Python made (docs/specs/structure-labelling.md): one line per figure with its cell, its raw
text cut from the redacted cell, its values and header cells, and a roadmap's date cells and text
lines; an item line out of format, or whose raw text is not a figure inside its cell, is refused
(bad_item_line). The caller hands the text in; the gateway reads no parsed deck text, runs
redaction again and refuses the call if anything changes. `load_structure_context` reads the
audit's consent and the names to protect, and nothing else. The deck parser has no link to the
gateway.

Logs and Mongo (rule 17) store model JSON output (labels naming listed items, roadmap pairs) and the
item list without raw text (values with cell references), the prompt version, the model version,
the content hash, token counts and cost; never deck text sent to the model. Delete audit removes
the model outputs (purge_run).

Verification (rule 18): model output never becomes Verified on its own. The model only labels the
figures Python listed: every value and cell is Python's, read from its source cell
(app/structures/items.py), and app/structures/verify.py rebuilds every period; anything it cannot
verify is shown as "AI suggestion, not verified" or dropped.

No other function here touches Mongo for audit data, and no module in this package performs file I/O: the
prompts are read from the `prompts` collection (`prompt_store`, docs/specs/prompt-store.md) and a missing prompt
means no model call.

Order of operations for a generation request:

    step config -> load computed results -> validate against MetricsPayload -> build payload -> allowlist
    -> pseudonymise segments + identifiers -> cache lookup -> advisory lock
    -> guards -> provider -> strict parse
    -> numeric guard -> re-identify -> cache -> log

Any failure downgrades to `narrative_status="unavailable"` and still returns the
computed metrics. The dashboard is never blocked by this gateway.
"""
import hashlib
import json
import logging
import os
import re
from datetime import datetime, timezone
from types import SimpleNamespace
from typing import Any, Dict, Iterable, List, NamedTuple, Optional, Tuple

from schemas.metrics import safe_problems

from .. import allowance, disclosure, formatting, readings
from ..structures import redact as structure_redact
from . import cache, guards, prompt_store, redaction, schemas, step_payloads
from .schemas import (FILE_RECOGNITION, FILE_TYPE, MAPPING_FIELDS, PAGE_CLAIMS, SHEET_READING, SHEET_STRUCTURE, STRUCTURE_TYPES, DeckUsage, FileRecognitionReply,
                      FileTypeReply, LabellingReply, Narrative, NarrativeResponse, PageClaimsReply, SheetStructureReply, StructureRead, StructureReply,
                      UsageResponse, narrative_output_schema)

logger = logging.getLogger("growth.llm")

CALLS_COLLECTION = guards.CALLS_COLLECTION
RESULTS_COLLECTION = "audits"
# The data inventory counts the audit's parsed decks: a number, never a read of their text (CLAUDE.md rule 16; George, 2026-10-11).
# The one place the gateway names this collection; test_gateway_data_boundary.py pins it to a count_documents on the audit id.
DECK_COUNT_COLLECTION = "deck_text"

# Shown when the stored metrics do not match the contract (schemas/metrics.py): no prompt is built, no model is called.
NARRATIVE_NOT_GENERATED = "Narrative could not be generated. The computed metrics below are unaffected."

REQUEST_TIMEOUT_SECONDS = 60.0
MAX_PROVIDER_RETRIES = 2          # network, 408/409/429 and 5xx (529 overloaded included) only
MAX_PARSE_RETRIES = 1             # one reask on a malformed body, then fail
# The provider's retry-after is honoured up to this, so the worst call stays inside the lock (guards.LOCK_TTL_SECONDS).
RETRY_AFTER_MAX_SECONDS = 20.0

# Per-1M-token list prices, used only to estimate spend for the cap and the
# usage endpoint. Not authoritative billing.
# Prices verified against Anthropic's pricing page on 2026-09-30. Re-check before relying on
# them for a spend decision: they go stale when Anthropic changes them or releases a model.
# There is deliberately no default price: a model missing from this table is refused by
# run_model(), so the spend caps can never be bypassed by an unpriced model.
MODEL_PRICING_USD = {
    "claude-opus-5-5": {"input": 4.00, "output": 20.00},
    "claude-opus-5": {"input": 5.00, "output": 25.00},
    "claude-sonnet-5-5": {"input": 2.00, "output": 10.00},
    "claude-sonnet-5": {"input": 2.00, "output": 10.00},
    "claude-haiku-4-5": {"input": 1.00, "output": 5.00},
}
DEFAULT_MODEL = "claude-sonnet-5-5"

# Sampling parameters were removed on the current Opus/Sonnet generation: sending
# `temperature` to those models is a 400. Only models listed here get it.
MODELS_ACCEPTING_TEMPERATURE = {"claude-haiku-4-5"}

def run_model() -> str:
    """The one model every step in a run uses.

    A run-level setting (NARRATIVE_MODEL in backend/.env, default DEFAULT_MODEL) rather than a per-step
    one, so sections of the same analysis can never be written by different models.
    Steps have no model of their own. An unknown model is refused: it would have no
    price, so the spend caps could not count it.
    """
    chosen = os.environ.get("NARRATIVE_MODEL", "").strip() or DEFAULT_MODEL
    if chosen not in MODEL_PRICING_USD:
        raise GatewayError("model_not_configured", f"NARRATIVE_MODEL {chosen!r} has no price entry")
    return chosen


# Per-step configuration. Only `growth_engine` has a prompt; the rest are
# scaffolded so wiring and guards are already in place when their prompts land.
STEP_CONFIG = {
    "growth_engine": {
        "prompt": "growth_engine",
        # Window lengths this step legitimately talks about ("12-month NRR"),
        # allowlisted so ordinary phrasing is not treated as a fabricated figure.
        "windows": [12, 24],
        "max_tokens": 4000,
        "temperature": 0.2,
        "enabled": True,
    },
    # The data inventory (A1) and data integrity (A2): written from the engine's stored output through
    # step_payloads (source keys, statuses and closed sentences only), with the same guards as growth_engine plus the
    # step guards of `step_problem`.
    "data_inventory": {
        "prompt": "data_inventory",
        "windows": [],
        "max_tokens": 3000,
        "temperature": 0.2,
        "max_words": 250,
        "verdicts": (),
        "enabled": True,
    },
    "data_integrity": {
        "prompt": "data_integrity",
        "windows": [],
        "max_tokens": 3000,
        "temperature": 0.2,
        "max_words": 300,
        "verdicts": step_payloads.DATA_INTEGRITY_VERDICTS,
        "enabled": True,
    },
    "cohort_retention": {
        "prompt": "cohort_retention",
        # Window lengths this step legitimately talks about ("12-month NRR"),
        # allowlisted so ordinary phrasing is not treated as a fabricated figure.
        "windows": [12, 24],
        "max_tokens": 3000,
        "temperature": 0.2,
        "enabled": False,
    },
    "cac_efficiency": {
        "prompt": "cac_efficiency",
        # Window lengths this step legitimately talks about ("12-month NRR"),
        # allowlisted so ordinary phrasing is not treated as a fabricated figure.
        "windows": [4],
        "max_tokens": 3000,
        "temperature": 0.2,
        "enabled": False,
    },
    "path_to_plan": {
        "prompt": "path_to_plan",
        # Window lengths this step legitimately talks about ("12-month NRR"),
        # allowlisted so ordinary phrasing is not treated as a fabricated figure.
        "windows": [12, 24],
        "max_tokens": 3000,
        "temperature": 0.2,
        "enabled": False,
    },
}


class GatewayError(Exception):
    """Generation failed in a way that yields narrative_status=unavailable. A provider error carries its
    HTTP status and error type (codes only, see _provider_error_type)."""

    def __init__(self, reason: str, detail: str = "", status: Optional[int] = None,
                 error_type: Optional[str] = None, check: Optional[str] = None, fields: Optional[List[str]] = None,
                 provider_message: Optional[str] = None):
        self.reason = reason
        self.detail = detail
        self.status = status
        self.error_type = error_type
        self.provider_message = provider_message    # a 4xx provider's own message, raw; logged only through _logged_provider_message
        self.check = check              # parse_failed on a structure reply: one of PARSE_CHECKS
        self.fields = fields or []      # ... and the schema fields that failed (closed names from the schema, never values)
        super().__init__(f"{reason}: {detail}" if detail else reason)


# ---------------------------------------------------------------------------
# The single data accessor
# ---------------------------------------------------------------------------
async def load_computed_results(db, run_id: str, step: str) -> dict:
    """`load_checked_results` without the contract verdict."""
    return (await load_checked_results(db, run_id, step))[0]


def contract_problems(results: Any) -> List[str]:
    """Where `results` does not match MetricsPayload or breaks a unit; empty when it is sound. Paths and error types only:
    a value can be a segment name or a reason text that quotes the upload, and this goes to a log line."""
    return safe_problems(results)


def contract_failed(run_id: str, step: str, problems: List[str], metrics: dict) -> NarrativeResponse:
    """No model call: log the problems, say so, and hand back the metrics so the dashboard still renders them."""
    logger.error("metrics contract violated for run %s step %s: %d problem(s), no model call: %s",
                 run_id, step, len(problems), "; ".join(problems[:20]))
    return _unavailable(run_id, step, NARRATIVE_NOT_GENERATED, metrics)


async def load_checked_results(db, run_id: str, step: str) -> Tuple[dict, List[str]]:
    """Read ONLY the calc engine's computed output for this run, and check it against the contract.

    The projection is the enforcement: `results` and the run's own identifiers
    are the only fields fetched. `datasets` (uploaded rows and file bytes) lives
    in another collection this gateway never queries.

    `step` selects which slice of the computed results the step is allowed to
    see, so a step cannot widen its own data access.
    """
    doc = await db[RESULTS_COLLECTION].find_one(
        {"id": run_id},
        {"_id": 0, "id": 1, "results": 1, "reporting_currency": 1,
         "target_arr": 1, "target_date": 1, "as_of_month": 1, "computed_at": 1, "fiscal_year_end": 1},
    )
    if not doc:
        raise GatewayError("run_not_found", f"no run {run_id}")
    if not doc.get("results"):
        raise GatewayError("not_computed", f"run {run_id} has no computed results")

    results = doc["results"]
    slice_ = _slice_for_step(results, step, await count_decks(db, run_id) if step == "data_inventory" else None,
                             int(doc.get("fiscal_year_end") or 12))
    return ({
        "run_id": run_id,
        "reporting_currency": doc.get("reporting_currency"),
        "target_arr": doc.get("target_arr"),
        "target_date": doc.get("target_date"),
        **period_fields(results),
        "computed_at": doc.get("computed_at"),
        "metrics": slice_,
        # The payload narratives were keyed on before the period fields: kept server-side to find them (never sent).
        "legacy_as_of": {"top": doc.get("as_of_month") or results.get("as_of_month"), "metrics": results.get("as_of_month")},
    }, contract_problems(results))


# Provenance row references: which spreadsheet rows fed a figure. Useful on the
# dashboard and in the export, but the model can't use them (they are neither
# figures to copy nor citations), and `row_numbers` runs to 500 integers per
# metric. Removed from the outbound payload only - never from stored results.
ROW_REFERENCE_KEYS = frozenset({"row_numbers", "rows"})


def strip_row_references(node: Any) -> Any:
    """Deep copy of `node` without row-reference keys. The input is not modified."""
    if isinstance(node, dict):
        return {k: strip_row_references(v) for k, v in node.items() if k not in ROW_REFERENCE_KEYS}
    if isinstance(node, list):
        return [strip_row_references(i) for i in node]
    return node


def withhold_partial_quarters(node: Any) -> Any:
    """Replace the payback figures of partial quarters with a reason, in a copy.

    A partial quarter's CAC payback pairs a full quarter of lagged S&M with part of a
    quarter's new MRR and overstates. The dashboard shows it, labelled; the model is
    not given the figure, so it cannot quote it as if it were comparable.
    """
    if not isinstance(node, dict):
        return node
    cac = (node.get("metrics") or {}).get("cac_payback")
    if not isinstance(cac, dict) or not isinstance(cac.get("quarters"), dict):
        return node
    quarters = {}
    for q, row in cac["quarters"].items():
        if isinstance(row, dict) and row.get("partial"):
            reason = f"partial quarter ({row.get('months_in_quarter')} of 3 months); not comparable"
            row = {k: ({"months": None, "reason": reason} if k in ("L0", "L1", "L2") else v)
                   for k, v in row.items()}
        quarters[q] = row
    return {**node, "metrics": {**node["metrics"], "cac_payback": {**cac, "quarters": quarters}}}


# ---------------------------------------------------------------------------
# Outbound allowlist
# ---------------------------------------------------------------------------
# The only field names the provider may receive. Everything else is dropped,
# so a field the engine adds later stays server-side until it is listed here.
# What may pass: metric names, figures, units, periods, rule/formula text,
# engine-written reasons and pseudonymised segment labels. Never file or sheet
# names, column headers or raw cell values (`source.file`, `source.sheet`,
# `source.columns`, `founder_involved_excluded.values`).
OUTBOUND_TOP_LEVEL = frozenset({"reporting_currency", "target_arr", "target_date", "evidence_to", "last_month_status", "metrics"})

OUTBOUND_FIELDS = frozenset({
    # metric blocks (the step slice)
    "arr", "nrr", "gross_churn", "cac_payback", "sales_cycle", "win_rate", "founder_win_rate",
    "acv_path", "segment_paths", "cohort_retention", "evidence_to", "last_month_status", "reporting_currency",
    "missing_data", "questions_for_management",
    # data inventory and data integrity (step_payloads.py): source keys, statuses and closed sentences
    "source_list", "inventory", "integrity", "source_key", "description", "category", "in_request_list", "quality_issues",
    "analyses_blocked", "months_supplied", "months_required", "check", "first_month", "last_month", "revenue_file_total",
    "pnl_total", "gap", "gap_pct", "tolerance", "window_over_tolerance", "months_over_tolerance",
    "deviation_points", "limit_points", "result", "threshold_note", "finding",
    # shared
    "value", "mrr", "month", "series", "n", "status", "reason", "computable", "available",
    "source", "rule",
    # nrr / gross churn
    "overall_pct", "nrr_pct", "churn_pct", "trailing_window_months", "nrr_base_customers",
    "by_segment", "by_cohort", "months_available", "insufficient_history",
    # cac payback
    "default_l", "quarters", "headline_quarter", "partial_quarter_excluded", "new_mrr", "n_customers",
    "months_in_quarter", "partial", "gross_margin_pct", "L0", "L1", "L2", "months", "sm_expense",
    # sales cycle / win rate
    "median_days", "iqr", "won", "lost", "win_rate_pct", "excluded_invalid", "excluded_after_as_of",
    "by_founder", "with_founder", "without_founder", "small_sample", "founder_involved_excluded", "count",
    # acv path
    "current_customers", "current_arr", "acv", "target_arr", "target_date", "bands", "overall_band",
    "key", "label", "low", "high", "range_label", "customers", "total_customers_at_target",
    "customers_needed", "additional_customers_needed", "required_net_new_per_year",
    "observed_net_new_per_year_12m", "observed_net_new_per_year_24m",
    "required_vs_observed_12m", "required_vs_observed_24m", "target_date_error",
    # segment paths
    "assumption", "missing_inputs", "input", "resolve", "horizon_months", "stage_one", "segments",
    "start_arr", "small_base", "projected_arr", "change_arr", "arr_change_per_nrr_point",
    "start_arr_total", "projected_base_arr", "unsegmented_customers", "unsegmented_arr", "gap_arr",
    "target_met_by_base", "landed", "reverse_solve", "reconciliation", "window_months",
    "gross_new_per_year", "unsegmented_new_customers", "new_customers", "landed_acv", "reachable",
    "new_customers_by_target", "required_blended_landed_acv", "best_segment", "best_segment_landed_acv",
    "current_mix_landed_acv", "required_new_per_year_at_current_mix", "required_vs_observed_gross",
    "moved_mix_pct", "current_mix_pct", "required_mix_pct", "shift_pct_points",
    "path_to_plan_ratio", "factor_compounded_base", "factor_landed_acv", "factor_gross_rate", "segment_ratio",
    # missing data / questions for management
    "metric", "absent_fields", "result_key", "dataset", "question",
    # cohort retention
    "cohorts", "max_offset", "data", "cohort", "start_mrr",
})

# Field names allowed only under one parent: a cohort row's `values` are
# retention percentages, while `founder_involved_excluded.values` are raw cells.
OUTBOUND_FIELDS_BY_PARENT = {"data": frozenset({"values"})}

# Containers whose keys are data, not field names, and what those keys may be.
_PERIOD_KEY = re.compile(r"^(\d{4}-(Q[1-4]|\d{2})|\d{1,3})$")   # 2024-Q3, 2024-06, 12, 0
PERIOD_KEYED = frozenset({"by_cohort", "quarters", "landed", "reverse_solve", "reconciliation", "values"})
DATASET_KEYED = {"absent_fields": frozenset({"revenue", "crm", "pnl"})}

def allowlist_payload(node: Any, key: Optional[str] = None) -> Any:
    """Deep copy of `node` keeping only allowlisted fields. The input is not modified.

    Segment-container keys (`by_segment`, `segments`) are kept as they are, to
    be relabelled by `redaction.redact`; period-keyed containers keep only keys
    that look like a period or a window length.
    """
    if isinstance(node, list):
        return [allowlist_payload(i, key) for i in node]
    if not isinstance(node, dict):
        return node
    if key is None:
        return {k: allowlist_payload(v, k) for k, v in node.items() if k in OUTBOUND_TOP_LEVEL}
    if key in redaction.SEGMENT_CONTAINERS:
        return {k: allowlist_payload(v, "_segment") for k, v in node.items() if isinstance(k, str)}
    if key in PERIOD_KEYED:
        return {k: allowlist_payload(v, "_period") for k, v in node.items()
                if isinstance(k, str) and _PERIOD_KEY.match(k)}
    if key in DATASET_KEYED:
        return {k: allowlist_payload(v, k) for k, v in node.items() if k in DATASET_KEYED[key]}
    allowed = OUTBOUND_FIELDS | OUTBOUND_FIELDS_BY_PARENT.get(key, frozenset())
    return {k: allowlist_payload(v, k) for k, v in node.items() if k in allowed}


def period_fields(results: dict) -> dict:
    """The period the model is told: where the evidence ends and the status of that month (always Complete), both read from the
    stored source period (dates-and-periods.md section 2). The as-of setting and the requested analysis date never go."""
    source = results.get("source_period") or {}
    return {"evidence_to": source.get("evidence_to"), "last_month_status": source.get("status")}


def legacy_computed(computed: dict, step: str) -> dict:
    """`computed` as it was before the period fields: the as-of setting in place of them. Used only to find a narrative
    stored under the earlier cache key, so it stays served until the analyst regenerates it (decision 7, 15 Oct 2026)."""
    old = computed.get("legacy_as_of") or {}
    out = {k: v for k, v in computed.items() if k not in ("evidence_to", "last_month_status", "legacy_as_of")}
    out["as_of_month"] = old.get("top")
    metrics = {k: v for k, v in (computed.get("metrics") or {}).items() if k not in ("evidence_to", "last_month_status")}
    if step in step_payloads.STEPS or old.get("metrics") is not None:
        metrics["as_of_month"] = old.get("metrics")
    out["metrics"] = metrics
    return out


async def cached_for(db, run_id: str, step: str, tag: str, model: str, computed: dict, mapping: dict, outbound: Any):
    """(key, stored record) for the current payload; when none is stored, the record written under the earlier payload
    shape, if its numbers still match. Reads only: the dashboard's read path uses it; Write narratives and the cost estimate
    do not, so an analyst's regenerate replaces the earlier narrative (and the estimate shows its cost)."""
    key = cache.cache_key(run_id, step, tag, model, outbound)
    found = await cache.get(db, key)
    if found or "legacy_as_of" not in computed:
        return key, found
    try:
        old = build_outbound(legacy_computed(computed, step), mapping)
    except GatewayError:
        return key, None
    return key, await cache.get(db, cache.cache_key(run_id, step, tag, model, old))


def build_outbound(computed: dict, mapping: dict) -> dict:
    """The payload the provider sees: display strings, allowlisted, then pseudonyms.

    Numbers are formatted here, from the raw computed values, so the model is
    only ever handed strings it can copy - never a float it could reformat.
    Raw values stay untouched in `computed` and in Mongo.
    """
    try:
        formatted = formatting.format_payload(withhold_partial_quarters(strip_row_references(computed)))
    except formatting.FormattingError as exc:
        raise GatewayError("format_failed", str(exc))
    return redaction.redact(allowlist_payload(formatted), mapping)


async def count_decks(db, run_id: str) -> Optional[int]:
    """How many decks the audit holds: a count, no document is returned. None when the count cannot be read."""
    try:
        return int(await db[DECK_COUNT_COLLECTION].count_documents({"audit_id": run_id}))
    except Exception:
        return None


def _slice_for_step(results: dict, step: str, deck_count: Optional[int] = None, fiscal_year_end: int = 12) -> dict:
    """Narrow computed results to what a step needs. Unknown keys are dropped. `deck_count` is the data inventory's
    only input that is not in the stored results; the audit's `fiscal_year_end` sets the data integrity's clustering quarters
    and is never sent."""
    if step in step_payloads.STEPS:
        return {**step_payloads.build(step, results, deck_count, fiscal_year_end), **period_fields(results)}
    wanted = {
        "growth_engine": [
            "arr", "nrr", "gross_churn", "cac_payback", "sales_cycle",
            "win_rate", "founder_win_rate", "acv_path", "segment_paths", "reporting_currency",
        ],
        "cohort_retention": ["cohort_retention"],
        "cac_efficiency": ["cac_payback"],
        "path_to_plan": ["acv_path", "segment_paths"],
    }.get(step, [])
    out = {k: results.get(k) for k in wanted if results.get(k) is not None}
    out.update({k: v for k, v in period_fields(results).items() if v is not None})
    if step == "growth_engine":
        # What could not be computed, and what was computed from another upload and
        # needs management's explanation. Stored results only - never file names,
        # raw rows or parsed text.
        for key, fields in _GAP_FIELDS.items():
            if results.get(key) is not None:
                out[key] = [{f: _outbound_gap_value(f, item) for f in fields if item.get(f) is not None}
                            for item in results[key] if isinstance(item, dict)]
    return out


# Missing-data sentences that quote raw cell values (currency codes, founder-involved
# entries). The model gets the same statement without them; Mongo keeps the original.
_NEUTRAL_REASONS = {
    "Revenue rows with unmapped currency":
        "{count} row(s) use a currency with no exchange rate provided — excluded, not guessed at 1.0",
    "CRM rows with unrecognized founder-involved value":
        "{count} row(s) have a founder_involved value that isn't yes/no-like — excluded from the founder "
        "split, not guessed",
}
_LEADING_COUNT = re.compile(r"^\d+")


def _outbound_gap_value(field: str, item: dict) -> Any:
    """A missing-data or question field as the model may see it."""
    if field == "question":
        return _neutral_question(item)
    if field == "reason" and item.get("metric") in _NEUTRAL_REASONS:
        count = _LEADING_COUNT.match(str(item["reason"]))
        return _NEUTRAL_REASONS[item["metric"]].format(count=count.group(0) if count else "Some")
    return item[field]


def _neutral_question(item: dict) -> str:
    """The management question without the upload's file name or column headers.

    The stored question names the columns the figure was computed from; the
    dashboard shows that version. The model gets engine field names only.
    """
    fields = ", ".join(sorted(item.get("columns") or {})) or "the mapped"
    return (f"{item.get('metric')} was computed from the {item.get('dataset')} upload because it was "
            f"not available from the expected upload. Please explain the result and confirm that the "
            f"{fields} fields are the right basis for it.")


_GAP_FIELDS = {
    "missing_data": ("metric", "status", "reason", "absent_fields"),
    "questions_for_management": ("metric", "status", "result_key", "dataset", "question"),
}


# ---------------------------------------------------------------------------
# Provider adapter - swap this class to change provider
# ---------------------------------------------------------------------------
def _user_content(user_payload: str, images: Optional[List[bytes]] = None):
    """The user message: the text alone, or, for a page read, the page images (PNG) followed by the text in the same request."""
    if not images:
        return user_payload
    import base64
    return [*({"type": "image", "source": {"type": "base64", "media_type": "image/png", "data": base64.b64encode(png).decode("ascii")}}
              for png in images), {"type": "text", "text": user_payload}]


def _assert_masked(user_payload: str) -> None:
    """The last line of the one masking rule (read-check-review.md section 8): no call leaves the server with an email, an IBAN,
    an ID number or a "+" phone number in its text. Every payload passes the masker before it gets here; this refuses one that
    did not, whatever the caller. The reason names kinds only, never the text."""
    kinds = structure_redact.personal_items(user_payload or "")
    if kinds:
        raise GatewayError("unmasked_personal_data", ",".join(kinds))


class AnthropicAdapter:
    """Thin adapter over the Anthropic Messages API.

    The only place in the codebase that talks to a model provider. Everything
    the rest of the gateway needs is expressed in `complete()`'s signature, so a
    different provider is a drop-in replacement for this class.
    """

    name = "anthropic"

    def __init__(self, api_key: Optional[str] = None, timeout: float = REQUEST_TIMEOUT_SECONDS):
        self._api_key = api_key if api_key is not None else os.environ.get("ANTHROPIC_API_KEY", "")
        self._timeout = timeout
        self._client = None

    def _ensure_client(self):
        """Import and construct lazily so the package is importable (and the
        test suite runnable) on a machine with no key and no SDK installed."""
        if self._client is not None:
            return self._client
        if not self._api_key:
            raise GatewayError(
                "provider_not_configured",
                "ANTHROPIC_API_KEY is not set; narrative generation is disabled",
            )
        try:
            import anthropic
        except ImportError as exc:  # pragma: no cover - depends on install
            raise GatewayError("provider_not_configured", f"anthropic SDK missing: {exc}")
        self._client = anthropic.Anthropic(
            api_key=self._api_key,
            timeout=self._timeout,
            # The gateway owns its retry policy; the SDK must not add its own.
            max_retries=0,
        )
        return self._client

    def complete(
        self,
        *,
        model: str,
        system: str,
        user_payload: str,
        max_tokens: int,
        temperature: Optional[float],
        json_schema: Optional[dict],
        cache_system: bool = False,
        images: Optional[List[bytes]] = None,
        prior: Optional[List[dict]] = None,
    ) -> Tuple[str, int, int]:
        """One provider call. Returns (text, input_tokens, output_tokens).

        `json_schema` is the strict output schema (`output_config.format`); None sends none, and the caller validates the text
        (the sheet reading: the schema goes as text in its request). `prior` is the turns before the user message, in order
        ([{"role": "user"|"assistant", "content": text}]): the sheet reading's retry sends its request, the reply that failed and
        the fix request as one conversation. Every text of a prior turn passes the masking check too.

        With `cache_system` the system prompt is marked for the provider's prompt cache (the page_claims step: the same
        prompt for every batch of an audit). The input tokens returned then count the cache writes and reads with the
        uncached tokens, so the token cap and the cost estimate count every token sent; the estimate is an upper bound,
        since a cache read is billed below list price.

        Raises `RetryableProviderError` for network/5xx so the caller can back
        off, and `GatewayError` for anything a retry would not fix.
        """
        _assert_masked(user_payload)
        for turn in prior or []:
            _assert_masked(turn["content"])
        client = self._ensure_client()
        kwargs = {
            "model": model,
            "max_tokens": max_tokens,
            "system": [{"type": "text", "text": system, "cache_control": {"type": "ephemeral"}}] if cache_system else system,
            "messages": [*({"role": t["role"], "content": t["content"]} for t in prior or []),
                         {"role": "user", "content": _user_content(user_payload, images)}],
        }
        if json_schema is not None:
            # Structured output is what makes strict parsing viable: the first
            # content block is guaranteed to be schema-valid JSON.
            kwargs["output_config"] = {"format": {"type": "json_schema", "schema": json_schema}}
        # Current Opus/Sonnet models reject sampling params with a 400.
        if temperature is not None and model in MODELS_ACCEPTING_TEMPERATURE:
            kwargs["temperature"] = temperature

        try:
            response = client.messages.create(**kwargs)
        except Exception as exc:
            raise _classify_provider_error(exc)
        if getattr(response, "stop_reason", None) == "refusal":
            # A declined request is not retried: the same request would be declined again.
            raise GatewayError("model_refused", "the model declined the request")

        text = next((b.text for b in response.content if getattr(b, "type", None) == "text"), "")
        usage = getattr(response, "usage", None)
        billed_in = int(getattr(usage, "input_tokens", 0) or 0)
        if cache_system:
            billed_in += int(getattr(usage, "cache_creation_input_tokens", 0) or 0) + \
                int(getattr(usage, "cache_read_input_tokens", 0) or 0)
        billed_out = int(getattr(usage, "output_tokens", 0) or 0)
        if getattr(response, "stop_reason", None) == "max_tokens":
            # A reply cut at max_tokens is not JSON the schema can check, and the same request would be cut again: it is
            # reported as "truncated" with the tokens it billed, never reasked (the page step splits the batch instead).
            cut = GatewayError("truncated", "the reply was cut at max_tokens")
            cut.tokens = (billed_in, billed_out)
            raise cut
        return text, billed_in, billed_out


    def count_tokens(self, *, model: str, system: Optional[str], user_payload: str,
                     json_schema: Optional[dict], images: Optional[List[bytes]] = None) -> int:
        """The input tokens a call would bill, from the provider's token counter (no call is made).
        With no system prompt and no schema it counts `user_payload` alone."""
        _assert_masked(user_payload)
        client = self._ensure_client()
        extra = {}
        if system is not None:
            extra["system"] = system
        if json_schema is not None:
            extra["output_config"] = {"format": {"type": "json_schema", "schema": json_schema}}
        try:
            response = client.messages.count_tokens(
                model=model, messages=[{"role": "user", "content": _user_content(user_payload, images)}], **extra)
        except Exception as exc:
            raise _classify_provider_error(exc)
        return int(getattr(response, "input_tokens", 0) or 0)


class RetryableProviderError(Exception):
    """Network error, 408/409/429 or 5xx - safe to retry with backoff."""

    def __init__(self, message: str, status: Optional[int] = None, error_type: Optional[str] = None,
                 retry_after: Optional[float] = None):
        super().__init__(message)
        self.status = status
        self.error_type = error_type
        self.retry_after = retry_after
        self.provider_message = None


_ERROR_CODE = re.compile(r"[a-z][a-z0-9_]{0,59}")


def _provider_error_type(exc: Exception) -> str:
    """The provider's error type ("rate_limit_error"), from the SDK's `type` or the body's error.type, when it
    reads as a code; otherwise the exception's class name. The message is never read: it can quote the request."""
    code = getattr(exc, "type", None)
    if not isinstance(code, str):
        body = getattr(exc, "body", None)
        error = body.get("error") if isinstance(body, dict) else None
        code = error.get("type") if isinstance(error, dict) else None
    return code if isinstance(code, str) and _ERROR_CODE.fullmatch(code) else type(exc).__name__


def _provider_message(exc: Exception, status: Optional[int]) -> Optional[str]:
    """The provider's own error message (body error.message, else the exception's text) on a 4xx; None otherwise."""
    if status is None or not 400 <= status < 500:
        return None
    body = getattr(exc, "body", None)
    error = body.get("error") if isinstance(body, dict) else None
    message = error.get("message") if isinstance(error, dict) else None
    return message if isinstance(message, str) and message else str(exc)


PROVIDER_MESSAGE_CAP = 300
_QUOTED = re.compile(r"""'[^']*'|"[^"]*"|`[^`]*`""")
_FIGURE = re.compile(r"[£$€]?\d[\d,.]{3,}")
_TOKEN = re.compile(r"Client-\d+|sk-[\w-]{8,}|Bearer\s+\S+")
_OVERLAP = 20


def _logged_provider_message(exc: Exception, *sent: Optional[str]) -> str:
    """The 4xx provider message for the "structure not read" line, or "-". 4xx messages name schema and request faults and carry no
    file content, so they are logged, capped at PROVIDER_MESSAGE_CAP; as a belt for a message that quotes the request anyway, quoted spans
    and figures are blanked, a message holding a token is left out, and so is one sharing a run of 20 characters with anything sent
    (the cells, the prompt). Request bodies, keys and the prompt are never logged."""
    message = getattr(exc, "provider_message", None)
    if not message:
        return "-"
    message = " ".join(_FIGURE.sub("#", _QUOTED.sub("…", message)).split())
    if _TOKEN.search(message):
        return "-"
    for text in sent:
        flat = " ".join((text or "").split())
        if any(message[i:i + _OVERLAP] in flat for i in range(max(0, len(message) - _OVERLAP + 1))):
            return "-"
    return message[:PROVIDER_MESSAGE_CAP] or "-"


def _message_field(exc: Exception, *sent) -> str:
    """` message=...` for a log line when the provider's 4xx message is loggable, else nothing."""
    message = _logged_provider_message(exc, *[x if isinstance(x, str) else json.dumps(x, default=str) for x in sent])
    return "" if message == "-" else f" message={message}"


def _retry_after_seconds(exc: Exception) -> Optional[float]:
    """The provider's retry-after header in seconds, or None."""
    try:
        value = float(getattr(getattr(exc, "response", None), "headers", {}).get("retry-after"))
    except (AttributeError, TypeError, ValueError):
        return None
    return value if 0 <= value < float("inf") else None


def _backoff_seconds(exc: Exception, attempt: int) -> float:
    """Exponential backoff (1 s, 2 s), or the provider's retry-after when longer, up to RETRY_AFTER_MAX_SECONDS."""
    retry_after = getattr(exc, "retry_after", None)
    return max(2 ** attempt * 0.5, min(retry_after or 0.0, RETRY_AFTER_MAX_SECONDS))


def _classify_provider_error(exc: Exception) -> Exception:
    """Decide whether a provider exception is worth retrying.

    Only connection failures, timeouts, 408/409/429 and 5xx are retryable. A
    400 (bad request) or 401 (bad key) is returned as-is, because retrying it
    just spends money on the same failure. Either carries the HTTP status and
    the provider's error type for the log and llm_calls.
    """
    status = getattr(exc, "status_code", None)
    name = type(exc).__name__
    error_type = _provider_error_type(exc)
    if status is not None and (status >= 500 or status in (408, 409, 429)):
        retry = RetryableProviderError(f"{name} {status}: {exc}", status, error_type, _retry_after_seconds(exc))
        retry.provider_message = _provider_message(exc, status)
        return retry
    if status is None and name in {
        "APIConnectionError", "APITimeoutError", "APIConnectionTimeoutError",
    }:
        return RetryableProviderError(f"{name}: {exc}", None, error_type)
    if status is not None:
        return GatewayError("provider_error", f"{name} {status}: {exc}", status, error_type,
                            provider_message=_provider_message(exc, status))
    return RetryableProviderError(f"{name}: {exc}", None, error_type)


def _unreachable(exc: RetryableProviderError) -> GatewayError:
    """The GatewayError for a retryable error that outlasted MAX_PROVIDER_RETRIES, with its status and type."""
    return GatewayError("provider_unreachable", str(exc), exc.status, exc.error_type, provider_message=exc.provider_message)


# ---------------------------------------------------------------------------
# Output integrity
# ---------------------------------------------------------------------------
# Fields whose numbers are load-bearing: a wrong figure in the headline or a
# table row is read as fact, so an unmatched number there kills the narrative.
HARD_FIELDS = ("headline",)
# Prose fields. An unmatched number here is usually rhetorical ("above 100") or
# a window length, so the narrative is shown and the number reported instead.
SOFT_FIELDS = ("what_this_means", "worth_flagging", "next_actions")

# Structural numerals that carry no claim about this company's figures. 100 is
# the retention baseline every NRR sentence refers to; per-step window lengths
# come from STEP_CONFIG["windows"].
GLOBAL_ALLOWED_NUMERALS = (100,)


class NumericGuardResult(NamedTuple):
    """Unmatched numbers, split by how much damage they could do."""

    hard: List[str]   # headline / table rows - narrative is dropped
    soft: List[str]   # prose - narrative is shown, flagged

    @property
    def all(self) -> List[str]:
        return sorted(set(self.hard) | set(self.soft), key=_numeric_sort_key)


def _numeric_sort_key(token: str):
    try:
        return (0, float(token))
    except ValueError:
        return (1, 0.0)


def allowed_numerals(payload: Any, windows: Iterable[int] = ()) -> set:
    """Every numeric token the model may legitimately use, exactly as the engine holds it."""
    return redaction.numbers_in(payload) | redaction.numbers_in(
        list(GLOBAL_ALLOWED_NUMERALS) + list(windows)
    )


# A negative engine figure may be written as its magnitude with the sign in words
# (change_arr "-77,949" -> "ARR falls by 77,949 EUR"), but only in a sentence that
# says it went down. Growth wording (even beside a decline word), or no direction at
# all, leaves it unverified. "contracts", "down" and "lower" are not decline words: they are
# usually the noun, a down payment or the lower band, and would let a dropped sign pass.
_DECLINE = re.compile(r"\b(?:fall(?:s|ing|en)?|fell|declin(?:e|es|ed|ing)|drop(?:s|ped|ping)?|"
                      r"decreas(?:e|es|ed|ing)|shr(?:ink|inks|inking|ank|unk)|"
                      r"loss of)\b", re.IGNORECASE)
_GROWTH = re.compile(r"\b(?:grow(?:s|ing|n)?|grew|ris(?:e|es|ing|en)|rose|increas(?:e|es|ed|ing)|"
                     r"up|higher|gain(?:s|ed|ing)?|add(?:s|ed|ing)?|expand(?:s|ed|ing)?|improv(?:e|es|ed|ing)|"
                     r"accelerat(?:e|es|ed|ing)|win(?:s|ning)?|won)\b", re.IGNORECASE)
_SENTENCE_END = re.compile(r"(?<=[.!?])\s+")


def _unmatched(text: str, allowed: set) -> set:
    """Numbers in `text` the engine did not produce, judged sentence by sentence."""
    out = set()
    for sentence in _SENTENCE_END.split(text or ""):
        says_decline = bool(_DECLINE.search(sentence)) and not _GROWTH.search(sentence)
        for token in redaction.numbers_in(sentence):
            if token in allowed or (says_decline and f"-{token}" in allowed):
                continue
            out.add(token)
    return out


def numeric_guard(
    narrative: Narrative, payload: Any, windows: Iterable[int] = ()
) -> NumericGuardResult:
    """Check every number the model wrote against the computed results.

    Numbers are the calc engine's job. A figure the engine never produced is
    either invented or derived, and both are wrong in a diligence report - but
    where it appears decides the response. In the headline or a table row it is
    read as fact and the narrative is dropped. In prose it is usually a turn of
    phrase, so the narrative ships with narrative_status="flagged" and the
    number is reported back for prompt tuning.
    """
    allowed = allowed_numerals(payload, windows)

    hard: set = set()
    for field in HARD_FIELDS:
        hard |= _unmatched(getattr(narrative, field, "") or "", allowed)
    for row in narrative.table_rows:
        hard |= _unmatched(f"{row.label}: {row.value}", allowed)  # the label carries the direction

    soft: set = set()
    for row in narrative.table_rows:
        soft |= _unmatched(row.decision_informed or "", allowed)
    for field in SOFT_FIELDS:
        value = getattr(narrative, field, None)
        for text in (value if isinstance(value, list) else [value or ""]):
            soft |= _unmatched(text, allowed)

    # A number that is unmatched in both tiers is reported once, as hard.
    soft -= hard
    return NumericGuardResult(
        hard=sorted(hard, key=_numeric_sort_key),
        soft=sorted(soft, key=_numeric_sort_key),
    )


def source_key_paths(node: Any) -> List[str]:
    """Every dotted path into the payload, e.g. "metrics.acv_path.acv".

    This is the canonical form: bare leaf names are ambiguous, since `label` and
    `value` occur under both `overall_band` and each entry of `bands`, so a row
    citing `label` cannot be traced to one figure. Lists are transparent - an
    array of objects contributes its fields under the array's own path rather
    than an index, because the model is describing a shape, not one element.
    """
    out: set = set()

    def walk(n: Any, path: str) -> None:
        if isinstance(n, dict):
            for key, value in n.items():
                child = f"{path}.{key}" if path else str(key)
                out.add(child)
                walk(value, child)
        elif isinstance(n, list):
            for item in n:
                walk(item, path)

    walk(node, "")
    return sorted(out)


def source_key_values(payload: Any) -> set:
    """The source keys (S1, S2 ...) a payload lists: the value of every `source_key` field (data inventory and data
    integrity). Empty for a payload that has none."""
    out: set = set()

    def walk(n: Any) -> None:
        if isinstance(n, dict):
            for key, value in n.items():
                if key == "source_key" and isinstance(value, str):
                    out.add(value)
                walk(value)
        elif isinstance(n, list):
            for item in n:
                walk(item)

    walk(payload)
    return out


def valid_source_keys(payload: Any) -> List[str]:
    """What the model is told it may cite: the payload's dotted paths and its source keys."""
    return sorted(set(source_key_paths(payload)) | source_key_values(payload))


def accepted_source_keys(payload: Any) -> set:
    """Dotted paths, their bare leaf names and the payload's source keys.

    The dotted path is what the model is told to use. Bare names stay accepted
    so a row citing `acv` is not thrown away over formatting - the point of the
    guard is that the figure is traceable, not that it is spelled one way.
    """
    full = source_key_paths(payload)
    return set(full) | {p.rsplit(".", 1)[-1] for p in full} | source_key_values(payload)


def source_key_guard(narrative: Narrative, payload: Any) -> Optional[str]:
    """Each table row must cite a source key that exists in the payload."""
    available = accepted_source_keys(payload)
    unknown = sorted({r.source_key for r in narrative.table_rows if r.source_key not in available})
    if unknown:
        return f"table row cites unknown source key(s): {', '.join(unknown[:8])}"
    return None


# The simple view (Path to Plan) and the segment view answer one question under different
# assumptions. Each has a ratio of "rate needed / rate observed".
SIMPLE_VIEW_RATIOS = {"required_vs_observed_12m", "required_vs_observed_24m", "path_to_plan_ratio"}
SEGMENT_VIEW_RATIOS = {"required_vs_observed_gross", "segment_ratio"}


def views_guard(narrative: Narrative, payload: Any) -> Optional[str]:
    """Evidence must not state one view's conclusion without the other's.

    When the payload holds a reconciliation of the two views, a table that cites the ratio of
    only one of them would show a reader one verdict while the page's panel shows the other.
    Checked on the evidence table (the cited, verified figures), like the source-key guard.
    """
    reconciliation = ((payload.get("metrics") or {}).get("segment_paths") or {}).get("reconciliation") or {}
    if not any(isinstance(v, dict) and v.get("available") is True for v in reconciliation.values()):
        return None
    cited = {row.source_key.split(".")[-1] for row in narrative.table_rows}
    simple, segment = cited & SIMPLE_VIEW_RATIOS, cited & SEGMENT_VIEW_RATIOS
    if bool(simple) != bool(segment):
        only, missing = ("simple view (Path to Plan)", "segment view") if simple else ("segment view", "simple view (Path to Plan)")
        return (f"evidence table cites the {only} ratio without the {missing} ratio; "
                "both views must be shown together")
    return None


def step_problem(config: dict, narrative: Narrative, payload: Any) -> Optional[str]:
    """The checks of the data inventory and data integrity steps; None for any other step.

    Word limit of the narrative text (headline, what this means, worth flagging, next actions), a "decision informed" on
    every evidence row, no tier code, no request for a category the app cannot ingest, and an integrity verdict that is one
    of the three labels and agrees with the stored reconciliation. Each is a reason to drop the narrative: the figures
    below it are unaffected.
    """
    if config.get("max_words") is None:
        return None
    prose = [narrative.headline, narrative.what_this_means, *narrative.worth_flagging, *narrative.next_actions]
    words = sum(len(text.split()) for text in prose)
    if words > config["max_words"]:
        return f"narrative has {words} words; the limit is {config['max_words']}"
    if any(not (row.decision_informed or "").strip() for row in narrative.table_rows):
        return "an evidence row has no decision informed"
    problem = step_payloads.tier_code_problem(prose + [t for r in narrative.table_rows for t in (r.label, r.decision_informed)])
    problem = problem or step_payloads.request_list_problem(payload, narrative.next_actions)
    if config.get("verdicts"):
        problem = problem or step_payloads.verdict_problem(payload, narrative.verdict)
    return problem


_JSON_BLOCK = re.compile(r"\{.*\}", re.DOTALL)


def parse_strict(text: str) -> Narrative:
    """Parse the model's reply into a Narrative, or raise.

    Structured outputs should make the body clean JSON; the fenced-block
    fallback only covers a provider that ignores the schema. Validation itself
    is never relaxed - extra keys are a parse failure.
    """
    candidate = text.strip()
    if not candidate:
        raise GatewayError("parse_failed", "empty response body")
    try:
        data = json.loads(candidate)
    except json.JSONDecodeError:
        match = _JSON_BLOCK.search(candidate)
        if not match:
            raise GatewayError("parse_failed", "response contained no JSON object")
        try:
            data = json.loads(match.group(0))
        except json.JSONDecodeError as exc:
            raise GatewayError("parse_failed", f"invalid JSON: {exc}")
    try:
        return Narrative.model_validate(data)
    except Exception as exc:
        raise GatewayError("parse_failed", f"did not match schema: {exc}")


# ---------------------------------------------------------------------------
# Logging
# ---------------------------------------------------------------------------
async def log_call(
    db, *, run_id: str, step: str, prompt_version: str, model: str,
    input_tokens: int, output_tokens: int, estimated_cost_usd: float,
    cache_hit: bool, status: str, unmatched_numbers: Optional[List[str]] = None,
    content_hash: Optional[str] = None, deck_id: Optional[str] = None,
    http_status: Optional[int] = None, error_type: Optional[str] = None, structure_type: Optional[str] = None,
    image_tokens: int = 0, image_cost_usd: float = 0.0,
) -> None:
    """Append to llm_calls.

    Deliberately records no prompt text and no payload contents - only the
    metadata needed for cost control and audit. `unmatched_numbers` is the one
    fragment of model output kept, and by construction it contains only numerals
    the payload does NOT hold, so it cannot echo the computed figures back. A
    structure reading call adds the content hash of the text sent (never the
    text) and the deck it came from (CLAUDE.md rule 17). A provider error adds
    its HTTP status and error type, never its message.
    """
    extra = {k: v for k, v in (("content_hash", content_hash), ("deck_id", deck_id), ("http_status", http_status),
                               ("error_type", error_type), ("structure_type", structure_type)) if v is not None}
    await db[CALLS_COLLECTION].insert_one({**extra,
        "run_id": run_id,
        "step": step,
        "prompt_version": prompt_version,
        "model": model,
        "input_tokens": int(input_tokens),
        "output_tokens": int(output_tokens),
        "estimated_cost_usd": round(float(estimated_cost_usd), 6),
        # The part of the two figures above that the page images account for (page-image.md section 6); 0 for a call with none.
        "image_tokens": int(image_tokens),
        "image_cost_usd": round(float(image_cost_usd), 6),
        "cache_hit": bool(cache_hit),
        "status": status,
        "unmatched_numbers": list(unmatched_numbers or []),
        "timestamp": datetime.now(timezone.utc).isoformat(),
    })
    if not cache_hit and (input_tokens or output_tokens):
        # A billed call counts against the tester's allowance, kept on the tester and not on the audit (usage-and-allowance.md).
        await allowance.record_for_audit(db, run_id, calls=1, tokens=int(input_tokens) + int(output_tokens),
                                         cost_usd=float(estimated_cost_usd))


_DATE_SUFFIX = re.compile(r"-\d{8}$")


def price_model(model: str) -> str:
    """The price-table entry of a model id: a dated version ("claude-sonnet-5-5-20260101") is priced as its family member."""
    return _DATE_SUFFIX.sub("", model or "")


def estimate_cost_usd(model: str, input_tokens: int, output_tokens: int) -> float:
    price = MODEL_PRICING_USD.get(model) or MODEL_PRICING_USD.get(price_model(model))
    if not price:
        return 0.0
    return (input_tokens / 1_000_000) * price["input"] + (
        output_tokens / 1_000_000
    ) * price["output"]


# ---------------------------------------------------------------------------
# Orchestration
# ---------------------------------------------------------------------------
async def generate_narrative(
    db, run_id: str, step: str, adapter: Optional[AnthropicAdapter] = None,
    sleep=None,
) -> NarrativeResponse:
    """Generate or return a cached narrative for run_id+step.

    Never raises for an LLM-side problem: every failure path returns the
    computed metrics with narrative_status="unavailable".
    """
    import asyncio
    sleep = sleep or asyncio.sleep

    config = STEP_CONFIG.get(step)
    if not config:
        return NarrativeResponse(
            run_id=run_id, step=step, narrative_status="unavailable",
            reason=f"unknown step {step!r}", metrics={},
        )

    # Data load is outside the try: a missing run is a real 404, not a
    # narrative-unavailable case.
    computed, problems = await load_checked_results(db, run_id, step)
    metrics = computed["metrics"]

    if not config.get("enabled"):
        return NarrativeResponse(
            run_id=run_id, step=step, narrative_status="unavailable",
            reason=f"step {step!r} is scaffolded but has no prompt yet", metrics=metrics,
        )
    if problems:                      # before any prompt is loaded or built
        return contract_failed(run_id, step, problems, metrics)

    try:
        prompt = await prompt_store.load(db, config["prompt"])
    except prompt_store.PromptMissing:
        return _unavailable(run_id, step, prompt_store.NO_PROMPT, metrics)       # no model call (docs/specs/prompt-store.md)

    try:
        model = run_model()
    except GatewayError as exc:
        return _unavailable(run_id, step, str(exc), metrics)
    config = {**config, "model": model}
    mapping = await redaction.get_or_create_map(db, run_id, computed)
    try:
        outbound = build_outbound(computed, mapping)
    except GatewayError as exc:
        return _unavailable(run_id, step, str(exc), metrics)

    # Last-line assertion: nothing from the audit's token map may appear outbound.
    leaks = redaction.find_leaks(outbound, mapping)
    if leaks:
        logger.error("redaction leak for run %s: %d identifier(s)", run_id, len(leaks))
        return _unavailable(run_id, step, "redaction check failed", metrics)

    key = cache.cache_key(run_id, step, prompt_store.cache_tag(prompt), model, outbound)

    cached = await cache.get(db, key)
    if cached:
        return await _from_cache(db, cached, run_id, step, prompt.version, model, metrics)

    # Circuit breaker: if another request for this run+step is mid-flight, wait
    # for it and serve its result rather than making a second call.
    token = await guards.acquire(db, run_id, step)
    if token is None:
        await guards.wait_for_inflight(db, run_id, step)
        cached = await cache.get(db, key)
        if cached:
            return await _from_cache(db, cached, run_id, step, prompt.version, model, metrics)
        return _unavailable(run_id, step, "another generation is in flight", metrics)

    try:
        try:
            await guards.check_call_cap(db, run_id)
            await guards.check_allowance(db, run_id)
            await guards.check_spend_cap(db)
        except guards.GuardRefusal as refusal:
            await log_call(
                db, run_id=run_id, step=step, prompt_version=prompt.version, model=model,
                input_tokens=0, output_tokens=0, estimated_cost_usd=0.0,
                cache_hit=False, status=refusal.reason,
            )
            return _unavailable(run_id, step, str(refusal), metrics)

        adapter = adapter or AnthropicAdapter()
        narrative, in_tok, out_tok = await _call_with_retries(
            adapter, config, prompt, outbound, sleep
        )

        guard = numeric_guard(narrative, outbound, config.get("windows", ()))
        bad_keys = source_key_guard(narrative, outbound)
        one_sided = views_guard(narrative, outbound)
        step_bad = step_problem(config, narrative, outbound)
        cost = estimate_cost_usd(model, in_tok, out_tok)

        # Hard tier: a fabricated figure in the headline or a table row, or a
        # row citing a source key that does not exist. Drop the narrative.
        if guard.hard or bad_keys or one_sided or step_bad:
            reason = bad_keys or one_sided or step_bad or (
                "model produced number(s) absent from the computed results in "
                f"headline/table rows: {', '.join(guard.hard[:8])}"
            )
            # The call still cost money, so it is logged and counted. Every
            # unmatched number is recorded, both tiers, for prompt tuning.
            await log_call(
                db, run_id=run_id, step=step, prompt_version=prompt.version, model=model,
                input_tokens=in_tok, output_tokens=out_tok, estimated_cost_usd=cost,
                cache_hit=False,
                status=("step_guard_rejected" if step_bad and not (guard.hard or bad_keys or one_sided) else
                        "views_guard_rejected" if one_sided and not (guard.hard or bad_keys) else "numeric_guard_rejected"),
                unmatched_numbers=guard.all,
            )
            logger.warning("narrative rejected for run %s step %s: %s", run_id, step, reason)
            return NarrativeResponse(
                run_id=run_id, step=step, narrative_status="unavailable",
                reason=reason, metrics=metrics, unmatched_numbers=guard.all,
            )

        # Soft tier: prose carries a number the engine did not produce. Ship it,
        # say so, and report the numbers.
        status = "flagged" if guard.soft else "ok"
        if guard.soft:
            logger.info(
                "narrative flagged for run %s step %s: unmatched prose number(s) %s",
                run_id, step, ", ".join(guard.soft),
            )

        restored = redaction.restore_deep(narrative.model_dump(), mapping)
        final = _define_acv(Narrative.model_validate(restored))

        # Our lock expired mid-call and another worker took over: its result is
        # the newer one. Discard ours (still logged, it was billed) and serve theirs.
        if not await guards.holds(db, run_id, step, token):
            await log_call(
                db, run_id=run_id, step=step, prompt_version=prompt.version, model=model,
                input_tokens=in_tok, output_tokens=out_tok, estimated_cost_usd=cost,
                cache_hit=False, status="lock_lost", unmatched_numbers=guard.soft,
            )
            logger.warning("lock lost for run %s step %s; result discarded", run_id, step)
            newer = await cache.get(db, key)
            if newer:
                return await _from_cache(db, newer, run_id, step, prompt.version, model, metrics)
            return _unavailable(run_id, step, "lock expired before the result was stored", metrics)

        await cache.put(
            db, key, run_id, step, prompt.version, model, final.model_dump(),
            narrative_status=status, unmatched_numbers=guard.soft,
        )
        await log_call(
            db, run_id=run_id, step=step, prompt_version=prompt.version, model=model,
            input_tokens=in_tok, output_tokens=out_tok, estimated_cost_usd=cost,
            cache_hit=False, status=status, unmatched_numbers=guard.soft,
        )
        stored = await cache.get(db, key)
        return NarrativeResponse(
            run_id=run_id, step=step, narrative_status=status, narrative=final,
            cache_hit=False, prompt_version=prompt.version, model=model,
            metrics=metrics, unmatched_numbers=guard.soft,
            generated_at=(stored or {}).get("created_at"),
        )

    except GatewayError as exc:
        await log_call(
            db, run_id=run_id, step=step, prompt_version=prompt.version, model=model,
            input_tokens=0, output_tokens=0, estimated_cost_usd=0.0,
            cache_hit=False, status=exc.reason, http_status=exc.status, error_type=exc.error_type,
        )
        return _unavailable(run_id, step, str(exc), metrics)
    except Exception as exc:  # never let the gateway block the dashboard
        # Error type only: the message and traceback can quote results text.
        logger.error("unexpected gateway failure for run %s step %s: error=%s", run_id, step, type(exc).__name__)
        return _unavailable(run_id, step, f"unexpected error: {type(exc).__name__}", metrics)
    finally:
        await guards.release(db, run_id, step, token)


def _define_acv(n: Narrative) -> Narrative:
    """Spell out "ACV (average contract value)" at its first use in reading order."""
    fields = [n.headline, n.what_this_means] + [r.label for r in n.table_rows] \
        + list(n.worth_flagging) + list(n.next_actions)
    out = formatting.define_acv_on_first_use(fields)
    it = iter(out)
    return n.model_copy(update={
        "headline": next(it),
        "what_this_means": next(it),
        "table_rows": [r.model_copy(update={"label": next(it)}) for r in n.table_rows],
        "worth_flagging": [next(it) for _ in n.worth_flagging],
        "next_actions": [next(it) for _ in n.next_actions],
    })


async def _call_with_retries(adapter, config, prompt, outbound, sleep):
    """Provider call with two policies layered.

    Network/5xx: up to MAX_PROVIDER_RETRIES with exponential backoff.
    Malformed body: one reask (MAX_PARSE_RETRIES), then fail. A reask is a fresh
    provider call and is billed, which is why it is capped at one.
    """
    schema = narrative_output_schema(decision=config.get("max_words") is not None, verdicts=config.get("verdicts") or ())
    system = prompt.text
    # Hand the model the exact source keys it may cite, in the exact form the
    # guard accepts. Derived from the payload, so the two can never drift; sent
    # alongside the data rather than baked into the prompt, since it is
    # per-payload. The cache key is still computed from `outbound` alone.
    message = dict(outbound)
    message["valid_source_keys"] = valid_source_keys(outbound)
    user_payload = cache.canonical_json(message)
    parse_attempts = 0
    network_attempts = 0

    while True:
        try:
            try:
                text, in_tok, out_tok = await _to_thread(
                    adapter.complete,
                    model=config["model"],
                    system=system,
                    user_payload=user_payload,
                    max_tokens=config["max_tokens"],
                    temperature=config.get("temperature"),
                    json_schema=schema,
                )
            except (RetryableProviderError, GatewayError):
                raise
            except Exception as raw:
                # An adapter that does not classify its own errors must still get
                # the gateway's retry policy - retryability is decided here, not
                # left to each provider implementation.
                raise _classify_provider_error(raw)
        except RetryableProviderError as exc:
            network_attempts += 1
            if network_attempts > MAX_PROVIDER_RETRIES:
                raise _unreachable(exc)
            await sleep(_backoff_seconds(exc, network_attempts))
            continue

        try:
            return parse_strict(text), in_tok, out_tok
        except GatewayError:
            parse_attempts += 1
            if parse_attempts > MAX_PARSE_RETRIES:
                raise
            continue


async def _to_thread(fn, **kwargs):
    """Run the blocking SDK call off the event loop."""
    import asyncio
    return await asyncio.to_thread(lambda: fn(**kwargs))


async def _from_cache(
    db, cached: dict, run_id: str, step: str, prompt_version: str,
    model: str, metrics: dict,
) -> NarrativeResponse:
    """Serve a stored narrative with the status it was stored under.

    A flagged narrative must come back flagged - otherwise the first viewer sees
    the warning and everyone after them sees a clean "ok" for the same text.
    """
    status = cached.get("narrative_status", "ok")
    unmatched = list(cached.get("unmatched_numbers", []))
    generated_at = cached.get("created_at")
    await log_call(
        db, run_id=run_id, step=step, prompt_version=prompt_version, model=model,
        input_tokens=0, output_tokens=0, estimated_cost_usd=0.0,
        cache_hit=True, status=status, unmatched_numbers=unmatched,
    )
    return NarrativeResponse(
        run_id=run_id, step=step, narrative_status=status,
        narrative=Narrative.model_validate(cached["narrative"]), cache_hit=True,
        prompt_version=prompt_version, model=model, metrics=metrics,
        unmatched_numbers=unmatched, generated_at=generated_at,
    )


def _unavailable(run_id: str, step: str, reason: str, metrics: dict) -> NarrativeResponse:
    return NarrativeResponse(
        run_id=run_id, step=step, narrative_status="unavailable",
        reason=reason, metrics=metrics,
    )


async def read_cached_narrative(db, run_id: str, step: str) -> NarrativeResponse:
    """Return an already-generated narrative, or nothing. Never calls a provider.

    This is the path a dashboard load takes. There is deliberately no branch
    here that reaches the adapter — opening an audit cannot spend money, no
    matter what state the cache is in. Generating is a separate, explicit act.

    A run whose results have changed produces a different cache key, so the old
    narrative simply is not found and the reader is offered a fresh generation
    rather than being shown a narrative about superseded numbers.
    """
    config = STEP_CONFIG.get(step)
    if not config:
        return NarrativeResponse(
            run_id=run_id, step=step, narrative_status="not_generated",
            reason=f"unknown step {step!r}", metrics={},
        )

    computed, problems = await load_checked_results(db, run_id, step)
    metrics = computed["metrics"]
    if problems:
        return contract_failed(run_id, step, problems, metrics)

    try:
        prompt = await prompt_store.load(db, config["prompt"])
    except prompt_store.PromptMissing:
        # No prompt means nothing could have been generated under it.
        return NarrativeResponse(
            run_id=run_id, step=step, narrative_status="not_generated", metrics=metrics,
        )

    try:
        model = run_model()
    except GatewayError:
        return NarrativeResponse(
            run_id=run_id, step=step, narrative_status="not_generated", metrics=metrics,
        )
    mapping = await redaction.get_or_create_map(db, run_id, computed, save=False)
    try:
        outbound = build_outbound(computed, mapping)
    except GatewayError:
        return NarrativeResponse(
            run_id=run_id, step=step, narrative_status="not_generated", metrics=metrics,
        )
    key, cached = await cached_for(db, run_id, step, prompt_store.cache_tag(prompt), model, computed, mapping, outbound)
    if not cached:
        # Nothing matches the current key. If something was written for an earlier
        # version of this run, say so - the reader may remember it - and say why.
        reason = await supersession(db, run_id, step, outbound, model)
        return NarrativeResponse(
            run_id=run_id, step=step, narrative_status="not_generated",
            metrics=metrics, superseded=reason is not None, superseded_reason=reason,
        )

    # A read is not a call: it is not written to llm_calls, so the usage figures
    # keep counting generation attempts rather than page views.
    return NarrativeResponse(
        run_id=run_id, step=step,
        narrative_status=cached.get("narrative_status", "ok"),
        narrative=Narrative.model_validate(cached["narrative"]),
        cache_hit=True, prompt_version=prompt.version, model=cached.get("model") or model,
        metrics=metrics,
        unmatched_numbers=list(cached.get("unmatched_numbers", [])),
        generated_at=cached.get("created_at"),
    )


async def supersession(db, run_id: str, step: str, outbound: Any, model: str) -> Optional[str]:
    """Why an earlier narrative for this run+step is no longer served, or None if none exists.

    The stored key is recomputed under the settings the narrative was written with,
    against the current numbers. If it still matches, the numbers did not move and the
    narrative is unreachable only because the prompt (a newer version was uploaded) or the model changed.
    Only if no stored narrative matches under its own settings did the data change.
    """
    records = await cache.records_for(db, run_id, step)
    if not records:
        return None
    reason = "data_changed"
    for rec in sorted(records, key=lambda r: r.get("created_at") or ""):  # newest match wins
        rec_model = rec.get("model") or model
        tag = prompt_store.tag_for(rec.get("prompt_version") or "")
        if cache.cache_key(run_id, step, tag, rec_model, outbound) == rec.get("key"):
            reason = "model_changed" if rec_model != model else "prompt_release_changed"
    return reason


async def narratives_for_run(db, run_id: str) -> list:
    """Every generated narrative for this run that is currently served, in step order.

    Read-only - it reuses `read_cached_narrative`, so it can never call a provider. A
    narrative is served only while its numbers still match, so what comes back describes
    the run as it stands now.
    """
    found = []
    for step, config in STEP_CONFIG.items():
        if not config.get("enabled"):
            continue
        result = await read_cached_narrative(db, run_id, step)
        if result.narrative is not None and result.narrative_status in ("ok", "flagged"):
            found.append(result)
    return found


async def estimate_narratives(db, run_id: str) -> dict:
    """What "Write all narratives" would run: for each enabled step, whether a narrative is already stored (no call) and whether it
    can be written now. No amount: cost is not shown to testers (usage-and-allowance.md section 9). It reads the same payload a
    generation builds, from the stored results; it makes no call and writes nothing (the token map is built in memory)."""
    steps = []
    model = None
    try:
        model = run_model()
    except GatewayError:
        pass
    for step, config in STEP_CONFIG.items():
        if not config.get("enabled"):
            continue
        entry = {"step": step, "label": disclosure.STEP_LABELS.get(step, step), "cached": False, "available": True}
        try:
            computed, problems = await load_checked_results(db, run_id, step)
            prompt = await prompt_store.load(db, config["prompt"])
            if problems or model is None:
                raise GatewayError("unavailable")
            outbound = build_outbound(computed, await redaction.get_or_create_map(db, run_id, computed, save=False))
            key = cache.cache_key(run_id, step, prompt_store.cache_tag(prompt), model, outbound)
            if await cache.get(db, key):
                entry["cached"] = True
        except GatewayError as exc:
            if exc.reason in ("run_not_found", "not_computed"):
                raise
            entry.update(available=False)
        except prompt_store.PromptMissing:             # nothing to check and no call: the generation says why
            entry.update(available=False)
        steps.append(entry)
    return {"model": model, "steps": steps}


def disclosure_from(narratives: list) -> Optional[dict]:
    """The provenance block for narratives already loaded."""
    return disclosure.build_disclosure([
        {"step": n.step, "model": n.model, "generated_at": n.generated_at} for n in narratives
    ])


async def disclosure_for_run(db, run_id: str) -> Optional[dict]:
    """The provenance block for every narrative that exists for this run."""
    return disclosure_from(await narratives_for_run(db, run_id))


# ---------------------------------------------------------------------------
# Structure reading (docs/specs/llm-structure-reading.md; CLAUDE.md rules 16-18)
# ---------------------------------------------------------------------------
# A constant, separate from NARRATIVE_MODEL: the structure path is pinned to one model. Changing it
# moves every structure cache key. Temperature stays at the model default and is never sent.
STRUCTURE_MODEL = "claude-sonnet-5-5"
# The page reader's model (docs/design/page-image.md section 2, CLAUDE.md rule 31): deck pages go to it as printed, under the API
# organisation's zero-data-retention arrangement, so only the Sonnet and Opus families may read them. PAGE_READER_MODEL overrides the
# default (STRUCTURE_MODEL); a name outside the allow-list blocks every page read, at startup (server.py) and before each read.
PAGE_READER_MODELS = re.compile(r"claude-(?:sonnet|opus)(?:-\d+)+(?:-\d{8})?")
PAGE_READER_BLOCKED = "AI read: blocked – model not permitted"
# The sheet reader (docs/design/read-check-review.md sections 3, 4, 9; CLAUDE.md rule 16 as amended for PR 2): one call per spreadsheet, every
# non-empty cell of every recognised sheet, masked, the prompt `sheet_reading` of the store (the repository holds a test stub only). The
# model is one exact id on an allow-list (SHEET_READER_MODELS; George, 2026-10-30), never a moving alias, so a stored reading names the model that made it
# (section 9). Only the Sonnet and Opus families may read a file in full (rule 31's allow-list, for the same zero-data-retention reason).
SHEET_READING_PROMPT = "sheet_reading"
REVIEWER_PROMPT = "reviewer"          # PR 3: the reviewer call (run_reviewer), the prompt of the store; the repository holds a test stub only
SHEET_READER_ENV = "SHEET_READER_MODEL"
SHEET_READER_MODELS = frozenset({"claude-sonnet-5-5", "claude-opus-5-5", "claude-sonnet-5", "claude-opus-5"})
SHEET_READER_BLOCKED = "AI read: blocked – the sheet reader model is not on the allow-list (SHEET_READER_MODEL)"
SHEET_READING_INPUT_CAP = 40_000        # tokens of the masked cells, by the provider's token counter: above it the file is refused, nothing is cut
SHEET_READING_MAX_TOKENS = 16_000       # the file map's reply
SHEET_READING_TIMEOUT_SECONDS = 300.0   # a long map takes minutes to write
SHEET_READING_TOO_LARGE = ("This file is too large to read in full (the limit is {limit} tokens of cells). "
                           "Remove the sheets that are not needed or split the file, then upload it again.")
SHEET_READING_CUT = ("The reading of this file was cut off because the file has too many rows to map in one read. "
                     "Remove the sheets that are not needed or split the file, then upload it again.")
SHEET_READING_LOCK_ROUNDS = 5
# A reply that FileMap does not validate, after the one retry (George, 2026-10-30: no strict output schema for the file map; the schema goes
# as text and the code validates). The strip's and the log's reason; the two raw replies are kept on the reading record (readings.put_failed).
SHEET_PROMPT_MISSING_TEXT = "the sheet_reading prompt is not in the prompt store"
SHEET_READING_NOT_STORED = "the stored reading is not there to be read again"
SHEET_READING_NOT_MATCHED = "reading did not match the map schema"
# The spreadsheet mapping path of PR 1 and before (file_type, file_recognition, sheet_structure and the column mapping) stays behind a flag
# for PR 2 only (read-check-review.md section 13): READER_V1=off turns its model calls off, anything else leaves them on. Its three calls
# are unchanged and still do not learn names.
OLD_SHEET_CALLS = frozenset({FILE_TYPE, FILE_RECOGNITION, SHEET_STRUCTURE, "column_mapping"})
STRUCTURE_PROMPT = "structure_reading"
PAGE_CLAIMS_PROMPT = "deck_reading"       # the page reader's prompt in the store (docs/specs/prompt-store.md); the repo holds a stub
FILE_TYPE_PROMPT = "file_type"
SHEET_STRUCTURE_PROMPT = "sheet_structure"
STRUCTURE_STEP = guards.STRUCTURE_STEP
PIPELINES = ("rules", "ai")                 # the DECK_PIPELINE switch
DEFAULT_PIPELINE = "ai"                     # since 2026-10-22 (docs/design/ai-reads-rules-check.md, built): the model reads every page


def page_reader_model() -> str:
    """The model the page reader is configured to use: PAGE_READER_MODEL, else STRUCTURE_MODEL."""
    return os.environ.get("PAGE_READER_MODEL", "").strip() or STRUCTURE_MODEL


def page_reader_problem() -> Optional[str]:
    """None when the configured page-reader model is on the allow-list (PAGE_READER_MODELS: the Sonnet and Opus families), else the
    panel line PAGE_READER_BLOCKED, after logging `page reader model <name> not permitted` as an error. Run at startup and before
    each page read, so a model change that slips past either is stopped by the other."""
    name = page_reader_model()
    if PAGE_READER_MODELS.fullmatch(name):
        return None
    logger.error("page reader model %s not permitted", name[:80])
    return PAGE_READER_BLOCKED


def reader_v1_enabled() -> bool:
    """READER_V1: "off" turns the old spreadsheet mapping calls off; any other value, or none, leaves them on (the default)."""
    return os.environ.get("READER_V1", "").strip().lower() != "off"


def sheet_reader_model() -> str:
    """The model the sheet reader is configured to use: SHEET_READER_MODEL, stripped, else STRUCTURE_MODEL."""
    return os.environ.get(SHEET_READER_ENV, "").strip() or STRUCTURE_MODEL


def sheet_reader_problem() -> Optional[str]:
    """None when the sheet reader's model is an exact id of SHEET_READER_MODELS (Sonnet and Opus) the price table knows, else the panel line
    SHEET_READER_BLOCKED, after logging `sheet reader model <name> not permitted` as an error. A moving alias, a name without a date and a
    model outside the two families are all refused, before anything is masked, drawn or sent."""
    name = sheet_reader_model()
    if _sheet_reader_model_ok(name):
        return None
    logger.error("sheet reader model %s not permitted", name[:80] or "(none)")
    return SHEET_READER_BLOCKED


def _sheet_reader_model_ok(name: str) -> bool:
    return name in SHEET_READER_MODELS and name in MODEL_PRICING_USD


async def sheet_reader_startup_problem(db) -> Optional[str]:
    """None when the sheet reader can run, else one line naming what is missing: the `sheet_reading` prompt in the store, the model, or both.
    For the startup log only; the strip keeps saying "not read" and every read is still refused where it is made."""
    missing = []
    try:
        await prompt_store.load(db, SHEET_READING_PROMPT)
    except prompt_store.PromptMissing:
        missing.append(f"prompt {SHEET_READING_PROMPT} is not in the store")
    name = sheet_reader_model()
    if not _sheet_reader_model_ok(name):
        missing.append(f"model {name[:80] or '(none)'} is not on the allow-list ({SHEET_READER_ENV})")
    return "; ".join(missing) or None


async def reviewer_startup_problem(db) -> Optional[str]:
    """None when the reviewer can run, else one line naming what is missing: the `reviewer` prompt in the store. (The model is the sheet
    reader's and is reported by sheet_reader_startup_problem.) Run audit asks it too, and leaves the reviewer stage out when it is set."""
    try:
        await prompt_store.load(db, REVIEWER_PROMPT)
    except prompt_store.PromptMissing:
        return f"prompt {REVIEWER_PROMPT} is not in the store"
    return None


def deck_pipeline() -> str:
    """The DECK_PIPELINE switch: "ai" (the default: the model reads the pages, Python checks each claim) or "rules" (the
    former rules read, kept for scripts/compare_pipelines.py). Anything else is the default, so a typo changes nothing on
    screen. The gateway reads it itself and refuses a page_claims call under "rules" (L1 of the review of PR #159,
    2026-10-22), so the boundary holds whatever the caller."""
    value = os.environ.get("DECK_PIPELINE", "").strip().lower()
    return value if value in PIPELINES else DEFAULT_PIPELINE


STRUCTURE_MAX_TOKENS = 4000
STRUCTURE_INPUT_CAP = 4000          # tokens of structure text plus item list, by the provider's token counter
STRUCTURE_CELL_MAX = 200            # a longer cell is prose
SHEET_INPUT_CAP = 12_000            # a sheet skeleton: tokens of its text, by the provider's token counter (chat-upload.md 26.4)
SHEET_MAX_TOKENS = 12_000           # ... and of its reply (a role, parent and meaning for up to 400 lines)
RECOGNITION_INPUT_CAP = 12_000      # a file recognition text: tokens, by the provider's token counter (revenue-file-recognition.md 5.5)
PAGE_INPUT_CAP = 12_000             # a page batch: tokens of its text (up to 5 pages), by the provider's token counter
# A page batch's reply. The design note (section 4) estimated 350 tokens per page; the live run of 2026-10-22 measured 90-150 tokens
# per claim and a 5-page batch of two 5-year tables cut at 4,000 in every pass (docs/test-runs/pages_2026-10-22_compare.md). A cut
# reply is "truncated" and the batch is split (structures.pages.read_pages).
PAGE_MAX_TOKENS = 8000
RECOGNITION_MAX_TOKENS = 1_000      # ... and of its reply
STRUCTURES_COLLECTION = cache.STRUCTURES_COLLECTION
# The tokens (input plus max_tokens) of the page reads in flight per audit, in this process; the token cap counts them (read_structure).
_inflight_tokens: Dict[str, int] = {}
PAGE_LOCK_ROUNDS = 60               # the lock waits of a page read: reads queue for it one after another
INFLIGHT_POLL_SECONDS = 0.05
NOT_READ = "Not read by AI"
# George, 2026-10-23 (review of PR 164, M6): the page reader found no deck_reading prompt in the store; shown on the deck, and Run audit reads it again.
PROMPT_MISSING_TEXT = "AI reading not run – deck_reading prompt missing in prompt store"
TOO_LARGE = "Too large for AI reading"
# The reason a cap refusal's "structure not read" line gives, per guard code (llm_calls keeps the code).
CAP_REASONS = {"daily_spend_cap_exceeded": "spend_cap", "structure_token_cap_reached": "token_cap",
               "reviewer_token_cap_reached": "reviewer_token_cap", "monthly_allowance_reached": "allowance"}
# The calls outside the daily spend cap: a column mapping (chat-upload.md 4.2) and a page read (ai-reads-rules-check.md). Both still
# count in the tester's monthly allowance and in the day's spend every other call is checked against.
SPEND_CAP_EXEMPT = frozenset({"column_mapping", PAGE_CLAIMS})
# A file name in the text means it was built from the wrong thing: refused.
_FILE_NAME = re.compile(r"(?i)\b[\w\-. ]{1,80}\.(?:pptx?|pdf|docx?|xlsx?|xlsm|xls|csv)\b")
_CONTROL = re.compile(r"[\x00-\x08\x0b-\x1f\x7f]")


async def load_structure_context(db, audit_id: str) -> dict:
    """The audit's consent and the names the structure path must protect, and nothing else.

    `company_name` is the target, never rewritten by redaction. Uploaded rows, parsed deck text and
    candidates are not read here: the text to read is handed in by the caller.
    """
    doc = await db[RESULTS_COLLECTION].find_one(
        {"id": audit_id},
        {"_id": 0, "id": 1, "company_name": 1,
         "structure_reading_consent": 1},
    )
    if not doc:
        raise GatewayError("run_not_found", f"no run {audit_id}")
    return doc


def structure_key(text: str, structure_type: str, prompt_tag: str, model: str, images: Optional[List[bytes]] = None) -> str:
    """sha256 of the text (with its item list), its type, the prompt cache tag, the model and the hash of the
    output schema its type is sent (structure-labelling.md section 3): a reading stored under another schema is
    never served. A page read adds the hash of its images, so a page read without its image is not served for one with it."""
    tag = f"{prompt_tag}:{schema_hash(structure_type)}"
    if images:
        tag += ":img:" + content_hash("".join(hashlib.sha256(i).hexdigest() for i in images))
    return cache.cache_key(STRUCTURE_STEP, structure_type, tag, model, text)


def schema_hash(structure_type: str) -> str:
    """sha256 of the output schema a structure of this type is sent: the labelling schema for a deck structure,
    its own for a column mapping."""
    schema = schemas.file_map_schema() if structure_type == SHEET_READING else schemas.output_schema(structure_type)
    return content_hash(cache.canonical_json(schema))


def content_hash(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def structure_text_problem(text: Any, structure_type: str, context: dict, mapping: Dict[str, str]) -> Optional[str]:
    """Why a text may not reach the provider, or None (CLAUDE.md rule 16, spec sections 1 and 3).

    Only extracted text with cell positions passes: one `r<row>c<col>: <text>` line per cell, a slide title
    a KPI panel takes as a label marked `r<row>c<col> title: <text>` (on the column-mapping path, sample and
    profile lines; for a deck structure, below "items:", Python's item lines, each raw text a figure inside
    its cell and never in a title cell, and a roadmap's date and text lines). Raw bytes,
    prose, a file name and a cell over 200 characters are refused. Redaction is run again and the text must come back unchanged. On the
    column-mapping path at most 3 header rows and 3 samples per column pass, and no text cell value.
    """
    if not isinstance(text, str):
        return "not_text"
    if not text.strip():
        return "empty"
    if _CONTROL.search(text):
        return "raw_bytes"
    if structure_type not in (PAGE_CLAIMS, SHEET_READING) and _FILE_NAME.search(text):          # a page goes as printed; a cell may name a file
        return "file_name"
    company = context.get("company_name")
    if structure_type == PAGE_CLAIMS:
        # Only while DECK_PIPELINE is "ai" (the default). The lines of pages whose text holds a digit, as printed, with no redaction (page-image.md section 2): at most 5 pages, every page with a digit, no
        # line over 200 characters (as for a structure cell; George, 2026-10-22, decision 1b on the review of PR #159).
        if deck_pipeline() != "ai":
            return "pipeline_rules"
        problem = structure_redact.page_text_problem(text)
        if problem:
            return problem
        pages = structure_redact.parse_page_text(text)
        if any(len(c["text"]) > STRUCTURE_CELL_MAX for cells in pages.values() for c in cells):
            return "cell_too_long"
        return None
    if structure_type == SHEET_READING:
        # Every non-empty cell of every recognised sheet (read-check-review.md section 8): one `A1: value` line each, masked by the one
        # module, so running it again must change nothing; nothing personal may stand in it; nothing is cut, the token cap refuses.
        problem = structure_redact.reading_text_problem(text)
        if problem:
            return problem
        again, _ = structure_redact.mask_reading(text, company, mapping)
        if again != text:
            return "redaction_changed"
        return "personal_data" if structure_redact.personal_items(text) else None
    if structure_type == SHEET_STRUCTURE:
        # Every text cell of one sheet, never a figure, at most 400 rows with text, the withhold rule and the redaction run again.
        problem = structure_redact.sheet_text_problem(text)
        if problem:
            return problem
        cells = structure_redact.parse_sheet_text(text)["cells"]
        if any(len(c["text"]) > STRUCTURE_CELL_MAX for c in cells):
            return "cell_too_long"
        redacted, _ = structure_redact.redact_structure(cells, company, mapping, structure_redact.file_type_withheld(context))
        return "redaction_changed" if redacted != cells else None
    if structure_type == FILE_RECOGNITION:
        # The file-type text with the row labels of a metric-labelled sheet, "Row n" for every other sheet, redaction run again (5.4).
        problem = structure_redact.recognition_text_problem(text)
        if problem:
            return problem
        withheld = structure_redact.file_type_withheld(context)
        for sheet in structure_redact.parse_recognition_text(text):
            cells = structure_redact.recognition_cells(sheet)
            if any(len(c["text"]) > STRUCTURE_CELL_MAX for c in cells):
                return "cell_too_long"
            redacted, _ = structure_redact.redact_structure(cells, company, mapping, withheld)
            if redacted != cells:
                return "redaction_changed"
        return None
    if structure_type == FILE_TYPE:
        problem = structure_redact.file_type_text_problem(text)
        if problem:
            return problem
        withheld = structure_redact.file_type_withheld(context)
        for sheet in structure_redact.parse_file_type_text(text):
            cells = structure_redact.file_type_cells(sheet)
            if any(len(c["text"]) > STRUCTURE_CELL_MAX for c in cells):
                return "cell_too_long"
            redacted, _ = structure_redact.redact_structure(cells, company, mapping, withheld)
            if redacted != cells:
                return "redaction_changed"
        return None
    if structure_type == "column_mapping":
        problem = structure_redact.column_text_problem(text)
        if problem:
            return problem
        cells = structure_redact.parse_column_text(text)["headers"]
    else:
        cell_text, listed = structure_redact.split_items(text)
        cells = structure_redact.parse_structure_text(cell_text)
        if not cells:
            return "not_cells"
        if listed is not None and not structure_redact.items_in_format(listed, cells, structure_type == "roadmap"):
            return "bad_item_line"
    if any(len(c["text"]) > STRUCTURE_CELL_MAX for c in cells):
        return "cell_too_long"
    redacted, _ = structure_redact.redact_structure(cells, company, mapping, deck=True)
    if redacted != cells:
        return "redaction_changed"
    return None


def parse_file_map_reply(reply: str, text: str):
    """Validate a sheet reading's reply (read-check-review.md section 4), or raise GatewayError("parse_failed"): the contract's FileMap
    (closed words, cell patterns, no extra keys) and nothing else here: every cell a reading cites is opened by app/checks.py, which
    decides, so a citation outside the sheet is a rejection with its reason and not a parse failure. A sheet named that was not sent is
    one failure."""
    from schemas.metrics import FileMap
    try:
        parsed = FileMap.model_validate(json.loads(_json_object(reply)))
    except Exception as exc:
        failed = GatewayError("parse_failed", f"reply did not match the schema: {type(exc).__name__}", check=_schema_check(exc),
                              fields=_schema_fields(exc))
        failed.errors = _validation_errors(exc)
        raise failed
    sent = {s["name"] for s in (structure_redact.parse_reading_text(text) or [])}
    if parsed.kind != "sheet" or any(s.sheet not in sent for s in parsed.sheets):
        failed = GatewayError("parse_failed", "reply names a sheet that was not sent", check="other")
        failed.errors = [{"loc": "sheets", "type": "unknown_sheet", "msg": "a sheet named in the reply was not in the request, or kind is not sheet"}]
        raise failed
    return parsed


def _json_object(reply: str) -> str:
    """The JSON object in a reply: from its first "{" to its last "}", so a code fence or a line of prose before or after it is dropped.
    A reply with no object is returned stripped, for json.loads to refuse."""
    reply = reply or ""
    start, end = reply.find("{"), reply.rfind("}")
    return reply[start:end + 1] if 0 <= start < end else reply.strip()


def _validation_errors(exc: Exception) -> List[dict]:
    """The first FILE_MAP_ERRORS_SENT errors of a failed reply, for the retry's fix request: location, type and message, never the input.
    A reply that is not JSON gives one error with the decoder's position."""
    if hasattr(exc, "errors"):
        errors = exc.errors(include_url=False, include_context=False, include_input=False)
        return [{"loc": ".".join(str(part) for part in e.get("loc", ())), "type": e.get("type", ""), "msg": e.get("msg", "")}
                for e in errors[:schemas.FILE_MAP_ERRORS_SENT]]
    return [{"loc": "", "type": "json_invalid", "msg": f"the reply is not one JSON object: {type(exc).__name__} {exc}"[:200]}]


LOGGED_ERRORS = 3          # the validation errors a "structure not read" line lists
LOGGED_ERROR_CHARS = 120


def _error_list(exc: Exception) -> str:
    """The first LOGGED_ERRORS validation errors of a failed sheet reading for its log line: `path: message`, joined with "; ". The
    errors are built without the input (_validation_errors); a message is capped. "-" when there are none."""
    errors = getattr(exc, "errors", None) or []
    return "; ".join(f"{e.get('loc') or '-'}: {str(e.get('msg', ''))[:LOGGED_ERROR_CHARS]}" for e in errors[:LOGGED_ERRORS]) or "-"


def _cited_cells(text: str, structure_type: str) -> set:
    """The cell ids a reply may cite: every cell of a deck structure, the header cells of a sheet, every cell of a page batch by
    its page id."""
    if structure_type == PAGE_CLAIMS:
        return {structure_redact.page_cell_id(page, c) for page, cells in (structure_redact.parse_page_text(text) or {}).items()
                for c in cells}
    if structure_type == "column_mapping":
        cells = (structure_redact.parse_column_text(text) or {}).get("headers") or []
    else:
        cells = structure_redact.parse_structure_text(structure_redact.split_items(text)[0]) or []
    return {structure_redact.cell_id(c) for c in cells}


# The check a structure reply failed, named last on its "structure not read" line (llm-structure-reading.md section 9,
# issue #64): a closed word, never the reply, the check's message or cell text.
PARSE_CHECKS = ("schema", "metric_list", "item_count", "other")
# The field names a "structure not read" line may name after fields= (a page reply's schema, the file map's): closed words, never a value.
PAGE_FIELDS = frozenset(schemas.PageClaim.model_fields) | {"type", "claims"}


def _map_fields() -> frozenset:
    from schemas import metrics
    models = (metrics.FileMap, metrics.MapSheet, metrics.MapRow, metrics.MapFigure, metrics.MapSource, metrics.MapLastActual,
              metrics.MapEvidence, metrics.MapVariance, metrics.MapVarianceColumns)
    return frozenset(f for m in models for f in m.model_fields)


MAP_FIELDS = _map_fields()


def _schema_check(exc: Exception) -> str:
    """"metric_list" when the schema fails on a metric outside the list and nothing else, else "schema". Read from
    the error locations and types only, never from the input they quote."""
    errors = exc.errors() if hasattr(exc, "errors") else []
    if errors and all(e["type"] == "literal_error" and e["loc"][-1:] in (("metric",), ("meaning",), ("role",), ("basis",)) for e in errors):
        return "metric_list"
    return "schema"


def parse_structure_reply(reply: str, structure_type: str, text: str):
    """The validated reply for the type Python sent, or raise GatewayError("parse_failed"): a labelling reply for
    a deck structure (parse_labelling_reply), the column-mapping reply for a column mapping, the file-type word for a file."""
    if structure_type == SHEET_READING:
        return parse_file_map_reply(reply, text)
    if structure_type == SHEET_STRUCTURE:
        return parse_sheet_reply(reply, text)
    if structure_type == PAGE_CLAIMS:
        return parse_page_reply(reply, text)
    if structure_type == FILE_RECOGNITION:
        try:
            return FileRecognitionReply.model_validate(json.loads((reply or "").strip()))
        except Exception as exc:
            raise GatewayError("parse_failed", f"reply did not match the schema: {type(exc).__name__}",
                               check=_schema_check(exc))
    if structure_type == FILE_TYPE:
        try:
            return FileTypeReply.model_validate(json.loads((reply or "").strip()))
        except Exception as exc:
            raise GatewayError("parse_failed", f"reply did not match the schema: {type(exc).__name__}",
                               check=_schema_check(exc))
    if structure_type != "column_mapping":
        return parse_labelling_reply(reply, structure_type, text)
    try:
        data = json.loads((reply or "").strip())
        parsed = StructureReply.model_validate(data)
    except Exception as exc:
        raise GatewayError("parse_failed", f"reply did not match the schema: {type(exc).__name__}",
                           check=_schema_check(exc))
    if parsed.type != "column_mapping":
        raise GatewayError("parse_failed", "type changed between a deck structure and a column mapping", check="other")
    if any(item.metric not in MAPPING_FIELDS for item in parsed.items):
        raise GatewayError("parse_failed", "a metric that does not belong to this kind of structure",
                           check="metric_list")
    known = _cited_cells(text, structure_type)
    for item in parsed.items:
        if item.value_cell not in known or any(c not in known for c in item.period_cells):
            raise GatewayError("parse_failed", "reply cites a cell that is not in the structure", check="other")
    return parsed


def _schema_fields(exc: Exception) -> List[str]:
    """The schema fields a reply failed on ("period", "label_cell"): the last named location of each validation error, read from
    the error locations only (the schema's own field names, closed words), never from the input they quote. [] for a reply that
    is not JSON or fails outside a named field."""
    found = set()
    for error in (exc.errors() if hasattr(exc, "errors") else []):
        names = [part for part in error.get("loc", ()) if isinstance(part, str)]
        if names:
            found.add(names[-1])
    return sorted(found)


def _page_of(raw) -> str:
    """The page number of a raw claim's value_cell ("p5r4c3" -> "5"), "?" when it has none: a closed digit string, never text."""
    cell = raw.get("value_cell") if isinstance(raw, dict) else None
    match = re.match(r"p([1-9]\d*)r", cell) if isinstance(cell, str) else None
    return match.group(1) if match else "?"


def parse_page_reply(reply: str, text: str) -> PageClaimsReply:
    """Validate a page batch's reply (docs/design/ai-reads-rules-check.md section 2), or raise GatewayError("parse_failed"): the
    top-level object (type word, a list of claims, no extra keys) or a reply that is not JSON rejects the whole reply. A claim that fails the schema (extra
    fields forbidden, every field a closed word, a number or a cell id) is dropped alone and logged as "page n: claim rejected
    (fields)" with the closed schema field names, never a value (George, 2026-10-23: one bad period lost a whole page). A claim that
    cites a cell (value, label, period) the batch did not send is dropped alone too, logged "page n: claim rejected (cell not in batch)". A claim with no value that is not a date claim (metric product with a period) is dropped alone
    too, logged "page n: claim rejected (no value)". Nothing else is checked here: the figure, the unit and the period
    are checked against the page by app/structures/page_check.py. The error names the fields that failed (closed schema names), so
    the "structure not read" line says which field the model gets wrong."""
    try:
        top = schemas.PageReplyTop.model_validate(json.loads((reply or "").strip()))
    except Exception as exc:
        raise GatewayError("parse_failed", f"reply did not match the schema: {type(exc).__name__}", check=_schema_check(exc),
                           fields=_schema_fields(exc))
    claims = []
    for raw in top.claims:
        try:
            claims.append(schemas.PageClaim.model_validate(raw))
        except Exception as exc:
            fields = ", ".join(_schema_fields(exc)) or "claim"          # schema field names only, never the input they quote
            logger.info("page %s: claim rejected (%s)", _page_of(raw), fields)
    known = _cited_cells(text, PAGE_CLAIMS)
    kept = []
    for claim in claims:
        if claim.value is None and not (claim.metric == "product" and claim.period):     # only a date claim (a product milestone) has no value
            logger.info("page %s: claim rejected (no value)", _page_of(claim.model_dump()))
            continue
        if any(c is not None and c not in known for c in (claim.value_cell, claim.label_cell, claim.period_cell)):
            logger.info("page %s: claim rejected (cell not in batch)", _page_of(claim.model_dump()))
        else:
            kept.append(claim)
    return PageClaimsReply(type=top.type, claims=kept)


def parse_sheet_reply(reply: str, text: str) -> SheetStructureReply:
    """Validate a sheet skeleton's reply (chat-upload.md section 26.4), or raise GatewayError("parse_failed"): the schema (extra
    fields forbidden), then every row, parent and column one the skeleton holds, no row twice and no row its own parent."""
    try:
        parsed = SheetStructureReply.model_validate(json.loads((reply or "").strip()))
    except Exception as exc:
        raise GatewayError("parse_failed", f"reply did not match the schema: {type(exc).__name__}", check=_schema_check(exc))
    sent = structure_redact.parse_sheet_text(text) or {"cells": [], "rows": {}, "withheld": {}}
    rows = set(sent["rows"]) | {c["row"] for c in sent["cells"]}
    cols = {c["col"] for c in sent["cells"]} | set(sent["withheld"]) | \
        {c for r in sent["rows"].values() for c in r["num"] + r["blank"]}
    named = [r.row for r in parsed.rows]
    if len(set(named)) != len(named):
        raise GatewayError("parse_failed", "a row is named twice", check="item_count")
    if parsed.header_row not in rows or parsed.label_col not in cols or any(p.col not in cols for p in parsed.periods):
        raise GatewayError("parse_failed", "reply names a row or column that is not in the skeleton", check="other")
    if any(r.row not in rows or (r.parent_row is not None and (r.parent_row not in rows or r.parent_row == r.row))
           for r in parsed.rows):
        raise GatewayError("parse_failed", "reply names a row or parent that is not in the skeleton", check="other")
    return parsed


def parse_labelling_reply(reply: str, structure_type: str, text: str) -> LabellingReply:
    """Validate a deck structure's reply (structure-labelling.md section 3), or raise GatewayError("parse_failed"):
    the schema (extra fields forbidden; the type may be corrected within the deck types, and is only logged),
    then every listed item id labelled exactly once (no unknown, duplicate or missing id), and every pair one
    listed text line and one listed date, a line paired at most once, on a structure sent as a roadmap only."""
    try:
        data = json.loads((reply or "").strip())
        parsed = LabellingReply.model_validate(data)
    except Exception as exc:
        raise GatewayError("parse_failed", f"reply did not match the schema: {type(exc).__name__}",
                           check=_schema_check(exc))
    listed = structure_redact.parse_item_lines(structure_redact.split_items(text)[1] or []) or \
        {"items": [], "dates": [], "lines": []}
    labelled = [label.item for label in parsed.labels]
    if len(set(labelled)) != len(labelled):
        raise GatewayError("parse_failed", "an item is labelled twice", check="item_count")
    if set(labelled) != {item["id"] for item in listed["items"]}:
        raise GatewayError("parse_failed", "the labels name an item that was not listed or leave one out",
                           check="item_count")
    if parsed.pairs and structure_type != "roadmap":
        raise GatewayError("parse_failed", "pairs on a structure not sent as a roadmap", check="other")
    lines, dates = {t["id"] for t in listed["lines"]}, {d["id"] for d in listed["dates"]}
    if any(pair.line not in lines or pair.date not in dates for pair in parsed.pairs):
        raise GatewayError("parse_failed", "a pair that is not one listed line and one listed date", check="other")
    if len({pair.line for pair in parsed.pairs}) != len(parsed.pairs):
        raise GatewayError("parse_failed", "a line paired twice", check="other")
    return parsed


def _rate_limited(exc: RetryableProviderError) -> bool:
    return exc.status == 429 or exc.error_type == "rate_limit_error"


async def _count_tokens(adapter, sleep, on_rate_limit=None, **kwargs) -> int:
    """The provider's token count, with the gateway's network retry policy. `on_rate_limit` is told of every 429."""
    attempts = 0
    while True:
        try:
            try:
                return int(await _to_thread(adapter.count_tokens, **kwargs))
            except (RetryableProviderError, GatewayError):
                raise
            except Exception as raw:
                raise _classify_provider_error(raw)
        except RetryableProviderError as exc:
            if on_rate_limit and _rate_limited(exc):
                on_rate_limit()
            attempts += 1
            if attempts > MAX_PROVIDER_RETRIES:
                raise _unreachable(exc)
            await sleep(_backoff_seconds(exc, attempts))


async def _structure_call(adapter, prompt, user_payload, structure_type, text, sleep, max_tokens=STRUCTURE_MAX_TOKENS,
                          on_rate_limit=None, model=STRUCTURE_MODEL, system=None, images=None):
    """(reply, input tokens, output tokens, billed calls) summed over every billed attempt. Network or 5xx: up to
    MAX_PROVIDER_RETRIES with backoff. A reply that fails validation: one reask, then GatewayError."""
    schema = schemas.output_schema(structure_type)
    parse_attempts = network_attempts = 0
    billed_in = billed_out = 0
    # A page batch marks the fixed prompt for the provider's prompt cache (design note section 4): the same system text is sent
    # for every batch of an audit, so the later batches read it from the cache. Other steps are unchanged.
    cached = {"cache_system": True} if structure_type == PAGE_CLAIMS else {}
    if images:
        cached["images"] = images
    billed_calls = 0
    replies: List[str] = []
    payload = user_payload
    failed_parse: Optional[GatewayError] = None          # the reply that failed validation, while its one retry is under way

    def schema_stands(exc_out):
        """A reading that failed validation stays "schema_mismatch" when its retry fails or is blocked (an outage, a cap): the first
        failure is the one the line names, never "provider_unreachable"."""
        if failed_parse is None or structure_type != SHEET_READING:
            return exc_out
        failed_parse.billed = (billed_in, billed_out)
        failed_parse.billed_calls = billed_calls
        failed_parse.replies = replies
        return failed_parse

    while True:
        try:
            try:
                reply, in_tok, out_tok = await _to_thread(
                    adapter.complete, model=model, system=system if system is not None else prompt.text, user_payload=payload,
                    max_tokens=max_tokens, temperature=0 if structure_type == SHEET_READING else None, json_schema=schema, **cached)
            except (RetryableProviderError, GatewayError):
                raise
            except Exception as raw:
                raise _classify_provider_error(raw)
        except RetryableProviderError as exc:
            if on_rate_limit and _rate_limited(exc):
                on_rate_limit()
            network_attempts += 1
            if network_attempts > MAX_PROVIDER_RETRIES:
                exc_out = _unreachable(exc)
                exc_out.billed = (billed_in, billed_out)
                exc_out.billed_calls = billed_calls
                raise schema_stands(exc_out)
            await sleep(_backoff_seconds(exc, network_attempts))
            continue
        except GatewayError as exc:
            cut = getattr(exc, "tokens", (0, 0))                 # a truncated reply billed its tokens too
            exc.billed = (billed_in + cut[0], billed_out + cut[1])
            exc.billed_calls = billed_calls + (1 if any(cut) else 0)
            raise schema_stands(exc)
        billed_in, billed_out, billed_calls = billed_in + in_tok, billed_out + out_tok, billed_calls + 1
        replies.append(reply)
        try:
            return parse_structure_reply(reply, structure_type, text), billed_in, billed_out, billed_calls
        except GatewayError as exc:
            parse_attempts += 1
            failed_parse = exc
            if parse_attempts > MAX_PARSE_RETRIES:
                exc.billed = (billed_in, billed_out)
                exc.billed_calls = billed_calls
                exc.replies = replies                # the raw replies, as received (masked space), for the reading record
                raise
            if structure_type == SHEET_READING:
                # The one retry is a fix request (George, 2026-10-30): the request, the reply that failed and the first validation errors
                # go as one conversation, and the model returns the full object again. Other steps resend the same request.
                cached["prior"] = [{"role": "user", "content": user_payload}, {"role": "assistant", "content": reply}]
                payload = cache.canonical_json({"type": structure_type, "fix": schemas.FILE_MAP_FIX,
                                                "errors": getattr(exc, "errors", None) or [{"loc": "", "type": exc.check or "other", "msg": ""}]})


def _structure_result(status, structure_type, reason=None, **fields) -> StructureRead:
    return StructureRead(status=status, type=structure_type, reason=reason, **fields)


def _reading(output: dict) -> dict:
    """The fields of a stored or new reply: a deck structure's labels and pairs, a column mapping's items."""
    if output.get("type") == FILE_RECOGNITION:
        return {"recognition": output}
    if "map_version" in output:
        return {"file_map": output}
    if "file_type" in output:
        return {"file_type": output["file_type"]}
    if "header_row" in output:
        return {"sheet": output}
    if "claims" in output:
        return {"claims": output["claims"]}
    if "labels" in output:
        return {"labels": output["labels"], "pairs": output.get("pairs") or []}
    return {"items": output.get("items") or []}


async def read_structure(
    db, audit_id: str, text: str, structure_type: str, *, deck_id: Optional[str] = None,
    page: Optional[int] = None, pages: Optional[List[int]] = None, adapter=None, sleep=None, use_cache: bool = True,
    on_rate_limit=None, images: Optional[List[bytes]] = None, file_hash: Optional[str] = None, recheck: Optional[List[dict]] = None,
    fiscal_year_end: int = 12, reread_of: Optional[Any] = None,
) -> StructureRead:
    """Read one structure or one sheet's headers with the model (CLAUDE.md rules 16-18).

    `text` is the redacted structure text the caller built (one `r<row>c<col>: <text>` line per
    cell, then for a deck structure the item list; for `column_mapping`, header cells, samples and
    profiles). It is checked again here and never stored: only the model's JSON output, the prompt
    version, the model, the content hash, the tokens and the cost are. A deck structure is sent the
    labelling schema, a column mapping its own. Order of operations:

        consent -> boundary and redaction check -> cache (audit, key) -> token count of the text and
        its item list (4,000 cap) -> token count of the whole call -> lock (step "structures") -> spend cap
        (not for a column mapping) -> token cap (400,000 per audit, with the whole call's input) -> provider
        -> schema, type and item id check (one reask) -> store -> log

    A column mapping is exempt from the daily spend cap (chat-upload.md section 4.2, 2026-10-17), and so is a page read
    (George, 2026-10-22, docs/design/ai-reads-rules-check.md): both are logged in llm_calls like any call, so their cost counts
    in the usage, in the tester's monthly allowance and in the day's spend the cap checks for every other call.

    A page read (PAGE_CLAIMS) runs beside the audit's other page reads (George, 2026-10-23, deck page reads: speed): the lock
    is held for the checks and the reservation of its tokens, not for the provider call. Every cap is checked as before, the
    tokens of the reads in flight counted at their worst case; a read the cap would refuse only because of them waits for them,
    so the cap stops the same call a one-by-one read would stop. `on_rate_limit` is called at every 429 the provider answers.

    A page read carries `images`, one PNG of each whole page, in the same request as the text (page-image.md); a page the file
    cannot be drawn for goes as text alone (page-image.md). The configured page-reader model must be on the allow-list (page_reader_problem) before each
    read, else the result is "blocked" and nothing is sent. The image tokens (the call's count with the images minus its count
    without) and their cost are reported apart from the text's, and logged beside them.

    `reread_of` (a stored reading, SHEET_READING only) pins the call to that reading: the prompt version and the model it was made with, and
    no provider call for the first reading (a reading not stored is "not_read"). A re-read is never a new full reading (section 9, PR 206).

    A sheet reading (SHEET_READING, read-check-review.md sections 3, 4 and 9) sends every non-empty cell of every recognised sheet,
    masked here (name learning included), with the prompt `sheet_reading` and the dated model SHEET_READER_MODEL. The reading is stored
    once under the account, the file's hash (`file_hash`), the prompt version and the model, never edited; the same file read again, in any audit of the account,
    gets the stored reading and makes no provider call. `recheck` ([{"item", "reason"}]) asks for a second reading of the items a check
    rejected, with the reasons attached; it is stored beside the first reading, once per item and reason. The result carries the
    reading in masked space (`file_map`) and the masked text (`payload`, in memory only) for the checks. A file over SHEET_READING_INPUT_CAP
    tokens is refused with a message; nothing is cut or sampled.

    Never raises for a model-side problem: the structure is then "Not read by AI" and Python's result
    stands. The output is not Verified here: the caller joins each label to Python's item and
    verifies it.
    """
    import asyncio
    sleep = sleep or asyncio.sleep
    if structure_type not in STRUCTURE_TYPES and structure_type not in (FILE_TYPE, SHEET_STRUCTURE, FILE_RECOGNITION, PAGE_CLAIMS, SHEET_READING):
        return _structure_result("not_read", structure_type, f"unknown structure type {structure_type!r}")
    if structure_type in OLD_SHEET_CALLS and not reader_v1_enabled():
        return _structure_result("not_read", structure_type, NOT_READ)
    context = await load_structure_context(db, audit_id)
    if context.get("structure_reading_consent") is not True:
        return _structure_result("no_consent", structure_type, "AI-assisted reading is off for this audit")
    mapping = await redaction.get_map(db, audit_id)
    masked_counts = None
    if structure_type == PAGE_CLAIMS and isinstance(text, str):
        # Every payload is masked at this boundary (read-check-review.md section 8): the page text is not masked by its caller, so the
        # gateway does it, the target company's name included. The image of the page goes as drawn.
        learned = structure_redact.page_company_names(text, context.get("company_name"), mapping)
        if context.get("company_name") or learned:
            # The target, and every company name under a company-name header the map does not hold: each gets the next Client-NN.
            mapping = await redaction.add_customers(db, audit_id, [n for n in [context.get("company_name"), *learned] if n])
        text, masked_counts = structure_redact.mask_pages(text, context.get("company_name"), mapping)
    if structure_type == SHEET_READING and isinstance(text, str):
        # The same, for a spreadsheet: a text cell under a company-name header the map does not hold is added to it (the next Client-NN),
        # then the cells are masked, the target's own name included. A figure is never rewritten.
        if not file_hash:
            return _structure_result("not_read", structure_type, "refused: no_file_hash")
        blocked = sheet_reader_problem()
        if blocked:
            return _structure_result("blocked", structure_type, blocked)
        learned = structure_redact.reading_company_names(text, context.get("company_name"), mapping)
        if context.get("company_name") or learned:
            mapping = await redaction.add_customers(db, audit_id, [n for n in [context.get("company_name"), *learned] if n])
        text, masked_counts = structure_redact.mask_reading(text, context.get("company_name"), mapping)
    problem = structure_text_problem(text, structure_type, context, mapping)
    if problem:
        logger.warning("structure refused: run_id=%s step=%s reason=%s", audit_id, STRUCTURE_STEP, problem)
        return _structure_result("refused", structure_type, f"refused: {problem}")
    model = STRUCTURE_MODEL
    if structure_type == PAGE_CLAIMS:
        blocked = page_reader_problem()
        if blocked:
            return _structure_result("blocked", structure_type, blocked)
        model = page_reader_model()
    elif structure_type == SHEET_READING:
        model, images = sheet_reader_model(), None
        if isinstance(reread_of, str):
            reread_of = {"key": reread_of}
        if reread_of:
            model = reread_of.get("model") or model
            if not _sheet_reader_model_ok(model):
                return _structure_result("blocked", structure_type, SHEET_READER_BLOCKED)
    else:
        images = None
    try:
        if structure_type == SHEET_READING and recheck:
            # A re-read takes the prompt text, version and model from the reading record it belongs to, never from the prompt store:
            # the second reading is made under the text the first was made under, whatever the store holds now.
            record = await db[readings.READINGS].find_one({"key": reread_of.get("key"), "status": {"$ne": readings.NOT_READ}}, {"_id": 0}) if reread_of else None
            if not record or not record.get("prompt_text") or readings.prompt_hash(record["prompt_text"]) != record.get("prompt_hash"):
                return _structure_result("not_read", structure_type, "the reading record holds no prompt text for a re-read")
            prompt = SimpleNamespace(text=record["prompt_text"], version=record.get("prompt_version") or "", name=SHEET_READING_PROMPT)
            model = record.get("model") or model
            if not _sheet_reader_model_ok(model):
                return _structure_result("blocked", structure_type, "the reading record's model is not permitted")
        else:
            prompt = await prompt_store.load(db, {FILE_TYPE: FILE_TYPE_PROMPT, FILE_RECOGNITION: FILE_TYPE_PROMPT, SHEET_STRUCTURE: SHEET_STRUCTURE_PROMPT,
                                                  PAGE_CLAIMS: PAGE_CLAIMS_PROMPT, SHEET_READING: SHEET_READING_PROMPT}.get(structure_type, STRUCTURE_PROMPT),
                                             version=(reread_of or {}).get("prompt_version") if structure_type == SHEET_READING else None)
    except prompt_store.PromptMissing:
        if structure_type == PAGE_CLAIMS:
            logger.warning("%s prompt missing: run_id=%s step=%s", PAGE_CLAIMS_PROMPT, audit_id, STRUCTURE_STEP)
        if structure_type == SHEET_READING:
            return _structure_result("not_read", structure_type, SHEET_PROMPT_MISSING_TEXT)
        return _structure_result("not_read", structure_type, PROMPT_MISSING_TEXT if structure_type == PAGE_CLAIMS else NOT_READ)
    if price_model(model) not in MODEL_PRICING_USD:
        return _structure_result("not_read", structure_type, NOT_READ)
    tag = (prompt.version if isinstance(prompt, SimpleNamespace) else prompt_store.cache_tag(prompt))
    key = structure_key(text, structure_type, tag, model, images)
    digest = content_hash(text)
    base = {"key": key, "prompt_version": prompt.version, "model": model}
    system = prompt.text
    account = await allowance.tester_of(db, audit_id) if structure_type == SHEET_READING else None
    prompt_hash = readings.prompt_hash(system)
    reading_key = readings.reading_key(account, file_hash, prompt_hash, model) if structure_type == SHEET_READING else None
    recheck_id = content_hash(cache.canonical_json(recheck)) if recheck else None
    recheck_items = [r["item"] for r in recheck or []]

    if structure_type == SHEET_READING:
        # Stored once, keyed on the file and the versions (section 9): the reading of this file is looked up before anything is counted
        # or sent. A hit makes no provider call, whichever audit of the account asked first; another account reads the file again. A second reading of rejected items is stored beside it.
        kept = await readings.get_reread(db, reading_key, recheck_items, recheck_id) if recheck else await readings.get(db, account, file_hash, prompt_hash, model)
        if kept:
            await readings.use(db, audit_id, reading_key)
            await log_call(db, run_id=audit_id, step=STRUCTURE_STEP, prompt_version=prompt.version, model=model, input_tokens=0, output_tokens=0,
                           estimated_cost_usd=0.0, cache_hit=True, status="cache_hit", content_hash=digest, deck_id=deck_id,
                           structure_type=structure_type)
            logger.info("sheet reading stored: run_id=%s step=%s hash=%s", audit_id, STRUCTURE_STEP, digest)
            stored_map = kept["output"] if recheck else kept["file_map"]
            return _structure_result("read", structure_type, cache_hit=True, masked=masked_counts, payload=text, reading_key=reading_key,
                                     file_map=_mask_map(stored_map, context.get("company_name"), mapping), **base)
        if reread_of and not recheck:
            # Pinned to a stored reading that is not there: nothing is read in full here, whatever the prompt or the model now is.
            return _structure_result("not_read", structure_type, SHEET_READING_NOT_STORED, **base)
    elif use_cache:
        hit = await cache.get_structure(db, audit_id, key)
        if hit:
            await log_call(db, run_id=audit_id, step=STRUCTURE_STEP, prompt_version=prompt.version,
                           model=model, input_tokens=0, output_tokens=0, estimated_cost_usd=0.0,
                           cache_hit=True, status="cache_hit", content_hash=digest, deck_id=deck_id, structure_type=structure_type)
            logger.info("structure cache hit: run_id=%s step=%s hash=%s type=%s", audit_id, STRUCTURE_STEP, digest, structure_type)
            return _structure_result("read", structure_type, model_type=hit.get("model_type"), cache_hit=True,
                                     masked=masked_counts, **_reading(hit["output"]), **base)

    # A sheet reading carries the file map's schema as text, with the ask for plain JSON (schemas.file_map_schema; no strict output schema).
    ask = {"answer": schemas.FILE_MAP_ANSWER, "schema": schemas.file_map_schema()} if structure_type == SHEET_READING else {}
    user_payload = cache.canonical_json({"type": structure_type, "text": text, **({"recheck": recheck} if recheck else {}), **ask})
    image_tokens = 0
    adapter = adapter or (AnthropicAdapter(timeout=SHEET_READING_TIMEOUT_SECONDS) if structure_type == SHEET_READING else AnthropicAdapter())
    sheet = structure_type == SHEET_STRUCTURE
    input_cap, max_tokens = (SHEET_INPUT_CAP, SHEET_MAX_TOKENS) if sheet else (STRUCTURE_INPUT_CAP, STRUCTURE_MAX_TOKENS)
    if structure_type == FILE_RECOGNITION:
        input_cap, max_tokens = RECOGNITION_INPUT_CAP, RECOGNITION_MAX_TOKENS
    if structure_type == PAGE_CLAIMS:
        input_cap, max_tokens = PAGE_INPUT_CAP, PAGE_MAX_TOKENS
    if structure_type == SHEET_READING:
        input_cap, max_tokens = SHEET_READING_INPUT_CAP, SHEET_READING_MAX_TOKENS
    try:
        # The 4,000-token cap is on the structure text plus its item list; the 400,000 cap counts the whole call.
        text_tokens = await _count_tokens(adapter, sleep, on_rate_limit, model=model, system=None, user_payload=text,
                                          json_schema=None)
        if text_tokens > input_cap:
            reason = SHEET_READING_TOO_LARGE.format(limit=formatting.fmt_count(input_cap)) if structure_type == SHEET_READING else TOO_LARGE
            return _structure_result("too_large", structure_type, reason, input_tokens=0, masked=masked_counts, **base)
        counted = await _count_tokens(adapter, sleep, on_rate_limit, model=model, system=system,
                                      user_payload=user_payload, json_schema=schemas.output_schema(structure_type))
        if images:
            # The images are counted apart: the whole call with them minus the same call without. They have no cap of their own
            # (page-image.md); the audit's token cap counts them with the rest.
            with_images = await _count_tokens(adapter, sleep, on_rate_limit, model=model, system=system, user_payload=user_payload,
                                              json_schema=schemas.output_schema(structure_type), images=images)
            image_tokens, counted = max(0, with_images - counted), with_images
    except GatewayError as exc:
        # Codes, and on a 4xx the provider's message, capped: it names schema and request faults and carries no file content
        # (_logged_provider_message). Never the exception's own text, a request body, a key or the prompt.
        code, status, kind = exc.reason, exc.status, exc.error_type
        await log_call(db, run_id=audit_id, step=STRUCTURE_STEP, prompt_version=prompt.version, model=model,
                       input_tokens=0, output_tokens=0, estimated_cost_usd=0.0, cache_hit=False, status=code,
                       content_hash=digest, deck_id=deck_id, http_status=status, error_type=kind, structure_type=structure_type)
        shown = _message_field(exc, text, system, user_payload, prompt.text)
        logger.warning("structure not read: run_id=%s step=%s hash=%s reason=%s status=%s type=%s%s", audit_id,
                       STRUCTURE_STEP, digest, code, status or "-", kind or "-", shown)
        return _structure_result("not_read", structure_type, NOT_READ, **base)

    parallel = structure_type == PAGE_CLAIMS
    lock_rounds = PAGE_LOCK_ROUNDS if parallel else SHEET_READING_LOCK_ROUNDS if structure_type == SHEET_READING else 1
    token = await guards.acquire(db, audit_id, STRUCTURE_STEP)
    # One structure call per audit at a time: wait for the one in flight, then take the lock. The page reads of a deck queue for it
    # one after another, each holding it for its checks only, so they wait as many rounds as there are reads beside it.
    rounds = 0
    while token is None and rounds < lock_rounds:
        rounds += 1
        await guards.wait_for_inflight(db, audit_id, STRUCTURE_STEP)
        token = await guards.acquire(db, audit_id, STRUCTURE_STEP)
    if token is None:
        return _structure_result("not_read", structure_type, NOT_READ, **base)
    billed = (0, 0)
    reserved = 0
    try:
        try:
            await guards.check_allowance(db, audit_id)
            if structure_type not in SPEND_CAP_EXEMPT:
                await guards.check_spend_cap(db)
            while True:
                beside = _inflight_tokens.get(audit_id, 0) if parallel else 0
                try:
                    await guards.check_structure_token_cap(db, audit_id, counted + beside, max_tokens)
                    break
                except guards.GuardRefusal:
                    if not beside:
                        raise                       # refused with no read beside it: the cap stops this call, as it would one by one
                    await asyncio.sleep(INFLIGHT_POLL_SECONDS)       # the reads beside it count at their worst case: wait for them
            if parallel:
                reserved = counted + max_tokens
                _inflight_tokens[audit_id] = _inflight_tokens.get(audit_id, 0) + reserved
                await guards.release(db, audit_id, STRUCTURE_STEP, token)       # the provider call runs outside the lock
                token = None
        except guards.GuardRefusal as refusal:
            await log_call(db, run_id=audit_id, step=STRUCTURE_STEP, prompt_version=prompt.version,
                           model=model, input_tokens=0, output_tokens=0, estimated_cost_usd=0.0,
                           cache_hit=False, status=refusal.reason, content_hash=digest, deck_id=deck_id, structure_type=structure_type)
            cap = CAP_REASONS.get(refusal.reason, "cap")          # a closed word, never the guard's message
            logger.warning("structure not read: run_id=%s step=%s hash=%s reason=%s status=- type=-", audit_id,
                           STRUCTURE_STEP, digest, cap)
            stopped = refusal.reason == "structure_token_cap_reached"
            return _structure_result("stopped" if stopped else "not_read", structure_type,
                                     refusal.detail if stopped else NOT_READ, **base)
        try:
            parsed, in_tok, out_tok, sent_calls = await _structure_call(adapter, prompt, user_payload, structure_type, text, sleep,
                                                                        max_tokens, on_rate_limit, model=model, system=system, images=images)
        except GatewayError as exc:
            # Codes only: the reason, the HTTP status, the provider's error type and the check a reply failed (issue
            # #64); on a 4xx the provider's message too, capped (_logged_provider_message); never the exception's own text.
            billed, code, status, kind = getattr(exc, "billed", (0, 0)), exc.reason, exc.status, exc.error_type
            check = exc.check if exc.check in PARSE_CHECKS else "-"
            named = PAGE_FIELDS | MAP_FIELDS if structure_type == SHEET_READING else PAGE_FIELDS
            fields = ",".join(f for f in exc.fields if f in named) or "-"       # schema field names only, never a value
            cost = estimate_cost_usd(model, *billed)
            shown = _message_field(exc, text, system, user_payload, prompt.text)
            image_billed = min(billed[0], image_tokens * getattr(exc, "billed_calls", 0))
            image_cost = estimate_cost_usd(model, image_billed, 0)
            await log_call(db, run_id=audit_id, step=STRUCTURE_STEP, prompt_version=prompt.version,
                           model=model, input_tokens=billed[0], output_tokens=billed[1],
                           estimated_cost_usd=cost, cache_hit=False, status=code, content_hash=digest,
                           deck_id=deck_id, http_status=status, error_type=kind, structure_type=structure_type,
                           image_tokens=image_billed, image_cost_usd=image_cost)
            # A sheet reading that failed validation says "schema_mismatch" and lists the first three errors (field path and message, no
            # value); llm_calls keeps the code. The same line whether the retry's reply failed again or the retry itself was blocked.
            mismatch = structure_type == SHEET_READING and code == "parse_failed"
            listed = f" errors={_error_list(exc)}" if mismatch else ""
            logger.warning("structure not read: run_id=%s step=%s hash=%s tokens=%d/%d cost=%.6f reason=%s "
                           "status=%s type=%s fields=%s check=%s%s%s", audit_id, STRUCTURE_STEP, digest, billed[0], billed[1], cost,
                           "schema_mismatch" if mismatch else code, status or "-", kind or "-", fields, check, listed, shown)
            # "truncated" (the reply cut at max_tokens) is kept apart, so the page step can split the batch and read it again.
            # A page reply that failed validation says so, with the check and the schema fields (closed words), so the deck
            # panel and the run log tell it from an outage.
            rejected = None
            if code == "parse_failed" and structure_type == PAGE_CLAIMS:
                rejected = check if fields == "-" else f"{check}: {fields}"
            reason = SHEET_READING_CUT if structure_type == SHEET_READING and code == "truncated" else NOT_READ
            if code == "parse_failed" and structure_type == SHEET_READING:
                rejected = check if fields == "-" else f"{check}: {fields}"
                reason = SHEET_READING_NOT_MATCHED
                # The strip's reason in the log too, and the raw replies (masked space, as received, never restored) on the reading
                # record for diagnosis; the record is not a reading: it is never served and the next read of the file replaces it.
                replies = list(getattr(exc, "replies", None) or [])
                logger.warning("sheet reading not read: run_id=%s hash=%s reason=%s replies=%d", audit_id, digest, reason, len(replies))
                await readings.put_failed(db, key=reading_key, reread=bool(recheck), items=recheck_items, account=account, file_hash=file_hash,
                                          prompt_version=prompt.version, model=model, reason=reason, replies=replies, recheck_id=recheck_id or "")
                await readings.use(db, audit_id, reading_key)
            return _structure_result("truncated" if code == "truncated" else "not_read", structure_type, reason,
                                     input_tokens=billed[0], output_tokens=billed[1], estimated_cost_usd=cost, rejected=rejected,
                                     image_tokens=image_billed, image_cost_usd=image_cost, **base)
        cost = estimate_cost_usd(model, in_tok, out_tok)
        image_billed = min(in_tok, image_tokens * sent_calls)           # a reasked call bills its images again
        image_cost = estimate_cost_usd(model, image_billed, 0)
        model_type = getattr(parsed, "type", structure_type)
        model_type = model_type if model_type != structure_type else None      # a sheet's type is fixed by its schema
        output = parsed.model_dump()
        if structure_type == PAGE_CLAIMS:
            output = redaction.restore_deep(output, mapping)         # display un-masks on the server: the tokens go back to the names
        stored = output
        if structure_type == FILE_RECOGNITION and output.get("revenue_row"):
            stored = {**output, "revenue_row": {"row": output["revenue_row"]["row"]}}        # the label echo is never kept (5.5)
        if structure_type == SHEET_READING:
            # Written once beside the file's hash (section 9), names restored: the token map goes with the audit, a reading may outlive it.
            if not recheck:
                from .. import series as series_mod        # series imports the checks, which import this module's package
                output = series_mod.attach(output, text, fiscal_year_end)       # the row series, written once with the reading (step a of PR 3)
            restored = redaction.restore_deep(output, mapping)
            if recheck:
                await readings.put_reread(db, reading=reading_key, items=recheck_items, reason=recheck_id, prompt_version=prompt.version, model=model,
                                          output=restored, input_tokens=in_tok, output_tokens=out_tok, cost=cost)
            else:
                await readings.put(db, account=account, file_hash=file_hash, prompt_version=prompt.version, prompt_hash=prompt_hash, model=model, reading=restored, prompt_text=system,
                                   input_tokens=in_tok, output_tokens=out_tok, cost=cost)
                await readings.use(db, audit_id, reading_key)
        else:
            await _store_structure(db, audit_id=audit_id, key=key, digest=digest, structure_type=structure_type,
                                   model_type=model_type, output=stored, prompt_version=prompt.version,
                                   input_tokens=in_tok, output_tokens=out_tok, cost=cost, deck_id=deck_id, page=page, pages=pages, model=model)
        await log_call(db, run_id=audit_id, step=STRUCTURE_STEP, prompt_version=prompt.version, model=model,
                       input_tokens=in_tok, output_tokens=out_tok, estimated_cost_usd=cost, cache_hit=False,
                       status="ok", content_hash=digest, deck_id=deck_id, structure_type=structure_type,
                       image_tokens=image_billed, image_cost_usd=image_cost)
        logger.info("structure read: run_id=%s step=%s hash=%s tokens=%d/%d cost=%.6f type_change=%s",
                    audit_id, STRUCTURE_STEP, digest, in_tok, out_tok, cost,
                    f"{structure_type}->{model_type}" if model_type else "none")
        extra = {"payload": text, "reading_key": reading_key} if structure_type == SHEET_READING else {}
        return _structure_result("read", structure_type, model_type=model_type, **_reading(output),
                                 input_tokens=in_tok, output_tokens=out_tok, estimated_cost_usd=cost,
                                 image_tokens=image_billed, image_cost_usd=image_cost, masked=masked_counts, **extra, **base)
    except Exception as exc:  # never let structure reading block an upload
        logger.error("unexpected structure failure: run_id=%s step=%s error=%s", audit_id, STRUCTURE_STEP,
                     type(exc).__name__)
        return _structure_result("not_read", structure_type, NOT_READ, **base)
    finally:
        if reserved:
            _inflight_tokens[audit_id] = max(0, _inflight_tokens.get(audit_id, 0) - reserved)
        if token is not None:
            await guards.release(db, audit_id, STRUCTURE_STEP, token)


REVIEWER_INPUT_CAP = 60_000      # tokens of the masked review input, by the provider's token counter: above it the review is refused, nothing is cut
REVIEWER_MAX_TOKENS = 4_000      # the findings' reply
REVIEWER_TIMEOUT_SECONDS = 180.0
REVIEWER_TOO_LARGE = "The files are too large to review in one call (the limit is {limit} tokens). Nothing was reviewed."
REVIEW_STRUCTURE_TYPE = "reviewer"


class ReviewRead(NamedTuple):
    """The result of the reviewer call: status ("read", or why not), the findings as the model wrote them (restored names), the reason."""
    status: str
    findings: List[dict] = []
    reason: Optional[str] = None
    prompt_version: Optional[str] = None
    prompt_hash: Optional[str] = None
    model: Optional[str] = None
    input_tokens: int = 0
    output_tokens: int = 0
    estimated_cost_usd: float = 0.0


def parse_review_reply(reply: str) -> "schemas.ReviewReply":
    """The reviewer's reply as the contract: plain JSON, validated in code. A failure is a GatewayError("parse_failed") carrying the first
    validation errors, which the one retry sends back."""
    try:
        return schemas.ReviewReply.model_validate(json.loads(_json_object(reply)))
    except Exception as exc:
        failed = GatewayError("parse_failed", f"reply did not match the schema: {type(exc).__name__}", check=_schema_check(exc),
                              fields=_schema_fields(exc))
        failed.errors = _validation_errors(exc)
        raise failed


def _walk_strings(node: Any, fn):
    if isinstance(node, dict):
        return {k: _walk_strings(v, fn) for k, v in node.items()}
    if isinstance(node, list):
        return [_walk_strings(v, fn) for v in node]
    return fn(node) if isinstance(node, str) else node


async def run_reviewer(db, audit_id: str, review_input: dict, adapter=None, sleep=None) -> ReviewRead:
    """One reviewer call for the audit (read-check-review.md section 7; CLAUDE.md rule 16 as amended for PR 3): the stored file maps and figures
    (the readers' evidence lines already left out by the caller), the computed results and the cannot-check list, masked here like every
    payload (every string as a stored reading is; figures are never rewritten), then sent with the prompt `reviewer` of the store on the
    reader's model (the same allow-list, SHEET_READER_MODELS). The reply is plain JSON validated in code, one retry carrying the errors.
    Names come back restored. Never raises for a model-side problem: the status says why nothing was reviewed (rule 20)."""
    import asyncio
    sleep = sleep or asyncio.sleep
    context = await load_structure_context(db, audit_id)
    if context.get("structure_reading_consent") is not True:
        return ReviewRead("no_consent", reason="AI-assisted reading is off for this audit")
    blocked = sheet_reader_problem()
    if blocked:
        return ReviewRead("blocked", reason=blocked)
    model = sheet_reader_model()
    try:
        prompt = await prompt_store.load(db, REVIEWER_PROMPT)
    except prompt_store.PromptMissing:
        return ReviewRead("not_read", reason=NOT_READ)
    if price_model(model) not in MODEL_PRICING_USD:
        return ReviewRead("not_read", reason=NOT_READ)
    mapping = await redaction.get_map(db, audit_id)
    company = context.get("company_name")
    if company and not any(structure_redact.norm(real) == structure_redact.norm(company) for real in mapping):
        mapping = await redaction.add_customers(db, audit_id, [company])
    def mask(text: str) -> str:
        # The names of the map and the target's own become their tokens first, then the personal rules run on what is left (emails, phone
        # numbers, IBANs, ID numbers, first-name personal names): a company with a first name in it is Client-NN, never "[person] Group".
        tokenised = structure_redact.mask_text(text, company, mapping)
        return structure_redact.redact_cells([{"row": 1, "col": 1, "text": tokenised}], company)[0][0]["text"]
    masked = _walk_strings(review_input, mask)
    text = cache.canonical_json(masked)
    try:
        _assert_masked(text)
    except GatewayError as exc:
        kinds = exc.reason
        logger.warning("review refused: run_id=%s reason=%s", audit_id, kinds)
        return ReviewRead("refused", reason=f"refused: {kinds}")
    user_payload = cache.canonical_json({"type": REVIEW_STRUCTURE_TYPE, "input": masked, "answer": schemas.REVIEW_ASK})
    system = prompt.text
    digest = content_hash(text)
    prompt_hash = readings.prompt_hash(system)
    base = dict(prompt_version=prompt.version, prompt_hash=prompt_hash, model=model)
    adapter = adapter or AnthropicAdapter(timeout=REVIEWER_TIMEOUT_SECONDS)
    try:
        counted = await _count_tokens(adapter, sleep, None, model=model, system=system, user_payload=user_payload, json_schema=None)
    except GatewayError as exc:
        await log_call(db, run_id=audit_id, step=STRUCTURE_STEP, prompt_version=prompt.version, model=model, input_tokens=0, output_tokens=0,
                       estimated_cost_usd=0.0, cache_hit=False, status=exc.reason, content_hash=digest, structure_type=REVIEW_STRUCTURE_TYPE)
        return ReviewRead("not_read", reason=NOT_READ, **base)
    if counted > REVIEWER_INPUT_CAP:
        return ReviewRead("too_large", reason=REVIEWER_TOO_LARGE.format(limit=formatting.fmt_count(REVIEWER_INPUT_CAP)), **base)
    token = await guards.acquire(db, audit_id, STRUCTURE_STEP)
    rounds = 0
    while token is None and rounds < SHEET_READING_LOCK_ROUNDS:
        rounds += 1
        await guards.wait_for_inflight(db, audit_id, STRUCTURE_STEP)
        token = await guards.acquire(db, audit_id, STRUCTURE_STEP)
    if token is None:
        return ReviewRead("not_read", reason=NOT_READ, **base)
    try:
        try:
            await guards.check_allowance(db, audit_id)
            await guards.check_spend_cap(db)
            await guards.check_reviewer_token_cap(db, audit_id, counted, REVIEWER_MAX_TOKENS)
        except guards.GuardRefusal as refusal:
            await log_call(db, run_id=audit_id, step=STRUCTURE_STEP, prompt_version=prompt.version, model=model, input_tokens=0, output_tokens=0,
                           estimated_cost_usd=0.0, cache_hit=False, status=refusal.reason, content_hash=digest, structure_type=REVIEW_STRUCTURE_TYPE)
            return ReviewRead("not_read", reason=NOT_READ, **base)
        billed_in = billed_out = attempts = 0
        prior, payload = None, user_payload
        while True:
            try:
                reply, in_tok, out_tok = await _to_thread(adapter.complete, model=model, system=system, user_payload=payload,
                                                          max_tokens=REVIEWER_MAX_TOKENS, temperature=0, json_schema=None,
                                                          **({"prior": prior} if prior else {}))
            except Exception as raw:
                err = raw if isinstance(raw, GatewayError) else _classify_provider_error(raw)
                code = getattr(err, "reason", None) or "provider_error"
                cost = estimate_cost_usd(model, billed_in, billed_out)
                await log_call(db, run_id=audit_id, step=STRUCTURE_STEP, prompt_version=prompt.version, model=model, input_tokens=billed_in,
                               output_tokens=billed_out, estimated_cost_usd=cost, cache_hit=False, status=code, content_hash=digest,
                               structure_type=REVIEW_STRUCTURE_TYPE)
                logger.warning("review not read: run_id=%s hash=%s reason=%s", audit_id, digest, code)
                return ReviewRead("not_read", reason=NOT_READ, input_tokens=billed_in, output_tokens=billed_out, estimated_cost_usd=cost, **base)
            billed_in, billed_out = billed_in + in_tok, billed_out + out_tok
            try:
                parsed = parse_review_reply(reply)
                break
            except GatewayError as exc:
                attempts += 1
                if attempts > MAX_PARSE_RETRIES:
                    cost = estimate_cost_usd(model, billed_in, billed_out)
                    check = exc.check if exc.check in PARSE_CHECKS else "-"
                    await log_call(db, run_id=audit_id, step=STRUCTURE_STEP, prompt_version=prompt.version, model=model, input_tokens=billed_in,
                                   output_tokens=billed_out, estimated_cost_usd=cost, cache_hit=False, status="parse_failed",
                                   content_hash=digest, structure_type=REVIEW_STRUCTURE_TYPE)
                    logger.warning("review not read: run_id=%s hash=%s reason=parse_failed check=%s", audit_id, digest, check)
                    return ReviewRead("not_read", reason="the review did not match the findings format", input_tokens=billed_in,
                                      output_tokens=billed_out, estimated_cost_usd=cost, **base)
                prior = [{"role": "user", "content": user_payload}, {"role": "assistant", "content": reply}]
                payload = cache.canonical_json({"type": REVIEW_STRUCTURE_TYPE, "fix": schemas.REVIEW_FIX,
                                                "errors": getattr(exc, "errors", None) or [{"loc": "", "type": exc.check or "other", "msg": ""}]})
        cost = estimate_cost_usd(model, billed_in, billed_out)
        findings = redaction.restore_deep(parsed.model_dump(), mapping)["findings"]         # display un-masks on the server
        await log_call(db, run_id=audit_id, step=STRUCTURE_STEP, prompt_version=prompt.version, model=model, input_tokens=billed_in,
                       output_tokens=billed_out, estimated_cost_usd=cost, cache_hit=False, status="ok", content_hash=digest,
                       structure_type=REVIEW_STRUCTURE_TYPE)
        logger.info("review read: run_id=%s hash=%s tokens=%d/%d cost=%.6f findings=%d", audit_id, digest, billed_in, billed_out, cost, len(findings))
        return ReviewRead("read", findings, None, input_tokens=billed_in, output_tokens=billed_out, estimated_cost_usd=cost, **base)
    except Exception as exc:  # never let a review block the audit
        logger.error("unexpected review failure: run_id=%s error=%s", audit_id, type(exc).__name__)
        return ReviewRead("not_read", reason=NOT_READ, **base)
    finally:
        await guards.release(db, audit_id, STRUCTURE_STEP, token)


def _mask_map(stored: dict, company_name: Optional[str], mapping: Dict[str, str]) -> dict:
    """A stored reading (names restored) in this audit's masked space: every string of it masked as a cell is, so the checks compare it
    with the cells of the file as masked for this audit."""
    def walk(node):
        if isinstance(node, dict):
            return {k: walk(v) for k, v in node.items()}
        if isinstance(node, list):
            return [walk(v) for v in node]
        if isinstance(node, str):
            return structure_redact.mask_text(node, company_name, mapping)
        return node
    return walk(stored)


async def _store_structure(db, *, audit_id, key, digest, structure_type, model_type, output, prompt_version,
                           input_tokens, output_tokens, cost, deck_id, page, pages=None, model=STRUCTURE_MODEL) -> None:
    """Store the model's JSON output with its metadata (spec section 9). The text sent is never stored. A page batch keeps the
    numbers of the pages it read."""
    await cache.put_structure(db, audit_id, key, {
        "content_hash": digest, "type": structure_type, "model_type": model_type, "output": output,
        "prompt_version": prompt_version, "model": model,
        "input_tokens": int(input_tokens), "output_tokens": int(output_tokens),
        "estimated_cost_usd": round(float(cost), 6), "deck_id": deck_id, "page": page,
        **({"pages": [int(p) for p in pages]} if pages else {})})


async def stored_structure(db, audit_id: str, key: str) -> Optional[dict]:
    """The stored model output for this audit and key (values with cell references), or None."""
    return await cache.get_structure(db, audit_id, key)


async def record_verification(db, audit_id: str, key: str, statuses: List[str], dropped: int = 0,
                              periods_corrected: int = 0, items: Optional[dict] = None) -> None:
    """Store the verifier status of each item next to the model output it checks, the number of periods Python
    corrected, and the item list the labels name, without raw text (structure-labelling.md section 5: ids,
    cells, positions, values, header ids). The output itself keeps the model's periods."""
    await cache.set_structure_statuses(db, audit_id, key, statuses, dropped, periods_corrected, items)


# ---------------------------------------------------------------------------
# Usage + cleanup
# ---------------------------------------------------------------------------
async def usage_for_run(db, run_id: str) -> UsageResponse:
    """Calls, tokens and cost for a run. `calls` counts billed narrative calls (what the call cap
    counts); structure reading calls are counted apart, against the token cap, and per deck."""
    cursor = db[CALLS_COLLECTION].find({"run_id": run_id}, {"_id": 0})
    rows = await cursor.to_list(100000)
    structures = [r for r in rows if r.get("step") == STRUCTURE_STEP]
    narratives = [r for r in rows if r.get("step") != STRUCTURE_STEP]
    by_deck: Dict[str, DeckUsage] = {}
    for r in structures:
        if not r.get("deck_id"):
            continue
        deck = by_deck.setdefault(r["deck_id"], DeckUsage())
        deck.calls += 0 if r.get("cache_hit") else 1
        deck.cache_hits += 1 if r.get("cache_hit") else 0
        deck.input_tokens += int(r.get("input_tokens", 0))
        deck.output_tokens += int(r.get("output_tokens", 0))
        deck.estimated_cost_usd = round(deck.estimated_cost_usd + float(r.get("estimated_cost_usd", 0.0)), 6)
        deck.image_tokens += int(r.get("image_tokens", 0))
        deck.image_cost_usd = round(deck.image_cost_usd + float(r.get("image_cost_usd", 0.0)), 6)
    by_step: Dict[str, DeckUsage] = {}
    for r in rows:
        name = r.get("step")
        if name == STRUCTURE_STEP:
            kind = r.get("structure_type")
            name = "deck_structure" if r.get("deck_id") else kind if kind in (FILE_TYPE, SHEET_STRUCTURE, FILE_RECOGNITION, SHEET_READING) else "column_mapping"
        step = by_step.setdefault(name, DeckUsage())
        step.calls += 0 if r.get("cache_hit") else 1
        step.cache_hits += 1 if r.get("cache_hit") else 0
        step.input_tokens += int(r.get("input_tokens", 0))
        step.output_tokens += int(r.get("output_tokens", 0))
        step.estimated_cost_usd = round(step.estimated_cost_usd + float(r.get("estimated_cost_usd", 0.0)), 6)
        step.image_tokens += int(r.get("image_tokens", 0))
        step.image_cost_usd = round(step.image_cost_usd + float(r.get("image_cost_usd", 0.0)), 6)
    return UsageResponse(
        run_id=run_id,
        by_step=by_step,
        calls=sum(1 for r in narratives if not r.get("cache_hit")),
        input_tokens=sum(int(r.get("input_tokens", 0)) for r in rows),
        output_tokens=sum(int(r.get("output_tokens", 0)) for r in rows),
        estimated_cost_usd=round(sum(float(r.get("estimated_cost_usd", 0.0)) for r in rows), 6),
        cache_hits=sum(1 for r in rows if r.get("cache_hit")),
        call_cap=guards.MAX_CALLS_PER_RUN,
        structure_calls=sum(1 for r in structures if not r.get("cache_hit")),
        structure_tokens=sum(int(r.get("input_tokens", 0)) + int(r.get("output_tokens", 0)) for r in structures),
        structure_token_cap=guards.STRUCTURE_TOKEN_CAP,
        by_deck=by_deck,
    )


async def purge_run(db, run_id: str) -> dict:
    """Remove every LLM artefact for a run.

    Called from the existing delete-audit action so deleting an audit leaves no
    narratives, no call log and no token map behind, in its current field or its former collection.
    """
    narratives = await cache.delete_run(db, run_id)
    calls = await db[CALLS_COLLECTION].delete_many({"run_id": run_id})
    tokens = await db[redaction.AUDITS_COLLECTION].update_one({"id": run_id}, {"$unset": {redaction.TOKEN_MAP_FIELD: ""}})
    legacy = await db[redaction.LEGACY_MAP_COLLECTION].delete_many({"run_id": run_id})
    locks = await db[guards.LOCKS_COLLECTION].delete_many({"run_id": run_id})
    structures = await cache.delete_structures(db, run_id)
    stored = await readings.purge_audit(db, run_id)
    return {
        "llm_narratives": narratives,
        "llm_calls": getattr(calls, "deleted_count", 0),
        "token_map": getattr(tokens, "modified_count", 0),
        "pseudonym_map": getattr(legacy, "deleted_count", 0),
        "llm_locks": getattr(locks, "deleted_count", 0),
        "llm_structures": structures,
        **stored,
    }


async def drop_legacy_map(db) -> int:
    """The one-off step that retires the former `pseudonym_map` collection (rule 22): it is dropped once Delete audit has emptied it.
    Returns the documents left; the log line carries that count only, never a name."""
    left = await db[redaction.LEGACY_MAP_COLLECTION].count_documents({})
    if left == 0:
        await db[redaction.LEGACY_MAP_COLLECTION].drop()
    logger.info("legacy pseudonym_map: %d document(s) left%s", left, "" if left else ", collection dropped")
    return left
