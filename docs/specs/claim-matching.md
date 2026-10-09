# Spec: Claim matching: approved claims tested against the computed metrics
Status: Draft; decisions of 2026-10-07 applied (§10). Location: docs/specs/claim-matching.md.
Follows deck-parser.md §6.
Amended 2026-10-09 (George): turnover, GMV, TPV and volume are ambiguous and are no longer revenue by default; new metric
"Transaction volume" and §11. This supersedes decision R2.
Amended 2026-10-08 (UI and claims fixes from live testing, George): a claim in another currency shows both figures and a
missing rate reads "FX rate needed" (§2, §4, §6); a direction with no figure is Unverified (§2, §4, §6). Amended the same
day by verdict-and-memo.md: the default gate date and "every row with an observed value" (§5), the register-only CSV
(§7) and "Not shown: value at stake" (§8) are replaced there.

## Goal
Test every register claim against the engine's computed metrics and write its gap, evidence label and proposed
gate. Python only: nothing reaches the gateway or a model.

## Scope
In: register claims; `audits.results` plus two new monthly series (table 2a).
Out: value at stake (its column is filled later by the ARR bridge, #6), bank data, narrative text, other new
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

A table row candidate gives one claim per value by period, id `<candidate id>#<n>`, n counted from 1.

Not inputs (2026-10-08): the Confidence column of the deck list (deck-parser.md §6) and a candidate's `type_from` and
`reading` and its `group` are not read here, so a claim's confidence changes no metric, gap or label. A candidate of type Unknown
(deck-parser.md §2) or Other cannot be approved without a type, so it never reaches the register; "Market size" is the
label of the claim type `market`, and its row is Unsupported (table 2a: every other claim type) as before.

## 2. Matching
Python proposes the metric from the claim type, a keyword in its snippet or borrowed label, and its unit
(table 2a); with none the row is Unsupported unless the analyst picks one. A segment is proposed when the snippet
or label names exactly one segment of the revenue file (whole word, any case); otherwise the claim is compared with
the whole-company figure and marked "whole company".

| Metric | Proposed for | Unit | Read from | Periods | Segment | Better |
|---|---|---|---|---|---|---|
| Revenue | revenue: "revenue", not "recurring revenue"; a turnover term is §11 | currency | new `revenue_series`: the revenue file by month in the reporting currency, recurring lines spread as for MRR, one-off lines in their invoice month | sum over the period's months | yes | higher |
| ARR | revenue: "ARR", "annual recurring revenue" | currency | `mrr_series` month total × 12 | period end month; no period: as-of | yes | higher |
| MRR | revenue: "MRR", "monthly recurring revenue", not "new MRR" | currency | `mrr_series` month total | period end month | yes | higher |
| Customer count | customers, a count | count | new `customers_series`: customers with MRR above 0 in the month, the engine's current-customer rule | period end month | yes | higher |
| New MRR | revenue: "new MRR" | currency | `new_mrr_by_quarter` | quarter | no | higher |
| NRR (12-month) | retention: "NRR", "net (revenue) retention" | % | `nrr.series`; `nrr.by_segment` | period end month from the 13th data month; by segment as-of | yes | higher |
| Gross revenue churn | retention: "revenue churn", "gross churn" | % | `gross_churn.series` | period end month from the 13th data month | no | lower |
| ACV | sales: "ACV" | currency | `acv_path.acv`, `.by_segment` | as-of | yes | higher |
| Median sales cycle | sales: "sales cycle" | days | `sales_cycle.median_days`, `.by_segment` | as-of | yes | lower |
| Win rate | sales: "win rate" | % | `win_rate.win_rate_pct` | as-of | no | higher |
| Gross margin | gross margin, in % | % | `cac_payback.quarters[q].gross_margin_pct` | quarter | no | higher |
| CAC payback | sales: "payback" | months | `cac_payback.quarters[q]` at the default L | quarter | no | lower |
| Transaction volume | a turnover term (§11), once the analyst or the rules of §11 say volume | currency | no engine source: always Unsupported | | | |
| none | every other claim type, growth rates and users among them; "bookings" alone; "retention" or "churn" without "net", "revenue" or "gross" | | | | | |

| Claim | Rule (table 2b) |
|---|---|
| Period end month | the metric's value in that month |
| Sum over the period's months | every month of the period lies in the data; if months are missing (before the first month, or a gap) the claim is Unverified and the reason names them ("months missing from the data: 2022-04 to 2022-12") |
| Quarter | the period's months equal one calendar quarter of the engine (every fiscal quarter does with a year-end in March, June, September or December) |
| As-of | the period ends in the as-of month |
| Period ends after the as-of month | forecast; observed is the as-of figure, for a sum the period's months up to the as-of month ("to date"; none yet: "—"), for a quarter metric the latest complete quarter (CAC payback: its headline quarter) |
| No period | the as-of figure (a quarter metric: the latest complete quarter; CAC payback: the headline quarter), marked "no period stated"; revenue, a sum, has no as-of figure: Unverified, reason "no period stated" |
| Other currency | converted at the saved FX rate before matching (the rate to the reporting currency, from the audit's FX settings on the mapping screen, chat-upload.md §16). The row shows both figures, "150,000 GBP (171,000 EUR)": the claimed amount and the converted amount, rounded to whole units (2026-10-09, George). The rate and the date it applies at (the as-of month's last day) are on hover, and stay in the stored row (`fx_rate`, `fx_date`), the CSV and the memo; the rate date never stands where the claim's date is expected. The Period column reads the claim's own period, or "no date" when it states none. A range converts at both ends. With no rate saved the row is Unverified, reason "FX rate needed", before any observed figure is read, whatever the period |
| No saved rate (2026-10-09) | the reason names the pair, "FX rate needed: GBP→EUR" (claim currency, reporting currency), and the screens link to the FX settings (chat-upload.md §16). The claim's own cell reads "150,000 BRL (BRL→EUR rate missing – enter it in FX settings at the top of the page)", with "FX settings" as the link |
| Direction with no figure | "Positive EBITDA" (deck-parser.md §2): no value, `claim_direction` "positive" or "negative". No metric is read and no gap is computed: the row is Unverified, reason "direction only: the claim states no figure to test", whatever the claim type. A figure typed over it by an edit ends the direction and the claim is tested as any other |
| Duration | 7 days a week, 30.44 a month, 12 months a year; hours stay unmatched, and so does a claim with no unit its metric measures (a sales cycle, ACV or ARR figure without a unit or currency) |
| Range | tested at the end nearest the observed value; inside it the gap is 0 |

## 3. Gap, rank, gloss
Gap = direction × (claimed − observed), in the metric's unit: positive is a miss, negative a beat. Normalised gap =
gap ÷ |claimed|. A forecast's gap is "to go" (claimed minus observed), not a miss. Every row with an observed value
shows its gap in native units and as % of the claim, Verified rows included. Rank: rows with a gap other than "to
go" by normalised gap, largest first, a beat counting as 0 so it never ranks as a miss; then the rest, in register
order. A gap of 0 reads "as claimed".

One rule for every gloss: the observed figure against the claimed one in plain words (higher or lower; longer or
shorter for days and months; more or fewer for a count), the kind in brackets: (miss), (beat), (to go by Dec 2026).

| Unit | Words | Examples |
|---|---|---|
| days | longer, shorter; a miss or to-go above the claim adds the working weeks (days ÷ 7, rounded; under 3.5: "under a working week") | "13.5 days longer, two working weeks (miss)"; "1.5 days shorter (beat)" |
| months | longer, shorter | "3.0 months longer (miss)"; "3.0 months shorter (beat)" |
| % | N points higher, lower | "7.0 points lower (miss)"; "5.0 points higher (beat)"; "17.0 points lower (to go by Dec 2026)" |
| currency | amount higher, lower; "to go" over €1M in millions | "€41,857 lower (miss)"; "€2,125 higher (beat)"; "€4.8M lower (to go by Dec 2026)" |
| count | N customers more, fewer | "1 customer fewer (miss)"; "1 customer more (beat)" |

## 4. Evidence label
Tested = the metric has a figure for the claim's period and segment, and the period ended by the as-of month.
Untested rows stay listed with a reason and observed "—" (a forecast shows its observed value).

| Label | Rule |
|---|---|
| Verified | Tested and within tolerance: ±5% of the claimed value for amounts, counts and durations; ±1 percentage point for rates. The boundary is Verified. |
| Contradicted | Tested and outside tolerance: a miss, or a beat. |
| Unverified | Not testable yet; the reason names what would test it: a Missing file (the engine's `unlocked_by`), a forecast period, a period before the metric's first month, no saved FX rate for the claim's currency ("FX rate needed"), a direction with no figure, a revenue claim with no period ("no period stated"), months of the period missing from the data (named), or a deck reading "AI suggestion, not verified" (until the analyst edits the claim, even unchanged): a claim that would otherwise be Verified or Contradicted; any other reason stands. |
| Unsupported | The app gives no figure: no metric proposed or picked, the metric not computed for that period or by segment, the segment not in the data, or the engine's "not computable" reason. |

## 5. Gate
No gate is proposed and no threshold has a default. For every row with an observed value the screen shows the claimed
and the observed figure beside an empty threshold field. The analyst sets the threshold, names the budget decision (max
200 characters) and may change the date; the gate is saved only when threshold and decision are both filled, and then
reads: "Before {budget decision}, {metric} must be at least (at most) {threshold} by {date}. Observed {value} ({month});
claimed {value} ({period})." The date defaults to the last day of the first fiscal quarter ending after the as-of month.

## 6. Claim register
One row per claim, no deck text (no snippet, no label). GET /api/audits/{id}/claims returns the rows in rank order
under `register`, beside today's `claims`; `register` is empty when the audit has no results.

| Field | Type | Note |
|---|---|---|
| `claim_id` | str | candidate id, `#n` for a value of a table row |
| `deck_file`, `page_ref` | str | "p12", "slide 4"; several joined by ", " |
| `claim_type`, `status` | str | CLAIM_TYPES; approved, edited |
| `deck_reading` | str | §1 |
| `claimed_value`, `claimed_high` | float, float or null | in the claim's currency |
| `claim_direction` | str or null | "positive" or "negative" for a claim with no figure; else null |
| `unit`, `currency` | str or null | |
| `claimed_converted`, `claimed_converted_high` | float or null | the claimed figure at the saved rate, in the reporting currency; null for a claim in the reporting currency or with no rate |
| `fx_rate`, `fx_date` | float, date; or null | the saved rate and the as-of month's last day; null as above |
| `period`, `period_start`, `period_end`, `period_note` | str, date, date, str; or null | note: "no period stated" |
| `segment`, `segment_set_by` | str | "Whole company", a data segment, "Not in the data"; python, analyst |
| `metric`, `metric_set_by` | str or null | table 2a; python, analyst |
| `direction` | str or null | higher, lower |
| `observed_value`, `observed_at` | float or null, str | "2024-02", "2023-Q4", "2024-01 to 2024-02" |
| `observed_source` | object | file, sheet, rows, rule |
| `gap`, `gap_normalised`, `gap_kind` | float or null | miss, beat, to go |
| `gloss` | str or null | table 3 |
| `evidence_label`, `reason`, `tolerance` | str | table 4; "±5%", "±1 pp" |
| `rank` | int | §3 |
| `value_at_stake_arr` | float or null | null until issue #6 |
| `gate_sentence` | str or null | §5; null until the gate is saved |
| `gate_threshold`, `gate_budget_decision`, `gate_date`, `gate_saved` | float, str, date, bool | |
| `as_of_month`, `as_of_defaulted` | str, bool | |
| `turnover_state`, `turnover_note`, `turnover_set_by`, `turnover_reason` | str or null | §11: null, ask, revenue, volume; the label or question; python, analyst; reason code |
| `implied_take_rate`, `implied_take_rate_source` | float or null, str or null | §11: a fraction; "revenue: file · sheet · rows; volume: deck file · page" |
| `turnover_suggested`, `deck_revenue_note` | str or null, str or null | §11 point 7: "volume" and "Deck revenue for the same period: 150,000 GBP (page 19); implied take rate 27%, derived, not verified"; both null unless the question is asked and the deck holds that revenue figure |

## 7. Monitoring baseline
GET /api/audits/{id}/claims.csv: the register rows in rank order as one CSV (the method's A9). Header = §6 field
names; numbers unformatted, dates ISO, `observed_source` as "file · sheet · rows".

## 8. Analyst screen
| Part | Content |
|---|---|
| Place | a new "Claim register" section on the Dashboard, under the metric cards, with a "Download baseline (CSV)" button |
| Row | rank, claim, period, segment, page, "Read from deck", observed value (source on hover), gap in native units and %, gloss, "Evidence" with its reason, gate (claimed and observed beside the empty fields of §5) |
| Editable | segment; metric (a metric in the claim's unit, or none); the gate's threshold, budget decision and date (the threshold field starts empty) |
| Read-only | everything else |
| Not shown | value at stake, until #6 fills it |

## 9. Data boundary and test fixture
The matching module imports nothing from `app.llm`; its fields and the two new series enter no gateway payload;
logs hold counts per label, never a value or gate text. The code PR extends test_gateway_data_boundary.py for each
(rules 14, 17).

Fixture `backend/tests/fixtures/claim_matching/testco_claims.json`: synthetic TestCo claims on `sample_data/`, one
in each label class at least for revenue, ARR and customer count. Public decks have no matching data.

| Setting or engine figure, measured on this branch (no network) | Value |
|---|---|
| Run A | EUR, December year-end, as-of 2024-02 defaulted from the last P&L month, P&L present; gate date 2024-03-31 |
| Runs B, C | run A without crm.csv; run A with a March year-end |
| Revenue FY2023; 2023-Q4; 2024-01 to 2024-02; first month | 187,701.05; 49,046.84; 33,520.81; 2023-01 |
| ARR 2024-02; 2023-12; first month | 202,125.48; 198,142.68; 2023-01 |
| Customer count, every month 2023-01 to 2024-02 | 5 (Enterprise 2, Mid-Market 2, SMB 1) |
| NRR 2024-02, whole company and each segment; first month | 112.68%; 2024-01 |
| Median sales cycle, whole and Enterprise; win rate | 58.5 days, 58.5; 40.0% |
| Gross margin 2023-Q4; CAC payback 2023-Q4 | 78.0%; not computable, "new MRR is zero" |

| # | Claim | Observed | Gap | Label | Rank |
|---|---|---|---|---|---|
| 1 | ARR €200,000, Feb 2024 | 202,125.48 | beat 2,125.48, 1.1% | Verified | 11 |
| 2 | "Enterprise sales cycle 60 days", no period | 58.5 (Enterprise) | beat 1.5 days, 2.5% | Verified | 12 |
| 3 | Win rate 41%, no period | 40.0% | 1.0 pp, 2.4% | Verified (boundary) | 9 |
| 4 | NRR 112%, Feb 2024 | 112.68% | beat 0.68 pp, 0.6% | Verified | 13 |
| 5 | ARR €240,000, FY2023 | 198,142.68 | 41,857.32, 17.4% | Contradicted | 3 |
| 6 | Sales cycle 45 days, no period | 58.5 | 13.5 days, 30.0% | Contradicted | 1 |
| 7 | Gross margin 85%, Q4 2023 | 78.0% | 7.0 pp, 8.2% | Contradicted | 5 |
| 8 | 4 customers, Feb 2024 | 5 | beat 1, 25.0% | Contradicted (a beat) | 14 |
| 9 | ARR €5,000,000, FY2026 | 202,125.48 (as-of) | to go 4,797,874.52, 96.0% | Unverified: forecast | 20 |
| 10 | NRR 115%, FY2023 | — | — | Unverified: before NRR's first month, 2024-01 | 21 |
| 11 | Run B: win rate 40%, no period | — | — | Unverified: Missing, "Upload CRM deals with …" | 1 (run B) |
| 12 | ARR $210,000, Feb 2024 | — | — | Unverified: FX rate needed | 22 |
| 13 | NRR 112%, Feb 2024, reading "AI suggestion, not verified" | 112.68% | beat 0.68 pp, 0.6% | Unverified: deck reading | 15 |
| 14 | TAM €2bn | — | — | Unsupported: no metric | 23 |
| 15 | 10,000 users | — | — | Unsupported: no metric | 24 |
| 16 | CAC payback 12 months, Q4 2023 | — | — | Unsupported: "new MRR is zero" | 25 |
| 17 | "Public sector NRR 130%", analyst sets "Not in the data" | — | — | Unsupported: segment not in the data | 26 |
| 18 | "Enterprise win rate 50%" | — | — | Unsupported: not computed by segment | 27 |
| 19 | Table row ARR €150,000 (Y/E 22) · €198,000 (Y/E 23) | —; 198,142.68 | —; beat 142.68, 0.1% | Unverified: before ARR's first month, 2023-01; Verified | 28; 16 |
| 20 | Run C: gross margin 85%, Q3 FY24 (Oct–Dec 2023) | 78.0% | 7.0 pp, 8.2% | Contradicted | 1 (run C) |
| 21 | ARR €190,000–210,000, Feb 2024 | 202,125.48 | 0, 0.0% (inside) | Verified | 17 |
| 22 | Win rate 42%, no period | 40.0% | 2.0 pp, 4.8% | Contradicted | 8 |
| 23 | ARR €212,700, Feb 2024 | 202,125.48 | 10,574.52, 4.97% | Verified (boundary) | 7 |
| 24 | ARR €213,000, Feb 2024 | 202,125.48 | 10,874.52, 5.11% | Contradicted | 6 |
| 25 | ARR €200,000, no period | 202,125.48 (as-of) | beat 2,125.48, 1.1% | Verified | 18 |
| 26 | "Public sector ARR €50,000", Feb 2024, analyst sets "Not in the data" | — | — | Unsupported: segment not in the data | 29 |
| 27 | Revenue €190,000, FY2023 | 187,701.05 | 2,298.95, 1.2% | Verified | 10 |
| 28 | Revenue €60,000, Q4 2023 | 49,046.84 | 10,953.16, 18.3% | Contradicted | 2 |
| 29 | Revenue €250,000, FY2024 | 33,520.81 (to date) | to go 216,479.19, 86.6% | Unverified: forecast | 30 |
| 30 | "Public sector revenue €40,000", FY2023, analyst sets "Not in the data" | — | — | Unsupported: segment not in the data | 31 |
| 31 | 5 customers, Dec 2023 | 5 | 0, 0.0% | Verified | 19 |
| 32 | 6 customers, FY2023 | 5 | 1, 16.7% | Contradicted | 4 |
| 33 | 8 customers, Y/E 22 | — | — | Unverified: before the first month, 2023-01 | 32 |
| 34 | "Public sector: 3 customers", Feb 2024, analyst sets "Not in the data" | — | — | Unsupported: segment not in the data | 33 |
| 35 | Run C: revenue €190,000, FY2023 (Apr 2022–Mar 2023) | — | — | Unverified: months missing, 2022-04 to 2022-12 | 2 (run C) |
| 36 | Run D: revenue €190,000, no period | — | — | Unverified: no period stated | 11 (run D) |

Unit-tested outside the fixture (test_claim_matching.py): ARR £150,000–160,000, Feb 2024 at a saved GBP rate of 1.14 reads
171,000–182,400 EUR at 1.14, 29 Feb 2024, and is tested at the converted figures; the same claim with no rate, for a period of
Feb 2024, FY2026 or none, is Unverified "FX rate needed"; "Positive EBITDA" and "Negative EBITDA" (Q2 2024) are Unverified
"direction only", also where the type has a metric, and a figure typed over the direction is tested.

Run D is run A's data with eleven more claims: one for each metric of table 2a that run A does not cover (MRR, New MRR,
gross revenue churn, ACV), figures by segment, and row 36. Its ranks stand on their own; the test file lists them.

## 10. Decisions
| # | Question | Decision of 2026-10-07 |
|---|---|---|
| D1 | Tolerance between Verified and Contradicted | ±5% for amounts, counts, durations; ±1 pp for rates; the gap in native units and % shown on every row, Verified rows included |
| D2 | A beat beyond tolerance | Contradicted, ranked after every miss |
| D3 | An unedited "AI suggestion, not verified" claim | Unverified until the analyst edits it |
| D4 | A claim with no period | tested at the as-of figure, marked "no period stated" |
| D5 | Metric list | table 2a, adding revenue, ARR and customer count by period; growth rates, users and bare retention or churn stay unmatched |
| D6 | Screen | §8 |
| R1 | Revenue for a period | recurring lines spread over their service months as for MRR, one-off lines in their invoice month |
| R2 | "Turnover" | superseded 2026-10-09 by §11: a turnover term maps to revenue or to transaction volume, never to one by default; "bookings" stays unmatched |
| Q1 | Revenue with no period | Unverified, reason "no period stated" |
| Q2 | A sum with months missing | Unverified, the reason names the months; Unsupported is only for metrics the app does not compute |
| Q3, Q4 | Forecast of a quarter metric; a sum with no month to date | latest complete quarter (CAC payback: headline); "—" |
| Q5 | A gap of 0 | gloss "as claimed" |
| Q6, Q7 | Gloss wording | one rule for all metrics: direction in plain words, kind in brackets (§3) |
| Q8 | Units | years × 12 → months; hours and unit-less claims stay unmatched |
| Q9 | Gate threshold | no default; claimed and observed beside an empty field; saved when filled (§5) |
| Q10–Q12 | Deck reading, table-row ids, no results | as implemented (§4, §1, §6) |

## 11. Turnover and transaction volume (2026-10-09)
Turnover terms: turnover, GMV, TPV, gross merchandise value or volume, trading volume, payment volume, transaction
volume, total payment volume (whole words, any case). A claim whose snippet or borrowed label holds one, and no
ARR, MRR or "new MRR", is a turnover claim. Resolution, in this order:
1. The analyst's metric for the claim, if set, stands (§8).
2. The analyst's answer, one click Revenue or Volume with a reason code: stored on the claim and on the audit under
   a hash of the term and the period (no deck text), so the same term and period in another claim reuses it.
   Reason codes: `deck_says_gross_revenue`, `deck_says_processed_volume`, `file_confirms`, `other`. The control is shown
   on every turnover row, so the analyst can change Revenue to Volume and back. No reason is preselected: the Revenue and
   Volume buttons stay disabled until one is chosen, and the server refuses the contradictory pairs (Volume with
   `deck_says_gross_revenue`, Revenue with `deck_says_processed_volume`) with 422.
3. A revenue file covers the claim period (revenue is read for every month, not a forecast). The file revenue is that of
   the segment the claim names (the whole company when it names none). A single figure is compared with it: within
   tolerance (§4): Revenue, tested as today, shown as "Gross revenue (turnover)"; above tolerance, whatever the multiple:
   Unverified, the question "Revenue or volume? Confirm below", reason "turnover or volume: confirm Revenue or Volume", until the
   analyst answers (amended 2026-10-09, George: the 3x threshold is dropped); below tolerance: Revenue, the ordinary
   revenue rule (Contradicted, a beat). A range is compared at the end nearest the file revenue (inside the range: within
   tolerance), and the same three cases apply. The claim is converted at the saved rate first; with no rate saved the row
   is Unverified, "FX rate needed: USD→EUR", before the question is asked.
4. No file covers the period (no revenue file, months missing, no period, a forecast): the question is asked. If the
   deck says "take rate" anywhere (any case, hyphen or space, singular or plural; read by Python from the parsed deck;
   only the yes or no is kept) the row reads as Volume until the analyst answers; otherwise it is Unverified, "turnover
   or volume: confirm Revenue or Volume". Fees, commission and spread no longer count (amended 2026-10-09, George: they
   are in most decks that have a subscription or a sales team).
5. Volume is never matched to engine revenue: Unsupported, "no engine volume source for transaction volume", until
   an engine volume source exists.
6. Implied take rate = file revenue for the claim period ÷ claimed volume (in the reporting currency), on a Volume row
   when the revenue file covers the period: `implied_take_rate` (fraction) and `implied_take_rate_source` ("revenue:
   file · sheet · rows; volume: deck file · page"). It is derived, never Verified. A volume figure from a column
   marked Volume in the upload is not read (it needs an engine field, contract change): decision pending.
7. Deck revenue for the same period (amended 2026-10-09, George): a turnover figure is never compared with a revenue
   figure for a deck inconsistency (deck-parser.md §2), whatever the deck's labels, until the analyst has confirmed the
   turnover claim as Revenue; turnover is compared with turnover and revenue with revenue. When the claims of the register
   hold, for a turnover claim that asks, one single revenue figure (deck label Revenue, same file, same currency, same
   period, one value) below the turnover figure beyond tolerance (§4), Volume is pre-selected in the question "Revenue or
   volume? Confirm below" and the row shows "Deck revenue for the same period: 150,000 GBP (page 19); implied take rate
   27%, derived, not verified" (revenue ÷ turnover, no currency conversion, never Verified, never stored). The state stays
   `ask` and the row stays Unverified: the Revenue and Volume buttons still need a reason and the analyst's click. Only
   the register's own claims are read: an unapproved revenue figure gives no hint. No comparison is made after the
   analyst confirms Revenue (decision pending: a deck inconsistency is flagged when the deck is parsed).
New register fields: `turnover_state` (null; ask; revenue; volume), `turnover_note` (the label or question),
`turnover_set_by` (python, analyst), `turnover_reason`, `implied_take_rate`, `implied_take_rate_source`,
`turnover_suggested` (null; volume), `deck_revenue_note`.
PUT /api/audits/{id}/claims/{claim_id}/turnover {as, reason}.

## Done when
- Every fixture row gives its label, gap, gloss and rank (`backend/tests/test_claim_matching.py`).
- The boundary tests pass; the CSV equals the register; the screen follows §8.
