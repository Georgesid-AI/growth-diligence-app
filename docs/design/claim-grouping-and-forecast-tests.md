# Design note: claim grouping, forecast tests, chart pairing, yearly CAC payback, the five

Status: draft for decision, 2026-10-26. No code, test or spec change; nothing below is built. Source: George's task of 26 Oct 2026, after
the first live run. Every example is synthetic: the TestCo fixture (`backend/tests/fixtures/claim_matching/testco_claims.json` on
`sample_data/`, run A: EUR, December year-end, as-of Feb 2024 defaulted, P&L monthly Jan 2023–Feb 2024), the forecast fixtures
(`backend/tests/fixtures/forecast/`) and pages built with `tests/pdf_support.pdf_page`. No public deck is named and no client figure appears.
Figures measured on this branch (no network, no MongoDB) with `tests/test_claim_matching.results_for(RUNS["A"])`; the CAC example is by hand
from `annual_forecast.csv`.

**No architecture note.** Everything is Python computed on read (`app/claim_matching.py`, `app/structures/`, the deck parser). The parser
gains layout only (rectangles, rotated text), never sent to a model; rule 16 and the page boundary are untouched. The one engine-field change
(item 6) follows rule 23.

## 0. Challenge and deletions (rule 4)

Needed: the live run put four quarters and their year into the five as five claims, annualised a quarter to a value at stake the year already
carried, labelled every forecast "cannot be tested" five times over, dated a bar from a marker's note and asked for a monthly P&L the company
does not keep. The simpler version: one claim per metric and fiscal year, one implied rate per forecast, one sentence for five forecasts.
Deleted first: the annualisation of a slice (item 2); the five repeats of the forecast sentence and the `#rank` prefix on the five (item 7); the
CAC payback data-gap request when a yearly figure exists (item 6); the fallback that lets any date cell on a page correct a period (items 4, 5).

TestCo figures the examples use (run A): revenue FY2023 187,701.05 (Q1 44,845.48 · Q2 46,204.35 · Q3 47,604.38 · Q4 49,046.84; H1 91,049.83 ·
H2 96,651.22); Dec 2023 16,511.89; Jan 2024 16,677.02; Feb 2024 16,843.79; ARR Feb 2024 202,125.48; MRR Jan 2023 14,800.00; customers 5 every
month; ACV 40,425.10; evidence to Feb 2024, 14 months of revenue.

## 1. Grouping: one claim per metric and fiscal year

**Rule.** On read (`build_register`, after `_expand`, before `_rank`), claims of the same metric, currency and unit whose periods lie in one
fiscal year of the audit (`period_range`, the audit's year-end) form one group when the year is stated and the parts complete it:
- a flow metric (Revenue, New MRR, gross profit, EBITDA, costs, burn): the quarters (4), halves (2) or months (12) of the year sum to the year
  figure within 2% (|Σ parts − year| ≤ 0.02 × year); every part of the year must be present, none twice;
- a balance or a count (ARR, MRR, customers, cash, headcount): the last part of the year (Q4, H2, the year-end month) equals the year figure
  within 2%; the other parts may be absent.
The year is the **headline** row: its own evidence label, gap, value at stake, rank, gate. The parts are **slices**: each keeps its own test
and label (a Q1 that is Contradicted stays Contradicted), is listed under the headline's Details ("Slices: Q1 44,845 Verified · Q2 … "), has
no rank, no gate, no value at stake (`vas_reason` "counted in the year, #n"), is never in the five, the banner, the proposal's candidates or
the memo's claim counts (Appendix A prints it indented under its headline). Register fields: `group` (the headline's `claim_id`, null for a
row in no group), `group_role` (`headline`, `slice`, null), `group_note` ("4 quarters sum to the year, 0.0% off"). Nothing is stored; an edit,
Undo or Not a company claim re-groups on the next read. A slice the analyst edits out of its year leaves the group.

