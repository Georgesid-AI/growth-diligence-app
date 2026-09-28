"""The LLM gateway - the only component permitted to call a model provider.

Data boundary
-------------
`load_computed_results` is the gateway's ONLY data accessor. It projects the
calc engine's output field and nothing else, so uploaded rows, raw file bytes
and parsed deck text are never fetched, let alone sent. No other function here
touches Mongo for audit data, and no module in this package except
`prompt_store` performs file I/O.

Order of operations for a generation request:

    step config -> load computed results -> build payload -> pseudonymise
    -> cache lookup -> advisory lock -> guards -> provider -> strict parse
    -> numeric guard -> re-identify -> cache -> log

Any failure downgrades to `narrative_status="unavailable"` and still returns the
computed metrics. The dashboard is never blocked by this gateway.
"""
import json
import logging
import os
import re
from datetime import datetime, timezone
from typing import Any, Iterable, List, NamedTuple, Optional, Tuple

from . import cache, guards, prompt_store, redaction
from .schemas import Narrative, NarrativeResponse, UsageResponse

logger = logging.getLogger("growth.llm")

CALLS_COLLECTION = guards.CALLS_COLLECTION
RESULTS_COLLECTION = "audits"

REQUEST_TIMEOUT_SECONDS = 60.0
MAX_PROVIDER_RETRIES = 2          # network / 5xx only
MAX_PARSE_RETRIES = 1             # one reask on a malformed body, then fail

# Per-1M-token list prices, used only to estimate spend for the cap and the
# usage endpoint. Not authoritative billing.
MODEL_PRICING_USD = {
    "claude-opus-5": {"input": 5.00, "output": 25.00},
    "claude-sonnet-5": {"input": 2.00, "output": 10.00},
    "claude-haiku-4-5": {"input": 1.00, "output": 5.00},
}
DEFAULT_MODEL = "claude-opus-5"

# Sampling parameters were removed on the current Opus/Sonnet generation: sending
# `temperature` to those models is a 400. Only models listed here get it.
MODELS_ACCEPTING_TEMPERATURE = {"claude-haiku-4-5"}

# Per-step configuration. Only `growth_engine` has a prompt; the rest are
# scaffolded so wiring and guards are already in place when their prompts land.
STEP_CONFIG = {
    "growth_engine": {
        "prompt": "growth_engine",
        # Window lengths this step legitimately talks about ("12-month NRR"),
        # allowlisted so ordinary phrasing is not treated as a fabricated figure.
        "windows": [12, 24],
        "model": DEFAULT_MODEL,
        "max_tokens": 4000,
        "temperature": 0.2,
        "enabled": True,
    },
    "cohort_retention": {
        "prompt": "cohort_retention",
        # Window lengths this step legitimately talks about ("12-month NRR"),
        # allowlisted so ordinary phrasing is not treated as a fabricated figure.
        "windows": [12, 24],
        "model": DEFAULT_MODEL,
        "max_tokens": 3000,
        "temperature": 0.2,
        "enabled": False,
    },
    "cac_efficiency": {
        "prompt": "cac_efficiency",
        # Window lengths this step legitimately talks about ("12-month NRR"),
        # allowlisted so ordinary phrasing is not treated as a fabricated figure.
        "windows": [4],
        "model": DEFAULT_MODEL,
        "max_tokens": 3000,
        "temperature": 0.2,
        "enabled": False,
    },
    "path_to_plan": {
        "prompt": "path_to_plan",
        # Window lengths this step legitimately talks about ("12-month NRR"),
        # allowlisted so ordinary phrasing is not treated as a fabricated figure.
        "windows": [12, 24],
        "model": DEFAULT_MODEL,
        "max_tokens": 3000,
        "temperature": 0.2,
        "enabled": False,
    },
}


class GatewayError(Exception):
    """Generation failed in a way that yields narrative_status=unavailable."""

    def __init__(self, reason: str, detail: str = ""):
        self.reason = reason
        self.detail = detail
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


