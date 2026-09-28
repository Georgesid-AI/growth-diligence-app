"""Strict output contract for narrative generation.

The model is asked for JSON matching `Narrative` and nothing else. Parsing is
strict: anything that does not validate is a parse failure, which the gateway
retries once before giving up. Numbers in the narrative are the calc engine's,
never the model's - see `gateway.numeric_guard`.
"""
from typing import List, Literal, Optional

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


NarrativeStatus = Literal["ok", "unavailable"]


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


class UsageResponse(BaseModel):
    run_id: str
    calls: int
    input_tokens: int
    output_tokens: int
    estimated_cost_usd: float
    cache_hits: int
    call_cap: int
