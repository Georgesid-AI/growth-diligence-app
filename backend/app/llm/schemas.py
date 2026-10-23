"""Strict output contract for narrative generation.

The model is asked for JSON matching `Narrative` and nothing else. Parsing is
strict: anything that does not validate is a parse failure, which the gateway
retries once before giving up. Numbers in the narrative are the calc engine's,
never the model's - see `gateway.numeric_guard`.
"""
import copy
import math
import re
from typing import Annotated, Any, Dict, List, Literal, Optional, Sequence

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
    # Data inventory and data integrity only: the IC decision this row informs. Absent from growth_engine's schema.
    decision_informed: Optional[str] = None


class Narrative(BaseModel):
    """What the model must return. No extra keys are accepted."""

    model_config = {"extra": "forbid"}

    headline: str
    what_this_means: str
    table_rows: List[TableRow] = Field(default_factory=list)
    worth_flagging: List[str] = Field(default_factory=list)
    next_actions: List[str] = Field(default_factory=list)
    source_keys: List[str] = Field(default_factory=list)
    # Data integrity only: Reliable / Needs clarification / Material concerns. Absent from the other schemas.
    verdict: Optional[str] = None


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


def narrative_output_schema(decision: bool = False, verdicts: Sequence[str] = ()) -> dict:
    """The JSON schema to send as `output_config.format.schema`.

    Deep-copied before sealing so the contract above is described once and this
    transport detail never mutates what Pydantic hands back to other callers.

    `decision` adds the required "decision informed" column to the evidence table and `verdicts` the required verdict
    (data inventory and data integrity); without them the schema is the growth-engine one, unchanged.
    """
    schema = copy.deepcopy(Narrative.model_json_schema())
    row = schema["$defs"]["TableRow"]
    if decision:
        row["properties"]["decision_informed"] = {"type": "string", "title": "Decision Informed"}
        row["required"] = [*row["required"], "decision_informed"]
    else:
        row["properties"].pop("decision_informed", None)
    if verdicts:
        schema["properties"]["verdict"] = {"type": "string", "enum": list(verdicts), "title": "Verdict"}
        schema["required"] = [*schema.get("required", []), "verdict"]
    else:
        schema["properties"].pop("verdict", None)
    return _seal_objects(schema)


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
    # Per step: each narrative step by name, `deck_structure` (deck_id set) and `column_mapping` (no deck_id). The steps
    # add up to the totals above (their calls are `calls` + `structure_calls`).
    by_step: Dict[str, "DeckUsage"] = Field(default_factory=dict)


# ---------------------------------------------------------------------------
# Structure reading. Deck structures are labelled (docs/specs/structure-labelling.md section 3): Python lists
# every figure, the model labels each listed item and pairs a roadmap's lines with its dates. A column mapping
# keeps its own schema (llm-structure-reading.md section 1). No field is free text, so a reply cannot carry
# deck prose into a log: the one string a reply fills itself, unit_other, must be an ISO currency code.
# ---------------------------------------------------------------------------
DECK_TYPES = ("table", "chart", "kpi_panel", "roadmap", "hiring_table", "unit_economics", "use_of_funds")
STRUCTURE_TYPES = DECK_TYPES + ("column_mapping",)
# A file's type (chat-upload.md section 19): the third kind of structure read. It has its own schema and prompt and is
# not a member of STRUCTURE_TYPES, so the column-mapping and labelling schemas (and the cache keys built on them) stay as they were.
FILE_TYPE = "file_type"
FILE_TYPES = ("revenue", "crm", "pnl", "unknown")
# deck-parser.md section 2 claim types, "Use of funds", and the FIELD_DEFS fields of server.py. The
# gateway imports neither the deck package nor the server, so the lists are written out here and a
# test keeps them equal to claims.CLAIM_TYPES and FIELD_DEFS.
CLAIM_METRICS = ("revenue", "revenue_growth", "growth", "retention", "sales", "customers", "users", "user_growth",
                 "gross_margin", "gross_profit", "costs", "ebitda", "net_profit", "people", "product", "market",
                 "cash", "burn", "runway", "ltv", "cac", "customer_lifetime", "ltv_cac", "trials_per_day",
                 "months_to_profitability", "arpa", "arpu", "pipeline")
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
# A label's metric: a claim type, use of funds, "other" for a company figure that is none of them (listed as type
# Other), or "not_a_metric" for page numbers, years and footnote marks (dropped and counted).
LABEL_METRICS = CLAIM_METRICS + ("use_of_funds", "other", "not_a_metric")
ROADMAP_CATEGORIES = ("launch", "feature", "expansion", "partnership", "hiring", "break_even", "funding",
                      "certification", "other")
