# Spec: Revenue file recognition, separate from classification
Status: **Draft for review (2026-10-19). Spec and failing tests only; no implementation.** Source: George's request of 19 Oct 2026. Location:
docs/specs/revenue-file-recognition.md. Extends docs/specs/chat-upload.md §3, §4.2, §16, §19 and §26 and amends its S2 (§11). The numbers of the
screen lines continue chat-upload.md: S31a–S31k. The owner's decisions of 2026-10-19 are in §14.

**Architecture (CLAUDE.md rule 1).** The model reading row labels widens the data boundary. George approved it on 2026-10-19 (decision 2, §14) and
asked for it as a dated amendment, like the amendment of 2026-10-18. This PR records it in docs/architecture.md ("The amendment of 2026-10-19")
and in CLAUDE.md rule 16, as that amendment did, and changes no code. Wording: §5.9.

## 0. Challenge and deletions (CLAUDE.md rule 4)
- Needed: real company files are one worksheet with line labels down column A and months across the top, with no customer ID. The rules of §3
  of chat-upload.md demand customer, date and amount, so such a file ends in the miss message or in S6. Simpler: three yes/no essentials, a closed
  list of six types, and Python deciding; the model only proposes a row and a boundary that Python then checks.
- Deleted first: the demand for a customer ID as a condition of being a revenue file; the "first sheet only" reading for this decision (every sheet
  is classified); a confidence number from the model (never asked for, S31 never shows one); a second model call (the one call per new file of §5.5
  also answers the file-type question of chat-upload.md §19, §5.6).

## 1. Definition
A revenue file holds historical information about sales, invoicing or recognised revenue, organised by transaction, customer, product or period.
Dates may sit in rows or in column headings. **Missing information narrows the analyses; it does not reject the file.** A file is rejected only
when an essential of §2 is missing, and the message names it.

## 2. Recognition: three essentials, all required
Python decides recognition, per sheet (`app/recognition.py`, pure, no I/O). The model never decides it.

| | Essential | Met by |
|---|---|---|
| A | A revenue measure: at least one identifiable monetary revenue measure | recognised revenue, revenue, net sales, sales, turnover, invoiced revenue, recurring revenue, MRR, ARR (the revenue vocabulary of §4.1), in a row label, a column header, the label column's header or a title row |
| B | A reporting reference: a date, period, transaction ID or other basis saying what the amount represents | a period header (month, quarter, half, year, year to date; the readings of chat-upload.md §19 and §26.2), a date or year in a title row, or a date column or an invoice, transaction, order, receipt or reference column |
| C | Numeric values: at least one usable number tied to the measure | a number in the measure's row (labels down the rows), in the amount column (one row per record) or in the measure's column (a snapshot) |

- **Where each is read, by layout.** The reading order is fixed: *labels* first, then *snapshot*, then *records*.
  - *labels*: labels down a column, at least one period header across (read by `structures/sheet.read`, chat-upload.md §26.2). A: on a
    metric-labelled sheet (§4) a candidate row (§2.1); on an entity-labelled or unsure sheet a revenue word in the title rows or in the label
    column's header ("Revenue by customer (EUR)"). B: the period headers. C: a number in a candidate row; on an entity-labelled sheet a number
    anywhere in the table.
  - *snapshot*: a label column and a column whose header is a revenue measure, no period header, no date column. B: a date or a year in a title row
    ("as at 30 June 2025"). C: a number under the measure.
  - *records*: one row per record. A: a numeric column headed with an amount word (amount, net, gross, total, value, price, revenue, sales, invoiced,
    billing), with no CRM word in the header (deal, opportunity, pipeline, quote, forecast, stage), on a sheet the rules do not type as CRM (§3 of
    chat-upload.md, share below 80). B: a date column (a header scoring 80 or more for invoice date) or an invoice, transaction, order, receipt or
    reference column. C: a number in the amount column.
- **Result.** `recognised` is true when A, B and C are all met. `missing` lists the unmet ones, in the order `revenue_measure`, `reference`,
  `numbers`. `message` (S31f) is built from closed words only: "Not a revenue file. Missing: {names}." with the names `a revenue measure
  (recognised revenue, invoiced revenue, sales, turnover, recurring revenue, MRR or ARR)` · `a date, period or transaction ID` · `a number for
  the revenue measure`, joined by "; ". No cell text, no sheet name.
- **Currency.** Detected where present: a three-letter code (EUR, USD, GBP, CHF, SEK, NOK, DKK, PLN) or a currency symbol in a title row, a header, a
  row label or a currency column, when exactly one currency is named. Result `{code, state}`: `seen` with the code, or `confirm` with no code when the
  file names none or several. A missing currency never rejects the file: the analyst confirms it (S31k), which counts as a click. The model's currency
  is a cross-check only: it is accepted when Python finds the same code in the cells, and dropped otherwise (rule 18).
- **Turnover.** A row or header whose revenue word is turnover follows chat-upload.md §15: the row waits for the one answer "Is this money the company
  earned (revenue) or the value of transactions processed (volume)?" (`money_kind`, reason `turnover_question`). Revenue: the row is used. Volume: the
  row is not revenue; the file is recognised again without it, and is rejected on A if nothing else qualifies.

### 2.1 Actuals against everything else
A row (or a sheet column header) is *recognised but never used as revenue* when its label holds a word of one of six kinds (`NON_REVENUE_KINDS`), checked before any revenue
word and so winning over it ("Forecast revenue" is a forecast, "Sales pipeline" a pipeline). First match in this order:

