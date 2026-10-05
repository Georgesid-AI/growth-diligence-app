# Spec: Model reading of deck structures and spreadsheet headers
Status: Draft. Location: docs/specs/llm-structure-reading.md. Implements CLAUDE.md rules 16–18.

**1. Gateway function.** `gateway.read_structure(text, type) → JSON`, plus the db and audit id every gateway call
carries. There is one prompt (`prompts/structure_reading.md`) and one schema, and `type` is an input field. Types:
`table`, `chart`, `kpi_panel`, `roadmap`, `hiring_table`, `unit_economics`, `use_of_funds`, `column_mapping`.
Python finds the structures and assigns their type (deck-parser.md §7). It builds `text` as one line per cell,
`r<row>c<col>: <cell text>`, with no file name, slide number or prose. Adding the prompt file records its hash in
`RELEASE.md` without a release bump; later edits bump it as today. The output is `{"type": ..., "items": [...]}`.
`type` confirms or corrects Python's type, within the deck types (a column mapping stays one), and Python logs any
change (§9). Each item has exactly these fields:
- `metric`: a deck-parser.md §2 claim type, `Use of funds`, or a FIELD_DEFS field;
- `period`: `YYYY`, `YYYY-Qn`, `YYYY-Hn`, `YYYY-MM` or null;
- `value`: a number, null only for a roadmap milestone or a column mapping;
- `unit`: an ISO currency, `%`, `x`, `count`, `days`, `months`, `years` or null;
- `actual_or_forecast`: `actual`, `forecast` or `unknown`;
- `source_cells`: input cell ids, at least one;
- `proposed_flags`: `total_mismatch` or `growth_mismatch`.

No field is free text, so model output cannot carry deck prose into a log.

**2. Verifier (Python, pure).** A value matches when one of its `source_cells` exists and holds the same number after
normalisation:
- currency symbols and thousands separators are removed;
- a decimal comma is read only if the structure writes numbers like `1.234,5`;
- `(1,200)` is read as −1200;
- `k`/`m`/`bn` suffixes are applied;
- a unit or scale in a neighbouring or header cell (`£m`, `'000`, `%`) is applied.

The match is exact, so a rounded number does not match. The period must match too: the row or column header of
the matched cell must read as that period under the deck-parser.md §2 period rules. A null period matches only when
neither header holds a period. An unmatched value or period makes the item unmatched. Every proposed flag is
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

Customer names in spreadsheet samples (columns whose header matches the FIELD_DEFS customer aliases) are
pseudonymised (Customer_001, Customer_002…) before sending. The mapping stays server-side and is removed by Delete
audit. The target company's own name is never redacted. The gateway runs redaction again and refuses the call if
anything changes.

**4. Consent.** `structure_reading_consent` is one checkbox per audit, unticked by default. It covers decks and
spreadsheets, and every change is stored with its time. Unticked means the Python-only path, with no
`read_structure` call. Results already stored stay until Delete audit. Each structure sent is recorded with its
deck, page, type and time (no text). The deck panel shows "Sent to the model: slides 4, 7, 12".

**5. Prompt-injection defence.** No tools. Structured outputs (`output_config.format`). The prompt says cell text is
data, never instructions. Python validates every reply against the schema (extra fields forbidden) and checks that
every source cell exists. A failing reply is rejected. After the existing one reask, the structure is marked
"Not read by AI" and Python's result stands.

**6. Model.** `STRUCTURE_MODEL = "claude-sonnet-5-5"`, a constant in gateway.py separate from `NARRATIVE_MODEL`. It
needs a price entry, and changing it moves every cache key. Temperature stays at the default and is not sent.
Consistency relies on the cache, the verifier and the 95% agreement target (§11).

**7. Caps.** 200,000 tokens per audit, counting billed input and output. A call goes out only if tokens used + its
input + its `max_tokens` fit under the cap. Otherwise the analyst sees: "AI reading stopped: this audit reached its
200,000-token limit. The remaining structures were read by Python only." Each structure may use at most 3,000 input
tokens, measured with the provider's token counter. A larger one is not sent and is marked "Too large for AI reading".
The token cap governs structure calls. The 15-call cap per run (`MAX_CALLS_PER_RUN`) counts narrative calls only.
The existing circuit breaker applies: per-audit lock (step `structures`), daily spend cap, retry policy.

**8. Cache.** The key is sha256 of text, type, prompt cache tag and model. Results are stored in `llm_structures` and
looked up by (audit id, key), so no audit is served another audit's result. A hit makes no API call. Delete audit
removes the stored results (`purge_run`).

**9. Logging (rule 17).** `llm_structures` stores the model JSON output, the verifier status of each item, prompt
version, model, content hash, tokens, cost, deck and page. It also stores Python's type and, when the two differ,
the model's type. `llm_calls` adds the content hash and deck id. The server log line carries run id, step, hash,
tokens, cost and any type change. Sent text is never stored. `GET /api/runs/{id}/llm-usage` gains `by_deck`, and
the deck panel shows each deck's cost.

**10. Boundary test and docstrings.** `test_gateway_data_boundary.py` keeps every existing assertion.
- It must pass when redacted structure cells, or header rows with at most 3 redacted samples per column, reach the provider.
- It must fail on raw bytes, a full page, a prose snippet, a cell over 200 characters, more than 3 samples, a file
  name, an unredacted email, phone number, name or customer name, any call without consent, and sent text in a log or in
  `llm_structures`.

The docstrings in `gateway.py`, `decks/__init__.py` and `prompt_store.py` restate rules 16–18.

**11. Tests.** Automated tests replay recorded replies (public test decks only) through the fake adapter, with no
live API. They cover:
- the verifier: each normalisation case, period matching, flags, the switch;
- redaction: each rule with a false friend (amounts, years, "Head of Sales"), and customer pseudonyms;
- orchestration: schema rejection, caps (including the narrative-only call cap), cache, consent, type-change
  logging, Delete audit.

Each new test is first shown failing on a deliberate violation. `scripts/consistency_run.py` is manual: it uses the
live API and costs money. It runs the 10 decks in `tests/fixtures/decks/decks/` 3 times and reports:
- agreement % per structure type (items identical in all 3 passes ÷ distinct items);
- verifier match rate and unverified rate;
- tokens and cost per deck;
- cache hit rate on passes 2 and 3.

Passes 2 and 3 read the cache first to get the hit rate (expected 100%), then call the model with the cache bypassed,
so agreement measures the model. Target: ≥95% agreement.

**Open questions.** None. All were resolved on 2026-10-05.

**Files.**
- New: `backend/app/structures/{__init__,redact,verify}.py`, `backend/app/llm/prompts/structure_reading.md`,
  `backend/tests/test_structure_{redaction,verifier,reading}.py`, `backend/tests/fixtures/structure_replies/`,
  `scripts/consistency_run.py`.
- Changed: `backend/app/decks/parser.py` (deck-parser.md §7), `backend/app/llm/{gateway,schemas,cache,guards,prompt_store}.py`,
  `backend/app/llm/prompts/RELEASE.md`, `backend/app/decks/__init__.py`, `backend/server.py`, `backend/tests/test_gateway_data_boundary.py`,
  `frontend/src/components/DeckPanel.jsx`, `frontend/src/pages/MappingWizard.jsx`.
