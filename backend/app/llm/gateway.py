"""The LLM gateway - the only component permitted to call a model provider.

Data boundary (CLAUDE.md rules 16-18, docs/specs/deck-parser.md section 4)
--------------------------------------------------------------------------
Two paths reach the provider, each with its own fields.

Narrative path: `load_computed_results` projects the calc engine's output field and nothing else,
so uploaded rows, raw file bytes and parsed deck text are never fetched, let alone sent.

Structure path (rule 16, read_structure): selected deck structures (tables, charts with data
labels, KPI panels, roadmaps and timelines, hiring, unit-economics and use-of-funds tables) and
spreadsheet header rows (at most 3) with, per column, up to 3 sample values (numeric and date
columns only) or a profile (distinct count, typical length, shape pattern) for text columns. Only
after redaction, only with the audit's consent, only as extracted text with cell positions; never
raw files, full pages or prose slides. The caller hands the text in; the gateway reads no parsed
deck text, runs redaction again and refuses the call if anything changes. `load_structure_context`
reads the audit's consent and the names to protect, and nothing else. The deck parser has no link
to the gateway.

Logs and Mongo (rule 17) store model JSON output (values with cell references), the prompt
version, the model version, the content hash, token counts and cost; never deck text sent to the
model. Delete audit removes the model outputs (purge_run).

Verification (rule 18): model output never becomes Verified on its own. app/structures/verify.py
matches every value to its source cell; unmatched values are shown as "AI suggestion, not
verified" or dropped.

No other function here touches Mongo for audit data, and no module in this package except
`prompt_store` performs file I/O.

Order of operations for a generation request:

    step config -> load computed results -> build payload -> allowlist
    -> pseudonymise segments + identifiers -> cache lookup -> advisory lock
    -> guards -> provider -> strict parse
    -> numeric guard -> re-identify -> cache -> log

Any failure downgrades to `narrative_status="unavailable"` and still returns the
computed metrics. The dashboard is never blocked by this gateway.
"""
import json
import logging
import os
import re
from datetime import datetime, timezone
from typing import Any, Dict, Iterable, List, NamedTuple, Optional, Tuple

from .. import disclosure, formatting
from ..structures import redact as structure_redact
from . import cache, guards, prompt_store, redaction
from .schemas import (CLAIM_METRICS, MAPPING_FIELDS, STRUCTURE_TYPES, DeckUsage, Narrative, NarrativeResponse,
                      StructureRead, StructureReply, UsageResponse, narrative_output_schema, structure_output_schema)

logger = logging.getLogger("growth.llm")

CALLS_COLLECTION = guards.CALLS_COLLECTION
RESULTS_COLLECTION = "audits"

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
                 error_type: Optional[str] = None):
        self.reason = reason
        self.detail = detail
        self.status = status
        self.error_type = error_type
        super().__init__(f"{reason}: {detail}" if detail else reason)


# ---------------------------------------------------------------------------
# The single data accessor
# ---------------------------------------------------------------------------
async def load_computed_results(db, run_id: str, step: str) -> dict:
    """Read ONLY the calc engine's computed output for this run.

    The projection is the enforcement: `results` and the run's own identifiers
    are the only fields fetched. `datasets` (uploaded rows and file bytes) lives
    in another collection this gateway never queries.

    `step` selects which slice of the computed results the step is allowed to
    see, so a step cannot widen its own data access.
    """
    doc = await db[RESULTS_COLLECTION].find_one(
        {"id": run_id},
        {"_id": 0, "id": 1, "results": 1, "reporting_currency": 1,
         "target_arr": 1, "target_date": 1, "as_of_month": 1, "computed_at": 1},
    )
    if not doc:
        raise GatewayError("run_not_found", f"no run {run_id}")
    if not doc.get("results"):
        raise GatewayError("not_computed", f"run {run_id} has no computed results")

    results = doc["results"]
    slice_ = _slice_for_step(results, step)
    return {
        "run_id": run_id,
        "reporting_currency": doc.get("reporting_currency"),
        "target_arr": doc.get("target_arr"),
        "target_date": doc.get("target_date"),
        "as_of_month": doc.get("as_of_month") or results.get("as_of_month"),
        "computed_at": doc.get("computed_at"),
        "metrics": slice_,
    }


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
OUTBOUND_TOP_LEVEL = frozenset({"reporting_currency", "target_arr", "target_date", "as_of_month", "metrics"})

