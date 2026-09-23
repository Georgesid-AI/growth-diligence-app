# Growth Diligence App — Growth Engine (Final Plan)

An invite-only web app that ingests a growth-stage company's structured data, computes its
growth metrics deterministically in Python/pandas, and shows them in a dashboard where every
number traces back to its exact source rows. The LLM (Phase 2) never calculates — it only
suggests column mappings and writes a short narrative from the computed results.

## Build order & review stops
- **Phase 1 — Growth Engine, no auth, no LLM.** Two stop points for your review:
  1. **Stop 1:** after the calculation engine + unit tests — I show you the test results.
  2. **Stop 2:** after the dashboard.
- **Phase 2 — accounts + LLM narrative** (built later): admin-invite-only accounts, admin
  login with TOTP 2FA, server-only prompt storage + admin prompt editor, LLM column-mapping
  suggestions, narrative writer using your own Anthropic key (`claude-sonnet-4-6`), and 90-day
  auto-deletion of audits. Model name kept in an environment variable so you can change it
  without code edits.

---

## Phase 1 scope

### Audit setup
Creating an audit captures: **company name, reporting currency (default EUR), plan target
ARR, target date.** Reporting currency is per-audit.

### Inputs — `.xlsx` / `.csv` only
Column mapping is by header-name matching; **you confirm every mapping** before compute (no
LLM in Phase 1). If a required column is unmapped the dataset can't be processed; if an
**optional** column is missing, the metrics needing it go to the missing-data panel —
**nothing is guessed.**

- **Revenue lines** — required: customer ID, invoice date, amount, currency. Optional: service
  start date, service end date, segment, revenue type (recurring/one-off).
- **CRM deals** — required: deal ID, created date, close date, stage (won/lost/open), amount.
  Optional: segment, founder involved (yes/no). If segment is missing, the segment split goes
  to the missing-data panel; if founder involved is missing, the founder win-rate split goes to
  the missing-data panel — but median sales cycle and overall win rate still compute.
- **P&L** — required: month, sales & marketing expense, revenue, cost of revenue.

### FX
If more than one currency appears, you enter **rate, date and source per currency**; everything
converts to the reporting currency. The FX table is stored with the audit.

### Metrics (implemented exactly as specified)
- **MRR** — recurring revenue only; one-off excluded. If service start/end dates exist, spread
  each invoice evenly across the service months. If not, treat each invoice as one month of
  revenue, unless you set the customer's billing term (monthly/quarterly/annual) on the
  mapping screen.
- **ARR** = MRR × 12.
- **NRR (12-month)** for month M (needs 12 months history): customers with MRR > 0 in M−12;
  NRR = their total MRR in M ÷ their total MRR in M−12. Reported overall, by segment, and by
  **start cohort** (quarter of first revenue).
- **Gross revenue churn (12-month)** — same customer base: (MRR lost to churn + MRR lost to
  contraction) ÷ MRR in M−12. Expansion not netted.
- **New MRR in a quarter** — MRR in the quarter's last month from customers whose first
  revenue month falls in that quarter. Expansion excluded.
- **CAC payback (months)** = S&M expense in the quarter lagged by L quarters ÷ (new MRR in the
  quarter × gross margin %). Gross margin % = (revenue − cost of revenue) ÷ revenue for that
  quarter (from P&L). **L = 0, 1, 2 shown side by side; default display L = 1.** If new MRR is
  zero, or gross margin % is zero or negative for a quarter, show **"not computable"** with the
  reason instead of a number.
- **Median sales cycle** — won deals only, days from created to close; report median, IQR, and
  n; by segment.
- **Win rate** = won ÷ (won + lost); open deals excluded. Split by founder-involved yes/no
  with n per group; flag "small sample" if n < 20 in either group.
- **Customers × ACV path to plan** — customer count and ACV (ARR ÷ customers) by segment. ACV
  bands (annual, reporting currency): <100 flies; 100–<1,000 mice; 1,000–<10,000 rabbits;
  10,000–<100,000 deer; 100,000+ elephants. Compute: customers needed to reach plan target ARR
  at current ACV; required net-new customers/year to the target date; observed net-new
  customers/year over the last 12 and 24 months; and required ÷ observed ratio.
- **Anomaly flags** (code only, no interpretation): months with negative MRR; customers with
  revenue gaps > 2 months that later resume; revenue lines missing customer ID; deals with
  close date before created date. Deals with close-date-before-created-date are **flagged AND
  excluded** from sales cycle and win rate, with the excluded count shown.

### Source referencing
Every computed number stores and displays its source reference — **file, sheet, rows**.

### Delete audit
A **"Delete audit"** button that permanently removes the audit's files and results.
(90-day auto-deletion is Phase 2.)

### Dashboard (Stop 2)
- **Metric cards:** current ARR, NRR, gross revenue churn, CAC payback (L=1), median sales
  cycle, win rate with/without founder.
- **Tables by segment.**
- **Cohort table:** rows = start cohort, columns = months since start, values = % of starting
  MRR retained.
- **Charts:** monthly MRR stacked by segment; NRR over time; required vs observed net-new
  customers.
- Every number shows its **source reference on hover**.
- **Missing-data panel:** which metrics couldn't be computed and which field/file would unlock
  each.

### Unit tests (shown at Stop 1)
Synthetic data generator with known answers (e.g. NRR exactly 110%, median sales cycle exactly
60 days); assert every metric. Edge cases: annual prepayments; a customer that churns and
later returns; a zero-revenue month; multiple currencies. **Stop 1 presents a table per test:
metric, expected value, actual value, pass/fail.**

---

## Phase 2 (planned now, built later)
- Accounts (admin-invite only), admin TOTP 2FA, server-only prompts, admin prompt editor.
- Anthropic `claude-sonnet-4-6` via your own key; **model name in an env var**.
- 90-day audit auto-deletion.
- **Prompt slot `growth_engine_narrative`:**
  - Input: Growth Engine results JSON (metrics, segments, anomaly flags, missing-data list).
  - Output: `{"headline": "<one sentence>", "summary": "<max 150 words>"}`, validated against
    that schema; on invalid output, retry once, then show an error.
  - Ships with clearly-marked placeholder prompt text; you enter the real prompt via the admin
    screen. The app never asks for prompt text in chat.
