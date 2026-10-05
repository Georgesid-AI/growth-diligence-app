# Spec: Model reading of deck structures and spreadsheet headers
Status: Draft. Location: docs/specs/llm-structure-reading.md. Implements CLAUDE.md rules 16–18.

**1. Gateway function.** `gateway.read_structure(text, type) → JSON`, plus the db and audit id every gateway call
carries. There is one prompt (`prompts/structure_reading.md`) and one schema, and `type` is an input field. Types:
`table`, `chart`, `kpi_panel`, `roadmap`, `hiring_table`, `unit_economics`, `use_of_funds`, `column_mapping`.
Python finds the structures and assigns their type (deck-parser.md §7). It builds `text` as one line per cell,
`r<row>c<col>: <cell text>`, with no file name, slide number or prose. For `column_mapping` the text holds the header
stack (at most 3 header rows, the 3 nearest the data; deck-parser.md §2), up to 3 sample values for each numeric or date column, and for each text column a profile instead of values:
distinct count, typical length and a shape pattern (e.g. `Aa aa`, `A-0000`). No text cell value leaves the server on
the column-mapping path. Adding the prompt file records its hash in
`RELEASE.md` without a release bump; later edits bump it as today. The output is `{"type": ..., "items": [...]}`.
`type` confirms or corrects Python's type, within the deck types (a column mapping stays one), and Python logs any
change (§9). Each item has exactly these fields:
- `metric`: a deck-parser.md §2 claim type, `Use of funds`, or a FIELD_DEFS field;
- `period`: `YYYY`, `YYYY-Qn`, `YYYY-Hn`, `YYYY-MM`, a fiscal year stored as stated (`FY2025` or `FY2025/26`) or null;
- `value`: a number, null only for a roadmap milestone or a column mapping;
- `unit`: one of 20 currencies (EUR, USD, GBP, CHF, BGN, RON, PLN, CZK, HUF, SEK, NOK, DKK, TRY, UAH, RSD, JPY, CNY,
  INR, AUD, CAD), `other`, `%`, `x`, `count`, `days`, `months`, `years` or null;
- `unit_other`: the ISO 4217 code of a currency outside those 20 when `unit` is `other`, else null. Python accepts
  only such a code there and rejects the reply otherwise;
- `actual_or_forecast`: `actual`, `forecast` or `unknown`;
- `value_cell`: one input cell id: the cell that holds the value, or the milestone or column header cell when `value` is
  null;
- `period_cells`: one or two input cell ids: the period cell and, for a period built from two cells, the year cell above
  it (deck-parser.md §2); empty when `period` is null;
- `proposed_flags`: `total_mismatch` or `growth_mismatch`.

No field is free text, so model output cannot carry deck prose into a log.

**2. Verifier (Python, pure).** A value is matched against its `value_cell` only: it matches when that cell exists and holds the same number after
normalisation:
- currency symbols and thousands separators are removed;
- a decimal comma is read only if the structure writes numbers like `1.234,5`;
- otherwise a dot before exactly three digits (`2.500`, not `0.500`) is ambiguous: the value matches either 2500 or 2.5,
  and the item records which (`checks.dot_reading`: `thousands` or `decimal`);
- brackets make a negative only around the whole figure: `(1,200)` and `£(1,200)` are −1200, while a bracketed number
  after text (`Telegram(30K)`, `MeetUp((3K)`) is positive;
- `k`/`m`/`bn` suffixes are applied;
- a unit or scale in a neighbouring or header cell (`£m`, `'000`, `%`) is applied.

