# Spec: Revenue file recognition, separate from classification
Status: **Implemented (2026-10-19, with the additions of section 6.7 and the amendments listed in section 15).** Source: George's request of 19 Oct 2026. Location:
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
    chat-upload.md, share below 80). B: a date column (a header scoring 80 or more for invoice date, or reading Month, Period, Date or a month name: "Month", "Period", "Date", "Jan-25")
    or an invoice, transaction, order, receipt or reference column. C: a number in the amount column.
  - *records with dates down the rows and measures across* (the accountant P&L: Month, Revenue, Cost of sales, Payroll ...): the same layout, read as *columns*
    when the sheet has a period column (Month, Period, Date) and no invoice, transaction or customer column. A: a measure column headed with a revenue word.
    B: the period column. C: a number in the measure column. Type: `financial_statements` with at least two cost and profit headers (§3 rule 3), else
    `monthly_revenue_report`; `series_basis` `column`; the result carries `revenue_column` {column, label, kind, confidence, state, reason, candidates}
    in place of `revenue_row`, checked as §6.1 checks a row, and `last_actual` {row, month, state, reason, candidates} names a dated row, not a column.
    A file the rules already type as a P&L by its columns is therefore recognised and never shows S31f (the TestCo P&L scored 0 on B before).
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

| Kind | Words (whole words, any case, punctuation as one space; the whole label is read, a bracket's content included: "Revenue (forecast)" is a forecast row) |
|---|---|
| `forecast` | forecast, forecasts, fcst, projected, projection, estimate, estimates, outlook |
| `budget` | budget, budgeted, target |
| `bookings` | booking, bookings, booked |
| `pipeline` | pipeline, backlog, opportunity, opportunities |
| `contract_value` | contract value, contracted revenue, total contract value, annual contract value, TCV, ACV, contracted ARR, committed ARR, committed MRR, CARR |
| `run_rate` | run rate, run-rate, annualised, annualized |

"Plan" is not on the list: a pricing plan ("MRR - Pro plan") is an actual row (chat-upload.md §26.15). A recognised row of these kinds is listed in
`non_revenue_rows` `[{row, label, kind}]` and is never a revenue candidate. The model may add rows and kinds (§5.7); the union is used, and a row
either side marks is out. Such rows are kept for claim matching: they enter the claim register through the existing path (Save claims,
chat-upload.md §20.4 and §26.15), as Unverified; this spec adds no claim code.

**Revenue candidates** (labels layout): a row that is not marked, whose label (bracket content left out for the revenue word and the exclusion words below, not for the six kinds above) holds a revenue word and none of: new, net
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
Sheet names, the title rows above the header (at most 6 rows), the column headers (at most 40 columns) and the masked sample: for each numeric or date
column up to 3 example values, and a profile (distinct count, typical length, shape) per text column. **Samples are never tied to a row (decision of
2026-10-19, on every sheet, metric-labelled or not).** The values of a column are drawn from different rows, and the rows are chosen
deterministically from the file hash, never in sheet order and never the same row in two neighbouring columns:
- *k* = min(3, ⌊n ÷ 2⌋) with *n* the number of data rows holding a number in the column (a sheet of one row sends no sample).
- For the numeric or date column at position *j* (counting such columns left to right), order the rows by `sha256(file_hash + ":" + j + ":" + row)`
  and take the first *k* rows that the column *j − 1* did not take. Columns *j* and *j − 1* therefore share no source row, and no row's series can be
  rebuilt from the text. The same bytes give the same text; other bytes give another choice.
- Samples are listed in row order inside a column, so the order of the lines does not reveal the row either.
A sheet name, title or header is redacted as in §19: the target company's name becomes [redacted], emails and phone numbers are masked, customers of the
per-audit pseudonym map take their pseudonyms. At most 6 sheets; a cell over 200 characters is cut.

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
`model_text(sheets, company_name, mapping, withheld, file_hash)` in `app/recognition.py` builds it from the sheets as Python read them.

### 5.3 Row labels
- **Metric-labelled** sheet (§4.2): its row labels are sent as written, after the redaction above.
- **Entity-labelled or unsure** sheet: row labels are sent masked, "Row 1", "Row 2" ... in sheet order, numbering label rows; no label text of any kind
  reaches the model. **No customer name ever reaches the model.** "Masked values" is read strictly: no value is tied to a row, on any sheet; the only figures are
  the per-column samples of §5.1, drawn from different rows and never from the same row in two neighbouring columns (decisions 5 and 7, §14).
- At most 400 rows with text per sheet, title rows and header row included (as chat-upload.md §26.11): the first 400 are read, by Python and by the
  model.
- A records layout has no row labels: its rows are data, never sent beyond the sample. A snapshot sends no label lines either (its rows carry no information the sample does not).

### 5.4 The gateway checks the text again
`structure_text_problem(text, "file_recognition", context, mapping)` refuses, with a closed problem code: a line of no kind (`not_cells`); more than 6
sheets or 6 title rows or 40 columns (the codes of §19); a sample that is not a number or a date, or more than 3 per column; a label line on a
`masked` sheet that is not "Row n" (`label_on_masked_sheet`); a label that is a figure (`figure_in_label`); more than 400 rows (`too_many_rows`); a
file name (`file_name`); a cell over 200 characters (`cell_too_long`); a text the redaction would change (`redaction_changed`). The gateway cannot
know whether Python's label mode is right; the label mode and the thresholds of §4 are tested in Python.

### 5.5 The call
- **When (decision 2 of 2026-10-19).** With the audit's consent, for **every recognised file** whose bytes have no stored answer, as for the column mapping,
  also when the rules are already `auto`; and when the rules find no type at 80 (§5.6). One call per new file. A file recognised by the rules and refused by the gateway, a timeout, a failure, no prompt in the store, no
  consent, the daily cap or the tester's allowance (monthly_allowance_reached) leave the rules' outcome standing (§6.5), and the file is still
  recognised.
- **Counts.** A recognition call counts toward the tester's allowance like any call (usage-and-allowance.md §4; no exemption), stays under the daily
  spend cap like the §19 file-type call, and is counted in `audits.usage` as step `recognition` by status. Budget `MAPPING_AI_SECONDS` (20 s); text
  cap `RECOGNITION_INPUT_CAP = 12,000` tokens; reply cap 1,000 tokens.
- **Cache.** Keyed by the file's sha256 and the prompt version, kept in `column_mappings` as `{audit_id, kind: "file_recognition", file_hash, prompt_tag, reply, saved_at}`;
  an upload of a new `file_type` prompt version is therefore asked again for the same bytes (the cache key of the gateway carries the tag too). The same
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
to the analyst: S31f (what is missing) is shown above the S6 type picker, which stays as the fallback (decision 3). A cached v1 answer is never served (the prompt tag is in the key).

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
redaction; for every other sheet the labels are sent as 'Row 1', 'Row 2'. No value is tied to a row on any sheet: the up to 3 sample values of a column
are drawn from different rows chosen from the file hash, never the same row in two neighbouring columns. Never a figure beyond the per-column sample of
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
  revenue row, never "revenue growth". `growth_label(result)` (a closed list: "Revenue growth", "MRR growth", "ARR growth", "Recurring revenue growth"; none for a snapshot) returns the label ("Revenue growth" only for kinds `recognised` and `invoiced` and for
  the sum of customer or category rows).
- Types with no revenue row (`invoice_transactions`, `customer_revenue`, `revenue_summary`, `arr_mrr_snapshot`) have `revenue_row: null` and
  `series_basis` `records`, `sum_of_rows` (the customer or category rows are summed), `sum_of_rows` and `snapshot`. For `monthly_revenue_report` and
  `financial_statements` it is `row` (or `column`, §2). The five values of `series_basis` are `records`, `row`, `column`, `sum_of_rows`, `snapshot`.
- **Total rows (review H3).** When a series is a sum of rows (`sum_of_rows`, and the snapshot value), a *total row* is never added to it. A row is a
  total row when its label holds the word total, totals, subtotal, grand total or sum anywhere (whole word, any case), or when its values equal the sum of two or
  more rows since the previous total, or of two or more total rows above it, in every period column it has a figure in, within rounding (0.5%,
  chat-upload.md §26.5); a row equal to the single row above it is never a total. Total rows are listed in `total_rows` `[{row, label, matches}]`, where `matches` says
  whether the total equals the sum of the rows it adds up (the rows since the previous total, all the rows used, or the totals above), within the same tolerance: the cross-check stays
  available, and a total that does not match is shown to the analyst. A row-basis series may itself be a total ("Total revenue" is a good revenue row); the rule is for sums.
- **Marked rows are never summed (review H2).** A sum of rows leaves out every row whose label holds a word of the six kinds of §2.1 (forecast, budget, bookings, pipeline, contract value,
  run-rate), on a metric-labelled or an entity-labelled sheet, and every row the model marked. The citation (`series_rows`) names the rows used.
- The result carries `series` `[{column, value}]` (the used rows summed, or the row's own values, per period column up to the boundary; the snapshot's one value), so the
  value is testable: a summary or snapshot with a total row gives the sum of its category rows once, never twice.

### 6.2 The last actual column and the boundary
- **Rules' reading.** The last column tagged actual (chat-upload.md §26.2: a tag over the columns, "Actual" over "Forecast"); with no tag, the last
  period column that has a number in the revenue row (a sheet with no revenue row: the last period column). The audit's **as-of month** is the stored
  `as_of_month` when it is set; else the audit's default, the last month of the P&L (chat-upload.md §2) — for a P&L file that is its own last month, so a
  clean audit with a defaulted as-of month asks no click; else none. The server passes this value as `as_of_month`.
- **Checks, in this order; the first failure is the reason and the state is `click`:**
  1. `not_a_period` — the proposed column is not a period column of the sheet.
  2. `no_as_of_month` — there is no as-of month at all (none stored, no P&L): **the boundary needs a click**, even when rules and model agree.
  3. `after_as_of` — the column's period ends after the as-of month: **rejected, needs a click**. The candidates are the period columns up to the
     as-of month.
  4. `rules_and_model_disagree` — the proposed column is not the rules' column.
  Otherwise `auto`. A boundary earlier than the as-of month is accepted: the engine reads to the last actual, as for a file that ends early.
- `last_actual` = `{column, month, state, reason, candidates}` with `candidates` `[{column, month}]`. `month` is the period's end month, YYYY-MM.
  Only the labels layout has period columns: a records or snapshot layout has `last_actual: null` and `excluded_columns: []` (the engine's as-of
  rule cuts invoice dates as it does for every revenue file).
- **Columns tagged forecast or budget are excluded wherever they sit** (review H5), before the boundary too: they are never read, never the last actual column, and one
  column per month is read (the first). In the dates-down layout the analyst's last actual month ends the series (review H4).
- **Columns after the boundary are excluded** from Run audit (`excluded_columns`), the same treatment as the forecast tables of PR #116 (chat-upload.md
  §20, §26.6). A file whose boundary waits for a click gives Run audit no column until the click (stage File mapping not done, as for a pending
  mapping). A later change of the as-of month re-checks a decided boundary on read: one now after the as-of month is `click` again.