| Kind | Words (whole words, any case, punctuation as one space, a bracket's content left out) |
|---|---|
| `forecast` | forecast, forecasts, fcst, projected, projection, estimate, estimates, outlook |
| `budget` | budget, budgeted, target |
| `bookings` | booking, bookings, booked |
| `pipeline` | pipeline, backlog, opportunity, opportunities |
| `contract_value` | contract value, contracted revenue, total contract value, annual contract value, TCV, ACV |
| `run_rate` | run rate, run-rate, annualised, annualized |

"Plan" is not on the list: a pricing plan ("MRR - Pro plan") is an actual row (chat-upload.md §26.15). A recognised row of these kinds is listed in
`non_revenue_rows` `[{row, label, kind}]` and is never a revenue candidate. The model may add rows and kinds (§5.7); the union is used, and a row
either side marks is out. Such rows are kept for claim matching: they enter the claim register through the existing path (Save claims,
chat-upload.md §20.4 and §26.15), as Unverified; this spec adds no claim code.

**Revenue candidates** (labels layout): a row that is not marked, whose label (bracket content left out) holds a revenue word and none of: new, net
new, lost, churn, churned, added, expansion, contraction, growth, per, average, avg, share, ratio, rate, margin, cost, costs, cogs, expense, expenses,
marketing, payroll, commission, or a "%" ("Sales and marketing", "New ARR - inbound", "Revenue per customer" are not candidates). Its kind:
`recurring` (MRR, ARR, recurring revenue), else `invoiced` (invoiced, invoicing, billing, billed), else `recognised` (revenue, revenues, sales,
turnover, net sales). Rank: recognised 0, invoiced 1, recurring 2. Candidates are ordered by rank, then confidence (§6.1), then sheet order.

## 3. Classification: six types, per sheet
Classification runs on a recognised sheet and is independent of recognition. The table is the agreed one; the last two columns are fixed lists. The codes are `RECOGNITION_TYPES`.

| Type (code) | Structure | Customer-level analysis | Trend analysis |
|---|---|---|---|
| Invoice transactions (`invoice_transactions`) | one row per invoice | yes, with a customer column | yes |
| Customer revenue (`customer_revenue`) | customers × periods | yes | yes |
| Monthly revenue report (`monthly_revenue_report`) | metrics × months | no | yes |
| Revenue summary (`revenue_summary`) | categories × periods | no | yes |
| Financial statements (`financial_statements`) | P&L with revenue lines | no | yes if 2+ periods |
| ARR/MRR snapshot (`arr_mrr_snapshot`) | one period, no series | no | no (claim matching only) |

**Customer-level analysis** means NRR, gross churn, concentration and cohorts. **Trend analysis** means MRR/ARR, growth and run-rate.

- **The rules** (first that applies):
  1. *records* layout: `invoice_transactions`. Customer-level needs a customer column (a header scoring 80 or more for customer ID); without one it is
     blocked with the data in §3.2 and the file is still recognised.
  2. *snapshot* layout: `arr_mrr_snapshot` when the measure is recurring (ARR, MRR); another measure is a `revenue_summary` of one period.
  3. *labels* layout, metric-labelled (§4): `financial_statements` when the labels hold at least two of the cost and profit line groups of the type
     rules (chat-upload.md §3: cost of sales, payroll, EBITDA, operating profit, gross profit/margin, sales and marketing, G&A, R&D, depreciation, net
     income), else `monthly_revenue_report`.
  4. *labels* layout, entity-labelled or unsure: the header cell of the label column decides. A customer word (customer, client, account, company,
     subscriber, logo, buyer) gives `customer_revenue`; a category word (product, service, region, country, segment, channel, category, business unit,
     division, geography, tier, line) gives `revenue_summary`; neither gives no type: `file_type` is null, `type_state` is `click`, and the candidates
     are `customer_revenue` and `revenue_summary` (S31a asks).
- **Periods.** Trend needs 2 or more period columns for every type but `invoice_transactions` (records are dated rows) and the snapshot (never).
  A period is a column of any grain (month, quarter, half, year); the sheet's `periods` counts them. Quarter, half and year columns are never split into
  months (chat-upload.md §26.6).
- **Best sheet.** Every sheet of a workbook is classified. Among the recognised ones the best is, in order: the one supporting more analyses; the one
  whose revenue row has the better rank (§2.1; a sheet with no revenue row ranks 0); the one with more period columns; the earlier sheet. The result is
  the best sheet's, plus `other_sheets` `[{sheet, file_type, recognised: true}]` for the other recognised sheets (S31g offers them, and the analyst's
  choice is final). When no sheet is recognised, the result is the sheet with the fewest unmet essentials (the earlier on a tie), with its `missing`.