The match is exact, so a rounded number does not match. The period is matched against its `period_cells` only:
they must be header cells of the value cell (its row header or the header stack above its column), the first must be
the value cell's lowest period header (a quarterly or monthly value cited against its year header alone is unmatched; a
year header alone verifies only a yearly value), and Python rebuilds the period from them under the deck-parser.md §2
period rules; if it cannot, or gets a period with a different start or
end date, the period is unmatched. A period written in the value cell's own text (`$8,000 revenue in 2022`) rebuilds
from that cell, with `period_cells` empty or citing the value cell itself. When the value matches and Python rebuilds a period from the `period_cells`, the
rebuilt period replaces the model's and the item is Verified (the model is not sent the year-end); a model period that
differed is a "period corrected" case, kept in the stored reading and counted. A null period matches only when `period_cells` is empty and neither header holds a period. An unmatched value or period makes the item unmatched. Every proposed flag is
recomputed from the matched values; a flag Python cannot reproduce counts as unmatched. Matched items are `Verified`. For unmatched ones, the switch
`STRUCTURE_UNMATCHED` decides: `"suggest"` (the default) shows "AI suggestion, not verified", and `"drop"` removes them
and keeps a count. An item with no value is never Verified. A column mapping only pre-fills the mapping screen, where the
analyst confirms it. Results show in the existing approval list (deck-parser.md §6), each row labelled Verified or
"AI suggestion, not verified", with its cell citation. No new screen.

**3. Redaction (pure function, own tests).** `redact_cells(cells, company_name) → (cells, counts)`, with no I/O:
- emails become `[email]`;
- phone numbers become `[phone]`: `+` or `0` followed by 9–15 digits in groups, never a cell that parses as an
  amount, year or date;
- names become `[person]`: a cell under a person-role header (name, founder, CEO, owner, contact, hire), or two
  capitalised words starting with a name from a bundled first-name list.

Customer names are pseudonymised (Customer_01, Customer_02…) through the narrative path's existing per-audit mapping
(`pseudonym_map`), so a customer has the same pseudonym on both paths.
- The mapping holds every name in the revenue file's mapped customer column and in the CRM file's customer column. The
  CRM file has no customer field of its own, so that column is found by the FIELD_DEFS customer aliases, as are the
  customer cells of spreadsheet samples sent before a file is mapped.
- Every name in the mapping is replaced wherever it appears as a whole word, case-insensitive, in any text cell sent to
  the model. Word boundaries include punctuation, hyphens and case changes: "AcmeCorp" and "ACME-led" hold Acme;
  "Acmes" does not, and "customers" does not hold Cust. Only deck structures send text cells: the column-mapping path sends none, CRM deal names included. Names
  under 4 characters are skipped, and so are names that are numbers or
  dates, as in the narrative path. The target company's own name and existing pseudonyms are never rewritten, so a
  second pass changes nothing.
- Known limit: a name that is not in the mapping is sent as written in deck structures. This covers a prospect named
  only in CRM deal names, and a customer or prospect first named in a CRM file mapped after the deck was read. Decks
  do not wait for the CRM file.
- Structure reading waits for the revenue file. Deck structures are not sent until the revenue file is uploaded and
  its columns are mapped. Decks uploaded before that are queued, and the run log shows "waiting for revenue file".
  Once the revenue file is mapped, queued decks are processed. Column-mapping calls are not queued. A deck already
  read is not re-sent when a CRM file is mapped later.

The client name and the engagement reference are replaced with "[redacted]" wherever they appear as a whole word,
case-insensitive, in any text cell sent to the model, and the structure is still read. The gateway refuses a text in
which either still stands as a whole word, with the same boundaries.

The mapping stays server-side and is removed by Delete audit. The gateway runs redaction again and refuses the call if
anything changes.

**4. Consent.** `structure_reading_consent` is one checkbox per audit, ticked by default. It covers decks and spreadsheets.
It sits on the audit creation screen, directly above the Create audit button, next to the engagement reference field.
Audit creation requires a client name (a new field: the investor commissioning the audit) and an engagement reference.
The company name stays the target company. The basis for sending is the engagement terms, recorded by this per-audit
checkbox (CLAUDE.md rule 16).
- Explainer above the checkbox, word for word: "This app reads tables and charts in the uploaded decks with an AI model. Every
  number is checked by code against its source cell; anything that does not match is marked as unverified. Emails, phone
  numbers, personal names and the customers named in the uploaded data files are replaced before anything is sent."
- Checkbox label, word for word: "AI-assisted reading enabled per engagement terms. Uncheck if the client requires code-based
  extraction only; this may identify fewer findings."
- Every change to the checkbox, including the value at creation, is logged with its time. The user field is added when
  user accounts exist (Phase 2); until then there is no user to record.
