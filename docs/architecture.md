29 Oct 2026: the architecture is no longer frozen. Changes follow CLAUDE.md rule 32. The read/check/review pipeline in docs/design/read-check-review.md supersedes the rules-based reading described below.

# Architecture

This is the file CLAUDE.md rules 16–18 amend. It describes; it decides nothing. A change to what is written here is an
architecture change (components, what crosses the server boundary, what the model sees, storage of readings): the PR that makes it
names it under the heading "Architecture change" in its description and needs George's approval before merge (rule 32). Execution
steps live in docs/specs/ and may change.

## Components

| Component | Where | What it does |
|---|---|---|
| Frontend | `frontend/` (React, CRA) | Pages AuditHub, MappingWizard, Dashboard, Diagnostics. The approval list and the deck panel (`DeckPanel.jsx`) show each claim with its source and its label (Verified, "AI suggestion, not verified"). Provenance hover cards show file, sheet, rows and rule for every metric. |
| API | `backend/server.py` (FastAPI) | Audit CRUD, uploads, column mapping (`FIELD_DEFS`), the claim register, exports. Reads `MONGO_URL` and `DB_NAME` at start. Every route but the health check and the field list needs a token (docs/specs/access-links.md section 3): audit routes check the request's token link against the audit's owner (`backend/app/access.py`); a tester's usage totals cover their own audits; the owner token sees all usage totals and the owner routes, never an audit. |
| Calc engine | `backend/growth_engine.py` | Pure, deterministic. Never guesses a missing input; every number carries a source reference (file, sheet, rows). |
| Deck parser | `backend/app/decks/` | Python only, no model: parsed text with slide or page references, candidate claims (`claims.py`), the structures of docs/specs/deck-parser.md §7 and the page grid (`pages.py`: every line of a page as a cell with an id, the amendment of 2026-10-22). Has no import of, or call to, the gateway. |
| Structure path | `backend/app/structures/` | Redaction of structure cells and page lines (`redact.py`), the item list Python makes from them (`items.py`), the verifier that rebuilds periods and sets Verified (`verify.py`), the cell-level check of page claims (`page_check.py`) and the page pipeline behind `DECK_PIPELINE` (`pages.py`), and the orchestration that queues decks until the revenue file is mapped and turns checked items into approval rows (`__init__.py`). |
| LLM gateway | `backend/app/llm/` | The only component allowed to call a model provider (`gateway.py`). Prompts are versioned documents in the MongoDB collection `prompts`, uploaded on the owner page and read by the gateway only (`prompt_store.py`); a missing prompt means no model call; cache keys carry text, type, prompt tag, model and schema hash (`cache.py`); guards hold the per-audit lock, the daily spend cap and the retry policy (`guards.py`); the per-audit pseudonym map (`redaction.py`); strict output schemas (`schemas.py`). |
| Supporting modules | `backend/app/` | `formatting.py`, `disclosure.py` (the AI-provenance block), `narrative_export.py`, `logsafety.py` (no secret reaches a log line). |
| Interface contracts | `backend/schemas/` | `metrics.py`: `MetricsPayload`, the one description of the calc engine's output (units, citations), validated by the engine, the gateway and the export (docs/specs/interface-contracts.md). |
| Storage | MongoDB | `readings`, `reading_uses`, `reading_rereads`, `reading_overrides`, `reading_checks` (a spreadsheet's stored reading and what hangs on it, `app/readings.py`, the amendment of 2026-10-29), `audits` (with the audit's `token_map`: real company and customer name → Client-NN, server side only, never in a log, a payload or an API response), `datasets`, `deck_text` (parsed text and structures), `deck_files` (the uploaded deck file, in parts, kept only while consent is ticked and the page pipeline is on, so that page images can be drawn from it; deleted with its deck and with the audit), `deck_candidates`, `llm_narratives`, `llm_structures`, `llm_calls`, `llm_locks`, `column_mappings`, `prompts` (the model prompts; no `audit_id`), `access_tokens` (tester-phase token hashes, id, label, expiry, and per-link AI usage counters and allowance (counts and costs only, no names or figures); never a token; removed at the move to accounts; no `audit_id`). Delete audit removes an audit's documents in every collection that holds any; `prompts` and `access_tokens` hold no audit data and stay. |
| Manual tooling | `scripts/consistency_run.py` | Live consistency runs (paid), `--fake` replays, `--diagnostic` and `--probe` on the 10 public test decks. Reports are committed to docs/test-runs/. |

## The amendment of 2026-10-29 (read-check-review, PR 2)

For George's approval before merge (rule 32; docs/design/read-check-review.md sections 3, 4, 8, 9 and 13). Three things change.