**Conflict.** Two different figures for the same metric, currency, unit and period (a year stated twice, or a year and parts that do not meet
it within 2% while another year figure does) are a conflict: today's "Deck inconsistency" pair becomes one card under Needs your attention,
"Two figures for Revenue FY2023: 210,000 EUR (p4, table) and 187,701 EUR (p4, panel). Which is the total?" with one button per figure and the
hint "The quarters on p4 sum to 187,700 EUR" when parts sum to one of them. Nothing is pre-selected (as the turnover question, claim-matching.md
§11). The answer is stored on the claim inputs under a hash of metric and period (no deck text, like the turnover answer): the chosen figure is
the headline (the slices group under it); the other keeps its figure and becomes a **segment** row, `segment` "Not in the data", Unverified
"segment not in the data" with the row's Fix control to name a data segment, after which it is tested by segment as any claim. Until the
analyst answers, both rows are Unverified "two figures for this period: confirm the total" and neither is in the five. A year whose parts miss it
by more than 2% with no second year figure is **not** grouped: the parts stay stand-alone claims (today), the year's Details carry "parts sum
to 190,500 EUR, 1.5% off" as an informational note.

**Worked example** (synthetic page, pdf_page): a table "Revenue (EUR)" with the header row Q1 2023 · Q2 2023 · Q3 2023 · Q4 2023 · FY2023 and the
values 44,845 · 46,204 · 47,604 · 49,047 · 187,701. Today: five register rows, 2023-Q4 ranked by its gap, the year and the quarters competing for
the five. After: one headline "Revenue · 187,701 EUR, FY2023", Verified (observed 187,701.05, as claimed), Details "Slices: Q1 2023 44,845 EUR
Verified · Q2 46,204 Verified · Q3 47,604 Verified · Q4 49,047 Verified · sum 187,700 EUR, 0.0% off". Conflict variant: the same table plus a KPI
box "2023 revenue 210,000 EUR": one card; answer 187,701 → the headline above; the 210,000 row reads "Revenue · 210,000 EUR, FY2023 · Not in the
data" until a segment is named. Balance variant: "ARR" row Q1–Q4 2023 with the FY2023 cell equal to Q4 → grouped, Q4 is the slice the year equals.

**Tests** (`test_claim_grouping.py`, each failing first on a deliberate violation, rule 11): four quarters within 2% group, five rows become one
headline and four slices with `group`, `group_role`, `group_note`; 2.5% off does not group and the year carries the note; three of four quarters do
not group; a balance groups on its last part only; a slice is never in `verdict.proposal`, `banner_ids` or the memo count, and its `vas_reason`
names the headline; a conflict raises one card (`GET /decks`, `attention`), the answer sets headline and segment, the unanswered pair is out of
the five; an edit of a slice's period re-groups on read; the March year-end run (run C) groups Apr–Mar. `test_gateway_data_boundary.py`: the three
fields and the card text (rule 14). Frontend: `FiveClaims.test.jsx` (slices under Details), `NeedsAttention.test.jsx` (the card and its hint).

**Specs that change.** claim-matching.md §1 (a group is computed on read), §3 (slices unranked), §6 (three fields), §8; deck-parser.md §2
"Deck inconsistency" (the mark becomes the conflict card for same-period pairs; different-currency and rate-vs-amount pairs unchanged);
verdict-and-memo.md §6.1 (candidates exclude slices), §7.2 Appendix A (indented slices); simplified-flow.md §2 (one card row: "Conflict").

## 2. Value at stake: no annualisation of a grouped slice; "run-rate" for a stand-alone part

**Rule.** `_value_at_stake` annualises a revenue-like amount as today (claim-matching.md, 2026-10-24: amount × 12 ÷ months of the period, capped
at Target ARR) with two changes: a slice has none (`vas_reason` "counted in the year, #n", item 1); a quarter, half or month with **no year figure
for its fiscal year in the register** (any page, any status but rejected) is annualised and its VaS line reads "{amount} EUR (run-rate: {period} ×
{factor})". The register row gains `vas_basis`: "as stated" (a year or ARR), "MRR × 12", "run-rate", null. Nothing else changes: ARR as stated, MRR ×
12, rates and counts as today, the cap stands.

