"""Strict output contract for narrative generation.

The model is asked for JSON matching `Narrative` and nothing else. Parsing is
strict: anything that does not validate is a parse failure, which the gateway
retries once before giving up. Numbers in the narrative are the calc engine's,
never the model's - see `gateway.numeric_guard`.
"""
import copy
from typing import Any, List, Literal, Optional

from pydantic import BaseModel, Field


class TableRow(BaseModel):
    """One row of the narrative's summary table.

    `source_key` is the key the value arrived under in the computed-results
    payload. The model must echo it back so every rendered figure can be traced
    to the engine output it came from.
    """

    label: str
    value: str
    source_key: str


class Narrative(BaseModel):
    """What the model must return. No extra keys are accepted."""

    model_config = {"extra": "forbid"}

    headline: str
    what_this_means: str
    table_rows: List[TableRow] = Field(default_factory=list)
    worth_flagging: List[str] = Field(default_factory=list)
    next_actions: List[str] = Field(default_factory=list)
    source_keys: List[str] = Field(default_factory=list)


# "flagged" means the narrative is shown but carries numbers the calc engine did
# not produce, in prose fields only. Hard violations (headline, table rows) are
# never shown - those become "unavailable".
# "not_generated" means nobody has asked yet - distinct from "unavailable",
# which means generation was attempted and failed.
NarrativeStatus = Literal["ok", "flagged", "unavailable", "not_generated"]


def _seal_objects(node: Any) -> Any:
    """Set `additionalProperties: false` on every object node, recursively.

    Structured outputs reject a schema where any object omits it:

        output_config.format.schema: For 'object' type,
        'additionalProperties' must be explicitly set to false

    Pydantic emits it for the root model (from `extra="forbid"`) but not for
    nested models, so `TableRow` under `$defs` comes back without it and the
    whole request 400s. Walking the tree covers `$defs`, array `items`, and any
    `anyOf`/`oneOf` branch without having to enumerate them.

    A node carrying `properties` is treated as an object even if `type` is
    absent, since that is the same shape by another spelling. Note this seals
    free-form mappings too - the Narrative contract has none, and if one is
    added it will need an explicit carve-out rather than silently forbidding
    every key.
    """
    if isinstance(node, dict):
        if node.get("type") == "object" or "properties" in node:
            node["additionalProperties"] = False
        for value in node.values():
            _seal_objects(value)
    elif isinstance(node, list):
        for item in node:
            _seal_objects(item)
    return node


def narrative_output_schema() -> dict:
    """The JSON schema to send as `output_config.format.schema`.

    Deep-copied before sealing so the contract above is described once and this
    transport detail never mutates what Pydantic hands back to other callers.
    """
    return _seal_objects(copy.deepcopy(Narrative.model_json_schema()))


class NarrativeResponse(BaseModel):
    """What the API returns. `metrics` is always present so the dashboard can
    render with or without a narrative - the gateway must never block it."""

    run_id: str
    step: str
    narrative_status: NarrativeStatus
    narrative: Optional[Narrative] = None
    reason: Optional[str] = None
    cache_hit: bool = False
    prompt_version: Optional[str] = None
    model: Optional[str] = None
    metrics: dict = Field(default_factory=dict)
    # Numbers the model produced that are absent from the computed results.
    # Populated when narrative_status is "flagged"; also carries the hard
    # violations that caused an "unavailable", so the prompt can be tuned.
    unmatched_numbers: List[str] = Field(default_factory=list)
    # When the stored narrative was written, so the UI can say "Written 28 Sep 2026".
    generated_at: Optional[str] = None
    # True when no narrative matches the current numbers but one exists for an
    # earlier version of this run and step - i.e. the data moved on.
    superseded: bool = False


class UsageResponse(BaseModel):
    run_id: str
    calls: int
    input_tokens: int
    output_tokens: int
    estimated_cost_usd: float
    cache_hits: int
    call_cap: int