### 3.1 Blocked analyses name the data
`supports` is a list of `customer_level`, `trend`, `claim_matching`. `blocked` is `[{analysis, needs}]` with the closed texts:
| Blocked | `needs` (constant in `app/recognition.py`) |
|---|---|
| `customer_level`, any type but invoices without a customer column | `NEEDS_BY_CUSTOMER` = "revenue by customer and month (one row per customer, or one row per invoice with a customer column)" |
| `customer_level`, invoices with no customer column | `NEEDS_CUSTOMER_COLUMN` = "a customer column (name or ID) on each invoice row" |
| `trend`, one period (financial statements, summary, report) | `NEEDS_PERIODS` = "the same figures for at least one more period (a prior year, or one column per month)" |
| `trend`, the snapshot | `NEEDS_SNAPSHOT_SERIES` = "ARR or MRR for at least two periods (one column per month)" |
| `monthly_series`, a labels sheet none of whose period columns is a month (yearly, half-year or quarterly columns only) | `NEEDS_MONTHLY` = "one column per month" |
Yearly, half-year and quarterly columns support trend when there are two or more (decision of 2026-10-19), and the blocked list still says the monthly
series is missing: `{analysis: "monthly_series", needs: NEEDS_MONTHLY}`, named "Monthly series missing" on screen and in the data inventory. It
follows `customer_level` and `trend` in the list. A snapshot and a records layout never carry it.
The snapshot supports `["claim_matching"]` only; every other type supports what its row of the table says.

### 3.2 The data inventory (V6)
Each `blocked` entry is written to the engine's `missing_data` as one line, "{analysis name} – Missing: {needs}", by `missing_lines(result)`, with the
analysis names "Customer-level analysis (NRR, gross churn, concentration, cohorts)", "Trend analysis (MRR/ARR, growth, run-rate)" and "Monthly series missing". Never "Missing"
without the data. The existing metrics (NRR, gross churn, ARR) keep their own Missing lines of the engine; the lines here add the reason this file
cannot supply them.

## 4. Row labels or entity labels: the key step
Customer revenue and Monthly revenue report look the same (labels × periods). Rules decide first.

### 4.1 The metric vocabulary
Whole words, any case, punctuation as one space, a bracket's content left out: revenue, revenues, sales, turnover, MRR, ARR, ARPA, ACV, TCV,
customer(s), client(s), subscriber(s), subscription(s), logo(s), churn, churned, retention, NRR, GRR, booking(s), booked, forecast, fcst, budget,
pipeline, backlog, contract, contracted, run rate, annualised, annualized, cost(s), COGS, expense(s), opex, margin, profit, EBITDA, cash, headcount,
FTE, payroll, salaries, growth, income, invoiced, billing(s), rent. (Revenue vocabulary of §2.1 ⊂ this list.)

### 4.2 The decision
- A **label row** is a row with a text label in the label column (chat-upload.md §26.2) and at least one non-blank value cell under the period
  columns. Notes and blank lines are not label rows.
- `share` = label rows whose label matches the vocabulary ÷ label rows. `hits` = the matching rows.
- **Metric-labelled** (`label_mode: "metric"`) when `share` is above `METRIC_LABEL_SHARE = 0.5` and `hits` is at least 3 and the label column's header
  holds no customer word (§3 rule 4). **Entity-labelled** (`entity`) when `share` is at most `ENTITY_LABEL_SHARE = 0.2`. Otherwise **unsure**
  (`unsure`). Unsure is treated as entity for what the model sees (§5.3) and leaves the type to the header words or a click (§3 rule 4).
- A label column headed with a customer word is never metric-labelled, even when every name matches ("Revenue Partners", "Cash Converters"): the
  worst error here is a customer name reaching the model, so a guard sits beside the threshold.
- **Confidence per sheet** (`confidence`, an integer 0–100, recorded with `label_mode` and `label_share`): metric = round(100 × share); entity =
  round(100 × (1 − share)); unsure = 0.