_CELL_ID = re.compile(r"^r[1-9]\d*c[1-9]\d*$")
_PERIOD = re.compile(r"^(?:\d{4}(?:-(?:Q[1-4]|H[12]|0[1-9]|1[0-2]))?|FY\d{4}(?:/\d{2})?)$")


def _period_format(v):
    if v is not None and not _PERIOD.match(v):
        raise ValueError("period must be YYYY, YYYY-Qn, YYYY-Hn, YYYY-MM, FY2025 or FY2025/26")
    return v


_MONTHS = ("jan", "feb", "mar", "apr", "may", "jun", "jul", "aug", "sep", "oct", "nov", "dec")
_MONTH = r"(?:jan(?:uary)?|feb(?:ruary)?|mar(?:ch)?|apr(?:il)?|may|june?|july?|aug(?:ust)?|sept?(?:ember)?|oct(?:ober)?|nov(?:ember)?|dec(?:ember)?)"
_SPAN_JOIN = r"\s*(?:-|\u2013|\u2014|to|until)\s*"
# "Jan-May 2022", "Q1-Q3 2022", "H1-H2 2022", "2022-2024", "FY22-24": two ends, so no one period.
_SPAN = re.compile(rf"(?i)^\s*(?:{_MONTH}\.?{_SPAN_JOIN}{_MONTH}\.?|[QH][1-4]{_SPAN_JOIN}[QH][1-4]|(?:FY\s*)?\d{{2,4}}{_SPAN_JOIN}\d{{2,4}})\b")


def _year(y: str) -> str:
    return y if len(y) == 4 else f"20{y}"


def normalise_period(v):
    """The allowed period form for a form a page commonly uses, before validation (George, 2026-10-23): "H2 2022" -> 2022-H2,
    "Q4 2021" -> 2021-Q4, "April 2022" -> 2022-04, "FY21/22" -> FY2021/22. A span ("Jan-May 2022", "2022-2024") is no period:
    None, and the claim stays. A form not listed here is returned as it came, for the format check to refuse."""
    if not isinstance(v, str) or _PERIOD.match(v):
        return v
    text = v.strip()
    if _PERIOD.match(text):
        return text
    if _SPAN.match(text):
        return None
    m = re.fullmatch(r"(?i)(?:fy|fiscal(?:\s+year)?)\s*[' ]?(\d{2}|\d{4})(?:\s*[/-]\s*(\d{2}|\d{4}))?", text)
    if m:
        first, second = _year(m.group(1)), m.group(2)
        return f"FY{first}" if second is None else f"FY{first}/{_year(second)[2:]}" if int(_year(second)) == int(first) + 1 else text
    m = re.fullmatch(r"(?i)([QH])([1-4])[\s,'-]*(\d{2}|\d{4})", text) or re.fullmatch(r"(?i)(\d{2}|\d{4})[\s,'-]*([QH])([1-4])", text)
    if m:
        kind, n, year = (m.group(1), m.group(2), m.group(3)) if m.group(1)[0].isalpha() else (m.group(2), m.group(3), m.group(1))
        if kind.upper() == "H" and n in "34":
            return text
        return f"{_year(year)}-{kind.upper()}{n}"
    m = re.fullmatch(rf"(?i)({_MONTH})\.?[\s,'-]*(\d{{2}}|\d{{4}})", text) or re.fullmatch(rf"(?i)(\d{{4}})[\s,'-]*({_MONTH})\.?", text)
    if m:
        name, year = (m.group(1), m.group(2)) if m.group(1)[0].isalpha() else (m.group(2), m.group(1))
        return f"{_year(year)}-{_MONTHS.index(name[:3].lower()) + 1:02d}"
    return text


