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