- **What the model sees.** A new step, `sheet_reading` (the prompt `sheet_reading` of the store): one call per uploaded spreadsheet, every
  non-empty cell of every recognised sheet as `A1 ref: value` lines, after the masking of PR 1, name learning included. A metric
  vocabulary (`structures/redact.METRIC_VOCABULARY`: the role and metric names of the file map and the common finance labels) is never
  tokenised, so "Revenue" under a "Customers" title goes out unchanged. No sampling, no truncation: above 40,000 tokens of cells the file
  is refused with a message. An exact id from an allow-list of Sonnet and Opus ids only (`SHEET_READER_MODELS`; `SHEET_READER_MODEL` picks one, default the structure model; George, 2026-10-30). The spreadsheet calls of the earlier
  amendments stay as they are, behind `READER_V1` (off turns them off; default on), for PR 2 only; they still do not learn names.
- **What Python does with the answer.** The model returns a file map (`schemas/metrics.FileMap`, one schema for sheets and decks).
  `app/checks.py` opens every cited cell and gives one of three outcomes: confirmed, rejected (with a reason written by code) or cannot
  check (five explicit cases). A rejected item is read once more, automatically, with the reason attached. The as-of month of a file
  stands only on evidence a check confirmed; the audit's is the latest across files; a typed month wins (`app/as_of.py`).
- **Storage of readings.** `readings` (file hash + prompt version + model, written once, names restored), `reading_uses`,
  `reading_rereads`, `reading_overrides`, `reading_checks` (`app/readings.py`). A reading outlives no audit that used it: Delete audit
  removes it with the last one (rule 22).

## The amendment of 2026-10-22