- **Why these numbers.** Measured on 17 label sheets in the repository's synthetic fixtures (`tests/fixtures/recognition/`, `mapping/`, `forecast/`):
  the 12 metric sheets (P&L, KPI, forecast, bookings tables) score 0.69 to 1.00 and the 5 entity sheets (customer lists, product categories, names)
  0.00 to 0.14. 0.5 is below the lowest metric sheet with a margin and far above the highest entity sheet; 0.2 is above the highest entity sheet and
  well below the lowest metric one; the band between is "unsure", which masks. At least 3 hits stops two coincidental names ("Cash Corp", "Sales
  Ltd") from making a sheet metric. A test (`test_the_label_share_threshold_separates...`) pins the constants and the fixtures. The cost of a false
  metric is a leaked name; the cost of a false entity is a masked label and a click, so the thresholds lean to masking.

## 5. What the model may see
### 5.1 Always
Sheet names, the title rows above the header (at most 6 rows), the column headers (at most 40 columns) and the existing masked sample of chat-upload.md
§4.2 and §19: for a records layout up to 3 numbers or dates per numeric or date column and a profile (distinct count, typical length, shape) per text
column, from the first 20 rows; for a labels layout, per period column the first 3 numbers from top to bottom below the header, as written, and no
other figure. A sheet name, title or header is redacted as in §19: the target company's name becomes [redacted], emails and phone numbers are masked,
customers of the per-audit pseudonym map take their pseudonyms. At most 6 sheets and a cell over 200 characters is cut.

### 5.2 The text (extends the file-type text of chat-upload.md §19)
One line per fact, built in memory, never stored, never logged:
```
s1: <sheet name>
s1 title r1c1: <text>
s1 header r3c2: <text>
s1 labels: metric                      (or: s1 labels: masked)
s1 label r4: <row label>               (metric)      s1 label r4: Row 1     (masked)
s1 c2 sample: <number>                 (at most 3 per column)
s1 c1 profile: distinct 12, typical length 14, shape Aa Aa
```
`model_text(sheets, company_name, mapping, withheld)` in `app/recognition.py` builds it from the sheets as Python read them.

### 5.3 Row labels
- **Metric-labelled** sheet (§4.2): its row labels are sent as written, after the redaction above.
- **Entity-labelled or unsure** sheet: row labels are sent masked, "Row 1", "Row 2" ... in sheet order, numbering label rows; no label text of any kind
  reaches the model. **No customer name ever reaches the model.** "Masked values" is read strictly: no value is tied to a row; the only figures are
  the per-column samples of §5.1 (decision 5, §14).
- At most 400 rows with text per sheet, title rows and header row included (as chat-upload.md §26.11): the first 400 are read, by Python and by the
  model.
- A records layout has no row labels: its rows are data, never sent beyond the sample.

### 5.4 The gateway checks the text again
`structure_text_problem(text, "file_recognition", context, mapping)` refuses, with a closed problem code: a line of no kind (`not_cells`); more than 6
sheets or 6 title rows or 40 columns (the codes of §19); a sample that is not a number or a date, or more than 3 per column; a label line on a
`masked` sheet that is not "Row n" (`label_on_masked_sheet`); a label that is a figure (`figure_in_label`); more than 400 rows (`too_many_rows`); a
file name (`file_name`); a cell over 200 characters (`cell_too_long`); a text the redaction would change (`redaction_changed`). The gateway cannot
know whether Python's label mode is right; the label mode and the thresholds of §4 are tested in Python.

### 5.5 The call
- **When.** With the audit's consent, for a file whose bytes have no stored answer, after Python has recognised it (§2) or when the rules find no type
  at 80 (§5.6). One call per new file. A file recognised by the rules and refused by the gateway, a timeout, a failure, no prompt in the store, no
  consent, the daily cap or the tester's allowance (monthly_allowance_reached) leave the rules' outcome standing (§6.5), and the file is still
  recognised.
- **Counts.** A recognition call counts toward the tester's allowance like any call (usage-and-allowance.md §4; no exemption), stays under the daily
  spend cap like the §19 file-type call, and is counted in `audits.usage` as step `recognition` by status. Budget `MAPPING_AI_SECONDS` (20 s); text
  cap `RECOGNITION_INPUT_CAP = 12,000` tokens; reply cap 1,000 tokens.
- **Cache.** Keyed by the file's sha256, kept in `column_mappings` as `{audit_id, kind: "file_recognition", file_hash, reply, saved_at}`. The same
  bytes again (a replace, a re-upload after a delete of the dataset, a second tester action) make no call. `reply` holds the reply without the label
  echo (§5.7).
- **Storage and logs (rule 17).** `llm_structures` and `llm_calls` keep the reply (rows, columns and closed words), its content hash, prompt version,
  model version, tokens and cost, with `structure_type: "file_recognition"`. Never the text sent, a sheet name, a title, a header or a label. The log
  line holds codes only: `recognition: type=<code> source=<rules|ai|you|stored> status=<code>`. Delete audit removes the kept answers with the other
  documents of the audit (rule 22).

### 5.6 One call replaces the file-type call of §19
The prompt is `file_type`, **version 2**, uploaded by the owner on the owner page (rule 26). It replaces the closed-word reply of §19 with the reply
of §5.7, whose `file_type` also holds `crm` and `pnl`. When the rules give no type at 80 (chat-upload.md §3) the same call runs, and its answer is used
like the §19 answer: `crm` and `pnl` as the file's type; one of the six types only if Python recognises the file (§2); `not_revenue` leaves the type
to the analyst (S6, or S31f when Python names what is missing). A cached v1 answer is never served (the prompt tag is in the key).

### 5.7 The reply (`FileRecognitionReply`, `llm/schemas.py`)
JSON only, `extra="forbid"`, no free text, **no confidence number**:
```
{"type": "file_recognition",
 "sheet": 1,                                     // the s<k> of the text: 1 to 6
 "file_type": "invoice_transactions" | "customer_revenue" | "monthly_revenue_report" | "revenue_summary" | "financial_statements"
              | "arr_mrr_snapshot" | "crm" | "pnl" | "not_revenue",
 "revenue_row": {"row": 4, "label": "Recognised revenue (EUR)"} | null,   // sheet row number and the label as sent
 "last_actual_column": 7 | null,                 // sheet column number (A = 1)
 "currency": "EUR" | null,                       // an ISO code, only if seen in the text
 "non_revenue_rows": [{"row": 9, "kind": "forecast" | "budget" | "bookings" | "pipeline" | "contract_value" | "run_rate"}]}
```
A reply with another key, a `confidence`, a kind or type outside the lists, a row or column below 1, a currency that is not three letters, or a
`revenue_row` without its label fails to parse (`parse_failed`, check `schema` or `metric_list`). The label echo is compared by Python with the label
of that row and then dropped: it is never kept (§5.5). On an entity-labelled or unsure sheet the labels the model saw are "Row n", so its
`revenue_row` is ignored there (customer revenue and summaries have no single revenue row; §6.2).

### 5.8 Wording of the consent explainer (S31h)
S2 of chat-upload.md §11 gains one sentence (applied to chat-upload.md in this PR as a spec edit, to `chatUpload.js` in the implementation PR):
"In a revenue file the AI also sees the row labels when they are metric names such as revenue, ARR or customers; where the rows may be customers it
sees Row 1, Row 2 instead, never a name." It follows the existing two sentences; nothing else of S2 changes.

### 5.9 Amendment of the boundary (approved 2026-10-19, decision 2)
Same form as the amendment of 2026-10-18: "For the `file_recognition` step only, the model may also receive the row labels of a sheet whose labels the
rules read as metric names (revenue, ARR, MRR, customers, churn, bookings, forecast, budget, cost, margin, cash and their common variants), after
redaction; for every other sheet the labels are sent as 'Row 1', 'Row 2' with no value tied to a row. Never a figure beyond the per-column sample of
rule 16; at most 400 rows with text per sheet." Placed in CLAUDE.md rule 16 and docs/architecture.md ("Data boundary" and "The amendment of 2026-10-19") by this PR, on George's instruction.

## 6. Python checks every proposal before anything is used
Python builds its own reading first (rules), then compares it with the proposal of §5.7. Everything runs in Python; the deck parser and the gateway
take no part in the checks. The reason codes below are the closed list `REASONS` (14 words); a result carries no other string from a file (rule 14).

### 6.1 The revenue row (types `monthly_revenue_report` and `financial_statements`)
- **Rules' reading.** The first candidate of §2.1, with `confidence` = label score × value fit: the label score is 100 when the label, bracket content
  and a leading "total" left out, is exactly a revenue synonym (revenue, revenues, net revenue, recognised revenue, net sales, sales, turnover, invoiced
  revenue, invoiced, recurring revenue, MRR, ARR, monthly or annual recurring revenue, subscription revenue) and 80 when the revenue word stands among
  other words ("Revenue - EMEA"); the value fit is the share of period columns with a number in the row; confidence is rounded to an integer. A tie of
  two candidates with the same rank and confidence is a tie.
- **States.** `auto` (no click), `click` (the analyst decides), `you` (decided). No proposal and no model: `auto` when the confidence is above 80
  (`MAPPING_THRESHOLD`, chat-upload.md §4.1, §21) and untied; a confidence of exactly 80 is `click` (`confidence_80`), a tie is `click` (`tie`), no
  candidate is `click` (`no_candidate`), turnover is `click` (`turnover_question`).
- **The model's proposed row** is checked in this order; the first failure is the reason and the state is `click`:
  `row_missing` (no such label row) · `marked_not_revenue` (the row is forecast, budget, bookings, pipeline, contract value or run-rate, by the rules or
  by the model) · `label_mismatch` (the label echoed is not that row's label) · `not_numeric_enough` (a number in fewer than `min(3, periods)` period
  columns) · `no_revenue_word` (the label holds no revenue word, §2.1) · `rules_and_model_disagree` (the row is not the rules' first candidate). A row
  that passes and is the rules' row is accepted at the thresholds above: 81 or more `auto`, exactly 80 `click`.
- **Three columns, or fewer when the sheet has fewer.** The row must be numeric in at least 3 columns; a sheet with fewer than 3 period columns needs
  the row numeric in each of them, so a two-year P&L and a one-period P&L (Financial statements, "trend yes if 2+ periods") are not unsure for being
  short. Decided under rule 19 (§12).
- `revenue_row` = `{row, label, kind, confidence, state, reason, candidates}`. `row` is the row Python would use when the analyst confirms (the rules'
  first candidate, or null with no candidate); `state: "click"` means no row is used until the analyst decides. `candidates` is the list the analyst
  chooses from: the unmarked candidates (`{row, label, kind, confidence}`). A model-marked row is removed from it.
- **A recurring row (decision of 2026-10-19).** A row of kind `recurring` (MRR, ARR, recurring revenue) may be the revenue row and the trend series. It
  is never shown or named as recognised revenue: S31c calls it a recurring row, its citation says it is read from an MRR or ARR line, and any growth
  computed from it is labelled by the row: "MRR growth" for an MRR row, "ARR growth" for an ARR row, "Recurring revenue growth" for a recurring
  revenue row, never "revenue growth". `growth_label(result)` returns the label ("Revenue growth" only for kinds `recognised` and `invoiced` and for
  the sum of customer or category rows).
- Types with no revenue row (`invoice_transactions`, `customer_revenue`, `revenue_summary`, `arr_mrr_snapshot`) have `revenue_row: null` and
  `series_basis` `records`, `sum_of_rows` (the customer or category rows are summed), `sum_of_rows` and `snapshot`. For the other two it is `row`.

### 6.2 The last actual column and the boundary
- **Rules' reading.** The last column tagged actual (chat-upload.md §26.2: a tag over the columns, "Actual" over "Forecast"); with no tag, the last
  period column that has a number in the revenue row (a sheet with no revenue row: the last period column). The audit's **as-of month** is the stored
  `as_of_month` (an explicit date, or none: "defaulted" is none).
- **Checks, in this order; the first failure is the reason and the state is `click`:**
  1. `not_a_period` — the proposed column is not a period column of the sheet.
  2. `no_as_of_month` — the audit has no as-of month: **the boundary needs a click**, even when rules and model agree.
  3. `after_as_of` — the column's period ends after the as-of month: **rejected, needs a click**. The candidates are the period columns up to the
     as-of month.
  4. `rules_and_model_disagree` — the proposed column is not the rules' column.
  Otherwise `auto`. A boundary earlier than the as-of month is accepted: the engine reads to the last actual, as for a file that ends early.
- `last_actual` = `{column, month, state, reason, candidates}` with `candidates` `[{column, month}]`. `month` is the period's end month, YYYY-MM.
  Only the labels layout has period columns: a records or snapshot layout has `last_actual: null` and `excluded_columns: []` (the engine's as-of
  rule cuts invoice dates as it does for every revenue file).
- **Columns after the boundary are excluded** from Run audit (`excluded_columns`), the same treatment as the forecast tables of PR #116 (chat-upload.md
  §20, §26.6). A file whose boundary waits for a click gives Run audit no column until the click (stage File mapping not done, as for a pending
  mapping). A later change of the as-of month re-checks a decided boundary on read: one now after the as-of month is `click` again.

### 6.3 The type
`file_type` is the rules' (§3). The model's `file_type` agrees, differs, or is `crm`/`pnl`/`not_revenue`: it never overrides a recognised type. When
the rules have a type and the model another of the six, the state is `click` (`rules_and_model_disagree`) with both as candidates; when the rules
have none (§3 rule 4) the model's choice among the candidates is shown as the AI suggestion and still waits for a click (`type_unsure`).

### 6.4 The workbook
The model's `sheet` is used only when it is the sheet Python chose as best (§3). A proposal for another sheet is dropped (the file is read by rules,
`type_source: "rules"`); the analyst can switch sheet (S31g), after which the sheet is read again.