### 6.3 The type
`file_type` is the rules' (§3). The model's `file_type` agrees, differs, or is `crm`/`pnl`/`not_revenue`: it never overrides a recognised type. When
the rules have a type and the model another of the six, the state is `click` (`rules_and_model_disagree`) with both as candidates; when the rules
have none (§3 rule 4) the model's choice among the candidates is shown as the AI suggestion and still waits for a click (`type_unsure`). The result carries
`type_reason` (`rules_and_model_disagree`, `type_unsure` or null); `type_source` is `rules` for a disagreement (the rules' type is shown, the model's is
a candidate) and `ai` for `type_unsure` (`file_type` holds the suggestion, `type_state` is `click`).

### 6.4 The workbook
The model's `sheet` is used only when it is the sheet Python chose as best (§3). A proposal for another sheet is dropped (the file is read by rules,
`type_source: "rules"`); the analyst can switch sheet (S31g), after which the sheet is read again.

### 6.5 The model is silent or wrong
If the model cannot be read, the rules' outcome stands, with the same thresholds (81+ `auto`, 80 and ties `click`), as for the column mapping
(chat-upload.md §4.2). Rules and model agreeing is **auto-accepted with a Correct button**; disagreeing or unsure shows the candidates.

### 6.6 The analyst
`POST /api/audits/{id}/datasets/{dtype}/recognition`, `dtype` `revenue` or `pnl` (a P&L carries its own recognition, §8), with one part at a time:
| Body | Effect |
|---|---|
| `{action: "confirm", part: "revenue_row" \| "last_actual" \| "file_type" \| "currency"}` | Correct: the proposal becomes `you` (the part must have a proposal) |
| `{action: "confirm", part: "pending"}` | the one Correct button (§7): every part waiting only for confirmation (reasons `confidence_80`, `no_as_of_month`) becomes `you` |
| `{action: "change", part: "revenue_row", row}` | one of the `candidates`; else 400 |
| `{action: "change", part: "last_actual", column}` | one of the period columns up to the as-of month; else 400 |
| `{action: "change", part: "file_type", file_type}` | one of the six types; else 400 |
| `{action: "change", part: "currency", currency}` | an ISO code (`ISO_CURRENCIES`); else 400 |
| `{action: "change", part: "money_kind", money_kind}` | `revenue` or `volume` (chat-upload.md §15); else 400 |
| `{action: "change", part: "sheet", sheet}` | a recognised sheet of the workbook; else 400 |
| `{action: "change", part: "series_source", series_source}` | `metrics_block` or `dated_list`, on a sheet with two tables (section 6.7); else 400 |
The server re-checks every choice (a row must be a candidate, a column a period up to the as-of month) and answers with the dataset view. Decisions
are saved with the dataset (`recognition_decisions`) and survive a reload; a replaced file clears them. Typed text is never accepted.