OUTBOUND_FIELDS = frozenset({
    # metric blocks (the step slice)
    "arr", "nrr", "gross_churn", "cac_payback", "sales_cycle", "win_rate", "founder_win_rate",
    "acv_path", "segment_paths", "cohort_retention", "as_of_month", "reporting_currency",
    "missing_data", "questions_for_management",
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


def _slice_for_step(results: dict, step: str) -> dict:
    """Narrow computed results to what a step needs. Unknown keys are dropped."""
    wanted = {
        "growth_engine": [
            "arr", "nrr", "gross_churn", "cac_payback", "sales_cycle",
            "win_rate", "founder_win_rate", "acv_path", "segment_paths", "as_of_month", "reporting_currency",
        ],
        "cohort_retention": ["cohort_retention", "as_of_month"],
        "cac_efficiency": ["cac_payback", "as_of_month"],
        "path_to_plan": ["acv_path", "segment_paths", "as_of_month"],
    }.get(step, [])
    out = {k: results.get(k) for k in wanted if results.get(k) is not None}
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
        json_schema: dict,
    ) -> Tuple[str, int, int]:
        """One provider call. Returns (text, input_tokens, output_tokens).

        Raises `RetryableProviderError` for network/5xx so the caller can back
        off, and `GatewayError` for anything a retry would not fix.
        """
        client = self._ensure_client()
        kwargs = {
            "model": model,
            "max_tokens": max_tokens,
            "system": system,
            "messages": [{"role": "user", "content": user_payload}],
            # Structured output is what makes strict parsing viable: the first
            # content block is guaranteed to be schema-valid JSON.
            "output_config": {"format": {"type": "json_schema", "schema": json_schema}},
        }
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
        return (
            text,
            int(getattr(usage, "input_tokens", 0) or 0),
            int(getattr(usage, "output_tokens", 0) or 0),
        )


    def count_tokens(self, *, model: str, system: Optional[str], user_payload: str,
                     json_schema: Optional[dict]) -> int:
        """The input tokens a call would bill, from the provider's token counter (no call is made).
        With no system prompt and no schema it counts `user_payload` alone."""
        client = self._ensure_client()
        extra = {}
        if system is not None:
            extra["system"] = system
        if json_schema is not None:
            extra["output_config"] = {"format": {"type": "json_schema", "schema": json_schema}}
        try:
            response = client.messages.count_tokens(
                model=model, messages=[{"role": "user", "content": user_payload}], **extra)
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
        return RetryableProviderError(f"{name} {status}: {exc}", status, error_type, _retry_after_seconds(exc))
    if status is None and name in {
        "APIConnectionError", "APITimeoutError", "APIConnectionTimeoutError",
    }:
        return RetryableProviderError(f"{name}: {exc}", None, error_type)
    if status is not None:
        return GatewayError("provider_error", f"{name} {status}: {exc}", status, error_type)
    return RetryableProviderError(f"{name}: {exc}", None, error_type)


def _unreachable(exc: RetryableProviderError) -> GatewayError:
    """The GatewayError for a retryable error that outlasted MAX_PROVIDER_RETRIES, with its status and type."""
    return GatewayError("provider_unreachable", str(exc), exc.status, exc.error_type)


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


def accepted_source_keys(payload: Any) -> set:
    """Dotted paths plus their bare leaf names.

    The dotted path is what the model is told to use. Bare names stay accepted
    so a row citing `acv` is not thrown away over formatting - the point of the
    guard is that the figure is traceable, not that it is spelled one way.
    """
    full = source_key_paths(payload)
    return set(full) | {p.rsplit(".", 1)[-1] for p in full}


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
    http_status: Optional[int] = None, error_type: Optional[str] = None,
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
                               ("error_type", error_type)) if v is not None}
    await db[CALLS_COLLECTION].insert_one({**extra,
        "run_id": run_id,
        "step": step,
        "prompt_version": prompt_version,
        "model": model,
        "input_tokens": int(input_tokens),
        "output_tokens": int(output_tokens),
        "estimated_cost_usd": round(float(estimated_cost_usd), 6),
        "cache_hit": bool(cache_hit),
        "status": status,
        "unmatched_numbers": list(unmatched_numbers or []),
        "timestamp": datetime.now(timezone.utc).isoformat(),
    })