### 6.5 The model is silent or wrong
If the model cannot be read, the rules' outcome stands, with the same thresholds (81+ `auto`, 80 and ties `click`), as for the column mapping
(chat-upload.md §4.2). Rules and model agreeing is **auto-accepted with a Correct button**; disagreeing or unsure shows the candidates.

### 6.6 The analyst
`POST /api/audits/{id}/datasets/revenue/recognition` with one part at a time:
| Body | Effect |
|---|---|
| `{action: "confirm", part: "revenue_row" \| "last_actual" \| "file_type" \| "currency"}` | Correct: the proposal becomes `you` (the part must have a proposal) |
| `{action: "change", part: "revenue_row", row}` | one of the `candidates`; else 400 |
| `{action: "change", part: "last_actual", column}` | one of the period columns up to the as-of month; else 400 |
| `{action: "change", part: "file_type", file_type}` | one of the six types; else 400 |
| `{action: "change", part: "currency", currency}` | an ISO code (`ISO_CURRENCIES`); else 400 |
| `{action: "change", part: "money_kind", money_kind}` | `revenue` or `volume` (chat-upload.md §15); else 400 |
| `{action: "change", part: "sheet", sheet}` | a recognised sheet of the workbook; else 400 |
The server re-checks every choice (a row must be a candidate, a column a period up to the as-of month) and answers with the dataset view. Decisions
are saved with the dataset (`recognition_decisions`) and survive a reload; a replaced file clears them. Typed text is never accepted.

