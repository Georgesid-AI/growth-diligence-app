# Architecture

This is the file CLAUDE.md rules 1 and 3 freeze and rules 16–18 amend. It describes; it decides nothing. A change to
what is written here is an architecture change: a session that needs one stops and reports an "Architecture note"
(rule 1). Execution steps live in docs/specs/ and may change.

## Components

| Component | Where | What it does |
|---|---|---|
| Frontend | `frontend/` (React, CRA) | Pages AuditHub, MappingWizard, Dashboard, Diagnostics. The approval list and the deck panel (`DeckPanel.jsx`) show each claim with its source and its label (Verified, "AI suggestion, not verified"). Provenance hover cards show file, sheet, rows and rule for every metric. |
| API | `backend/server.py` (FastAPI) | Audit CRUD, uploads, column mapping (`FIELD_DEFS`), the claim register, exports. Reads `MONGO_URL` and `DB_NAME` at start. |
| Calc engine | `backend/growth_engine.py` | Pure, deterministic. Never guesses a missing input; every number carries a source reference (file, sheet, rows). |
| Deck parser | `backend/app/decks/` | Python only, no model: parsed text with slide or page references, candidate claims (`claims.py`), and the structures of docs/specs/deck-parser.md §7. Has no import of, or call to, the gateway. |
| Structure path | `backend/app/structures/` | Redaction of structure cells (`redact.py`), the item list Python makes from them (`items.py`), the verifier that rebuilds periods and sets Verified (`verify.py`), and the orchestration that queues decks until the revenue file is mapped and turns checked items into approval rows (`__init__.py`). |
| LLM gateway | `backend/app/llm/` | The only component allowed to call a model provider (`gateway.py`). Prompts are server-side files with a version and a release stamp (`prompt_store.py`, `prompts/`); cache keys carry text, type, prompt tag, model and schema hash (`cache.py`); guards hold the per-audit lock, the daily spend cap and the retry policy (`guards.py`); the per-audit pseudonym map (`redaction.py`); strict output schemas (`schemas.py`). |
| Supporting modules | `backend/app/` | `formatting.py`, `disclosure.py` (the AI-provenance block), `narrative_export.py`, `logsafety.py` (no secret reaches a log line). |
| Interface contracts | `backend/schemas/` | `metrics.py`: `MetricsPayload`, the one description of the calc engine's output (units, citations), validated by the engine, the gateway and the export (docs/specs/interface-contracts.md). |
| Storage | MongoDB | `audits`, `datasets`, `deck_text` (parsed text and structures), `deck_candidates`, `llm_narratives`, `llm_structures`, `llm_calls`, `llm_locks`, `pseudonym_map`, `column_mappings`. Delete audit removes an audit's documents in every collection. |
| Manual tooling | `scripts/consistency_run.py` | Live consistency runs (paid), `--fake` replays, `--diagnostic` and `--probe` on the 10 public test decks. Reports are committed to docs/test-runs/. |

## Evidence method

Python computes and cites; the model explains or labels. Every figure the analyst sees carries a source reference:
file, sheet and rows for a computed metric, file, slide or page and cell for a deck claim. The model never produces a
number: the narrative path explains computed results and may not add a figure the engine did not produce (the
gateway's numeric guard); the structure path labels the figures Python listed from redacted cells. Verification is
Python's alone (rule 18): an item is Verified when Python read its value from its source cell and rebuilt its period
from the cells; everything else is shown as "AI suggestion, not verified" or dropped. The analyst approves, edits
or rejects every claim; nothing enters the claim register on its own.

## Data boundary

Two paths reach the gateway and each has its own fields (docs/specs/deck-parser.md §4):

- Narrative path: computed results from MongoDB and the structured claim fields (type, value, high value of a range,
  unit, date, status). Never uploaded rows, raw file bytes or parsed deck text.
- Structure path (rule 16): redacted deck structures and spreadsheet header rows, as extracted text with cell
  positions, only with per-audit consent. What the text may hold is defined in docs/specs/llm-structure-reading.md
  §1 and §3.

What is stored (rule 17): model JSON output with cell references, the item list without raw text, prompt version,
model version, content hash, token counts and cost. Never deck text sent to the model. The boundary is enforced in
`backend/tests/test_gateway_data_boundary.py` (rule 14), which must pass on every build.

## The amendment of 2026-10-05

Until 2026-10-05 the gateway read no parsed deck text at all (the former deck-parser.md §4). The amendment added
rules 16–18 to CLAUDE.md, which hold their wording: the gateway may read selected deck structures and spreadsheet
header rows under the conditions of rule 16; logs and MongoDB store model output and metadata and never sent text
(rule 17); model output never becomes Verified on its own (rule 18). The structure path above is its implementation,
specified in docs/specs/llm-structure-reading.md and docs/specs/structure-labelling.md. The deck parser still has no
direct link to the gateway.