def _other_currency(unit, unit_other):
    """unit_other is an ISO currency code outside the listed 20, beside unit "other", and null otherwise: never
    free text."""
    if unit == OTHER_UNIT:
        if unit_other not in ISO_CURRENCIES or unit_other in SCHEMA_CURRENCIES:
            raise ValueError("unit other needs the ISO code of a currency that is not listed")
    elif unit_other is not None:
        raise ValueError("unit_other is set only when unit is other")


class StructureItem(BaseModel):
    """One column a column-mapping reply maps, citing its header cell (llm-structure-reading.md section 1).
    Exactly these fields."""

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
    def _period(cls, v):
        return _period_format(v)

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
    def _unit_other(self):
        _other_currency(self.unit, self.unit_other)
        return self


class StructureReply(BaseModel):
    """What the model must return for a column mapping. No extra keys are accepted."""

    model_config = {"extra": "forbid"}

    type: Literal[STRUCTURE_TYPES]
    items: List[StructureItem]


class FileTypeReply(BaseModel):
    """What the model must return for a file's type: one closed word. No extra keys, no free text."""

    model_config = {"extra": "forbid"}

    type: Literal["file_type"]
    file_type: Literal[FILE_TYPES]


# Revenue file recognition (docs/specs/revenue-file-recognition.md section 5): the same prompt as the file type (`file_type`, version 2) asks
# one question per file and the reply names a sheet, a row, a column and closed words, never a confidence or free text. The label echo of
# `revenue_row` is compared by Python and dropped before anything is stored (section 5.5).
FILE_RECOGNITION = "file_recognition"
RECOGNITION_TYPES = ("invoice_transactions", "customer_revenue", "monthly_revenue_report", "revenue_summary", "financial_statements",
                     "arr_mrr_snapshot")
RECOGNITION_REPLY_TYPES = RECOGNITION_TYPES + ("crm", "pnl", "not_revenue")
NON_REVENUE_KINDS = ("forecast", "budget", "bookings", "pipeline", "contract_value", "run_rate")
RECOGNITION_MAX_SHEETS = 6
RECOGNITION_MAX_ROWS = 400


class RecognitionRow(BaseModel):
    model_config = {"extra": "forbid"}

    row: int = Field(ge=1)
    label: str = Field(min_length=1, max_length=200)


class RecognitionNonRevenue(BaseModel):
    model_config = {"extra": "forbid"}

    row: int = Field(ge=1)
    kind: Literal[NON_REVENUE_KINDS]


class FileRecognitionReply(BaseModel):
    """What the model must return for a file (spec section 5.7): exactly these keys, no confidence, no free text."""

    model_config = {"extra": "forbid"}

    type: Literal["file_recognition"]
    sheet: int = Field(ge=1, le=RECOGNITION_MAX_SHEETS)
    file_type: Literal[RECOGNITION_REPLY_TYPES]
    revenue_row: Optional[RecognitionRow]
    last_actual_column: Optional[int] = Field(ge=1)
    currency: Optional[str] = Field(pattern=r"^[A-Z]{3}$")
    non_revenue_rows: List[RecognitionNonRevenue] = Field(max_length=RECOGNITION_MAX_ROWS)