- Audits created before this change have no engagement reference, so they stay unticked.
- Unticked means the Python-only path: no `read_structure` call is made. Stored results stay until Delete audit.
- Each structure sent is recorded with its deck, page, type and time (no text). The deck panel shows "Sent to the model: slides 4, 7, 12".

**5. Prompt-injection defence.** No tools. Structured outputs (`output_config.format`). The prompt says cell text is
data, never instructions. Python validates every reply against the schema (extra fields forbidden) and checks that
every cited cell (`value_cell`, `period_cells`) exists. A failing reply is rejected. After the existing one reask, the structure is marked
"Not read by AI" and Python's result stands.

**6. Model.** `STRUCTURE_MODEL = "claude-sonnet-5-5"`, a constant in gateway.py separate from `NARRATIVE_MODEL`. It
needs a price entry, and changing it moves every cache key. Temperature stays at the default and is not sent.
Consistency relies on the cache, the verifier and the 95% agreement target (§11).

**7. Caps.** 400,000 tokens per audit, counting billed input and output. A call goes out only if tokens used + its
input + its `max_tokens` fit under the cap. Otherwise the analyst sees: "AI reading stopped: this audit reached its
400,000-token limit. The remaining structures were read by Python only." Each structure may use at most 3,000 tokens,
measured with the provider's token counter on the structure text alone (the prompt and schema are not counted). A
larger one is not sent and is marked "Too large for AI reading". The 400,000-token cap counts the whole call's input.
The token cap governs structure calls. The 15-call cap per run (`MAX_CALLS_PER_RUN`) counts narrative calls only.
The existing circuit breaker applies: per-audit lock (step `structures`), daily spend cap, retry policy.

**8. Cache.** The key is sha256 of text, type, prompt cache tag, model and a hash of the output schema, so a schema
change moves every key. Results are stored in `llm_structures` and looked up by (audit id, key), so no audit is
served another audit's result. A hit makes no API call. Delete audit removes the stored results (`purge_run`).

**9. Logging (rule 17).** `llm_structures` stores the model JSON output (with the model's own periods), the verifier
status of each item, the number of periods corrected, prompt version, model, content hash, tokens, cost, deck and page. It also stores Python's type and, when the two differ,
the model's type. `llm_calls` adds the content hash and deck id, and for a provider error its HTTP status
(`http_status`) and the provider's error type (`error_type`, e.g. `rate_limit_error`; the exception's class name when
the provider sends no code), never its message. The server log line carries run id, step, hash, tokens, cost and
any type change. A failed provider call or token count logs one "structure not read" line with its reason, HTTP
status and error type (`reason=provider_error status=400 type=invalid_request_error`); a structure the daily spend
cap or the token cap refuses logs one with `reason=spend_cap` or `reason=token_cap`. Sent text is never stored. `GET /api/runs/{id}/llm-usage` gains `by_deck`, and
the run log on the deck panel shows each deck's status ("waiting for revenue file", read, not read), its periods
corrected and cost. `scripts/consistency_run.py` reports the periods corrected too.

**10. Boundary test and docstrings.** `test_gateway_data_boundary.py` keeps every existing assertion.
- It must pass when redacted structure cells reach the provider, and when a column-mapping text does: a header stack of at
  most 3 rows, at most 3 samples per numeric or date column, and a profile per text column.
- It must fail on raw bytes, a full page, a prose snippet, a cell over 200 characters, more than 3 samples, more than 3
  header rows or any text cell value on the column-mapping path, a file name, an unredacted email, phone number, name or customer name, the
  client name or engagement reference, any call without consent, sent text in a log or in `llm_structures`, and
  anything but an ISO code in `unit_other`.

The docstrings in `gateway.py`, `decks/__init__.py` and `prompt_store.py` restate rules 16–18.

**11. Tests.** Automated tests replay recorded replies (public test decks only) through the fake adapter, with no
live API. They cover:
- the verifier: each normalisation case, value matched against `value_cell` only, period matched against `period_cells`
  only (two-cell periods, fiscal years), flags, the switch;