### 6.7 A sheet with two tables: a dated list and a metrics block (owner request of 19 Oct 2026)
A sheet may hold a **dated list** (a header reading Date, Month or Period beside a text header such as Value, and below it at least three rows
holding a date and a number; the dates may be days, they are summed by month) and a **metrics block** (labels down a column, periods across,
read as §2 to §4 read any labels sheet; its header row is found by the existing rule, within the first ten rows). The list sits below the block or
beside it, and its rows are never labels of the block: they leave the label statistics (§4.2) and the text the model reads (§5.3).
- **Detect both, classify each.** The result carries `tables` `[{kind: "metrics_block" | "dated_list", file_type, header_row, ...}]`, positions and counts only, never text.
  The block is typed by §3; a dated list is a `monthly_revenue_report`.
- **Which table supplies the revenue series (`series_source` `{supplier, state, cross_check}`).** A metrics row of **recognised revenue** (kind `recognised`, §2.1) wins.
  When the dated list sums to that row **month by month within 1%** (`SOURCE_TOLERANCE`; every month of the row up to the boundary must be in the list),
  the list is recorded as a **cross-check** (`cross_check.status` `match`), not a second source: `supplier` is `metrics_block`, `state` `auto`, no click.
  When they do not match (`mismatch`, with `months`, `months_off` and the largest `max_gap_pct`), or the row is not recognised revenue (an MRR or ARR row never wins
  by itself), `state` is `click`: **the analyst chooses** (`POST …/recognition` `{action: "change", part: "series_source"}`), the revenue row stands until the choice, and
  the audit waits for it like for any other click. The choice is `you`. A list that supplies the series gives `series_basis` `column` and cites its own rows (`series_rows`).
