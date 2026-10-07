# Spec: Claim matching: approved claims tested against the computed metrics
Status: Draft; decisions of 2026-10-07 applied, open ones in §10. Location: docs/specs/claim-matching.md.
Follows deck-parser.md §6.

## Goal
Test every register claim against the engine's computed metrics and write its gap, evidence label and proposed
gate. Python only: nothing reaches the gateway or a model.

## Scope
In: register claims and `audits.results`.
Out: value at stake (its column is filled later by the ARR bridge, #6), bank data, narrative text, new engine
metrics, claim edits (they stay in the approval list).
No architecture change: the analyst's inputs (§5, §8) are stored on the register's `deck_candidates` rows; the
rest is computed on read by a pure module.

## 1. Inputs
| Input | Read from |
|---|---|
| Claim type, value (low, high), unit, currency | the candidate; an edited claim gives the analyst's values |
| Period: target date, start, end | the candidate (`resolve_period`, the audit's fiscal year-end) |
| Page reference | `sources`: file, slide or page |
| Deck reading | `parser` (Python read the text), `Verified`, `AI suggestion, not verified`, `edited` (an edit clears the AI label) |
| Segment, metric | §2; the analyst may set either (§8) |
| Computed figure and its source | `audits.results` (file, sheet, rows, rule); the as-of month and whether it was defaulted |

A table row candidate gives one claim per value by period, id `<candidate id>#<n>`.

## 2. Matching
Python proposes the metric from the claim type, a keyword in its snippet or borrowed label, and its unit
(table 2a); with none the row is Unsupported unless the analyst picks one. A segment is proposed when the snippet
or label names exactly one segment of the revenue file (whole word, any case); otherwise the claim is compared with
the whole-company figure and marked "whole company".

| Metric | Proposed for | Unit | Read from | Periods | Segment | Better |
|---|---|---|---|---|---|---|
| ARR | revenue: "ARR" | currency | `mrr_series` month total × 12 | any data month | yes | higher |
| MRR | revenue: "MRR", not "new MRR" | currency | `mrr_series` month total | any data month | yes | higher |
| New MRR | revenue: "new MRR" | currency | `new_mrr_by_quarter` | quarter | no | higher |
| NRR (12-month) | retention: "NRR", "net (revenue) retention" | % | `nrr.series`; `nrr.by_segment` | from the 13th data month; by segment as-of | yes | higher |
| Gross revenue churn | retention: "revenue churn", "gross churn" | % | `gross_churn.series` | from the 13th data month | no | lower |
| Customers | customers, a count | count | `acv_path.current_customers`, `.by_segment` | as-of | yes | higher |
| ACV | sales: "ACV" | currency | `acv_path.acv`, `.by_segment` | as-of | yes | higher |
| Median sales cycle | sales: "sales cycle" | days | `sales_cycle.median_days`, `.by_segment` | as-of | yes | lower |
| Win rate | sales: "win rate" | % | `win_rate.win_rate_pct` | as-of | no | higher |
| Gross margin | gross margin, in % | % | `cac_payback.quarters[q].gross_margin_pct` | quarter | no | higher |
| CAC payback | sales: "payback" | months | `cac_payback.quarters[q]` at the default L | quarter | no | lower |
| none (D5) | every other claim type; "revenue", "turnover", "bookings" alone; "retention" or "churn" without "net", "revenue" or "gross" | | | | | |

| Claim | Rule (table 2b) |
|---|---|
| Period, any data month | read at the period's end month |
| Period, quarter | the period's months equal one calendar quarter of the engine (every fiscal quarter does with a year-end in March, June, September or December) |
| Period, as-of | the period ends in the as-of month |
| Period ends after the as-of month | forecast |
| No period | the as-of figure (CAC payback: the headline quarter), marked "no period stated" (D4) |
| Other currency | converted at the audit's FX rate |
| Duration | 7 days a week, 30.44 a month |
| Range | tested at the end nearest the observed value; inside it the gap is 0 |

## 3. Gap, rank, gloss
Gap = direction × (claimed − observed), in the metric's unit: positive is a miss, negative a beat. Normalised gap =
gap ÷ |claimed|. A forecast's gap is "to go" (claimed minus the as-of figure), not a miss. Rank: rows with a miss or
beat by normalised gap, largest first, a beat counting as 0 so it never ranks as a miss; then the rest, in register
order.

| Unit | Miss | Beat | To go |
|---|---|---|---|
| days | "13.5 days longer, two working weeks" (days ÷ 7, rounded; under 3.5: "under a working week") | "1.5 days shorter than claimed" | as miss |
| months | "3.0 months longer" | "3.0 months shorter than claimed" | as miss |
| % | "7.0 points lower, 8% of the claim" | "0.7 points better than claimed" | "17.0 points to go by Dec 2026" |
| currency, count | "€41,857 short, 17% of the claim"; "1 customer fewer" | "€2,125 better than claimed" | "€4.8M to go by Dec 2026, 96% of the claim" |

## 4. Evidence label
Tested = the metric has a figure for the claim's period and segment, and the period ended by the as-of month.
Untested rows stay listed with a reason and observed "—" (a forecast shows the as-of figure).

| Label | Rule (D1–D3) |
|---|---|
| Verified | Tested and within tolerance: ±5% of the claimed value for amounts, counts and durations; ±1 percentage point for rates. The boundary is Verified. |
| Contradicted | Tested and outside tolerance: a miss, or a beat (D2). |
| Unverified | Not testable yet; the reason names what would test it: a Missing file (the engine's `unlocked_by`), a forecast period, a period before the metric's first month, no FX rate for the claim's currency, or a deck reading "AI suggestion, not verified" (D3). |
| Unsupported | The app gives no figure: no metric proposed or picked, the metric not computed for that period or by segment, the segment not in the data, or the engine's "not computable" reason. |

## 5. Gate
Proposed for every row with an observed value: "Before {budget decision}, {metric} must be at least (at most)
{threshold} by {date}. Observed {value} ({month}); claimed {value} ({period})." The date is the last day of the
first fiscal quarter ending after the as-of month. The analyst sets the threshold and names the budget decision (max
200 characters); the gate is saved only when both are filled.

## 6. Claim register
One row per claim, no deck text (no snippet, no label). GET /api/audits/{id}/claims returns the rows in rank order
under `register`, beside today's `claims`.

| Field | Type | Note |
|---|---|---|
| `claim_id` | str | candidate id, `#n` for a value of a table row |
| `deck_file`, `page_ref` | str | "p12", "slide 4"; several joined by ", " |
| `claim_type`, `status` | str | CLAIM_TYPES; approved, edited |
| `deck_reading` | str | §1 |
| `claimed_value`, `claimed_high` | float, float or null | in the claim's currency |
| `unit`, `currency` | str or null | |
| `period`, `period_start`, `period_end`, `period_note` | str, date, date, str; or null | note: "no period stated" |
| `segment`, `segment_set_by` | str | "Whole company", a data segment, "Not in the data"; python, analyst |
| `metric`, `metric_set_by` | str or null | table 2a; python, analyst |
| `direction` | str or null | higher, lower |
| `observed_value`, `observed_at` | float or null, str | "2024-02", "2023-Q4" |
| `observed_source` | object | file, sheet, rows, rule |
| `gap`, `gap_normalised`, `gap_kind` | float or null | miss, beat, to go |
| `gloss` | str or null | table 3 |
| `evidence_label`, `reason`, `tolerance` | str | table 4; "±5%", "±1 pp" |
| `rank` | int | §3 |
| `value_at_stake_arr` | float or null | null until issue #6 |
| `gate_sentence` | str or null | §5 |
| `gate_threshold`, `gate_budget_decision`, `gate_date`, `gate_saved` | float, str, date, bool | |
| `as_of_month`, `as_of_defaulted` | str, bool | |

## 7. Monitoring baseline
GET /api/audits/{id}/claims.csv: the register rows in rank order as one CSV (the method's A9). Header = §6 field
names; numbers unformatted, dates ISO, `observed_source` as "file · sheet · rows".

## 8. Analyst screen
A row shows rank, claim, period, segment, page, deck reading, observed value (source on hover), gap and gloss,
evidence label and reason, and the gate. Editable: segment, metric (a metric in the claim's unit, or none), the
gate's threshold, budget decision and date. All else is read-only (D6).

## 9. Data boundary and test fixture
The matching module imports nothing from `app.llm`; its fields enter no gateway payload; logs hold counts per
label, never a value or gate text. The code PR extends test_gateway_data_boundary.py for each (rules 14, 17).

Fixture `backend/tests/fixtures/claim_matching/testco_claims.json`: synthetic TestCo claims on `sample_data/`.
Public decks have no matching data and are not used.

| Setting or engine figure, measured on this branch (no network) | Value |
|---|---|
| Run A | EUR, December year-end, as-of 2024-02 defaulted from the last P&L month, P&L present; gate date 2024-03-31 |
| Runs B, C | run A without crm.csv; run A with a March year-end |
| ARR 2024-02; 2023-12; first month | 202,125.48; 198,142.68; 2023-01 |
| NRR 2024-02, whole company and each segment; first month | 112.68%; 2024-01 |
| Customers; median sales cycle, whole and Enterprise; win rate | 5; 58.5 days, 58.5; 40.0% |
| Gross margin 2023-Q4; CAC payback 2023-Q4 | 78.0%; not computable, "new MRR is zero" |

| # | Claim | Observed | Gap | Label | Rank |
|---|---|---|---|---|---|
| 1 | ARR €200,000, Feb 2024 | 202,125.48 | beat 2,125.48 | Verified | 8 |
| 2 | "Enterprise sales cycle 60 days", no period | 58.5 (Enterprise) | beat 1.5 days | Verified | 9 |
| 3 | Win rate 41%, no period | 40.0% | 1.0 pp, 2.4% | Verified (boundary) | 7 |
| 4 | NRR 112%, Feb 2024 | 112.68% | beat 0.68 pp | Verified | 10 |
| 5 | ARR €240,000, FY2023 | 198,142.68 | 41,857.32, 17.4% | Contradicted | 2 |
| 6 | Sales cycle 45 days, no period | 58.5 | 13.5 days, 30.0% | Contradicted | 1 |
| 7 | Gross margin 85%, Q4 2023 | 78.0% | 7.0 pp, 8.2% | Contradicted | 3 |
| 8 | 4 customers, Feb 2024 | 5 | beat 1 (25%) | Contradicted (D2) | 11 |
| 9 | ARR €5,000,000, FY2026 | 202,125.48 (as-of) | to go 4,797,874.52, 96.0% | Unverified: forecast | 15 |
| 10 | NRR 115%, FY2023 | — | — | Unverified: before NRR's first month, 2024-01 | 16 |
| 11 | Run B: win rate 40%, no period | — | — | Unverified: Missing, "Upload CRM deals with …" | 1 (run B) |
| 12 | ARR $210,000, Feb 2024 | — | — | Unverified: no FX rate for USD | 17 |
| 13 | NRR 112%, Feb 2024, reading "AI suggestion, not verified" | 112.68% | beat 0.68 pp | Unverified (D3) | 12 |
| 14 | TAM €2bn | — | — | Unsupported: no metric | 18 |
| 15 | 10,000 users | — | — | Unsupported: no metric | 19 |
| 16 | CAC payback 12 months, Q4 2023 | — | — | Unsupported: "new MRR is zero" | 20 |
| 17 | "Public sector NRR 130%", analyst sets "Not in the data" | — | — | Unsupported: segment not in the data | 21 |
| 18 | "Enterprise win rate 50%" | — | — | Unsupported: not computed by segment | 22 |
| 19 | Table row ARR €150,000 (Y/E 22) · €198,000 (Y/E 23) | —; 198,142.68 | —; beat 142.68 | Unverified: before ARR's first month, 2023-01; Verified | 23; 13 |
| 20 | Run C: gross margin 85%, Q3 FY24 (Oct–Dec 2023) | 78.0% | 7.0 pp, 8.2% | Contradicted | 1 (run C) |
| 21 | ARR €190,000–210,000, Feb 2024 | 202,125.48 | 0, inside | Verified | 14 |
| 22 | Win rate 42%, no period | 40.0% | 2.0 pp, 4.8% | Contradicted | 6 |
| 23 | ARR €212,700, Feb 2024 | 202,125.48 | 10,574.52, 4.97% | Verified (boundary) | 5 |
| 24 | ARR €213,000, Feb 2024 | 202,125.48 | 10,874.52, 5.11% | Contradicted | 4 |

## 10. Open decisions
| # | Question | Options | Recommendation |
|---|---|---|---|
| D1 (kind 1) | What tolerance separates Verified from Contradicted? | a) ±5% of the claim for amounts, counts, durations; ±1 pp for rates. b) ±10% and ±2 pp. c) half the claim's last stated digit plus 2%. | a: covers whole-percent rounding and keeps "$4M" against $3.6M a contradiction. |
| D2 (kind 1) | Is a beat beyond tolerance Contradicted? | a) Contradicted, ranked after every miss. b) Verified, gloss "better than claimed" (fixture row 8). | a: the label says whether the figure holds; the rank carries the risk. |
| D3 (kind 1) | Can an unedited "AI suggestion, not verified" claim be Verified or Contradicted? | a) No: Unverified until the analyst edits it, even unchanged. b) Yes, tested like any claim (fixture row 13 Verified). | a: rule 18; Python has not matched that figure to its cell. |
| D4 (kind 1) | Is a claim with no period tested? | a) Yes, at the as-of figure, marked "no period stated". b) No: Unverified (fixture rows 2, 3, 6, 22). | a: undated deck KPIs describe the present. |
| D5 (kind 1) | Is table 2a the metric list? | a) As written: no proposal for plain revenue, users, growth rates, bare retention or churn. b) Name rows to change. | a: the analyst can still pick a metric per row. |
| D6 (kind 3) | Where and how does the register show? | a) New "Claim register" section on the Dashboard under the metric cards; columns of §8; headers "Read from deck" and "Evidence" (both can say Verified); value at stake hidden until #6; edits of §8; a "Download baseline (CSV)" button. b) A tab beside "All" in the deck panel, same columns. | a: observed figures and their source hover live on the Dashboard. |

## Done when
- Every fixture row gives its label, gap, gloss and rank (`backend/tests/test_claim_matching.py`).
- The boundary tests pass; the CSV equals the register; the screen follows D6.