# The sheet skeleton (chat-upload.md section 26): a P&L the rules cannot map, read as a statement. Its own schema and prompt, outside
# STRUCTURE_TYPES like the file type, so no other schema or cache key moves. The reply names rows, columns and closed words only:
# Python rebuilds every period from its header cell and reads every figure from its cell (rule 18).
SHEET_STRUCTURE = "sheet_structure"
SHEET_GRAINS = ("month", "quarter", "half", "year", "ytd", "period_to_date")
SHEET_TAGS = ("actual", "forecast", "budget", "unknown")
SHEET_ROLES = ("heading", "total", "subline", "rate", "note", "other")
SHEET_MEANINGS = ("revenue", "cost_of_revenue", "sm_expense", "gross_margin", "opex", "ebitda", "arr", "mrr", "new_arr",
                  "churned_mrr", "churn_rate", "growth_rate", "bookings", "acv", "tcv", "customers", "headcount", "cash_balance",
                  "arpa", "subscriptions", "contracted_revenue", "other")
# How a line is measured (chat-upload.md section 26.15): month, quarter, ytd (running total for the year), ltm (last 12 months),
# lifetime, balance (value at period end).
SHEET_BASES = ("month", "quarter", "ytd", "ltm", "lifetime", "balance")
_SHEET_START = re.compile(r"^\d{4}-(?:0[1-9]|1[0-2])(?:-\d{2})?$")
SheetPosition = Annotated[int, Field(ge=1, strict=True)]


class SheetPeriod(BaseModel):
    """A period column as the model reads it: its column, grain, first month and tag. Python keeps only what it rebuilds."""

    model_config = {"extra": "forbid"}

    col: SheetPosition
    grain: Literal[SHEET_GRAINS]
    start: Optional[str]
    tag: Literal[SHEET_TAGS]

    @field_validator("start")
    @classmethod
    def _start(cls, v):
        if v is not None and not _SHEET_START.match(v):
            raise ValueError("start must be YYYY-MM or YYYY-MM-DD")
        return v


class SheetRow(BaseModel):
    """What one line of the sheet is: its role, the line it hangs from and its meaning. No figure, no text."""

    model_config = {"extra": "forbid"}

    row: SheetPosition
    role: Literal[SHEET_ROLES]
    parent_row: Optional[SheetPosition]
    meaning: Literal[SHEET_MEANINGS]
    basis: Optional[Literal[SHEET_BASES]] = None     # a reply without it keeps Python's reading from the label (26.15)


class SheetStructureReply(BaseModel):
    """What the model must return for a sheet skeleton. No extra keys. The gateway also checks every row and column against the
    skeleton it sent (gateway.parse_sheet_reply)."""

    model_config = {"extra": "forbid"}

    type: Literal["sheet_structure"]
    header_row: SheetPosition
    label_col: SheetPosition
    periods: List[SheetPeriod]
    rows: List[SheetRow]


def sheet_output_schema() -> dict:
    """The sheet skeleton's JSON schema, written by hand like the others: the start format, the positions and the rows against
    the skeleton are checked after the reply arrives."""
    period = {
        "type": "object",
        "properties": {"col": {"type": "integer"}, "grain": {"type": "string", "enum": list(SHEET_GRAINS)},
                       "start": _nullable({"type": "string"}), "tag": {"type": "string", "enum": list(SHEET_TAGS)}},
        "required": ["col", "grain", "start", "tag"],
        "additionalProperties": False,
    }
    row = {
        "type": "object",
        "properties": {"row": {"type": "integer"}, "role": {"type": "string", "enum": list(SHEET_ROLES)},
                       "parent_row": _nullable({"type": "integer"}),
                       "meaning": {"type": "string", "enum": list(SHEET_MEANINGS)},
                       "basis": _nullable({"type": "string", "enum": list(SHEET_BASES)})},
        "required": ["row", "role", "parent_row", "meaning", "basis"],
        "additionalProperties": False,
    }
    return {
        "type": "object",
        "properties": {"type": {"type": "string", "enum": [SHEET_STRUCTURE]}, "header_row": {"type": "integer"},
                       "label_col": {"type": "integer"}, "periods": {"type": "array", "items": period},
                       "rows": {"type": "array", "items": row}},
        "required": ["type", "header_row", "label_col", "periods", "rows"],
        "additionalProperties": False,
    }