def _slice_for_step(results: dict, step: str) -> dict:
    """Narrow computed results to what a step needs. Unknown keys are dropped."""
    wanted = {
        "growth_engine": [
            "arr", "nrr", "gross_churn", "cac_payback", "sales_cycle",
            "win_rate", "acv_path", "as_of_month", "reporting_currency",
        ],
        "cohort_retention": ["cohort_retention", "as_of_month"],
        "cac_efficiency": ["cac_payback", "as_of_month"],
        "path_to_plan": ["acv_path", "as_of_month"],
    }.get(step, [])
    return {k: results.get(k) for k in wanted if results.get(k) is not None}


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

        text = next((b.text for b in response.content if getattr(b, "type", None) == "text"), "")
        usage = getattr(response, "usage", None)
        return (
            text,
            int(getattr(usage, "input_tokens", 0) or 0),
            int(getattr(usage, "output_tokens", 0) or 0),
        )


class RetryableProviderError(Exception):
    """Network error or 5xx - safe to retry with backoff."""


def _classify_provider_error(exc: Exception) -> Exception:
    """Decide whether a provider exception is worth retrying.

    Only connection failures, timeouts, 408/409/429 and 5xx are retryable. A
    400 (bad request) or 401 (bad key) is returned as-is, because retrying it
    just spends money on the same failure.
    """
    status = getattr(exc, "status_code", None)
    name = type(exc).__name__
    if status is not None and (status >= 500 or status in (408, 409, 429)):
        return RetryableProviderError(f"{name} {status}: {exc}")
    if status is None and name in {
        "APIConnectionError", "APITimeoutError", "APIConnectionTimeoutError",
    }:
        return RetryableProviderError(f"{name}: {exc}")
    if status is not None:
        return GatewayError("provider_error", f"{name} {status}: {exc}")
    return RetryableProviderError(f"{name}: {exc}")


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
    """Every numeric token the model may legitimately use."""
    return redaction.numbers_in(payload) | redaction.numbers_in(
        list(GLOBAL_ALLOWED_NUMERALS) + list(windows)
    )


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
        hard |= redaction.numbers_in(getattr(narrative, field, "") or "")
    for row in narrative.table_rows:
        hard |= redaction.numbers_in(row.value)
        hard |= redaction.numbers_in(row.label)

    soft: set = set()
    for field in SOFT_FIELDS:
        value = getattr(narrative, field, None)
        soft |= redaction.numbers_in(value if value is not None else "")

    # A number that is unmatched in both tiers is reported once, as hard.
    hard_unmatched = hard - allowed
    soft_unmatched = (soft - allowed) - hard_unmatched
    return NumericGuardResult(
        hard=sorted(hard_unmatched, key=_numeric_sort_key),
        soft=sorted(soft_unmatched, key=_numeric_sort_key),
    )


def source_key_guard(narrative: Narrative, payload: Any) -> Optional[str]:
    """Each table row must cite a source key that exists in the payload."""
    available = set(_all_keys(payload))
    unknown = sorted({r.source_key for r in narrative.table_rows if r.source_key not in available})
    if unknown:
        return f"table row cites unknown source key(s): {', '.join(unknown[:8])}"
    return None