def estimate_cost_usd(model: str, input_tokens: int, output_tokens: int) -> float:
    price = MODEL_PRICING_USD.get(model)
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
    computed = await load_computed_results(db, run_id, step)
    metrics = computed["metrics"]

    if not config.get("enabled"):
        return NarrativeResponse(
            run_id=run_id, step=step, narrative_status="unavailable",
            reason=f"step {step!r} is scaffolded but has no prompt yet", metrics=metrics,
        )

    try:
        prompt = prompt_store.load(config["prompt"])
    except (FileNotFoundError, ValueError) as exc:
        return _unavailable(run_id, step, f"prompt unavailable: {exc}", metrics)

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

    # Last-line assertion: nothing from pseudonym_map may appear outbound.
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
        cost = estimate_cost_usd(model, in_tok, out_tok)

        # Hard tier: a fabricated figure in the headline or a table row, or a
        # row citing a source key that does not exist. Drop the narrative.
        if guard.hard or bad_keys or one_sided:
            reason = bad_keys or one_sided or (
                "model produced number(s) absent from the computed results in "
                f"headline/table rows: {', '.join(guard.hard[:8])}"
            )
            # The call still cost money, so it is logged and counted. Every
            # unmatched number is recorded, both tiers, for prompt tuning.
            await log_call(
                db, run_id=run_id, step=step, prompt_version=prompt.version, model=model,
                input_tokens=in_tok, output_tokens=out_tok, estimated_cost_usd=cost,
                cache_hit=False,
                status="views_guard_rejected" if one_sided and not (guard.hard or bad_keys) else "numeric_guard_rejected",
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
            prompt_release=prompt_store.release(),
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
    schema = narrative_output_schema()
    system = prompt.text
    # Hand the model the exact source keys it may cite, in the exact form the
    # guard accepts. Derived from the payload, so the two can never drift; sent
    # alongside the data rather than baked into the prompt, since it is
    # per-payload. The cache key is still computed from `outbound` alone.
    message = dict(outbound)
    message["valid_source_keys"] = source_key_paths(outbound)
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

    computed = await load_computed_results(db, run_id, step)
    metrics = computed["metrics"]

    try:
        prompt = prompt_store.load(config["prompt"])
    except (FileNotFoundError, ValueError):
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
    mapping = await redaction.get_or_create_map(db, run_id, computed)
    try:
        outbound = build_outbound(computed, mapping)
    except GatewayError:
        return NarrativeResponse(
            run_id=run_id, step=step, narrative_status="not_generated", metrics=metrics,
        )
    key = cache.cache_key(run_id, step, prompt_store.cache_tag(prompt), model, outbound)

    cached = await cache.get(db, key)
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
    narrative is unreachable only because the prompt release or the model changed.
    Only if no stored narrative matches under its own settings did the data change.
    Records from before releases were stamped count as the baseline release.
    """
    records = await cache.records_for(db, run_id, step)
    if not records:
        return None
    reason = "data_changed"
    for rec in sorted(records, key=lambda r: r.get("created_at") or ""):  # newest match wins
        rec_release = rec.get("prompt_release") or prompt_store.BASELINE_RELEASE
        rec_model = rec.get("model") or model
        tag = prompt_store.tag_for(rec_release, rec.get("prompt_version") or "")
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
STRUCTURE_PROMPT = "structure_reading"
STRUCTURE_STEP = guards.STRUCTURE_STEP
STRUCTURE_MAX_TOKENS = 4000
STRUCTURE_INPUT_CAP = 3000          # tokens of structure text alone, by the provider's token counter
STRUCTURE_CELL_MAX = 200            # a longer cell is prose
STRUCTURES_COLLECTION = cache.STRUCTURES_COLLECTION
NOT_READ = "Not read by AI"
TOO_LARGE = "Too large for AI reading"
# The reason a cap refusal's "structure not read" line gives, per guard code (llm_calls keeps the code).
CAP_REASONS = {"daily_spend_cap_exceeded": "spend_cap", "structure_token_cap_reached": "token_cap"}
# A file name in the text means it was built from the wrong thing: refused.
_FILE_NAME = re.compile(r"(?i)\b[\w\-. ]{1,80}\.(?:pptx?|pdf|docx?|xlsx?|xlsm|xls|csv)\b")
_CONTROL = re.compile(r"[\x00-\x08\x0b-\x1f\x7f]")


async def load_structure_context(db, audit_id: str) -> dict:
    """The audit's consent and the names the structure path must protect, and nothing else.

    `company_name` is the target, never rewritten by redaction; `client_name` and
    `engagement_reference` must never reach the provider. Uploaded rows, parsed deck text and
    candidates are not read here: the text to read is handed in by the caller.
    """
    doc = await db[RESULTS_COLLECTION].find_one(
        {"id": audit_id},
        {"_id": 0, "id": 1, "company_name": 1, "client_name": 1, "engagement_reference": 1,
         "structure_reading_consent": 1},
    )
    if not doc:
        raise GatewayError("run_not_found", f"no run {audit_id}")
    return doc


def structure_key(text: str, structure_type: str, prompt_tag: str, model: str) -> str:
    """sha256 of the text, its type, the prompt cache tag and the model (spec section 8)."""
    return cache.cache_key(STRUCTURE_STEP, structure_type, prompt_tag, model, text)


def content_hash(text: str) -> str:
    import hashlib
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def structure_text_problem(text: Any, structure_type: str, context: dict, mapping: Dict[str, str]) -> Optional[str]:
    """Why a text may not reach the provider, or None (CLAUDE.md rule 16, spec sections 1 and 3).

    Only extracted text with cell positions passes: one `r<row>c<col>: <text>` line per cell (and, on
    the column-mapping path, sample and profile lines). Raw bytes, prose, a file name and a cell over
    200 characters are refused. The client name and the engagement reference reach the provider only
    as "[redacted]": the caller replaces them (redact.withheld_values), and one still standing in the
    text as a whole word (any case; a word ends at a space, punctuation, a hyphen or a change of
    case, as in redaction) is refused. Redaction is run again and the text must come back unchanged. On the
    column-mapping path at most 3 header rows and 3 samples per column pass, and no text cell value.
    """
    if not isinstance(text, str):
        return "not_text"
    if not text.strip():
        return "empty"
    if _CONTROL.search(text):
        return "raw_bytes"
    if _FILE_NAME.search(text):
        return "file_name"
    for field in ("client_name", "engagement_reference"):
        if structure_redact.has_word(text, str(context.get(field) or "").strip()):
            return field
    company = context.get("company_name")
    if structure_type == "column_mapping":
        problem = structure_redact.column_text_problem(text)
        if problem:
            return problem
        cells = structure_redact.parse_column_text(text)["headers"]
    else:
        cells = structure_redact.parse_structure_text(text)
        if not cells:
            return "not_cells"
    if any(len(c["text"]) > STRUCTURE_CELL_MAX for c in cells):
        return "cell_too_long"
    redacted, _ = structure_redact.redact_structure(cells, company, mapping, structure_redact.withheld_values(context))
    if redacted != cells:
        return "redaction_changed"
    return None


def _cited_cells(text: str, structure_type: str) -> set:
    """The cell ids a reply may cite: every cell of a deck structure, the header cells of a sheet."""
    if structure_type == "column_mapping":
        cells = (structure_redact.parse_column_text(text) or {}).get("headers") or []
    else:
        cells = structure_redact.parse_structure_text(text) or []
    return {structure_redact.cell_id(c) for c in cells}


def parse_structure_reply(reply: str, structure_type: str, text: str) -> StructureReply:
    """Validate a reply against the schema (extra fields forbidden), the type rule and the cells, or
    raise GatewayError("parse_failed"). The type may be corrected within the deck types only; a
    column mapping stays one. Every cited cell must exist in the text that was sent."""
    try:
        data = json.loads((reply or "").strip())
        parsed = StructureReply.model_validate(data)
    except Exception as exc:
        raise GatewayError("parse_failed", f"reply did not match the schema: {type(exc).__name__}")
    if (structure_type == "column_mapping") != (parsed.type == "column_mapping"):
        raise GatewayError("parse_failed", "type changed between a deck structure and a column mapping")
    allowed = MAPPING_FIELDS if structure_type == "column_mapping" else CLAIM_METRICS + ("use_of_funds",)
    if any(item.metric not in allowed for item in parsed.items):
        raise GatewayError("parse_failed", "a metric that does not belong to this kind of structure")
    known = _cited_cells(text, structure_type)
    for item in parsed.items:
        if item.value_cell not in known or any(c not in known for c in item.period_cells):
            raise GatewayError("parse_failed", "reply cites a cell that is not in the structure")
    return parsed


async def _count_tokens(adapter, sleep, **kwargs) -> int:
    """The provider's token count, with the gateway's network retry policy."""
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
            attempts += 1
            if attempts > MAX_PROVIDER_RETRIES:
                raise _unreachable(exc)
            await sleep(_backoff_seconds(exc, attempts))


async def _structure_call(adapter, prompt, user_payload, structure_type, text, sleep):
    """(reply, input tokens, output tokens) summed over every billed attempt. Network or 5xx: up to
    MAX_PROVIDER_RETRIES with backoff. A reply that fails validation: one reask, then GatewayError."""
    schema = structure_output_schema()
    parse_attempts = network_attempts = 0
    billed_in = billed_out = 0
    while True:
        try:
            try:
                reply, in_tok, out_tok = await _to_thread(
                    adapter.complete, model=STRUCTURE_MODEL, system=prompt.text, user_payload=user_payload,
                    max_tokens=STRUCTURE_MAX_TOKENS, temperature=None, json_schema=schema)
            except (RetryableProviderError, GatewayError):
                raise
            except Exception as raw:
                raise _classify_provider_error(raw)
        except RetryableProviderError as exc:
            network_attempts += 1
            if network_attempts > MAX_PROVIDER_RETRIES:
                exc_out = _unreachable(exc)
                exc_out.billed = (billed_in, billed_out)
                raise exc_out
            await sleep(_backoff_seconds(exc, network_attempts))
            continue
        except GatewayError as exc:
            exc.billed = (billed_in, billed_out)
            raise
        billed_in, billed_out = billed_in + in_tok, billed_out + out_tok
        try:
            return parse_structure_reply(reply, structure_type, text), billed_in, billed_out
        except GatewayError as exc:
            parse_attempts += 1
            if parse_attempts > MAX_PARSE_RETRIES:
                exc.billed = (billed_in, billed_out)
                raise


def _structure_result(status, structure_type, reason=None, **fields) -> StructureRead:
    return StructureRead(status=status, type=structure_type, reason=reason, **fields)


async def read_structure(
    db, audit_id: str, text: str, structure_type: str, *, deck_id: Optional[str] = None,
    page: Optional[int] = None, adapter=None, sleep=None, use_cache: bool = True,
) -> StructureRead:
    """Read one structure or one sheet's headers with the model (CLAUDE.md rules 16-18).

    `text` is the redacted structure text the caller built (one `r<row>c<col>: <text>` line per
    cell; for `column_mapping`, header cells, samples and profiles). It is checked again here and
    never stored: only the model's JSON output (values with cell references), the prompt version,
    the model, the content hash, the tokens and the cost are. Order of operations:

        consent -> boundary and redaction check -> cache (audit, key) -> token count of the text
        alone (3,000 cap) -> token count of the whole call -> lock (step "structures") -> spend cap
        -> token cap (400,000 per audit, with the whole call's input) -> provider
        -> schema, type and cell check (one reask) -> store -> log

    Never raises for a model-side problem: the structure is then "Not read by AI" and Python's result
    stands. The output is not Verified here: the caller matches every value to its source cell.
    """
    import asyncio
    sleep = sleep or asyncio.sleep
    if structure_type not in STRUCTURE_TYPES:
        return _structure_result("not_read", structure_type, f"unknown structure type {structure_type!r}")
    context = await load_structure_context(db, audit_id)
    if context.get("structure_reading_consent") is not True:
        return _structure_result("no_consent", structure_type, "AI-assisted reading is off for this audit")
    mapping = await redaction.get_map(db, audit_id)
    problem = structure_text_problem(text, structure_type, context, mapping)
    if problem:
        logger.warning("structure refused: run_id=%s step=%s reason=%s", audit_id, STRUCTURE_STEP, problem)
        return _structure_result("refused", structure_type, f"refused: {problem}")
    try:
        prompt = prompt_store.load(STRUCTURE_PROMPT)
    except (FileNotFoundError, ValueError):
        return _structure_result("not_read", structure_type, NOT_READ)
    if STRUCTURE_MODEL not in MODEL_PRICING_USD:
        return _structure_result("not_read", structure_type, NOT_READ)
    key = structure_key(text, structure_type, prompt_store.cache_tag(prompt), STRUCTURE_MODEL)
    digest = content_hash(text)
    base = {"key": key, "prompt_version": prompt.version, "model": STRUCTURE_MODEL}

    if use_cache:
        hit = await cache.get_structure(db, audit_id, key)
        if hit:
            await log_call(db, run_id=audit_id, step=STRUCTURE_STEP, prompt_version=prompt.version,
                           model=STRUCTURE_MODEL, input_tokens=0, output_tokens=0, estimated_cost_usd=0.0,
                           cache_hit=True, status="cache_hit", content_hash=digest, deck_id=deck_id)
            return _structure_result("read", structure_type, model_type=hit.get("model_type"),
                                     items=hit["output"]["items"], cache_hit=True, **base)

    user_payload = cache.canonical_json({"type": structure_type, "text": text})
    adapter = adapter or AnthropicAdapter()
    try:
        # The 3,000-token cap is on the structure text alone; the 400,000 cap counts the whole call.
        text_tokens = await _count_tokens(adapter, sleep, model=STRUCTURE_MODEL, system=None, user_payload=text,
                                          json_schema=None)
        if text_tokens > STRUCTURE_INPUT_CAP:
            return _structure_result("too_large", structure_type, TOO_LARGE, input_tokens=0, **base)
        counted = await _count_tokens(adapter, sleep, model=STRUCTURE_MODEL, system=prompt.text,
                                      user_payload=user_payload, json_schema=structure_output_schema())
    except GatewayError as exc:
        # Codes only: the reason, the HTTP status and the provider's error type; never the exception's message.
        code, status, kind = exc.reason, exc.status, exc.error_type
        await log_call(db, run_id=audit_id, step=STRUCTURE_STEP, prompt_version=prompt.version, model=STRUCTURE_MODEL,
                       input_tokens=0, output_tokens=0, estimated_cost_usd=0.0, cache_hit=False, status=code,
                       content_hash=digest, deck_id=deck_id, http_status=status, error_type=kind)
        logger.warning("structure not read: run_id=%s step=%s hash=%s reason=%s status=%s type=%s", audit_id,
                       STRUCTURE_STEP, digest, code, status or "-", kind or "-")
        return _structure_result("not_read", structure_type, NOT_READ, **base)

    token = await guards.acquire(db, audit_id, STRUCTURE_STEP)
    if token is None:
        # One structure call per audit at a time: wait for the one in flight, then take the lock.
        await guards.wait_for_inflight(db, audit_id, STRUCTURE_STEP)
        token = await guards.acquire(db, audit_id, STRUCTURE_STEP)
        if token is None:
            return _structure_result("not_read", structure_type, NOT_READ, **base)
    billed = (0, 0)
    try:
        try:
            await guards.check_spend_cap(db)
            await guards.check_structure_token_cap(db, audit_id, counted, STRUCTURE_MAX_TOKENS)
        except guards.GuardRefusal as refusal:
            await log_call(db, run_id=audit_id, step=STRUCTURE_STEP, prompt_version=prompt.version,
                           model=STRUCTURE_MODEL, input_tokens=0, output_tokens=0, estimated_cost_usd=0.0,
                           cache_hit=False, status=refusal.reason, content_hash=digest, deck_id=deck_id)
            cap = CAP_REASONS.get(refusal.reason, "cap")          # a closed word, never the guard's message
            logger.warning("structure not read: run_id=%s step=%s hash=%s reason=%s status=- type=-", audit_id,
                           STRUCTURE_STEP, digest, cap)
            stopped = refusal.reason == "structure_token_cap_reached"
            return _structure_result("stopped" if stopped else "not_read", structure_type,
                                     refusal.detail if stopped else NOT_READ, **base)
        try:
            parsed, in_tok, out_tok = await _structure_call(adapter, prompt, user_payload, structure_type, text, sleep)
        except GatewayError as exc:
            # Codes only: the reason, the HTTP status and the provider's error type; never the message.
            billed, code, status, kind = getattr(exc, "billed", (0, 0)), exc.reason, exc.status, exc.error_type
            cost = estimate_cost_usd(STRUCTURE_MODEL, *billed)
            await log_call(db, run_id=audit_id, step=STRUCTURE_STEP, prompt_version=prompt.version,
                           model=STRUCTURE_MODEL, input_tokens=billed[0], output_tokens=billed[1],
                           estimated_cost_usd=cost, cache_hit=False, status=code, content_hash=digest,
                           deck_id=deck_id, http_status=status, error_type=kind)
            logger.warning("structure not read: run_id=%s step=%s hash=%s tokens=%d/%d cost=%.6f reason=%s "
                           "status=%s type=%s", audit_id, STRUCTURE_STEP, digest, billed[0], billed[1], cost, code,
                           status or "-", kind or "-")
            return _structure_result("not_read", structure_type, NOT_READ, input_tokens=billed[0],
                                     output_tokens=billed[1], estimated_cost_usd=cost, **base)
        cost = estimate_cost_usd(STRUCTURE_MODEL, in_tok, out_tok)
        model_type = parsed.type if parsed.type != structure_type else None
        output = parsed.model_dump()
        await _store_structure(db, audit_id=audit_id, key=key, digest=digest, structure_type=structure_type,
                               model_type=model_type, output=output, prompt_version=prompt.version,
                               input_tokens=in_tok, output_tokens=out_tok, cost=cost, deck_id=deck_id, page=page)
        await log_call(db, run_id=audit_id, step=STRUCTURE_STEP, prompt_version=prompt.version, model=STRUCTURE_MODEL,
                       input_tokens=in_tok, output_tokens=out_tok, estimated_cost_usd=cost, cache_hit=False,
                       status="ok", content_hash=digest, deck_id=deck_id)
        logger.info("structure read: run_id=%s step=%s hash=%s tokens=%d/%d cost=%.6f type_change=%s",
                    audit_id, STRUCTURE_STEP, digest, in_tok, out_tok, cost,
                    f"{structure_type}->{model_type}" if model_type else "none")
        return _structure_result("read", structure_type, model_type=model_type, items=output["items"],
                                 input_tokens=in_tok, output_tokens=out_tok, estimated_cost_usd=cost, **base)
    except Exception as exc:  # never let structure reading block an upload
        logger.error("unexpected structure failure: run_id=%s step=%s error=%s", audit_id, STRUCTURE_STEP,
                     type(exc).__name__)
        return _structure_result("not_read", structure_type, NOT_READ, **base)
    finally:
        await guards.release(db, audit_id, STRUCTURE_STEP, token)


async def _store_structure(db, *, audit_id, key, digest, structure_type, model_type, output, prompt_version,
                           input_tokens, output_tokens, cost, deck_id, page) -> None:
    """Store the model's JSON output with its metadata (spec section 9). The text sent is never stored."""
    await cache.put_structure(db, audit_id, key, {
        "content_hash": digest, "type": structure_type, "model_type": model_type, "output": output,
        "prompt_version": prompt_version, "prompt_release": prompt_store.release(), "model": STRUCTURE_MODEL,
        "input_tokens": int(input_tokens), "output_tokens": int(output_tokens),
        "estimated_cost_usd": round(float(cost), 6), "deck_id": deck_id, "page": page})


async def stored_structure(db, audit_id: str, key: str) -> Optional[dict]:
    """The stored model output for this audit and key (values with cell references), or None."""
    return await cache.get_structure(db, audit_id, key)


async def record_verification(db, audit_id: str, key: str, statuses: List[str], dropped: int = 0,
                              periods_corrected: int = 0) -> None:
    """Store the verifier status of each item next to the model output it checks, and the number of
    periods Python corrected (spec section 9). The output itself keeps the model's periods."""
    await cache.set_structure_statuses(db, audit_id, key, statuses, dropped, periods_corrected)


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
    return UsageResponse(
        run_id=run_id,
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
    narratives, no call log and no pseudonym mapping behind.
    """
    narratives = await cache.delete_run(db, run_id)
    calls = await db[CALLS_COLLECTION].delete_many({"run_id": run_id})
    pseudonyms = await db[redaction.PSEUDONYM_COLLECTION].delete_many({"run_id": run_id})
    locks = await db[guards.LOCKS_COLLECTION].delete_many({"run_id": run_id})
    structures = await cache.delete_structures(db, run_id)
    return {
        "llm_narratives": narratives,
        "llm_calls": getattr(calls, "deleted_count", 0),
        "pseudonym_map": getattr(pseudonyms, "deleted_count", 0),
        "llm_locks": getattr(locks, "deleted_count", 0),
        "llm_structures": structures,
    }