class StructureLabel(BaseModel):
    """What one listed item measures. Exactly these fields: no value, cell id or flag (the values and cells are
    Python's, the flags Python's to compute). `item` must be a listed id: the gateway checks it."""

    model_config = {"extra": "forbid"}

    item: str
    metric: Literal[LABEL_METRICS]
    period: Optional[str]
    unit: Optional[Literal[STRUCTURE_UNITS]]
    unit_other: Optional[str]
    actual_or_forecast: Literal["actual", "forecast", "unknown"]

    @field_validator("period")
    @classmethod
    def _period(cls, v):
        return _period_format(v)

    @model_validator(mode="after")
    def _unit_other(self):
        _other_currency(self.unit, self.unit_other)
        return self


class RoadmapPair(BaseModel):
    """A roadmap text line paired with its date cell (ids the gateway checks against the list it sent), and the
    milestone's category."""

    model_config = {"extra": "forbid"}

    line: str
    date: str
    category: Literal[ROADMAP_CATEGORIES]


class LabellingReply(BaseModel):
    """What the model must return for a deck structure. No extra keys are accepted. The gateway also checks the
    ids against the item list it sent (gateway.parse_labelling_reply)."""

    model_config = {"extra": "forbid"}

    type: Literal[DECK_TYPES]
    labels: List[StructureLabel]
    pairs: List[RoadmapPair]


def _nullable(schema: dict) -> dict:
    return {"anyOf": [schema, {"type": "null"}]}


def labelling_output_schema() -> dict:
    """The JSON schema a deck structure's call sends as `output_config.format.schema`. Written by hand, as
    structure_output_schema is: the id formats and unit_other are checked by LabellingReply after the reply
    arrives, and the ids against the item list by the gateway."""
    label = {
        "type": "object",
        "properties": {
            "item": {"type": "string"},
            "metric": {"type": "string", "enum": list(LABEL_METRICS)},
            "period": _nullable({"type": "string"}),
            "unit": _nullable({"type": "string", "enum": list(STRUCTURE_UNITS)}),
            "unit_other": _nullable({"type": "string"}),
            "actual_or_forecast": {"type": "string", "enum": ["actual", "forecast", "unknown"]},
        },
        "required": ["item", "metric", "period", "unit", "unit_other", "actual_or_forecast"],
        "additionalProperties": False,
    }
    pair = {
        "type": "object",
        "properties": {"line": {"type": "string"}, "date": {"type": "string"},
                       "category": {"type": "string", "enum": list(ROADMAP_CATEGORIES)}},
        "required": ["line", "date", "category"],
        "additionalProperties": False,
    }
    return {
        "type": "object",
        "properties": {"type": {"type": "string", "enum": list(DECK_TYPES)},
                       "labels": {"type": "array", "items": label},
                       "pairs": {"type": "array", "items": pair}},
        "required": ["type", "labels", "pairs"],
        "additionalProperties": False,
    }


def output_schema(structure_type: str) -> dict:
    """The schema a call sends for its type: a column mapping and a file type keep their own, every deck type is labelled."""
    if structure_type == FILE_TYPE:
        return file_type_output_schema()
    if structure_type == SHEET_STRUCTURE:
        return sheet_output_schema()
    if structure_type == FILE_RECOGNITION:
        return file_recognition_output_schema()
    if structure_type == PAGE_CLAIMS:
        return page_claims_output_schema()
    return structure_output_schema() if structure_type == "column_mapping" else labelling_output_schema()