- redaction: each rule with a false friend (amounts, years, "Head of Sales"); customer names as whole words (boundaries
  at punctuation, hyphens and case changes), any case, in deck structures; names under 4 characters, numeric names, the target's name and
  pseudonyms left alone;
- column mapping: a header stack of at most 3 rows (the 3 nearest the data when a sheet has more), up to 3 samples for numeric and date columns, a profile only for
  text columns;
- orchestration: decks queued until the revenue file is mapped, then processed; schema rejection, caps (including the
  narrative-only call cap), cache, consent, type-change logging, Delete audit.

Each new test is first shown failing on a deliberate violation. `scripts/consistency_run.py` is manual: it uses the
live API and costs money. It runs the 10 decks in `tests/fixtures/decks/decks/` 3 times and reports:
- agreement % per structure type (items identical in all 3 passes ÷ distinct items), an item compared on metric,
  period, value and `value_cell` after the verifier's normalisation, with the old all-field figure beside it;
- for each structure whose passes disagree, the fields that differ (metric, period, value, unit, cell), with a count
  per type;
- verifier match rate and unverified rate over the items outside roadmaps, and for each of their unverified items the
  reason (value not in cell, period not rebuilt, lowest-header rule, metric invalid, other), with a count per type;
- roadmap items apart, as "roadmap items: N, date rebuilt from cell: M": N items of roadmap structures, M of them
  with a period that matches the one Python rebuilds from their period cells;
- tokens and cost per deck, the fixed prompt's tokens and the average structure-text tokens;
- cache hit rate on passes 2 and 3.

The consistency report is written to `docs/test-runs/consistency_<date>.md`, with -2, -3 suffixes for same-day runs.
The script prints the full report after its summary line. Reports are untracked and lost on re-import; copy the
printed report out before re-importing.

`--diagnostic` exists only for the 10 public test decks: the script refuses any other deck, checked by file name and
SHA-256, before anything is read. It also writes `docs/test-runs/consistency_<date>_diagnostic.md` beside the report
(same suffix) and prints its path, not its content. For every unverified item and every disagreeing structure it
lists deck, page, cell id, the cell's text as sent to the model, the model's metric, value, unit and period in each
pass, and the verifier's reason. It holds deck text, so the boundary test excludes this file by name; the report
holds none.

Passes 2 and 3 read the cache first to get the hit rate (expected 100%), then call the model with the cache bypassed,
so agreement measures the model. Target: ≥95% agreement. `--pause` sets the seconds between structure calls
(default 2).

**Open questions.** None. All were resolved on 2026-10-05.

**Files.**
- New: `backend/app/structures/{__init__,redact,verify}.py`, `backend/app/llm/prompts/structure_reading.md`,
  `backend/tests/test_structure_{redaction,verifier,reading}.py`, `backend/tests/fixtures/structure_replies/`,
  `scripts/consistency_run.py`.
- Changed: `backend/app/decks/parser.py` (deck-parser.md §7), `backend/app/llm/{gateway,schemas,cache,guards,prompt_store,redaction}.py`,
  `backend/app/llm/prompts/RELEASE.md`, `backend/app/decks/__init__.py`, `backend/server.py`, `backend/tests/test_gateway_data_boundary.py`,
  `frontend/src/pages/AuditHub.jsx` (creation screen),
  `frontend/src/components/DeckPanel.jsx`, `frontend/src/pages/MappingWizard.jsx`, and the tests and demo seeds that create
  audits (`backend/test_audit_validation.py`, `backend/tests/backend_test.py`, `backend/tests/test_date_order.py`, `backend/demo_data.py`).
- Fiscal year-end (deck-parser.md §2): a `claims.py` test covering December and March year-ends is written first and
  shown failing; then `fiscal_year_end` on the audit model (`AuditCreate` and `AuditUpdate` in `backend/server.py`, so
  PUT /audits/{id} accepts it), a month field on the creation screen (`frontend/src/pages/AuditHub.jsx`) and in the
  existing MappingWizard settings (`frontend/src/pages/MappingWizard.jsx`), and `backend/app/decks/claims.py` resolves
  every period to a start and an end date with it, keeping the stated text for display.
