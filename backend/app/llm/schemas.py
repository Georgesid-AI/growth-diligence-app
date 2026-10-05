"""Strict output contract for narrative generation.

The model is asked for JSON matching `Narrative` and nothing else. Parsing is
strict: anything that does not validate is a parse failure, which the gateway
retries once before giving up. Numbers in the narrative are the calc engine's,
never the model's - see `gateway.numeric_guard`.
"""
import copy
import math
import re
from typing import Any, Dict, List, Literal, Optional

from pydantic import BaseModel, Field, field_validator, model_validator

from .. import formatting


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
SupersededReason = Literal["data_changed", "prompt_release_changed", "model_changed"]

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
    # Why a stored narrative is not being served, when one exists: the numbers moved on,
    # the prompt release changed, or the model changed. The reader needs to know which,
    # since "the data changed" would be false for the last two.
    superseded_reason: Optional[SupersededReason] = None
    # Plain-English name for each table row, keyed by the row's source_key. Filled
    # in from the narrative at response time and never sent to or read from the
    # model, so the path stays the citation and this is only what is shown.
    row_labels: Dict[str, str] = Field(default_factory=dict)

    @model_validator(mode="after")
    def _fill_row_labels(self):
        if self.narrative is not None and not self.row_labels:
            self.row_labels = {
                r.source_key: formatting.display_name(r.source_key, r.label)
                for r in self.narrative.table_rows
            }
        return self


class UsageResponse(BaseModel):
    run_id: str
    calls: int                      # narrative calls billed; the call cap counts these only
    input_tokens: int
    output_tokens: int
    estimated_cost_usd: float
    cache_hits: int
    call_cap: int
    structure_calls: int = 0        # structure reading calls billed, capped by tokens instead
    structure_tokens: int = 0
    structure_token_cap: int = 0
    by_deck: Dict[str, "DeckUsage"] = Field(default_factory=dict)


# ---------------------------------------------------------------------------
# Structure reading (docs/specs/llm-structure-reading.md section 1). One schema for every type.
# No field is free text, so a reply cannot carry deck prose into a log: the one string an item fills
# itself, unit_other, must be an ISO currency code.
# ---------------------------------------------------------------------------
DECK_TYPES = ("table", "chart", "kpi_panel", "roadmap", "hiring_table", "unit_economics", "use_of_funds")
STRUCTURE_TYPES = DECK_TYPES + ("column_mapping",)
# deck-parser.md section 2 claim types, "Use of funds", and the FIELD_DEFS fields of server.py. The
# gateway imports neither the deck package nor the server, so the lists are written out here and a
# test keeps them equal to claims.CLAIM_TYPES and FIELD_DEFS.
CLAIM_METRICS = ("revenue", "revenue_growth", "growth", "retention", "sales", "customers", "users", "user_growth",
                 "gross_margin", "gross_profit", "costs", "ebitda", "net_profit", "people", "product", "market")
MAPPING_FIELDS = ("customer_id", "invoice_date", "amount", "currency", "service_start", "service_end", "segment",
                  "revenue_type", "deal_id", "created_date", "close_date", "stage", "founder_involved", "month",
                  "sm_expense", "revenue", "cost_of_revenue")
STRUCTURE_METRICS = CLAIM_METRICS + ("use_of_funds",) + tuple(f for f in MAPPING_FIELDS if f not in CLAIM_METRICS)
ISO_CURRENCIES = tuple("""AED AFN ALL AMD ANG AOA ARS AUD AWG AZN BAM BBD BDT BGN BHD BIF BMD BND BOB BRL BSD BTN BWP
BYN BZD CAD CDF CHF CLP CNY COP CRC CUP CVE CZK DJF DKK DOP DZD EGP ERN ETB EUR FJD FKP GBP GEL GHS GIP GMD GNF
GTQ GYD HKD HNL HTG HUF IDR ILS INR IQD IRR ISK JMD JOD JPY KES KGS KHR KMF KPW KRW KWD KYD KZT LAK LBP LKR LRD
LSL LYD MAD MDL MGA MKD MMK MNT MOP MRU MUR MVR MWK MXN MYR MZN NAD NGN NIO NOK NPR NZD OMR PAB PEN PGK PHP PKR
PLN PYG QAR RON RSD RUB RWF SAR SBD SCR SDG SEK SGD SHP SLE SOS SRD SSP STN SVC SYP SZL THB TJS TMT TND TOP TRY
TTD TWD TZS UAH UGX USD UYU UZS VES VND VUV WST XAF XCD XOF XPF YER ZAR ZMW ZWL""".split())
# The schema lists 20 currencies; any other ISO currency is unit "other", with its code in unit_other. The full
# ISO list stays here, to check unit_other, and is never sent: its enum cost every call input tokens.
SCHEMA_CURRENCIES = ("EUR", "USD", "GBP", "CHF", "BGN", "RON", "PLN", "CZK", "HUF", "SEK", "NOK", "DKK", "TRY", "UAH",
                     "RSD", "JPY", "CNY", "INR", "AUD", "CAD")