def file_recognition_output_schema() -> dict:
    """The recognition JSON schema (spec section 5.7): written by hand like the others; the limits are checked by FileRecognitionReply."""
    nullable = _nullable
    return {
        "type": "object",
        "properties": {
            "type": {"type": "string", "enum": [FILE_RECOGNITION]},
            "sheet": {"type": "integer"},
            "file_type": {"type": "string", "enum": list(RECOGNITION_REPLY_TYPES)},
            "revenue_row": nullable({"type": "object", "properties": {"row": {"type": "integer"}, "label": {"type": "string"}},
                                     "required": ["row", "label"], "additionalProperties": False}),
            "last_actual_column": nullable({"type": "integer"}),
            "currency": nullable({"type": "string"}),
            "non_revenue_rows": {"type": "array", "items": {
                "type": "object", "properties": {"row": {"type": "integer"}, "kind": {"type": "string", "enum": list(NON_REVENUE_KINDS)}},
                "required": ["row", "kind"], "additionalProperties": False}},
        },
        "required": ["type", "sheet", "file_type", "revenue_row", "last_actual_column", "currency", "non_revenue_rows"],
        "additionalProperties": False,
    }


def file_type_output_schema() -> dict:
    """The file-type JSON schema: the type word and nothing else."""
    return {
        "type": "object",
        "properties": {"type": {"type": "string", "enum": [FILE_TYPE]},
                       "file_type": {"type": "string", "enum": list(FILE_TYPES)}},
        "required": ["type", "file_type"],
        "additionalProperties": False,
    }


def structure_output_schema() -> dict:
    """The column-mapping JSON schema sent as `output_config.format.schema`. Written by hand: structured
    outputs take no array or string constraints, so the item limits (two period cells, the cell id and
    period formats, unit_other an ISO code beside unit "other") are checked by StructureReply after the
    reply arrives."""
    nullable = _nullable
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


# Page claims (docs/design/ai-reads-rules-check.md; CLAUDE.md rule 16 as amended 2026-10-22): the model reads the redacted text
# lines of deck pages that carry a figure as digits and returns claims. No free text: every field is a closed word, a number or
# the id of a cell it was sent (p<page>r<row>c<col>); the label is a cell id and Python reads its text, so rule 17 holds. The
# metric is CLAIM_METRICS or "other"; Python checks the figure, the unit and the period at cell level (app/structures/page_check.py)
# and never the metric. The gateway checks every cited id against the text it sent (gateway.parse_page_reply).
PAGE_CLAIMS = "page_claims"
# Added 2026-10-23 (George; engine contract 7): the seven words the register tells apart. Python maps each to a register claim type
# (decks.claims.PAGE_CLAIM_TYPE). The structure reads keep CLAIM_METRICS.
PAGE_METRICS = CLAIM_METRICS + ("arr", "mrr", "churn", "nrr", "market_share", "pricing", "use_of_funds", "other")
# What a page figure is (docs/design/ai-reads-rules-check.md, built 2026-10-22): an actual, a projection (a plan or forecast figure),
# or a scenario figure (one case of several); and which case. The register reads basis as its figure type (actual -> actual,
# projection and scenario -> target); the checker flags a scenario whose label is not on the page (structures/checker.py).
PAGE_BASES = ("actual", "projection", "scenario")
PAGE_SCENARIOS = ("best", "realistic", "worst", "none")
_PAGE_CELL_ID = re.compile(r"^p[1-9]\d*r[1-9]\d*c[1-9]\d*$")


def _page_cell(v, field):
    if v is not None and not _PAGE_CELL_ID.match(v):
        raise ValueError(f"{field} must be one page cell id like p5r4c3")
    return v