George approved (22 Oct 2026, decision 1b on PR #158, docs/design/ai-reads-rules-check.md) widening the deck boundary for one new
step. For the `page_claims` step only, the default path since 22 Oct 2026 (`DECK_PIPELINE=ai`; the former rules read of
docs/specs/deck-parser.md section 2 is the fallback behind `DECK_PIPELINE=rules`, kept until the first tester decks are read; George,
2026-10-22), the model may receive every deck page that carries a figure written in digits, as masked text with the page image unmasked (rule 16, amended 2026-10-29): the page's
text lines, prose lines included, as extracted text with cell positions (`p<page>r<row>c<col>: <text>`, the page grid of
`app/decks/pages.py`), at most 5 pages per call, and one PNG of the whole page in the same request (a page the file cannot be drawn
for goes as text alone). A page with no such figure never goes; number-words do not count as figures. The reply
holds closed words, numbers and cell ids only, with each claim's `basis` and `scenario` (closed words); Python checks each claim
at cell level (`app/structures/page_check.py`: figure in its cell, unit adjacent, period from that cell's own sources) and labels
it "Matched to page" or "AI suggestion, not matched" (decisions 2a and 3a), then flags it (`app/structures/checker.py`: the
value, unit, scenario and period labels on the page, the page in range, the former parser rules as post-checks; a flag never
deletes or retypes, a flagged claim is listed in the Review view). The prompt is `deck_reading` in the store. All other steps
keep the boundary as it was. CLAUDE.md rule 16 carries the same wording.

Amended 2026-10-22 (George, review of PR #159, decisions 1b and 2a and findings H1, M1, L1, L2): the gateway refuses a
`page_claims` call unless `DECK_PIPELINE` is `ai`, whatever the caller (`gateway.deck_pipeline`). A page line over 200
characters is left out by the sender and refused by the gateway (`cell_too_long`), as a structure cell is. A line that is only
the page's own printed number ("3", "Slide 3", "3/25", "Page 3 of 20") is no figure, for the page grid and for the gateway's
floor alike (`decks/claims.page_number_line`), so a prose page with a footer number stays on the server. The role words of the
people-name rule match in any case ("Rohan Mehta, Co-Founder", "– Founder", "Head of Product"). With no customer list, a
customer-type header blanks the cells under it in its own text box or table column, and the lines directly under it in its
column before the first figure line (the part the gateway can re-run on the text as sent, which carries no layout); a figure
elsewhere on the page survives. When the figure check fails, the row shows the model's value and range, labelled "AI suggestion,
not matched", never the cell's first figure ("€2 7K" claimed as 27,000 is one row 27,000 to confirm or reject).

## The amendment of 2026-10-19

George approved (19 Oct 2026, decision 2 on PR #134, docs/specs/revenue-file-recognition.md §5) widening the spreadsheet boundary for one more
step. For the `file_recognition` step only, the model may also receive the row labels of a sheet whose labels the rules read as metric names
(revenue, ARR, MRR, customers, churn, bookings, forecast, budget, cost, margin, cash and their common variants), after redaction; for every other
sheet the labels are sent as "Row 1", "Row 2". No value is tied to a row on any sheet: the up to 3 sample values of a column are drawn from different rows,
chosen deterministically from the file hash, never the same row in two neighbouring columns. Never a figure beyond the per-column sample of rule 16; at most
400 rows with text per sheet. All other steps keep the boundary as it was. CLAUDE.md rule 16 carries the same wording.

## The amendment of 2026-10-18

George approved (18 Oct 2026, with the task of docs/specs/chat-upload.md §26) widening the spreadsheet boundary for one step. For the
`sheet_structure` step only, the model may receive every text cell of a sheet (title rows, headers, row labels, indents, num/blank
markers), after redaction and the withhold rule of llm-structure-reading.md §3; never any figure; a cap of 400 labelled rows per
sheet. All other steps keep the boundary of rule 16 as it was: sheet names, title rows and header rows, with up to 3 samples or a
profile per column. CLAUDE.md rule 16 carries the same wording.

## The amendment of 2026-10-15

George approved (decision 1, 15 Oct 2026) one new MongoDB collection, `access_tokens`, and the token check in the API row, for
the tester phase on Emergent (docs/specs/access-links.md §6, option a). The collection holds SHA-256 hashes, ids, labels and
dates only. It is not an audit document, so Delete audit does not touch it. It is removed at the move to magic-link accounts.

The prompt store (docs/specs/prompt-store.md, CLAUDE.md rule 26) adds the collection `prompts` and replaces the prompt files in
the repository, which is public. The wording above is the one proposed in prompt-store.md §7, applied by George's instruction.

## Evidence method

Python computes and cites; the model explains or labels. Every figure the analyst sees carries a source reference:
file, sheet and rows for a computed metric, file, slide or page and cell for a deck claim. The model never produces a
number: the narrative path explains computed results and may not add a figure the engine did not produce (the
gateway's numeric guard); the structure path labels the figures Python listed from redacted cells. Verification is
Python's alone (rule 18): an item is Verified when Python read its value from its source cell and rebuilt its period
from the cells; everything else is shown as "AI suggestion, not verified" or dropped. Python enters every claim it matched
to its page and tested against the data; the analyst answers the questions Python cannot: a claim a check flagged, a
claim that is not matched, a Revenue / Volume or Definition question. The analyst can still correct or exclude any claim.

## Data boundary

Two paths reach the gateway and each has its own fields (docs/specs/deck-parser.md §4):

- Narrative path: computed results from MongoDB and the structured claim fields (type, value, high value of a range,
  unit, date, status). Never uploaded rows, raw file bytes or parsed deck text.
- Structure path (rule 16): redacted deck structures and spreadsheet sheet names, title rows and header rows, as extracted text with cell
  positions, only with per-audit consent. What the text may hold is defined in docs/specs/llm-structure-reading.md
  §1 and §3. For the `sheet_structure` step only (the amendment of 2026-10-18 above): every text cell of a sheet (title rows,
  headers, row labels, indents, num/blank markers), after redaction and the withhold rule; never any figure; at most 400
  labelled rows per sheet. For the `file_recognition` step only (the amendment of 2026-10-19 above): the row labels of a
  metric-labelled sheet, "Row n" for every other sheet, never a figure beyond the per-column sample. For the `page_claims` step
  only (the amendment of 2026-10-22 above, behind `DECK_PIPELINE`): a deck page that carries a figure as digits, with its text lines masked (prose
  included) and one unmasked image of the whole page, at most 5 pages per call; never a page without such a figure.

What is stored (rule 17): model JSON output with cell references, the item list without raw text, prompt version,
model version, content hash, token counts and cost. Never deck text sent to the model. The one stored copy of client data is the uploaded
deck file (`deck_files`), which holds the bytes for drawing page images, only while consent is ticked and the page pipeline is on; it is
deleted with its deck and with the audit. The boundary is enforced in
`backend/tests/test_gateway_data_boundary.py` (rule 14), which must pass on every build.

The narrative path may read a count of deck documents per audit (number only). It never reads deck text, titles or file names.

Python enters a matched claim on Run audit and tests it against the data, whatever its label; it enters nothing a check asks about. A claim Python entered stays correctable and excludable one by one; a claim the analyst answered, edited or added is never changed by a later run.

## The amendment of 2026-10-05

Until 2026-10-05 the gateway read no parsed deck text at all (the former deck-parser.md §4). The amendment added
rules 16–18 to CLAUDE.md, which hold their wording: the gateway may read selected deck structures and spreadsheet
sheet names, title rows and header rows under the conditions of rule 16; logs and MongoDB store model output and metadata and never sent text
(rule 17); model output never becomes Verified on its own (rule 18). The structure path above is its implementation,
specified in docs/specs/llm-structure-reading.md and docs/specs/structure-labelling.md. The deck parser still has no
direct link to the gateway.
