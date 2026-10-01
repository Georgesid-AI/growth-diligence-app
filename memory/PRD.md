# Growth Diligence — PRD

## Original problem statement
A list of prompts that due-diligence the growth assumptions of a growth-stage tech company,
to be sold as an app to investors and to the companies themselves.

## Approved approach (Growth Engine)
Ingest a company's structured data (xlsx/csv), compute growth metrics **deterministically in
Python/pandas**, and show them in a dashboard where every number traces back to its exact
source rows. The LLM (Phase 2) never calculates — it only suggests column mappings and writes
a short narrative from computed results.

## Personas
- Investor / analyst running diligence on a target.
- Founder / operator preparing for a raise.

## Architecture
- Backend: FastAPI (`/app/backend/server.py`) + pure engine (`growth_engine.py`) + demo
  generator (`demo_data.py`). MongoDB collections: `audits`, `datasets`.
- Frontend: React (CRA) with pages AuditHub, MappingWizard, Dashboard, Diagnostics.
- Deterministic engine unit-tested in `test_growth_engine.py` (16/16 known-answer cases pass).

## Phase 1 — DONE (2026-06)
- Audit CRUD (create with company/currency/target ARR/target date, list, delete permanently).
- Upload xlsx/csv for Revenue lines, CRM deals, P&L; fuzzy header auto-mapping with
  scored+unique assignment; user confirms every mapping; FX-rate editor per currency.
- Deterministic metrics: MRR/ARR, 12-month NRR (overall / segment / start-cohort + time
  series), gross revenue churn, new MRR by quarter, CAC payback (L=0,1,2; default L=1;
  "not computable" with reason), median sales cycle + IQR (by segment), win rate (founder
  split, small-sample flag), customers × ACV path to plan (fly/mice/rabbit/deer/elephant
  bands, required vs observed net-new), anomaly flags, missing-data panel.
- Source referencing (file / sheet / rows) on every metric via hover provenance cards.
- Dashboard: metric strip, stacked MRR by segment, NRR-over-time, cohort retention heatmap,
  path-to-plan, segment tables, CAC-by-quarter table, anomaly + missing-data panels.
- Two seeded demo audits so the dashboard is populated on first load.

## Phase 2 — PLANNED (built later)
- Accounts (admin-invite only), admin TOTP 2FA.
- Server-only prompt storage + admin prompt editor.
- Anthropic `claude-sonnet-4-6` (model name in env var) for LLM column-mapping suggestions and
  a narrative writer (prompt slot `growth_engine_narrative`, JSON-schema-validated, retry once).
- 90-day audit auto-deletion.

## Backlog / next
- P1: per-customer billing-term UI on the mapping screen (engine already supports it).
- P1: CSV/PDF export of the dashboard.
- P2: multi-sheet xlsx selection.

## Session log

### 2026-10-01 — V6: compute-before-Missing rule
- Rule: before an item stays in `results["missing_data"]`, every upload (revenue, CRM,
  P&L — still one file per type, no schema change) is tested for the columns the analysis
  needs. A file's own type is read through its current mapping; the other types through
  the FIELD_DEFS column aliases (`server.candidate_views`).
- Engine (`growth_engine.py`): `ANALYSIS_NEEDS`, `can_compute(analysis, files)`,
  `resolve_missing(...)`, run as a post-pass at the end of `compute_all` (new optional
  `files=` argument). Covered analyses: sales cycle, win rate, win rate by founder
  involvement, NRR, gross churn, CAC payback. A file counts only if it has every field
  and its rows yield a result.
  - Computable → result stored under its own key with a source citation (file, sheet,
    rows, rule, dataset, columns) and `status: "Computed – explanation requested"`; an
    entry is added to `results["questions_for_management"]`; the item leaves missing_data.
  - Not computable → stays in missing_data with `status: "Missing"` and `absent_fields`
    per dataset type (empty list = columns present but no usable rows).
  - Results the engine already produced from the expected file are never replaced.
- New Missing item "Sales cycle" when CRM deals are uploaded without a created/close date
  (previously a silent `n: 0`). Fixed `cut_deals_at_as_of` crashing when a CRM date column
  is absent.
- Gateway: the growth_engine slice now carries `missing_data` and
  `questions_for_management` (metric, status, reason/absent_fields or result_key,
  dataset, question — no raw rows or parsed text) and `founder_win_rate`. Missing data was
  not in the payload before.
- Prompt: `growth_engine.md` v6, new rule 10 (rule 8 unchanged); release r3, hash
  re-recorded. All stored narratives become superseded (`prompt_release_changed`); none
  are regenerated in bulk — each regenerates only through the gateway POST (circuit
  breaker, call/spend caps) when a user generates it on an opened audit.
- Not built (out of scope, do not exist yet): data inventory, "Analyses it blocks",
  gap/request lists. Export: `absent_fields` is flattened to text in the Missing Data sheet.
- Stored audits pick up the new fields on their next recompute; nothing is recomputed in bulk.
- Tests: `tests/test_compute_before_missing.py` (7). Suite: 297 passed, 26 skipped.