class PageClaim(BaseModel):
    """One claim read from a page. Exactly these fields."""

    model_config = {"extra": "forbid"}

    metric: Literal[PAGE_METRICS]
    value: Optional[float]
    value_high: Optional[float]
    unit: Optional[Literal[STRUCTURE_UNITS]]
    unit_other: Optional[str]
    period: Optional[str]
    basis: Literal[PAGE_BASES]
    scenario: Literal[PAGE_SCENARIOS]
    value_cell: str
    label_cell: Optional[str]
    period_cell: Optional[str]

    @field_validator("period", mode="before")
    @classmethod
    def _normal_period(cls, v):
        return normalise_period(v)

    @field_validator("period")
    @classmethod
    def _period(cls, v):
        return _period_format(v)

    @field_validator("value_cell")
    @classmethod
    def _value_cell(cls, v):
        return _page_cell(v, "value_cell")

    @field_validator("label_cell")
    @classmethod
    def _label_cell(cls, v):
        return _page_cell(v, "label_cell")

    @field_validator("period_cell")
    @classmethod
    def _period_cell(cls, v):
        return _page_cell(v, "period_cell")

    @field_validator("value", "value_high")
    @classmethod
    def _finite(cls, v):
        if v is not None and (math.isnan(v) or math.isinf(v)):
            raise ValueError("a value must be a finite number")
        return v

    @model_validator(mode="after")
    def _consistent(self):
        _other_currency(self.unit, self.unit_other)
        if self.value is None and self.value_high is not None:
            raise ValueError("value_high needs a value")
        return self


class PageClaimsReply(BaseModel):
    """What the model must return for a batch of pages. No extra keys are accepted."""

    model_config = {"extra": "forbid"}

    type: Literal[PAGE_CLAIMS]
    claims: List[PageClaim]


class PageReplyTop(BaseModel):
    """The page reply's top-level object: the type word and a list. Each claim is validated on its own by gateway.parse_page_reply, so
    one invalid claim drops that claim and not the reply."""

    model_config = {"extra": "forbid"}

    type: Literal[PAGE_CLAIMS]
    claims: List[Any]


def page_claims_output_schema() -> dict:
    """The JSON schema a page batch's call sends as `output_config.format.schema`. Written by hand like the others: the id and
    period formats and unit_other are checked by PageClaim after the reply arrives, the ids against the text by the gateway."""
    nullable = _nullable
    claim = {
        "type": "object",
        "properties": {
            "metric": {"type": "string", "enum": list(PAGE_METRICS)},
            "value": nullable({"type": "number"}),
            "value_high": nullable({"type": "number"}),
            "unit": nullable({"type": "string", "enum": list(STRUCTURE_UNITS)}),
            "unit_other": nullable({"type": "string"}),
            "period": nullable({"type": "string"}),
            "basis": {"type": "string", "enum": list(PAGE_BASES)},
            "scenario": {"type": "string", "enum": list(PAGE_SCENARIOS)},
            "value_cell": {"type": "string"},
            "label_cell": nullable({"type": "string"}),
            "period_cell": nullable({"type": "string"}),
        },
        "required": ["metric", "value", "value_high", "unit", "unit_other", "period", "basis", "scenario", "value_cell",
                     "label_cell", "period_cell"],
        "additionalProperties": False,
    }
    return {
        "type": "object",
        "properties": {"type": {"type": "string", "enum": [PAGE_CLAIMS]},
                       "claims": {"type": "array", "items": claim}},
        "required": ["type", "claims"],
        "additionalProperties": False,
    }


StructureStatus = Literal["read", "not_read", "too_large", "truncated", "stopped", "no_consent", "refused"]


class StructureRead(BaseModel):
    """What read_structure returns: the validated model output, never the text that was sent. A deck
    structure's `labels` (one per listed item id) and `pairs` (a roadmap's lines and dates); a column
    mapping's `items` (fields with the header cells they cite); a page batch's `claims`."""

    status: StructureStatus
    reason: Optional[str] = None
    rejected: Optional[str] = None          # a page reply that failed validation: the check and schema fields, closed words, never the reply
    type: str
    model_type: Optional[str] = None
    file_type: Optional[str] = None
    sheet: Optional[dict] = None            # a sheet skeleton's reply: header row, label column, periods and rows
    recognition: Optional[dict] = None      # a file recognition reply (spec 5.7); in memory it still holds the label echo, stored it does not
    items: List[dict] = Field(default_factory=list)
    labels: List[dict] = Field(default_factory=list)
    pairs: List[dict] = Field(default_factory=list)
    claims: List[dict] = Field(default_factory=list)     # a page batch's claims (PageClaimsReply), cells cited by page id
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