OTHER_UNIT = "other"
STRUCTURE_UNITS = SCHEMA_CURRENCIES + (OTHER_UNIT, "%", "x", "count", "days", "months", "years")
STRUCTURE_FLAGS = ("total_mismatch", "growth_mismatch")
_CELL_ID = re.compile(r"^r[1-9]\d*c[1-9]\d*$")
_PERIOD = re.compile(r"^(?:\d{4}(?:-(?:Q[1-4]|H[12]|0[1-9]|1[0-2]))?|FY\d{4}(?:/\d{2})?)$")


class StructureItem(BaseModel):
    """One figure the model read, with the cells it cites. Exactly these fields."""

    model_config = {"extra": "forbid"}

    metric: Literal[STRUCTURE_METRICS]
    period: Optional[str]
    value: Optional[float]
    unit: Optional[Literal[STRUCTURE_UNITS]]
    unit_other: Optional[str]
    actual_or_forecast: Literal["actual", "forecast", "unknown"]
    value_cell: str
    period_cells: List[str]
    proposed_flags: List[Literal[STRUCTURE_FLAGS]]

    @field_validator("period")
    @classmethod
    def _period_format(cls, v):
        if v is not None and not _PERIOD.match(v):
            raise ValueError("period must be YYYY, YYYY-Qn, YYYY-Hn, YYYY-MM, FY2025 or FY2025/26")
        return v

    @field_validator("value_cell")
    @classmethod
    def _cell_format(cls, v):
        if not _CELL_ID.match(v):
            raise ValueError("value_cell must be one cell id like r4c3")
        return v

    @field_validator("period_cells")
    @classmethod
    def _period_cells(cls, v):
        if len(v) > 2 or not all(_CELL_ID.match(c) for c in v):
            raise ValueError("period_cells holds at most two cell ids")
        return v

    @field_validator("value")
    @classmethod
    def _finite(cls, v):
        if v is not None and (math.isnan(v) or math.isinf(v)):
            raise ValueError("value must be a finite number")
        return v

    @model_validator(mode="after")
    def _other_currency(self):
        """unit_other is an ISO currency code outside the listed 20, beside unit "other", and null otherwise:
        never free text."""
        if self.unit == OTHER_UNIT:
            if self.unit_other not in ISO_CURRENCIES or self.unit_other in SCHEMA_CURRENCIES:
                raise ValueError("unit other needs the ISO code of a currency that is not listed")
        elif self.unit_other is not None:
            raise ValueError("unit_other is set only when unit is other")
        return self


class StructureReply(BaseModel):
    """What the model must return for one structure. No extra keys are accepted."""

    model_config = {"extra": "forbid"}

    type: Literal[STRUCTURE_TYPES]
    items: List[StructureItem]


def structure_output_schema() -> dict:
    """The JSON schema sent as `output_config.format.schema`. Written by hand: structured outputs take
    no array or string constraints, so the item limits (two period cells, the cell id and period
    formats, unit_other an ISO code beside unit "other") are checked by StructureReply after the reply
    arrives."""
    nullable = lambda schema: {"anyOf": [schema, {"type": "null"}]}  # noqa: E731
    item = {
        "type": "object",
        "properties": {
            "metric": {"type": "string", "enum": list(STRUCTURE_METRICS)},
            "period": nullable({"type": "string"}),
            "value": nullable({"type": "number"}),
            "unit": nullable({"type": "string", "enum": list(STRUCTURE_UNITS)}),
            "unit_other": nullable({"type": "string"}),
            "actual_or_forecast": {"type": "string", "enum": ["actual", "forecast", "unknown"]},
            "value_cell": {"type": "string"},
            "period_cells": {"type": "array", "items": {"type": "string"}},
            "proposed_flags": {"type": "array", "items": {"type": "string", "enum": list(STRUCTURE_FLAGS)}},
        },
        "required": ["metric", "period", "value", "unit", "unit_other", "actual_or_forecast", "value_cell",
                     "period_cells", "proposed_flags"],
        "additionalProperties": False,
    }
    return {
        "type": "object",
        "properties": {"type": {"type": "string", "enum": list(STRUCTURE_TYPES)},
                       "items": {"type": "array", "items": item}},
        "required": ["type", "items"],
        "additionalProperties": False,
    }


StructureStatus = Literal["read", "not_read", "too_large", "stopped", "no_consent", "refused"]


class StructureRead(BaseModel):
    """What read_structure returns. `items` is the validated model output (values with cell
    references), never the text that was sent."""

    status: StructureStatus
    reason: Optional[str] = None
    type: str
    model_type: Optional[str] = None
    items: List[dict] = Field(default_factory=list)
    key: Optional[str] = None
    cache_hit: bool = False
    input_tokens: int = 0
    output_tokens: int = 0
    estimated_cost_usd: float = 0.0
    prompt_version: Optional[str] = None
    model: Optional[str] = None


class DeckUsage(BaseModel):
    calls: int = 0
    cache_hits: int = 0
    input_tokens: int = 0
    output_tokens: int = 0
    estimated_cost_usd: float = 0.0


UsageResponse.model_rebuild()