**Worked example** (TestCo). Grouped: the FY2023 headline above has VaS 187,701 EUR (as stated); its Q4 slice none, "counted in the year, #1".
Stand-alone: a deck that states only "Q4 2023 revenue 49,047 EUR" gives VaS 196,188 EUR, "run-rate: Q4 2023 × 4"; "Dec 2023 revenue 16,512 EUR"
alone gives 198,142 EUR, "run-rate: Dec 2023 × 12". Today both read the amount with no word for how it was reached.

**Tests** (`test_claim_grouping.py`, `test_vas_top5_reasons.py`): a grouped quarter has no VaS and names the headline;
the same quarter with the year row rejected is annualised and reads run-rate; the cap applies to the run-rate; `vas_basis` on each case;
`claimRegister.test.js` for the VaS text. Boundary: `vas_basis` and the two strings.

**Specs that change.** claim-matching.md (the 2026-10-24 value-at-stake paragraph and §6: `vas_basis`); chat-upload.md §29.2 (the VaS line);
verdict-and-memo.md Appendix A (the VaS cell prints the basis word).

## 3. Forecast claims: tested as an implied rate

**Rule.** A claim whose period ends after the as-of month (table 2b's "forecast") is no longer only "Forecast period after the data". For the
types revenue, arr, mrr and customers (and revenue_growth as today) Python computes:

| Field | Revenue (a sum) | ARR, MRR (a balance) | Customers (a count) |
|---|---|---|---|
| Base period | the latest full fiscal year every month of which is in the data (`metric_periods`, no missing month, ending on or before `evidence_to`); none: the 12 months to `evidence_to` when the data holds them; fewer: no base | the metric at `evidence_to` | the count at `evidence_to` |
| Base figure B | the revenue sum of the base period | ARR or MRR at `evidence_to` | customers at `evidence_to` |
| Months m | base period end → forecast period end | `evidence_to` → forecast period end | as ARR |
| Implied annual rate | (F ÷ B)^(12 ÷ m) − 1 (m = 12: F ÷ B − 1) | same | same |
| Observed annual rate | YoY of the base period (dates-and-periods.md §5: Σv(s..e) ÷ Σv(s−12..e−12) − 1) when the 12 months before it are in the data; else the annualised rate over the data window, (v(e) ÷ v(s))^(12 ÷ (e − s)) − 1, s the first month, e `evidence_to`, when e − s ≥ 12; else the same over the shorter window | the annualised rate of `mrr_series` over the window (YoY when 24 months exist) | the same of `customers_series` |

F is the forecast figure in the reporting currency (a range: the end nearer the observed rate, as a range is tested today). A forecast of a
quarter or a month is F as stated with m to its own end (no annualisation of F). Result on the rate, with tolerance T = 5 percentage points
(recommended; decision 3) and the direction "a plan may assume at most the growth shown":

| Case | Label | Reason (word for word) |
|---|---|---|
| no base, or a base of 0 or below, or no observed rate | Unverified | "Forecast period after the data (as-of {month}); cannot be tested until that period's revenue lines are supplied." (unchanged) |
| observed rate from a window under 12 months | Inconclusive | "forecast implies {x}% a year; observed {y}% from {n} months only" (the figures shown, no gap: evidence-labels.md §3 invariant) |
| implied ≤ observed + T | Verified | "forecast implies {x}% a year; observed {y}% ({window})"; implied below observed − T is marked (beat) and listed under Worth flagging |
| implied > observed + T | Contradicted | "forecast implies {x}% a year; observed {y}% ({window}); {d} points above" |

The figure itself is not retyped: `observed_value` stays the as-of figure "to go" (today), the row gains `implied_rate`, `implied_basis` ("{F} ÷
{B} ({base period}), {m} months"), `observed_rate`, `observed_rate_window` ("Jan 2023–Feb 2024, annualised" / "FY2023 vs FY2022"), and under
Details the sentence "Forecast period after the data (as-of {month}); the figure cannot be tested until that period's revenue lines are supplied"
stays, below the rate line. The gap, gloss and rank are the rate's (points above, as a rate), so a forecast ranks with the tested rows. Value at
stake is unchanged. The growth-rate test of dates-and-periods.md §5 is not touched: a stated growth claim still tests its stated basis.

Where the deck states both a revenue (or ARR) forecast and a customer count for the same period, two derived lines go under Details of each,
never a label (derived, like the take rate of §11): "implies {F ÷ customers} per customer; ACV in the data {acv}" and "at today's ACV the
revenue implies {F ÷ acv} customers; the deck states {n}". `implied_per_customer`, `implied_customers` on the row; null otherwise.

**Worked example** (TestCo run A, fixture rows 9 and 29, plus two rows to add).
- Row 29, Revenue 250,000 EUR, FY2024: base FY2023 = 187,701.05 (every month in the data), m = 12, implied 33.2%. Observed: FY2022 is not in the
  data, so the window Jan 2023–Feb 2024 (13 months, ≥ 12): (16,843.79 ÷ 14,800.00)^(12 ÷ 13) − 1 = 12.7%. 33.2 > 12.7 + 5 → **Contradicted**,
  "forecast implies 33.2% a year; observed 12.7% (Jan 2023–Feb 2024, annualised); 20.5 points above". Details: "Forecast period after the data
  (as-of Feb 2024) …", to go 216,479.19 as today.
- Row 9, ARR 5,000,000 EUR, FY2026: B = 202,125.48 at Feb 2024, m = 34 (Feb 2024 → Dec 2026), implied (5,000,000 ÷ 202,125.48)^(12 ÷ 34) − 1 =
  210.3% a year; observed MRR growth 12.7% → **Contradicted**, 197.6 points above.
- New row, Revenue 205,000 EUR, FY2024: implied 9.2% ≤ 12.7 + 5 → **Verified**, "forecast implies 9.2% a year; observed 12.7% (…)".
- New row, ARR 240,000 EUR, Dec 2024: m = 10, implied 22.9% → Contradicted (5.2 points above), to show m ≠ 12.
- Run E (to add): run A's revenue file cut at Sep 2023 (9 months): the window is 9 months → **Inconclusive** on every forecast row, "observed
  {y}% from 9 months only"; a file of 3 months gives no base → Unverified, the sentence as today.
- Customers: a page stating "250,000 EUR revenue and 8 customers in 2024": the revenue row's Details read "implies 31,250 EUR per customer; ACV in
  the data 40,425 EUR" and "at today's ACV the revenue implies 6.2 customers; the deck states 8". The customers row (8, FY2024, B = 5, m = 10)
  implies 76% a year against observed 0% → Contradicted.

**Tests** (`test_forecast_rates.py`): each table row above with the figures to 0.1 point; the base-period choice (full fiscal year, then 12 months,
then none) shown on three cut files; YoY used when 24 months exist (a 26-month synthetic file); m from the period end, 12 for a next-year figure;
a range takes the nearer end; T at the boundary (implied = observed + 5.0 is Verified); the beat mark below observed − T; the per-customer lines
present only when both figures exist for the period; the rank is the rate's; the Details sentence is kept; a growth claim is unchanged
(`test_dates_and_periods.py` untouched and still green); the conclusion counts a Contradicted forecast (`test_verdict.py`). Boundary: the five
fields and three reason texts (rule 14). Contract: no engine field (computed on read), so `schemas/metrics.py` is unchanged; the register's
`FIELDS` and the CSV header grow (`test_claim_register_api.py` round trip).

**Specs that change.** claim-matching.md table 2b (the forecast row), §3 (a forecast's rank), §4 (the four cases), §6 (seven fields), the
2026-10-25 amendment (the sentence moves under Details); evidence-labels.md §3 (an Inconclusive case: "observed rate from under 12 months");
dates-and-periods.md §5 (the window rule is shared, one function); verdict-and-memo.md §7.2 (Worth flagging lists a conservative forecast);
docs/specs/forecast-claims.md, named "to be written" in deck-parser.md §2, is this section once decided.

## 4. Period correction from headings: the token, never the text

**Rule.** The correction `period not on page` (claim-matching.md, Amended 2026-10-26) and the flag `period from page heading` take their
candidate from a heading's **period token** only: `claims.period_cell` run over the heading cell (a title cell or a top-band cell above the figure,
`page_check.period_check`) gives a year ("2024", "FY24", "2024E"), a quarter or half with its year in the same heading ("Q3 2024 plan", "H1 FY25"),
or a month with its year ("March 2025 board"). The candidate is that label and the cell id; the heading's words are never stored, shown or logged
(the Diagnostics line and `corrections[].original/corrected` hold "2024" and "p3r1c1"). A heading with no year token gives nothing ("Q3 highlights":
no year is inferred from the deck date or another heading); a year range gives nothing (issue #148); a heading with two tokens ("2023 vs 2024")
gives two candidates, so a card; a heading below the figure gives nothing (borrowing never reads below). A sentence in the figure's own block is
no source (issue #154); "from 2021" in the value cell keeps the flag `growth dated to start year`.

**Worked example** (synthetic page): title "FY2024 plan — what we will deliver", a KPI box "Revenue 1.2M EUR" with no date of its own; the model
cites the title as `period_cell`. Today: period 2024 with the informational flag and `original` the heading text in Diagnostics. After: the same
period, the correction record reads `{field: period, original: null, corrected: "2024", cell: "p3r1c1"}`. Title "Q3 highlights" over the same box:
no period, "Period not read – set it in the claim row" (table 2b). Title "2023 vs 2024 plan": two candidates, a card with two buttons.

**Tests** (`test_period_from_heading.py`): the four heading forms give their token; the Diagnostics line and the stored correction hold no heading
word (a heading with the word "Confidential" never appears in any stored field: the boundary test's text-leak check); a quarter without a year
gives none; two tokens give a card; a heading below gives none. Boundary: the log line shape (rule 17).

**Specs that change.** claim-matching.md, Amended 2026-10-26 point 1 (the candidate is a token); deck-parser.md §2 "Borrowing" (the heading rule
applies to the page read's corrections); chat-upload.md §28 (`period from page heading`).

## 5. Chart pairing checks

**Rule.** The PDF reader keeps, with the page grid and never sent (layout, as `next_to` and `bar_year`): the page's filled rectangles (position,
size, fill colour; `pdfplumber` `page.rects`), each text cell's `in_rect` (the smallest rectangle that contains its baseline), and `rotated` for
a line built from chars with `upright` false (joined along their baseline into one cell at the chars' position). Then:
1. **A figure inside a bar segment cites the segment's own label or the legend.** A value cell with `in_rect` is paired with the text cell of the
   same rectangle that holds words and no figure (the segment's label), else with the legend entry whose swatch (a rectangle of at most 2% of the
   page's width, directly left of a short text line) has the same fill colour. That cell is the one label candidate (`corrections.label_candidates`)
   and the only cell `page_check.label_cells` accepts for the figure besides its own; a label cited elsewhere is `label mismatch`. A figure with
   `in_rect` and neither candidate keeps "no heading".
2. **Rotated axis text counts as a label.** A `rotated` cell is a date source, a header and a label like any upright cell: a rotated year row under
   the bars is the axis of `claims.bar_years` (the labels are "nothing but a year", overlap measured on the rotated extent); a rotated axis title
   ("Revenue, EUR m") is a label and a unit source (`unit_check` next-to).
3. **A marker or line with no printed figure yields no claim.** A claim whose `value_cell` holds no figure (a legend entry, an axis title, a marker's
   note) and whose value is in no cell of the page (`figure_check` false, `find_elsewhere` none) is dropped before the register with the Diagnostics
   line `{page, kind: "figure on no cell, not a claim", metric, value, period}`, as the derived-figure drop of 2026-10-26; no card. A claim whose
   value is on a cell keeps today's checks (`value not on page` stays a card for a value that is on the page but not where cited).
4. **A date attached to a marker is never the period of another figure.** A date cell is "attached" when its cell or box holds words other than the
   date ("Series A · Jun 2023"), or it lies inside the plot area (between the axis row and the chart's top text, not in the axis row, not in a top
   band) with no `in_rect`. Such a cell is a date source only for a figure in its own cell: `date_sources`, `holds_period`, the `period from another
   cell` correction and `period not on page` candidates all skip it. The axis row and a heading are unchanged.

**Worked example** (synthetic page, pdf_page with rects): a stacked bar chart "Revenue by line (EUR k)": three bars over the rotated labels 2022 ·
2023 · 2024; each bar two filled rectangles; "120" printed inside the lower segment of the 2024 bar, "80" inside the upper; a legend bottom-right,
two swatches beside "Subscriptions" and "Services"; a dot on a line above the bars with the note "Series A · Jun 2023". The model's reply: 120
(label cell: the legend entry "Subscriptions", period 2024), 80 ("Services", 2024), and a third claim 200 citing the dot's note cell with period
2023-06. After: 120 and 80 are Matched to page with their legend labels (rule 1) and the rotated 2024 (rule 2); 200 is dropped with a Diagnostics
line (rule 3); nothing takes Jun 2023 (rule 4), and a model period of 2023-06 on 120 is `period not on page` with the one candidate 2024 from the
axis, applied as a single-candidate correction. Today: the legend is outside the figure's row and column (label mismatch, hotfix of PR 182), a rotated
label is read as the file writes its chars with no rotated extent (the parser reads no `upright` flag, so no axis row), 200 is a Review card,
and Jun 2023 is a correction candidate for every figure on the page.

**Tests** (`test_chart_pairing.py`, pages built with rects): each rule against its violation (a figure inside a rect takes the legend swatch of the
same colour and not of another; a rotated year row is the axis; a claim on the note cell is dropped and logged; the note's date is in no source
list for the bar figures); `test_deck_parser.py`: rects and rotated lines are read, kept with the grid and absent from `redact.structure_text`
and the page text sent (`test_gateway_data_boundary.py`: `in_rect`, `rotated`, `rects` join the layout fields never sent).

**Specs that change.** deck-parser.md §1 (rects, rotated chars), §2 "Bars" and "Dropped" (rules 2–4), §7 (chart cells); ai-reads-rules-check.md
§2 check 3 (date sources); chat-upload.md §28 (the drop and its line); claim-matching.md, Amended 2026-10-26 point 1 (candidates skip an attached
date). Measured in the build PR with `scripts/consistency_run.py --probe` on the public test decks (the README rule), counts in the spec lines.

## 6. CAC payback on a yearly basis when the P&L is yearly

**Rule.** When no monthly P&L is mapped and `yearly_basis` holds the claim's fiscal year (chat-upload.md §26.8), a `cac_payback` claim (and a
sales "payback" claim) is tested against that year's figure, which becomes: **CAC payback (yearly basis) = 12 × annual S&M ÷ (new ARR × gross
margin)**, months; new ARR = ARR at the fiscal year end − ARR at the previous year end from `mrr_series` × 12 when the revenue file holds both
year-end months; else today's new revenue (revenue − the year before), the rule text naming which. `yearly_basis.years[].new_arr`,
`new_arr_source` ("mrr_series" / "yearly revenue") are added (rule 23: `schemas/metrics.py`, the contract test, contract 10). The register row:
metric "CAC payback", `observed_at` "FY2024 (yearly basis)", tolerance ±5%, lower is better, the citation's rule ending "· yearly basis, not
monthly"; the five and the memo print "(yearly basis)" after the observed figure. The growth-engine rating reads the yearly figure when the
monthly one is absent, its line ending "CAC payback 6.7 months (yearly basis)". **No data request for a monthly P&L in that case**: the
`missing_data` item "CAC payback" and the Data gaps row ("P&L is yearly; CAC payback needs monthly S&M …", §29.4) are not written when the yearly
figure exists for any actual year; `yearly_basis.missing` drops "CAC payback (monthly)". With no S&M line, no prior year or a non-positive margin
the reason of today stands and the request stays.

**Worked example** (`annual_forecast.csv`, EUR thousands, read as a statement; by hand): 2024A revenue 1,240 (2023A 820), cost of goods sold 450,
marketing expenses 150 (the S&M line). Gross margin 63.7%; new revenue 420 (no revenue file in the fixture, so the fallback); payback = 12 × 150 ÷
(420 × 0.6371) = **6.7 months**, "yearly basis, not monthly". A deck claim "CAC payback 8 months, 2024": observed 6.7, beat 1.3 months (15.9%) →
Verified (beat). "CAC payback 5 months, 2024": miss 1.7 months (34%) → Contradicted. With TestCo's revenue file beside a yearly P&L, new ARR for
2023 would be 198,142.68 − ARR at Dec 2022 (not in the data: 2023 has no new-ARR figure, the fallback applies, the reason "no ARR for the year
before" in `new_arr_source`).

**Tests** (`test_cac_payback_yearly.py`): the figure above to 0.1 month from the fixture through the statement path; new ARR used when both year
ends are in `mrr_series` (a synthetic 26-month revenue file) and the rule text says so; the claim rows above (Verified beat, Contradicted) with
"(yearly basis)" in `observed_at`; no "CAC payback" missing-data item and no Data gaps row while the yearly figure exists, the row back when the
S&M line is removed; the rating line; `test_interface_contracts.py` pins the two fields and contract 10 (results under 9 read "Stale – re-run
audit"); `YearlyBasis.test.jsx` (the column reads new ARR or new revenue, as the row says).

**Specs that change.** chat-upload.md §26.8 (the formula), §29.4 (the gap text is conditional), S30g (a New ARR column); claim-matching.md table 2a
(CAC payback: "quarter, or the fiscal year on a yearly basis"); interface-contracts.md (contract 10); simplified-flow.md §3 (the rating row).

## 7. Audit page: the five when they are forecasts

**Rule** (`FiveClaims.jsx`, `verdict.five`). The five's columns become **Plan figure · Period · Implied assumption · Observed rate · Result**:
- Plan figure: the claim's type and figure as `claimCellText` prints it; **no `#rank`** and no claim id anywhere in the block (the rank stays in the
  register and the memo);
- Period: the claim's period text only ("FY2024", "Q4 2023", "Dec 2024"); the "period read as …" note, the page reference and the source go to
  the Source link and Details, not the column;
- Implied assumption: "{x}% growth a year from {base period}" for a forecast (item 3); for a tested figure "—"; for a slice-grouped year the
  headline's own (item 1);
- Observed rate: "{y}% ({window})" for a forecast; the observed figure and month for a tested figure (today's Evidence shows);
- Result: the label chip and the reason, as today.
When **all five are forecasts**, one sentence sits above the rows in place of five repeats: "All five selected claims are forecasts: each is tested
as the growth it implies against the growth observed in the revenue data ({window})." and no row repeats the "Forecast period after the data"
sentence (it stays under each row's Details). With one to four forecasts the sentence is not shown and each forecast row's reason reads its rate
line (item 3). The memo's Verdict detail prints the same five columns.

**Worked example** (TestCo run A with rows 9, 29 and the two new forecast rows in the five, plus one more forecast): the sentence above; a row
"Revenue · 250,000 EUR | FY2024 | 33.2% growth a year from FY2023 | 12.7% (Jan 2023–Feb 2024, annualised) | Contradicted · forecast implies
33.2% a year; observed 12.7%; 20.5 points above"; a row "ARR · 5,000,000 EUR | FY2026 | 210.3% a year from Feb 2024 | 12.7% (…) | Contradicted …".
Mixed five (row 5 ARR 240,000 FY2023 among them): no sentence; its row "ARR · 240,000 EUR | FY2023 | — | 198,143 EUR · 2023-12 | Contradicted ·
41,857 EUR lower (miss)".

**Tests**: `FiveClaims.test.jsx` (five columns and headers; no "#" in the block; the period cell holds the period string only; the sentence with
five forecasts, absent with four; implied and observed cells from the register fields; Details keeps the forecast sentence); `test_verdict.py`
(`five[]` carries `implied_rate`, `observed_rate`, `period`, `forecast` and `all_forecasts`); `test_ic_memo.py` (the five columns in Verdict
detail; the number check accepts the rates as register figures, §7.4 c); `Dashboard.simplifiedFlow.test.jsx` unchanged otherwise.

**Specs that change.** simplified-flow.md §1 item 4 (the columns, the sentence); claim-review-conclusion.md §3 (unchanged wording, the five's
rows); verdict-and-memo.md §6.4 (five claims) and §7.2 (the memo's five); evidence-labels.md §1 (the hover explainers on the Result header stay).

## 8. Build order and one PR each

1. Item 4 (heading token) and item 5 (chart pairing): parser and checker, no screen change but the dropped card (decision 5).
2. Item 1 and item 2 together (grouping and VaS): register, five, card.
3. Item 3 (forecast rates) with item 7 (the five's columns): the one PR that changes labels and the conclusion.
4. Item 6 (yearly CAC payback): engine field, contract 10.
Each PR: spec lines first, the failing tests, then code; the session log of rule 7; the counts of the README rule measured on the public decks in
the PR, never in a spec line of this note.

## 9. Decisions for George (rule 19: what the analyst sees, and what may be Verified)

1. **Grouping** (item 1, rows disappear): four quarters and a year become one row with the slices under Details; the memo's counts count the
   headline only. Options: (a) as written, slices under Details and out of every count (recommended); (b) slices stay rows, marked "part of #n",
   out of the five only. Also: 2% as the sum tolerance (rounding on a slide); a year that its parts miss by more than 2% is not grouped and
   carries a note, no card (a card would ask about every rounded chart).
2. **Conflict card** (item 1, a new card): "Which is the total?" with one button per figure, nothing pre-selected, the loser a segment row "Not
   in the data" with Fix. Options: (a) as written (recommended); (b) keep today's Deck inconsistency mark on both rows and no card.
3. **Forecast rates may be labelled** (item 3, rule 19.1): Verified / Inconclusive / Contradicted on the implied growth against the observed
   growth; T = 5 percentage points; a forecast below observed − 5 is Verified (beat); "Contradicted" reads "forecast implies x% a year; observed y%;
   d points above". A Contradicted forecast then drives the conclusion ("Selected claims not supported"). Options: (a) as written (recommended);
   (b) T = 10 points; (c) the rate never Contradicts: the top case reads Inconclusive and only a forecast at or below the observed rate is
   Verified. The base period and the window rule (full fiscal year → 12 months → none; YoY when 24 months exist, else annualised over the
   window, Inconclusive under 12 months) are engineering and decided here.
4. **Run-rate label** (item 2, a changed VaS line): "{amount} (run-rate: Q4 2023 × 4)" on a stand-alone part. Confirm the word.
5. **A dropped card** (item 5 rule 3): a claim on a cell with no figure and a value on no cell is dropped with a Diagnostics line, not a Review
   card. Options: (a) drop (recommended: the model read a marker's height); (b) keep the card.
6. **The five's columns** (item 7, George's ask): Plan figure · Period · Implied assumption · Observed rate · Result, no `#`, the one sentence
   when all five are forecasts. Confirm the header words and the sentence.
7. **Yearly CAC payback** (item 6): new ARR from the revenue file's year-end ARR when both ends exist, else new revenue, the rule text naming
   which; the monthly-P&L request is not written while the yearly figure exists. Confirm "new ARR" over "new revenue" as the first choice.
8. **Appendix A** (items 1 and 7): slices indented under their headline; the five's implied and observed rates in Verdict detail. Confirm.