## 7. What the analyst sees
On Upload & Mapping, under the file's bubble head (above the mapping table where there is one), `frontend/src/components/RecognitionLine.jsx` renders
the `recognition` block. The wording never mentions the model's confidence or a cost, and no number but the row and column positions the analyst needs
to find the cell. (Wording chosen under rule 19, as chat-upload.md §13 did; George reviews it in this PR.)

| Id | Where | Text |
|---|---|---|
| S31a | the type line | Type: {Invoice transactions / Customer revenue / Monthly revenue report / Revenue summary / Financial statements / ARR/MRR snapshot} ({by rules / AI suggestion / your choice}) and a **Change** button that offers the other five types. An unclassed type reads "Type: choose the type" with a drop-down of the two candidates |
| S31b | what it supports and blocks, one line | (a `monthly_series` item reads "monthly series missing, needs one column per month") Supports: {trend analysis (MRR/ARR, growth, run-rate) / customer-level analysis (NRR, gross churn, concentration, cohorts) and trend analysis (…) / claim matching only}. Blocked: {analysis}, needs {data}; {analysis}, needs {data}. — the "Blocked" part is left out when nothing is blocked; the data is the closed `needs` text of §3.1 |
| S31c | the revenue row | Revenue row: {label} (row {n}) — for kind `recurring` "Recurring row: {label} (row {n})" — with **Correct** and **Change** (Change opens the candidates: "{label} (row {n})"). Needs a click: "Revenue row: choose the row. {reason}" with the drop-down and no Correct. Decided: Change only. Not shown for a type with no revenue row |
| S31d | the last actual month | Last actual month: {Mon YYYY}. Columns after it are not used. with **Correct** and **Change** (the candidate months). Needs a click: "Last actual month: choose the month. {reason}" with the drop-down and no Correct. Decided: Change only. The second sentence is left out when no column follows |
| S31e | the reasons, closed texts (`REASON_TEXT` in `lib/recognition.js`, one per code of §6) | no_candidate: No row looks like revenue. Choose the revenue row. · tie: Two rows fit equally. Choose the revenue row. · confidence_80: Please confirm the revenue row. · row_missing, label_mismatch: The proposed row could not be matched to the sheet. Choose the revenue row. · marked_not_revenue: The proposed row is a forecast, budget, bookings, pipeline, contract value or run-rate row. Choose the revenue row. · not_numeric_enough: The proposed row has too few numbers. Choose the revenue row. · no_revenue_word: The proposed row has no revenue word in its label. Choose the revenue row. · rules_and_model_disagree: Two readings differ. Choose the revenue row. (for the month: … Choose the last actual month.) · no_as_of_month: The audit has no as-of month, so this month needs your confirmation. · after_as_of: The proposed month is after the as-of month. Choose a month up to it. · not_a_period: The proposed column is not a month. Choose the last actual month. · turnover_question: the question of chat-upload.md §15 with the buttons Revenue / Volume · type_unsure: Choose the type. |
| S31f | not a revenue file | the server's message of §2: "Not a revenue file. Missing: {names}." It replaces S6 and every other line of the recognition |
| S31g | other sheets | Other sheets in this file: {sheet} ({type}) **Use this sheet**, one per recognised sheet. Left out when there is none |
| S31h | the consent explainer | The sentence of §5.8 added to S2 |
| S31i | rows kept out of revenue | {n} rows ({kinds}) are not used as revenue and are kept as claims for matching. — "1 row ({kind}) is not used as revenue and is kept as a claim for matching." for one. The kinds are the closed words, in sheet order, without repeats. Left out when none |
| S31j | the S13 status line of a file with a click open | {n} choices wait for you · Ready – press Run audit (S13 of chat-upload.md; the count is the parts in `click`: type, revenue row, last actual month, currency, money kind) |
| S31k | currency | Currency: {code}. Or, with none found: Currency not found in the file. Confirm the currency: {drop-down of ISO codes, the audit's reporting currency first} |

The banner is unchanged (rule 21): a revenue file with an open click counts as "uploaded, mapping not confirmed" (S16d); a recognised file with
nothing open clears it. No banner kind is added.

## 8. API, storage and routing
- **Upload.** `POST /api/audits/{id}/datasets/upload` runs recognition (§2, §3) on every sheet of every file that the rules do not type as CRM. The
  view of a dataset gains `recognition`: `{recognised, missing, message, sheet, header_row, file_type, type_state, type_source, type_candidates,
  label_mode, label_share, confidence, series_basis, periods, revenue_row, last_actual, excluded_columns, currency, money_kind, non_revenue_rows,
  supports, blocked, other_sheets, needs_click}`. `type_source` is `rules` (Python decided, with the model silent or agreeing), `ai` (the type is the
  model's choice among candidates), or `you`. `money_kind` is `{asked, answer?}`. A file that is not recognised and gets no type answers
  `{status: "unknown_type", recognition: {recognised: false, missing, message}}` and stores nothing.
- **Routing (decided, §14 item 3).** A recognised file is stored as the audit's revenue file (`dtype: "revenue"`) with its
  recognition. Types with customer rows (`invoice_transactions`, `customer_revenue`) keep the column mapping of chat-upload.md §4 beside the
  recognition line; the other four types have no column mapping, hold no required field (as a statement file, chat-upload.md §26.6) and wait only for
  the clicks of §7. A P&L the rules type by its columns, or a statement-shaped P&L (financial statements) that the P&L path of §26 reads, stays the
  audit's P&L (CAC payback needs it) and also carries its `recognition` block; it satisfies the required revenue file once its recognition is confirmed with two or more periods (decision 3, §14). Banner kinds are unchanged (rule 21).
- **When the P&L is the only revenue source** (no separate revenue file; the recognised revenue comes from the P&L), the revenue-versus-P&L
  reconciliation compares a source with itself. `revenue_reconciliation` then carries `status: "not_applicable"` and the text "Not applicable – same
  source", Diagnostics shows that text instead of the table (S22), and the integrity check "Revenue reconciliation" (integrity-coverage.md) is
  **Not applicable**, not Completed: never Green, not in Block A, not counted in "Completed x of y applicable checks", and it cannot supply the
  reconciliation the conclusion needs. It is not a blocker (rule 21 holds).
- **Run audit.** Reads, for the four types without a customer mapping, the confirmed revenue row (or the sum of rows, or the snapshot value) in the
  period columns up to the boundary, as a revenue series with its cells as the citation. Excluded columns are never read. Trend analyses
  (MRR/ARR, growth, run-rate) read the series; customer-level analyses report the Missing line of §3.2.
- **Usage.** `audits.usage.steps.recognition` counts calls by status (no names, no figures).

## 9. Contract fields the implementation PR will need
This PR changes no schema (CLAUDE.md rule 23; docs/specs/interface-contracts.md). The implementation PR changes `backend/schemas/metrics.py` and
`backend/tests/test_interface_contracts.py` in the same commit, and raises `contract_version`. Expected, server-only unless stated:
- `revenue_series`: a `basis` (`customer_rows` · `revenue_row` · `sum_of_rows` · `snapshot`), the `file_type` code, and a citation naming the row or the
  rows and the columns up to the boundary (file, sheet, rows, rule), as every cited block.
- `missing_data`: entries with the lines of §3.2 (`metric`, `status: "Missing"`, `reason`, `unlocked_by` = the `needs` text, `file`); no new key.
- `recognition` (a summary on the audit's results, closed words and counts only: type code, `series_basis`, the periods used, the count of excluded
  columns, `currency_confirmed`) so the memo and the export can state the basis. Not in any narrative slice; the boundary test is extended (rule 14).
- `revenue_reconciliation`: a `status` (`computed` · `not_applicable`) and, for `not_applicable`, the reason "Not applicable – same source"; `available`
  stays false then, and `integrity.assess` reads the status (decision of 2026-10-19).
- A growth label on any growth figure computed from a recurring row ("MRR growth", "ARR growth"; `growth_label`).
- `mrr_series` and `arr` from a `recurring` revenue row: their `source` says the figure is read from a row labelled MRR or ARR, not computed from
  customers (decision 1).
Labels and titles are never a contract field.

## 10. Tests (written first; all fail today for the reason in the last column)
| Area | Test file | Fails today because |
|---|---|---|
| The fifteen cases of the request, recognition and classification, the checks of §6, determinism | `backend/tests/test_revenue_recognition.py` (pure, on `backend/tests/fixtures/recognition/*.csv` and workbooks built in the test) | `app/recognition.py` does not exist (ModuleNotFoundError) |
| Upload, one call per file, cache by hash, nothing stored or logged, consent, failure, allowance, Correct / Change, delete audit | `backend/tests/test_revenue_recognition.py` (API, `api` fixture, fake adapter) | no `recognition` in the view, no endpoint (404) |
| The model's text: no row label on an entity sheet, labels on a metric sheet, nothing beyond the sample rule, redaction, 400-row cap, the gateway's refusals, the closed reply, the closed lists of types, kinds and reasons | `backend/tests/test_gateway_data_boundary.py` (rule 14) | `app/recognition.py` does not exist; no `file_recognition` structure type |
| The type line, supports/blocks line, Correct / Change, reasons, other sheets, S2 | `frontend/src/components/RecognitionLine.test.jsx` (`yarn test --no-cache`, rule 25) | `RecognitionLine` and `lib/recognition` do not exist |
Fixtures (synthetic, invented names, every figure unique so a leaked value can be told from another; rule 15): `monthly_report_actual_forecast`
(metrics × months, actual and forecast columns, forecast/bookings/pipeline rows), `customer_revenue_months` (12 customers, one named with a metric
word), `invoice_transactions`, `revenue_summary_by_product`, `pnl_multi_period`, `pnl_single_period`, `arr_snapshot`, `bookings_pipeline_only` (a
"Sales pipeline" title and a "Forecast revenue" row: no revenue measure), `monthly_report_no_currency`, `unclassed_names_by_quarter`.
Measured outcome of the rules on the fixtures is in the tests. Each new boundary test was shown failing on a deliberate violation (labels sent for
every sheet; a fourth sample; the customer-header guard removed) against a throwaway reference implementation, which is not committed.

## 11. Prompt (rule 26)
No prompt text is in the repository. `backend/tests/fixtures/prompts/file_type.md` stays the test-only stub; tests do not assert wording. The fields
the v2 `file_type` prompt must return are the reply of §5.7 and are listed in the PR description for the owner.

## 12. Decided (engineering, rule 19)
The vocabulary and the exclusion words (§2.1, §4.1, measured on the fixtures); the thresholds and the three-hit minimum of §4.2; the customer-header
guard; the label-row definition; the confidence formula (§6.1); the check orders of §6.1 and §6.2; "min(3, periods)" for the numeric-column check;
the best-sheet order (§3); one call per new file shared with §19; no call without consent; the model's proposal for a sheet Python did not pick is
dropped; the currency of the model is a cross-check only; the label echo is checked and never stored; the text grammar and problem codes; routing
(decided, §14 item 3); typed text is never accepted.

## 13. Not built here
Column-oriented layouts with dates down the rows and measures across (the accountant P&L): the existing rules of chat-upload.md §4 keep reading them.
Currency conversion of a recognised file (FX, chat-upload.md §16, applies as before). Any change to the engine, the schemas, the gateway, the
prompt store or the frontend beyond the tests. Re-reading a decided file when the as-of month changes beyond the re-check of §6.2.

Files the implementation PR will add or change: new `backend/app/recognition.py`, `backend/app/llm/{schemas,gateway,prompt_store,step_payloads?}.py`
(structure type `file_recognition`, `FileRecognitionReply`, the text check, the stored form), `backend/app/structures/{__init__,redact}.py` (the text
grammar), `backend/server.py` (ingest, the recognition endpoint, the dataset view, Run audit input), `backend/growth_engine.py` and
`backend/schemas/metrics.py` with `backend/tests/test_interface_contracts.py` (§9), `backend/app/usage.py` (step `recognition`), `frontend/src/components/
RecognitionLine.jsx`, `frontend/src/lib/{recognition,chatUpload,api}.js`, `frontend/src/components/UploadChat.jsx`, CLAUDE.md rule 16 and
docs/architecture.md (recorded in this PR).

## 14. Decisions of the owner (19 Oct 2026, on PR #134)
1. **A row labelled ARR or MRR may be the revenue row and the trend series**, kind `recurring`, never shown as recognised revenue; growth from it is
   labelled "ARR growth" or "MRR growth", not "revenue growth" (§6.1, S31c, §9).
2. **Rule 16 and the data boundary are widened for the `file_recognition` step** as a dated amendment (19 Oct 2026), recorded in the frozen
   architecture like the `access_tokens` amendment (§5.9; docs/architecture.md and CLAUDE.md rule 16 in this PR).
3. **A P&L stays the P&L and carries the recognition; it satisfies the required revenue file once confirmed with two or more periods.** When it is the
   only revenue source the reconciliation reads "Not applicable – same source", is not Green and does not count as a completed integrity check (§8).
   Yearly periods support trend, and the blocked list says the monthly series is missing (§3.1). A KPI sheet with a recognised, invoiced or MRR/ARR
   row becomes a Monthly revenue report and the revenue file; a KPI sheet without one keeps chat-upload.md §26.14.
4. **S4 changes** to "Required: a revenue file – revenue by customer, invoices or a monthly revenue report (24–36 months)." (the rest of S4 stays),
   with the implementation.
5. **The strict reading of "masked values"** (no value tied to a row) stands (§5.3).
6. **"Lesser of 3 and the period count"** for the numeric-column check is accepted (§6.1).