def _all_keys(node: Any) -> set:
    keys: set = set()
    if isinstance(node, dict):
        for k, v in node.items():
            keys.add(k)
            keys |= _all_keys(v)
    elif isinstance(node, list):
        for item in node:
            keys |= _all_keys(item)
    return keys


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
) -> None:
    """Append to llm_calls.

    Deliberately records no prompt text and no payload contents - only the
    metadata needed for cost control and audit. `unmatched_numbers` is the one
    fragment of model output kept, and by construction it contains only numerals
    the payload does NOT hold, so it cannot echo the computed figures back.
    """
    await db[CALLS_COLLECTION].insert_one({
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

    model = config["model"]
    mapping = await redaction.get_or_create_map(db, run_id, computed)
    outbound = redaction.redact(computed, mapping)

    # Last-line assertion: nothing from pseudonym_map may appear outbound.
    leaks = redaction.find_leaks(outbound, mapping)
    if leaks:
        logger.error("redaction leak for run %s: %d identifier(s)", run_id, len(leaks))
        return _unavailable(run_id, step, "redaction check failed", metrics)

    key = cache.cache_key(run_id, step, prompt.version, model, outbound)

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
        cost = estimate_cost_usd(model, in_tok, out_tok)

        # Hard tier: a fabricated figure in the headline or a table row, or a
        # row citing a source key that does not exist. Drop the narrative.
        if guard.hard or bad_keys:
            reason = bad_keys or (
                "model produced number(s) absent from the computed results in "
                f"headline/table rows: {', '.join(guard.hard[:8])}"
            )
            # The call still cost money, so it is logged and counted. Every
            # unmatched number is recorded, both tiers, for prompt tuning.
            await log_call(
                db, run_id=run_id, step=step, prompt_version=prompt.version, model=model,
                input_tokens=in_tok, output_tokens=out_tok, estimated_cost_usd=cost,
                cache_hit=False, status="numeric_guard_rejected",
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
        final = Narrative.model_validate(restored)

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
            cache_hit=False, status=exc.reason,
        )
        return _unavailable(run_id, step, str(exc), metrics)
    except Exception as exc:  # never let the gateway block the dashboard
        logger.exception("unexpected gateway failure for run %s step %s", run_id, step)
        return _unavailable(run_id, step, f"unexpected error: {type(exc).__name__}", metrics)
    finally:
        await guards.release(db, run_id, step, token)


async def _call_with_retries(adapter, config, prompt, outbound, sleep):
    """Provider call with two policies layered.

    Network/5xx: up to MAX_PROVIDER_RETRIES with exponential backoff.
    Malformed body: one reask (MAX_PARSE_RETRIES), then fail. A reask is a fresh
    provider call and is billed, which is why it is capped at one.
    """
    schema = Narrative.model_json_schema()
    system = prompt.text
    user_payload = cache.canonical_json(outbound)
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
                raise GatewayError("provider_unreachable", str(exc))
            await sleep(2 ** network_attempts * 0.5)
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

    model = config["model"]
    mapping = await redaction.get_or_create_map(db, run_id, computed)
    outbound = redaction.redact(computed, mapping)
    key = cache.cache_key(run_id, step, prompt.version, model, outbound)

    cached = await cache.get(db, key)
    if not cached:
        # Nothing matches the current numbers. If something was written for an
        # earlier version of this run, say so - the reader may remember it.
        return NarrativeResponse(
            run_id=run_id, step=step, narrative_status="not_generated",
            metrics=metrics, superseded=await cache.has_any(db, run_id, step),
        )

    # A read is not a call: it is not written to llm_calls, so the usage figures
    # keep counting generation attempts rather than page views.
    return NarrativeResponse(
        run_id=run_id, step=step,
        narrative_status=cached.get("narrative_status", "ok"),
        narrative=Narrative.model_validate(cached["narrative"]),
        cache_hit=True, prompt_version=prompt.version, model=model,
        metrics=metrics,
        unmatched_numbers=list(cached.get("unmatched_numbers", [])),
        generated_at=cached.get("created_at"),
    )


# ---------------------------------------------------------------------------
# Usage + cleanup
# ---------------------------------------------------------------------------
async def usage_for_run(db, run_id: str) -> UsageResponse:
    cursor = db[CALLS_COLLECTION].find({"run_id": run_id}, {"_id": 0})
    rows = await cursor.to_list(1000)
    billed = [r for r in rows if not r.get("cache_hit")]
    return UsageResponse(
        run_id=run_id,
        calls=len(billed),
        input_tokens=sum(int(r.get("input_tokens", 0)) for r in rows),
        output_tokens=sum(int(r.get("output_tokens", 0)) for r in rows),
        estimated_cost_usd=round(sum(float(r.get("estimated_cost_usd", 0.0)) for r in rows), 6),
        cache_hits=sum(1 for r in rows if r.get("cache_hit")),
        call_cap=guards.MAX_CALLS_PER_RUN,
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
    return {
        "llm_narratives": narratives,
        "llm_calls": getattr(calls, "deleted_count", 0),
        "pseudonym_map": getattr(pseudonyms, "deleted_count", 0),
        "llm_locks": getattr(locks, "deleted_count", 0),
    }