- **The mismatch appears in Worth flagging.** The engine keeps `series_source`, `cross_check`, `cross_check_months` and `cross_check_gaps` in the `recognition` block (§9); the memo
  lists the mismatch under Worth flagging in one sentence: "{k} of {n} months differ between the dated list and the revenue row on the same sheet: {month}: revenue row {value} ({sheet}, {cell}) vs dated list {value} ({sheet}, {cells}), …; the revenue series is read from the {table}." Each month that differs is named with both figures and both sources as cell positions (owner decision 4 on PR 135). It is a finding, never a banner blocker (rule 21).
- Not built: a list whose header is not within reach of the block's header rule, more than one dated list per sheet (only the first is compared) and a
  list beside a metrics block that is itself a dated-rows table.

## 7. What the analyst sees
On Upload & Mapping, under the file's bubble head (above the mapping table where there is one), `frontend/src/components/RecognitionLine.jsx` renders
the `recognition` block. The wording never mentions the model's confidence or a cost, and no number but the row and column positions the analyst needs
to find the cell. (Wording chosen under rule 19, as chat-upload.md §13 did; George reviews it in this PR.)

| Id | Where | Text |
|---|---|---|
| S31a | the type line | Type: {Invoice transactions / Customer revenue / Monthly revenue report / Revenue summary / Financial statements / ARR/MRR snapshot} ({by rules / AI suggestion, not verified / your choice}) and a **Change** button that offers the other five types. An unclassed type reads "Type: choose the type" with a drop-down of the two candidates. A type waiting for a click reads "Type: {type} ({source}). {reason}" with Correct and Change (`TYPE_REASON_TEXT`: `rules_and_model_disagree` Two readings differ. Choose the type. · `type_unsure` Choose the type.). An AI suggestion always says "not verified" (CLAUDE.md rule 18) |
| S31b | what it supports and blocks, one line | (a `monthly_series` item reads "monthly series missing, needs one column per month") Supports: {trend analysis (MRR/ARR, growth, run-rate) / customer-level analysis (NRR, gross churn, concentration, cohorts) and trend analysis (…) / claim matching only}. Blocked: {analysis}, needs {data}; {analysis}, needs {data}. — the "Blocked" part is left out when nothing is blocked; the data is the closed `needs` text of §3.1 |
| S31c | the revenue row | Revenue row: {label} (row {n}) — for kind `recurring` "Recurring row: {label} (row {n})" — with **Correct** and **Change** (Change opens the candidates: "{label} (row {n})"). Waiting only for confirmation (`confidence_80`): the same line followed by the reason, no drop-down until Change. Needs a choice (any other reason): "Revenue row: choose the row. {reason}" with the drop-down and no Correct. Decided: Change only. Not shown for a type with no revenue row |
| S31d | the last actual month | Last actual month: {Mon YYYY}. Columns after it are not used. with **Correct** and **Change** (the candidate months). Waiting only for confirmation (`no_as_of_month`): the same line followed by the reason, no drop-down until Change. Needs a choice (`after_as_of`, `not_a_period`, `rules_and_model_disagree`): "Last actual month: choose the month. {reason}" with the drop-down and no Correct. Decided: Change only. The second sentence is left out when no column follows |
| S31e | the reasons, closed texts (`REASON_TEXT` in `lib/recognition.js`, one per code of §6) | no_candidate: No row looks like revenue. Choose the revenue row. · tie: Two rows fit equally. Choose the revenue row. · confidence_80: Please confirm the revenue row. · row_missing, label_mismatch: The proposed row could not be matched to the sheet. Choose the revenue row. · marked_not_revenue: The proposed row is a forecast, budget, bookings, pipeline, contract value or run-rate row. Choose the revenue row. · not_numeric_enough: The proposed row has too few numbers. Choose the revenue row. · no_revenue_word: The proposed row has no revenue word in its label. Choose the revenue row. · rules_and_model_disagree: Two readings differ. Choose the revenue row. (for the month: … Choose the last actual month.) · no_as_of_month: The audit has no as-of month, so this month needs your confirmation. · after_as_of: The proposed month is after the as-of month. Choose a month up to it. · not_a_period: The proposed column is not a month. Choose the last actual month. · turnover_question: the question of chat-upload.md §15 with the buttons Revenue / Volume · type_unsure: Choose the type. |
| S31f | not a revenue file | the server's message of §2: "Not a revenue file. Missing: {names}." It replaces every other line of the recognition and is shown **above the S6 type picker, which stays** as the fallback (decision 3, §14) |
| S31g | other sheets | Other sheets in this file: {sheet} ({type}) **Use this sheet**, one per recognised sheet. Left out when there is none |
| S31h | the consent explainer | The sentence of §5.8 added to S2 |
| S31i | rows kept out of revenue | {n} rows ({kinds}) are not used as revenue and are kept as claims for matching. — "1 row ({kind}) is not used as revenue and is kept as a claim for matching." for one. The kinds are the closed words, in sheet order, without repeats. Left out when none |
| S31j | the S13 status line of a file with a click open | (a turnover row's row and money kind are one choice, one answer settles both; with a column mapping also open, S13's "{n} columns wait for your decision" and this count are added; `choices_waiting(result)` counts the recognition's) {n} choices wait for you · Ready – press Run audit (S13 of chat-upload.md; the count is the parts in `click`: type, revenue row, last actual month, currency, money kind, series source). A file read by recognition only (section 8) has no mapping table, no billing-terms block and no "Map the customer ID column first": the monthly report and the revenue summary need no customer ID column |
| S31k | currency | Currency: {code}. Or, with none found: Currency not found in the file. Confirm the currency: {drop-down of ISO codes, the audit's reporting currency first}. A file with a column mapping and no currency column shows the same question in place of "Required field not mapped: currency" (the answer becomes a constant column mapped as the currency field) |
| S31l | two tables on one sheet (section 6.7) | Two tables on this sheet: a metrics block and a dated list. Then, when the revenue row wins: Revenue series: the revenue row of the metrics block. The dated list matches it month by month ({n} months). — when the analyst chooses: {The dated list and the revenue row differ in {k} of {n} months. / The dated list matches the row month by month ({n} months).} Choose which table supplies the revenue series: with the buttons Use the revenue row and Use the dated list; after the choice: Revenue series: {the revenue row of the metrics block / the dated list}. The dated list and the revenue row differ in {k} of {n} months. |

**One Correct button (decision 4, §14).** Where one or more parts wait only for confirmation (reasons `confidence_80` and `no_as_of_month`, the *confirm-only* reasons), the parts keep their lines and Change, and the file shows one **Correct** button (`part: "pending"`, §6.6) instead of one per part. Correct on an auto part (the accepted proposals above) keeps its own button.

The banner is unchanged (rule 21): a revenue file with an open click counts as "uploaded, mapping not confirmed" (S16d); a recognised file with
nothing open clears it. No banner kind is added.

## 8. API, storage and routing
- **Upload.** `POST /api/audits/{id}/datasets/upload` runs recognition (§2, §3) on every sheet of every file that the rules do not type as CRM. The
  view of a dataset gains `recognition`: `{recognised, missing, message, sheet, header_row, file_type, type_state, type_source, type_candidates,
  label_mode, label_share, confidence, series_basis, periods, revenue_row, last_actual, excluded_columns, currency, money_kind, non_revenue_rows,
  supports, blocked, other_sheets, needs_click, type_reason, series, series_rows, total_rows, revenue_column, tables, series_source}`. `type_source` is `rules` (Python decided, with the model silent or agreeing), `ai` (the type is the
  model's choice among candidates), or `you`. `money_kind` is `{asked, answer?}`. A file that is not recognised and gets no type answers
  `{status: "unknown_type", recognition: {recognised: false, missing, message}}` and stores nothing.
- **Routing (decided, §14 item 3).** A recognised file is stored as the audit's revenue file (`dtype: "revenue"`) with its
  recognition. Types with customer rows (`invoice_transactions`, `customer_revenue`) keep the column mapping of chat-upload.md §4 beside the
  recognition line; the other four types have no column mapping, hold no required field (as a statement file, chat-upload.md §26.6) and wait only for
  the clicks of §7. A P&L the rules type by its columns, or a statement-shaped P&L (financial statements) that the P&L path of §26 reads, stays the
  audit's P&L (CAC payback needs it) and also carries its `recognition` block; it satisfies the required revenue file once its recognition is confirmed with two or more periods (decision 3, §14).
  **How a P&L's recognition is confirmed (review H2):** the P&L's own bubble shows the same recognition line (S31, ids with `pnl`), served by the P&L dataset's
  `recognition` block, and the analyst presses **Correct** on its revenue row (`POST …/datasets/pnl/recognition` `{action: "confirm", part: "revenue_row"}`, or
  `part: "pending"`). Confirmed means no part in `click` and the revenue row `you`; with fewer than two periods it is never confirmed for this purpose (the banner S16a
  stays). A `revenue` upload is unaffected (its S16d rule is chat-upload.md §16). Banner kinds are unchanged (rule 21).
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
- `revenue_series`: a `basis` (the five values of `series_basis`: `records` · `row` · `column` · `sum_of_rows` · `snapshot`), the `file_type` code, and a citation naming the row or the
  rows and the columns up to the boundary (file, sheet, rows, rule), as every cited block.
- `missing_data`: entries with the lines of §3.2 (`metric`, `status: "Missing"`, `reason`, `unlocked_by` = the `needs` text, `file`); no new key.
- `recognition` (a summary on the audit's results, closed words and counts only: type code, `series_basis`, the periods used, the count of excluded
  columns, `currency_confirmed`, `source` `revenue_file` or `pnl`, and for a sheet with two tables `series_source`, `cross_check`, `cross_check_months` and `cross_check_gaps` `[{month, row_value, list_value, row_cell, list_cells}]`: cell positions and two figures per month that differs, never file text) so the memo and the export can state the basis. Not in any narrative slice; the boundary test is extended (rule 14).
- `revenue_reconciliation`: a `status` (`computed` · `not_applicable`) and, for `not_applicable`, the reason "Not applicable – same source"; `available`
  stays false then, `by_month` (required today, `schemas/metrics.py` `RevenueReconciliation`) is an empty list, and `integrity.assess` reads the status (decision of 2026-10-19).
- `growth_label` (text, the closed list of §6.1) on the growth figure of `revenue_series`, so the screen never says "revenue growth" for an MRR or ARR row. A closed word, not file text.
- `mrr_series` and `arr` from a `recurring` revenue row: their `source` says the figure is read from a row labelled MRR or ARR, not computed from
  customers (decision 1).
File text (labels, titles, sheet names) is never a contract field; the closed words above are.

## 10. Tests (written first as strict expected failures; the implementation PR removed the markers and all of them pass)
The frontend file uses a helper with the same effect (jest 27 has no `test.failing`); it loads the component inside each test so a missing module fails the test, not the suite.
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
(decided, §14 item 3); typed text is never accepted; the effective as-of month of §6.2; the total-row rule (§6.1); the `pending` part and the confirm-only reasons; `prompt_tag` in the kept answer.

## 13. Not built here
The column mapping of dates-down layouts stays as chat-upload.md §4 reads it; only their recognition is new (§2).
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
7. **Samples are never tied to a row, on every sheet** (second review, 19 Oct 2026): the 3 example values of a column come from different rows chosen
   from the file hash, never the same row in two neighbouring columns (§5.1, §5.9; docs/architecture.md and CLAUDE.md rule 16 carry the wording).
8. **The recognition call runs for every recognised file**, cached by file hash (and prompt version), as the column mapping is (§5.5).
9. **The S6 type picker stays** as the fallback when Python recognises no type; S31f sits above it (§7).
10. **Two confirm-only reasons on one file collapse into one Correct button** (§7, §6.6 `pending`).
11. **Every new test is `xfail(strict=True, reason="awaiting implementation: revenue-file recognition")`**; the implementation PR removes the markers.

## 15. Amendments made with the implementation (owner request of 19 Oct 2026)
1. **S31a** reads "AI suggestion, not verified" (CLAUDE.md rule 18), not "(AI suggestion)".
2. **Section 6.7**: a sheet with a dated list and a metrics block (above).
3. **Currency** (S31k): a missing currency asks the analyst to confirm it; "Required field not mapped: currency" is no longer shown. A revenue file with a column mapping and no
   currency column keeps the currency field required, and the analyst's answer supplies it as a constant column ("Currency (confirmed)"), so the audit waits for the answer as it did for the mapping.
4. **Customer ID**: a file read by recognition only (monthly revenue report, revenue summary, financial statements, ARR/MRR snapshot) holds no required field, shows no billing-terms block and never says
   "Map the customer ID column first".
5. **The reply** is parsed with exactly the keys of §5.7 and nothing else (`FileRecognitionReply`, `extra="forbid"`, no `confidence`); the label echo is compared and dropped before anything is stored (§5.5).
6. **Recognition clicks gate Run audit for a file read by recognition only and for a P&L carrying the revenue file**; for a file with a column mapping (invoices, customers by periods) the recognition line is shown and
   only a missing currency holds the audit (decision for the owner, see the pull request).
7. The recognition call of a file the rules type comes after its column-mapping call (one call per new file, §5.5); a file the rules cannot type is asked first (§5.6).


8. **Stored sheets** (owner decisions on PR 135): the dataset keeps every row of each **recognised** sheet, never a cut, and no other tab of the workbook. A file that already keeps its rows keeps no sheet beyond the one recognition read:
   customers by period keep that one sheet, and one row per invoice keeps only a few facts (the columns found, the month count, the currency codes), no sheet. Every cell is stored as a number, text, a boolean or a datetime (a time of day becomes text, a duration seconds). A dataset is one MongoDB document; its size is measured in BSON bytes, as MongoDB counts it. Over `DATASET_MAX_BYTES` (15 MB) any upload stops with a clear message (413) before the model is called and nothing is stored. Stored sheets are deleted with the audit and follow the retention of other datasets.
9. **A file with no monthly revenue series is not the revenue file** (owner decision 1 on PR 135): a snapshot, a yearly or quarterly report and a sheet read as a snapshot get the type picker (S6) as before the recognition, and a stored P&L with only yearly periods does not satisfy the banner (S16a) or Run audit. A statement-shaped P&L is still the audit's P&L.
10. **Mixed currencies** (review L3): amounts that show two currencies (signs or codes in the amount cells) have no single currency to confirm; the required field stays open as before. A column headed Name is entity-labelled whatever its values (review L1).
