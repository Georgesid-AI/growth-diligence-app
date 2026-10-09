# Spec: Chat-style upload and column mapping
Status: Final (2026-10-08); decisions applied (§12); amended 2026-10-08 for the mapping-screen wording, the delete dialog
and the banner (§12, §13, S5, S9, S15, S16a, S16d, S18, S18b, S23–S25), and 2026-10-09 for §15 and §16. Location: docs/specs/chat-upload.md.
Replaces the content of the MappingWizard page. Supersedes in part docs/specs/llm-structure-reading.md §1 for
the column-mapping path only: which columns are sent and from how many rows (§4.2). Everything else in that spec
stands, including the rule-16 shape of what is sent and §9 (sent text is never stored).

## 0. Challenge and deletions (CLAUDE.md rule 4)
- Needed by the analyst: one place showing what each file was read as and which columns still need them. Simpler
  version: keep the three panels and add per-column confidence with Confirm and Correct. The chat shell adds type
  detection and a message list, but no new evidence. A text box that only refuses text invites typing; it stays
  because it was asked for. The model's own confidence would change nothing, because every AI column needs a
  click, so it is not asked for (Q5).
- Delete first: the three per-type panels and their upload buttons; the "Confirm mapping" button (decisions are
  per column, and the mapping saves when nothing is pending); the auto-recompute on upload with an unconfirmed
  mapping; sending already-decided columns to the model.

## 1. Scope and the architecture
In: the MappingWizard page content, upload with type detection, the column-mapping rule (rules, then the model,
then the analyst), saved mappings, the blocker banner, degrade-on-gateway-failure, the delete confirmation, the
usage counters and their totals, the revenue reconciliation and its evidence table, the CLAUDE.md lines (§6.4),
three messy fixtures and their tests.
Out: decks (the deck panel stays as it is, below the chat), multi-sheet reading (the first sheet only, as today),
data cleaning (a column the engine cannot read stays unreadable; the bubble says so), and any new metric on the
Dashboard.

The request as written crosses the frozen architecture in three places. This spec builds the in-architecture
version of each, as decided on 2026-10-08 (Q1 A, Q2 A):
| Request | Crosses | In-architecture version (decided) |
|---|---|---|
| Sample = headers + 20 masked rows, numeric values kept, names and IDs tokenised | Rule 16: per column, at most 3 sample values (numeric and date columns only) or a profile for text columns. The gateway already refuses more than 3 samples, and refuses text values (test_gateway_data_boundary.py) | The rule-16 shape, built from the first 20 data rows, for the undecided columns only. Every customer column, numeric IDs included, sends a profile only, so no tokens are needed (§4.2) |
| Masked sample stored as a MongoDB document `mapping_sample`; the gateway reads it from MongoDB | Rule 17 and docs/architecture.md "What is stored": model output and metadata, never sent text. llm-structure-reading.md §9: "Sent text is never stored". The Storage row lists every collection, and this would be a new one | The sample is built in memory by a pure function and handed to `gateway.read_structure`, as today; only its content hash is stored. The gateway still never reads the upload, and the boundary test enforces this |
| Usage log as its own collection; a totals page | The Storage row (every collection is listed) and the Frontend row (four pages) | Usage counters on the audit document (`audits.usage`), tokens and cost read from `llm_calls`, and totals as a section of the audit list (AuditHub) |

## 2. Screen
- The MappingWizard page keeps its route, its title and the header bar (Compute Metrics). Below the header, at the top of
  the page, sit the audit's set-up fields (2026-10-09, George): Reporting currency, Target ARR, Target date, As-of month and
  Fiscal year-end, each with one line of help under it, then the FX settings (§16), then the chat panel: a pure white message
  list with the input bar at the bottom. The deck panel stays below the chat panel, unchanged. The page uses the existing
  light theme. The set-up fields save as they change (PUT /audits/{id}); a refused save names the field and the reason.
  Help lines, word for word: Reporting currency "All figures are converted to this currency. Use the company's home
  currency; the verdict and memo use it." · Target ARR "The plan figure the audit tests. Every claim's value at stake is
  measured against it." · Target date "When the plan says Target ARR is reached. Sets the forecast horizon." · As-of month
  "Last month of actual data. Metrics are computed up to this month. Defaults to the last P&L month." · Fiscal year-end
  "Maps FY labels in the deck to months. A wrong setting shifts every FY claim." The creation dialog asks for the company
  (audit) name and the client, and holds the consent tick; the five fields start at EUR, 0, no date, no as-of month and
  December.
- Input bar: a paperclip (a file picker that accepts several files), a drop zone over the whole panel, and a text
  field. Text sent from the field gets a system reply, word for word: "This window accepts files and mapping
  confirmations." The text is never sent to the server, stored or logged.
- An explainer line sits above the drop zone and is tied to `structure_reading_consent`. The consent tick stays on
  the creation screen, so this panel only shows its state. When ticked, the panel shows explainer S2; when unticked,
  S3 (§11).
- Analyst bubble, one per file: file name, size, and a type icon (xlsx or csv).
- System bubble, one per file: the detected type, rows and months found (S5), then the info box "Why this step
  matters" (S25, above the first mapping table of the page only), then the mapping table (§4). For a revenue file,
  the billing-terms block follows the table unchanged. The FX rates are not part of the bubble: they sit in their own FX settings section
  of the page, below the chat, and belong to the audit (§16). A status line ends the bubble (S13).
- Mapping table columns (S23): In your file · Means · Confidence · Mapped by · action. "Mapped by" is one of the four
  values of S24: Rules, AI suggestion – confirm, You, Saved from earlier upload (a column with no proposal yet reads
  "You – choose"). There is no "Your decision" label. Confidence is never a dash (S9). Rows are ordered by §4.4.
  Columns left unused are folded into one "Not used (n)" row that opens to show them, each with Correct.
- Dates (amended 2026-10-08 and 2026-10-09, George): every date the analyst sets (the set-up fields' target date and as-of
  date, the gate date of the claim register) uses the app's own date picker, not the browser's
  date input: a calendar with month arrows and year arrows and a year the analyst can type. Years run from 2000 to
  2100. A year typed outside is rejected with "Year must be between 2000 and 2100" and the calendar stays where it
  was; the arrows stop at January 2000 and December 2100; a stored value outside the range is shown empty, so year 0001
  never appears. The value stays an ISO date (YYYY-MM-DD). The server holds the same range for the target date, the
  as-of date and the gate date. The engagement reference field is gone from the creation screen, the audit record, the
  memo, the CSV and the "Other" note check (llm-structure-reading.md §4); an audit stored with one has it removed
  when the server starts. Typing (2026-10-09): the date box also takes a typed date, as 2026-06-30 or 30.06.2026 and no other
  form (06/07/2026 is June in one locale and July in another); a text that is not a real date inside the range is refused
  with "Type the date as 2026-06-30 or 30.06.2026" and the value stays. The calendar opens below the box when it fits, else
  above; it keeps that side until it closes, and always shows six week rows, so it never jumps. Tested in DateField.test.jsx.
- The month range of the detected line (S5) shows once the date column is confirmed (decided by the analyst, or
  accepted by the rules); before that the line ends on the row count, with no text in place of the months.
- On reload, the panel rebuilds one analyst bubble and one system bubble per stored dataset. Text replies and
  refused files are not kept.

## 3. Upload and detection
- `POST /api/audits/{id}/datasets/upload` (multipart, `dtype` optional, `replace` default false). Files are sent
  one at a time, in drop order. The typed endpoint `POST .../datasets/{dtype}/upload` stays for the demo seed and
  the tests.
- Accepted: .xlsx and .csv (amended 2026-10-08, George). Anything else is refused in the browser (S7) and counted by extension (§7). An old .xls workbook is refused with S7b, "Save as .xlsx or .csv and upload again.", in the browser and by the server (400), and counted as "xls"; the file picker lists .xlsx and .csv only.
- Header row: among the first 10 sheet rows, the header row is the first row that fills at least half of the
  widest row's cells and holds no number other than a year. Rows above it (titles, blanks) are dropped and never
  stored. Header-like rows directly below it join the header stack, as today (at most 3). The file is read without
  a header (`header=None`), with short rows padded and blank lines counted, so a one-cell title row cannot break a
  CSV. Every stored row keeps its sheet row number, and `normalize` uses that number for `_row`, so citations name
  the real sheet rows. Today `_row` assumes the header is on row 1 and that there are no blank lines.
- Type: for each type, the share of its required fields that the rules map (score above 0). The type with the
  unique highest share wins, if that share is at least 50%; otherwise the type is unknown. Measured on
  sample_data/: 3 of 3 files detected, with margins of 100% against 50% (revenue), 100% against 50% (CRM) and
  100% against 25% (P&L). Months found are the distinct months of the date column: invoice date for revenue,
  close date for CRM, month for the P&L.
- Unknown: nothing is stored. The bubble asks for the type (S6), and the browser sends the same file again with
  that `dtype`.
- A type that is already loaded: if the hash is the same, the bubble says S14 and there is no prompt. If the hash
  differs, the server stores nothing and answers 409 with the detected type; the bubble asks S8, and Replace sends
  the file again with `replace=true`.

## 4. Mapping rule
### 4.1 Step 1: rules (Python)
- Header score: the existing `_score`, the best over a field's aliases (100, 80, 60, 40 or 30). A header that
  pandas de-duplicated ("Customer ID.1") is scored on its cell text, so duplicate headers tie.
- Value fit: the share of the column's non-blank values, over all data rows, that the engine can read as the
  field's kind. For a date field, the date parser reads the value; a day/month order it cannot settle still
  counts as a date. For a numeric field, `pd.to_numeric` reads it. For currency, the value is three letters. A
  text field (customer, deal ID, stage, segment, revenue type, founder involved) accepts any non-blank value. A
  column with no non-blank value has a fit of 0.
- Confidence = round(header score × value fit). The rules propose one column per field, using the existing greedy
  `suggest_mapping` order.
- Auto-accepted: confidence at or above `MAPPING_THRESHOLD = 80` (Q3), and no tie. These rows are shown with
  Correct and need no click. Measured on sample_data/: 16 of 17 columns score 100. "S&M Expense" scores 30 (the
  3-letter alias "s&m"), so it needs one Confirm.
- Unsure: below the threshold, or tied. A tie means two columns share a field's best score, or one column shares
  its best score between two fields. The rules' proposal is shown with Confirm and Correct. If consent is ticked,
  the column also goes to step 2.
- Undecided: a column with no proposal while a field of its type is still open. With consent, it goes to step 2.
  A column with no proposal and no open field goes to "Not used".

### 4.2 Step 2: the model (only with consent)
- The column-mapping text (`structures.column_mapping_text`) is built only from the unsure and undecided columns.
  It uses the first 20 data rows and is redacted as today: the header stack (at most 3 rows), up to 3 samples for
  each numeric or date column, and a profile for each text column. Columns keep their sheet positions (`r1c5`),
  so replies map back. Every column whose header matches a customer alias at any score, and every column tied for
  `customer_id`, sends a profile only, even when its values are numbers. Decided columns and their headers are not
  sent. The open fields are named by field name only.
- The text never touches MongoDB. `llm_structures` and `llm_calls` keep the reply, its content hash, tokens and
  cost, as today.
- A budget of `MAPPING_AI_SECONDS = 20` covers the call (`asyncio.wait_for`). On a timeout, provider error, spend
  cap, token cap or parse failure, the columns that were sent become "Needs your decision" and the bubble shows
  S12. The per-audit lock is released on cancellation, and a test covers this. Nothing waits for the model.
- A model proposal that maps a column to a field becomes AI suggestion, not verified, with Confirm and Correct.
  Columns the reply leaves out go to "Not used". Python checks every proposal against the open fields and the sent
  cells (`proposed_mapping`, as today). The output schema stays as it is (Q5).

### 4.3 Step 3: the analyst
- Confirm accepts the proposal. Correct opens a field dropdown (the existing field names and "Not used"; a field
  held by another column is disabled and names that column) and a reason dropdown (S11, a fixed list). The chosen
  reason stays selected for the next correction on the page until it is changed.
- "Other" also opens a text box (S20) for an optional note of at most 60 characters. The note is cleared after
  each correction; the code stays. The server trims the note and drops control characters. Column header text is
  allowed: each header of the audit's uploaded files (the header stack's cells, whole, any case) is set aside
  before the other checks, so a header that contains a cell word still passes. The server refuses the rest of the
  note, with a 400 and S21, when it holds any of these: a digit (also inside a header, so "Revenue 2024" cannot be
  quoted); a file name of the audit, with or without its extension; a cell text from the data rows of an uploaded
  file of the audit (a whole word, any case, 4 or more characters, the same boundaries as the redaction rules);
  the company name or client name. A refused note saves nothing. A kept note goes only to
  the usage counters (§7). The mapping version keeps the code "other" and not the note.
- "Needs your decision" rows show the field dropdown, preset to "Not used".
- Compute waits for two things: no AI or unsure row left unconfirmed in any uploaded file, and every required
  field of each file mapped. Until then, the Compute button is disabled, the status line shows S13, and the
  auto-recompute after an upload or decision skips, leaving `metrics_stale` set as it does today.
- Decisions go to `POST /api/audits/{id}/datasets/{dtype}/decisions` as `[{column, action: confirm|correct, field,
  reason, note}]`. The server applies them, works out what is still pending, and writes a mapping version (§5) when the
  file has nothing pending and on every later change. The existing mapping endpoint keeps saving FX rates and
  billing terms. The pseudonym map is filled when the mapping saves, as today.

### 4.4 Row order
Rows that need a click come first (unsure, AI suggestion, no proposal), then the rest by ascending confidence, so the
auto-accepted 100s come last. A row with no score (an AI suggestion, a column with no proposal, a row the analyst
decided) counts as the lowest. Rows of equal confidence keep the order of the file. The order follows the state, so a
row moves down when its click is made. Unused columns stay in the "Not used" fold.

## 5. Saved mapping
- A version is stored in `column_mappings` with: audit id, type, file hash (sha256 of the bytes), header key (as
  today), version number, field→column mapping, and per column its source, confidence, decision and reason code.
  Earlier versions are kept. Delete audit removes all of them.
- Re-upload with the same file hash: the latest version is applied, with no rules run, no model call and no
  clicks, and the bubble says S14.
- Same headers but a different hash: the latest version counts as confidence 100 for each column it mapped,
  scaled by that column's value fit on the new data. No model call is made.

## 6. Reliability rules (app-wide)
### 6.1 Degrade, don't die
When the gateway fails or times out anywhere, every computed metric still renders with its citation and a
narrative-unavailable note (S17). The mapping path degrades as in §4.2; the deck path falls back to Python's
candidates, as it does today; the narrative path keeps `narrative_status="unavailable"`, as it does today. A test
forces each failure.

### 6.2 Blocker banner
`GET /api/audits/{id}/blockers` returns at most three kinds of blocker. The `Layout` header renders them at the
top of every audit view (Mapping, Dashboard, Diagnostics). The audit list has no banner. Nothing else may enter
the banner: a test checks the kinds. One exception to "every audit view" (2026-10-09, §16): the S16a wording ("Revenue
file missing") is held back until the first Calculate; S16d and the other two kinds show whenever the server reports them.
| Kind | Rule (decided 2026-10-08, Q4) | Text |
|---|---|---|
| required file missing | the revenue file (the only file marked required) is not uploaded (S16a), or is uploaded and its mapping is not confirmed (S16d); one blocker of this kind, with the text of the case that applies | S16a or S16d |
| top-5 claim contradicted | a claim-register row ranked 1–5 has evidence label Contradicted, whether a miss or a beat (the label as claim-matching.md §4 defines it) | S16b, with the row's citation |
| revenue reconciliation | new engine result `revenue_reconciliation`: the revenue file's monthly revenue (`revenue_series`, reporting currency) against the P&L revenue column, summed over the window (the months both files cover up to the as-of month, at most the last 12); gap = abs(file − P&L) ÷ P&L; a blocker above 2%; no check without a P&L | S16c, with both files' rows as its citation; it links to the evidence table |

Evidence table (never a blocker). `revenue_reconciliation.by_month` holds one row per month of the window: the
revenue file figure, the P&L figure, the gap (file − P&L), and the gap as a % of the P&L figure ("—" when that
figure is 0). Each row cites its revenue-file rows and its P&L row. The Diagnostics page shows the table as a
"Revenue reconciliation" section (S22), with the window total as its last row, whenever a P&L is uploaded; without
one the section is hidden. Only the window total decides the blocker: a single month above 2% shows in the table
and never in the banner. `revenue_reconciliation` is server-only: it is kept out of every narrative slice, and the
boundary test is extended for it (rule 14).

### 6.3 Delete audit
`DELETE /api/audits/{id}` takes the JSON body `{"confirm": "<company name>"}`. The name goes in the body, never
the URL, so no access log holds it. Matching trims leading and trailing whitespace, then is exact and case-sensitive (amended 2026-10-08; it was
exact after trimming, ignoring case): the server and the dialog use the same rule. A wrong or missing name gets a
400 and deletes nothing. The dialog (S18) enables Delete only when the typed text is the company name exactly (after trimming), and
shows S18b under the box once the typed text is not empty, does not match, and either about one second has passed
without typing or the box has lost focus (not on every keystroke). A test asserts that no
document with the audit id remains in any collection: datasets (the stored rows, i.e. the raw file content),
deck_text, column_mappings (every saved version) and the rest. There is no mapping_sample collection to remove
(§1). The demo seed and the tests that delete pass the name.

### 6.4 CLAUDE.md lines (added word for word with the first implementation commit)
- Rule 7, the session-log sentence becomes: "...create docs/session-log/YYYY-MM-DD-<branch>.md (-2, -3, ... if the
  name exists) with six lines: date and branch; deleted; decided (what and why, optimizations included); slow or
  unclear; root cause and the rule that prevents it next time; one process change to propose." The rest of rule 7
  stays.
- Rule 20: "Degrade, don't die: if the LLM gateway fails or times out anywhere, every computed metric still renders
  with its citation and a 'narrative unavailable' note."
- Rule 21: "Three hard blockers, and nothing else, render at the top of every audit view: the revenue file Missing,
  a top-5 claim Contradicted (a miss or a beat), and a revenue reconciliation gap above 2% over the window of
  docs/specs/chat-upload.md §6.2. Per-month gaps go in the reconciliation evidence table, never in the banner."
  Amended 2026-10-09 (§16): the revenue-file blocker reads S16a from the first Calculate and S16d at all times; the line in
  CLAUDE.md carries that wording.
- Rule 22: "Delete audit requires typing the company name and removes every document of the audit in every
  collection, saved mappings and stored files included."

## 7. Usage counters (no file names, no values)
- `audits.usage` (Q2) holds: `first_upload_at`, `first_export_at` (the first xlsx export, which carries the IC
  memo), `last_screen` (mapping, dashboard or diagnostics, sent by each page on mount; any other value is refused);
  `files.uploaded` by type and `files.rejected` by extension; `columns` mapped by rules, saved mapping, the model's
  proposal, confirmed and corrected, with a count per reason code; `other_notes`, the kept "Other" notes (§4.3) as
  `{note, at}`, at most 50 per audit with the oldest dropped first, and with no column, file or field beside them;
  `steps.compute` runs and failures by error type; and `steps.mapping_ai` by status.
- Computed on read, never stored: tokens and cost per step (from `llm_calls`); evidence-label counts (claim
  register labels, and the metrics with status Missing); analyst changes (mapping corrections, plus claims edited
  or rejected, plus register metric or segment overrides).
- `GET /api/usage/totals` returns sums across audits, the median time from first upload to first export, and the
  50 newest "Other" notes across audits. It has no per-audit rows, names or ids. AuditHub shows the totals as a
  folded "Usage totals (all audits)" section (S19).
- Delete audit removes the counters with the audit (§6.3).

## 8. Privacy
There is no admin view of files, audits or results. An "Other" note may contain column header text (§4.3); it is
kept only in `audits.usage.other_notes` and shown only in the usage totals. Logs carry model JSON output and
metadata only: never raw rows, sample text, header text, file names, company names, typed text or "Other" notes,
whether or not the note quotes a header. New log lines carry codes only (type, status, error type, reason code).

## 9. Data boundary (rule 14)
`test_gateway_data_boundary.py` gains these assertions, and each new test is first shown failing on a deliberate
violation:
- The column-mapping text holds only unsure and undecided columns. Decided columns' headers are absent, and the
  text is built from at most 20 data rows.
- A customer-alias column sends a profile only, numeric IDs included. No fixture customer name and no text cell
  value appears in the text.
- No collection holds the sent text after an upload with consent.
- Every new log line holds no file name, header, cell value, company name or note. `audits.usage` and the totals
  response hold no file name, cell value or company name, and hold header text only inside a kept note. A reason
  code outside the fixed list is refused.
- An "Other" note is refused when, after its headers are set aside, it holds a digit, a file name, a cell text from
  a data row, or the company or client name, or when it is over 60 characters. A note
  that quotes a header is kept, including a header that contains a cell word; a header with a digit is refused. A
  kept note is found only in `audits.usage.other_notes` and the totals response: never in a log line,
  `llm_calls`, `column_mappings` or a model call.
- `revenue_reconciliation` is absent from every narrative slice.

## 10. Tests
Fixtures: synthetic CSV files under `backend/tests/fixtures/messy/` (rule 15: invented names only).
| Fixture | Content | Rules map (auto) | Sent to the model |
|---|---|---|---|
| `blank_vs_zero.csv` (revenue, 24 rows) | Amount with 4 blank and 3 zero cells; an "Adj" column, mostly blank and 0 | Customer ID, Invoice Date, Amount, Currency, Segment | Adj |
| `mixed_currency.csv` (revenue, 20 rows) | Amount written as "€1,200", "$950", "1.200,00 EUR"; no currency column | Customer, Invoice Date, Tier | Amount (confidence 0: no value is a number) |
| `duplicate_ids_header_row3.csv` (revenue, 30 rows) | Title on row 1, blank row 2, header on row 3; two columns headed "Customer ID" (codes and names); IDs repeat, and one ID carries two names | Date, Amount, Currency | both Customer ID columns (tie) |
Expected outcomes are under threshold 80. The third fixture also runs as an .xlsx file built in the test.
Tests (backend: `test_chat_upload.py`; frontend: `MappingWizard.test.jsx`, `Layout.test.jsx`, `AuditHub.test.jsx`):
1. For each fixture, the rules map exactly the clean columns, and only the ambiguous ones are in the model text.
2. Masking: no fixture customer name, and no text cell, is in the model text.
3. Re-upload of the same bytes: the fake adapter's call count is unchanged, every column is auto, nothing is
   pending.
4. Gateway forced to fail (an adapter error and a timeout): the sent columns become "Needs your decision"; after
   the decisions, compute runs, every metric carries its source, the narrative is unavailable, and the Dashboard
   renders the metrics with S17.
5. Fixture 3 cites sheet rows from 4 upward. Detection is right on sample_data/ and on the three fixtures.
6. Compute is refused while an AI or unsure row is pending. The reason stays selected for the next correction.
   Typed text causes no API call.
7. Delete: a wrong name is refused; the right name leaves no document in any collection.
8. Banner: only the three kinds; each appears and clears on its rule.
9. Reconciliation: the window total decides the blocker. A month above 2%, with the total under 2%, is in the
   evidence table and not in the banner. Every row cites its rows. With no P&L there is no section and no blocker.
10. "Other" note: each refusal case in §9; a kept note that quotes a header, and one whose header contains a cell
    word; a note quoting a header with a digit refused. The code stays selected and the note clears.
11. Mapping table (MappingWizard.test.jsx): the headers of S23 and no "Your decision"; "Mapped by" has the values of
    S24; the confidence cell is never a dash (rule row, AI, saved, no proposal, decided, unused: S9); the rows come in
    the order of §4.4; the detected line has no months text before the date column is confirmed (S5); the info box
    S25 is open, holds the four paragraphs word for word, sits above the first table and is one box for several files.
12. Delete dialog (AuditHub.test.jsx; test_chat_upload.py): title and body of S18 with the name in bold; Delete stays
    disabled for another case and a partial name, enabled with surrounding spaces; S18b shows under the box on a
    mismatch only after a pause of about a second or on blur, never while typing, and not on an empty box; the server refuses the same texts and deletes nothing.
13. Banner (test_chat_upload.py): S16a with no revenue file, S16d with a revenue file whose mapping is not confirmed,
    nothing once it is; one blocker of the kind, never two.

## 11. Screen wording (S1–S22 approved 2026-10-08; S5, S9, S15, S16a, S18 amended and S16d, S18b, S23–S25 added the same day)
| Id | Where | Text |
|---|---|---|
| S1 | text reply | This window accepts files and mapping confirmations. (as given) |
| S2 | explainer, consent ticked | Mapping is done by rules first. Where rules cannot decide, the AI sees only those columns' headers, up to 3 example numbers or dates per column and a pattern for text columns – never your full file and never a name – and you confirm those columns. |
| S3 | explainer, consent unticked | Mapping is done by rules only: AI-assisted reading is off for this audit. You map the columns the rules cannot decide. |
| S4 | drop zone | Drop files here or use the paperclip. Required: revenue by customer (monthly, 24–36 months). Also useful: CRM export, P&L. Board decks go to the Deck panel. .xlsx or .csv only. |
| S5 | bubble head | Detected: Revenue lines · 1,240 rows · 24 months (Jan 2023 – Dec 2024). Before the date column is confirmed the months are left out: "Detected: Revenue lines · 1,240 rows". |
| S6 | unknown type | Could not tell what this file holds. Pick its type: Revenue lines / CRM deals / P&L (monthly). |
| S7 | refused file | This window takes .xlsx and .csv files. Decks go in the deck panel below. |
| S7b | refused .xls file | Save as .xlsx or .csv and upload again. |
| S8 | replace | A revenue file is already loaded ({file}). Replace it? [Replace] [Keep current] |
| S9 | confidence cell | A rule row: its number, 100 · or, when the fit lowers it: 0 · 0 of 20 values are numbers. An AI suggestion, or a column with no proposal, until decided: needs confirmation (decided: confirmed). A saved mapping: reused. A column the rules found no field for: 0. Never a dash. |
| S10 | buttons | Confirm · Correct · Not used (n) |
| S11 | reason codes | Header is misleading · Another column is the right one · Values do not fit this field · Wrong kind of date · Column not needed · Other (opens S20) |
| S12 | model failed | AI reading unavailable – these columns need your decision. |
| S13 | status line | Ready for compute · {n} columns wait for your decision · Required field not mapped: {field} |
| S14 | same file | Same file as before: saved mapping v{n} applied. |
| S15 | AI row | AI suggestion – confirm (the column "Mapped by", S24; amended 2026-10-08, it was "AI suggestion, not verified"). The label "AI suggestion, not verified" stays on model-read claim values, rule 18. |
| S16a | banner | Revenue file missing: upload and map it to compute metrics. (Only when no revenue file exists; shown from the first Calculate, §16.) |
| S16d | banner | Revenue file uploaded – confirm the mapping to compute metrics. (A revenue file exists and its mapping is not confirmed; always shown, in every tab and on every day: a stored file means Calculate was pressed.) |
| S16b | banner | Top-5 claim contradicted: {claim type} {claimed} vs {observed} observed ({deck}, {page}). |
| S16c | banner | Revenue file and P&L differ by {x}% over {first}–{last} ({file total} vs {P&L total}). |
| S17 | narrative failed | Today's text, unchanged: "Narrative could not be generated. The computed metrics below are unaffected — they come from the calculation engine, not the narrative." |
| S18 | delete dialog | Title: Delete {company name}? Body: Deleting this audit with its files, mappings and results cannot be undone. Type **{company name}** to confirm. (the name in bold, in both; body reworded 2026-10-09, George) |
| S18b | delete dialog | Name does not match (under the box, after about a second without typing or when the box loses focus, while the trimmed text is not empty and is not the name exactly) |
| S19 | audit list | Title: Usage totals (all audits) (folded). Explainer under the title: "Totals across all audits on this server since counting began. Counts and costs only — no file names, figures or company names. Kept to improve the app." Content: files uploaded and refused by type; columns by rules, saved, AI, corrected (by reason); compute runs and failures; evidence labels as five named counts in a row, Verified · Unverified · Unsupported · Contradicted · Metrics missing; analyst changes; median days from first upload to export; tokens and cost by step (cost to 2 decimals); "Other" notes, newest first (at most 50). |
| S20 | "Other" box placeholder | Why? Up to 60 characters; no file names, figures or names. |
| S21 | "Other" note refused | Leave out file names, figures and cell values: this note is kept with the usage counts. |
| S22 | Diagnostics section | Revenue reconciliation · columns: Month · Revenue file · P&L · Gap · Gap % · last row: Window total |
| S23 | mapping table headers | In your file · Means · Confidence · Mapped by (the fifth column, the buttons, has no header). The label "Your decision" is removed. |
| S24 | "Mapped by" values | Rules · AI suggestion – confirm · You · Saved from earlier upload. A column the rules and the model left without a proposal reads "You – choose" until the analyst decides it. A row the analyst confirmed or corrected reads "You". |
| S25 | info box | Title: Why this step matters. A collapsible box, open by default, above the first mapping table of the page (one box, not one per file). Text, word for word, four paragraphs: "Every figure in this audit depends on how the columns are interpreted. If a column is mapped incorrectly—for example, bookings are treated as revenue, or an invoice date as a service date—the resulting calculations may look correct but be wrong." / "The app suggests a mapping for each column and indicates its confidence level. High-confidence mappings are accepted automatically, but you can change them. Low-confidence mappings appear at the top of the table and require your review." / "No calculations begin until all required columns are confirmed." / "Your choices are saved with the audit and automatically reused if you upload the same file again." |

## 12. Decisions of 2026-10-08
| Q | Question | Decision |
|---|---|---|
| Q1 | What the model sees for mapping, and where it is kept | A: the rule-16 shape for the undecided columns, built from the first 20 rows, handed over in memory; nothing stored but the hash (§4.2) |
| Q2 | Usage store and totals | A: counters on the audit document; totals as a section of the audit list (§7) |
| Q3 | `MAPPING_THRESHOLD` | 80 |
| Q4 | Banner rules | The window total of file against P&L, at most the last 12 months, above 2%; the revenue file is the required file; a beat counts as Contradicted. Per-month gaps are shown in the reconciliation evidence table, never as a blocker (§6.2) |
| Q5 | The model's own confidence on screen | No: the schema is unchanged |
| Q6 | Wording | S1–S19 approved, with S2 as proposed and the existing S17. "Other" gets a free-text box of up to 60 characters, kept with the counters, with no file names or values (§4.3, §7) |
| — | Amendment the same day (UI and labelling, George) | Delete dialog with the name in the title and in bold, exact case-sensitive match, S18b; mapping table headers and "Mapped by" (S23, S24), no "Your decision"; confidence cell never a dash (S9); row order (§4.4); the banner says what is left to do when the file is uploaded (S16d); months of the detected line only once the date column is confirmed (S5); the info box S25. The wording not given in the request was chosen under rule 19 (§13) |
| — | Follow-up the same day | Approved: the reconciliation section on Diagnostics, with the banner link; the S19 extension; S20–S22. Column headers are allowed in "Other" notes; digits, cell text, file names, the company and client names stay refused (the engagement reference was removed on 2026-10-08); logs still never hold header text or notes (§4.3, §8, §9). S21 reworded to match ("…file names, figures and cell values…"); spec final |
| — | UI and claims fixes from live testing (2026-10-08, George) | S4 reads: "Drop files here or use the paperclip. Required: revenue by customer (monthly, 24–36 months). Also useful: CRM export, P&L. Board decks go to the Deck panel. .xlsx or .csv only."; own date picker for every date, 2000 to 2100 (§2); the engagement reference is removed (§2); the deck panel's changes are in deck-parser.md §2 and §6 and claim-matching.md §2 and §6 |
| — | UI and parser fixes from the Zero2Hero audit (2026-10-09, George) | S18 body reworded; the five set-up fields move from the creation dialog to the top of the mapping page with one help line each (§2); typed dates and a calendar that keeps its side (§2); claim rows show the converted figure only, the rate and its date on hover (deck-parser.md §6, claim-matching.md §2); "no date" in the Period column; bars take the year label under them (deck-parser.md §2); every refused save names the field and the reason |

## 13. Decided (engineering, rule 19)
- Every background request (the deck AI-reading status, the blockers, the usage totals) stops when the audit is deleted
  or the page is left: a 404 or any error on such a poll is caught, the poll ends, nothing is shown, and no state is
  set after unmount. Tested in DeckPanel.test.jsx, Layout.test.jsx and AuditHub.test.jsx.
- Detection is Python only.
- An unknown file is held in the browser and nothing is stored.
- Files are sent one at a time.
- Typed text never leaves the browser.
- Unused columns need no click; only a column mapped into the engine needs rules confidence or a click.
- The reason stays selected for the page session; an "Other" note clears after each correction.
- "No file names or values" in an "Other" note is enforced on the server by refusal, not by rewriting. Headers are
  set aside before the cell-text check, so quoting a header never trips it; a digit is refused everywhere.
- The model budget is 20 s.
- The header row is found in the first 10 rows, and rows above it are dropped.
- Duplicate headers tie.
- Customer-alias columns are always profile-only.
- Delete takes the confirmation in the body.
- Usage figures that already exist (tokens, cost, labels, changes) are read, not copied.
- Totals have no per-audit rows.
- The CLAUDE.md lines are final in §6.4 and go in, word for word, with the first implementation commit.
- Amendment of 2026-10-08 (rule 19, engineering): a column with no proposal reads "You – choose" in "Mapped by" and
  "needs confirmation" in Confidence until decided; a decided AI suggestion or no-proposal column reads "confirmed" in
  Confidence; a rules-unused column scores 0, not a dash; a saved mapping reads "reused" even when the new data lowered
  it and it waits for a click; the info box is one per page, above the first table; the delete match trims surrounding
  whitespace first (George, later the same day), and S18b waits for a one-second pause or blur; the banner keeps one kind
  (`revenue_file_missing`) with the text of the case that applies, so the three-kind rule of §6.2 holds.

## 14. Files
- New: `backend/app/column_rules.py` (header row, value fit, confidence, detection; pure),
  `frontend/src/components/UploadChat.jsx`, `frontend/src/components/BlockerBanner.jsx`,
  `backend/tests/test_chat_upload.py`, `backend/tests/fixtures/messy/*.csv`, the frontend tests in §10.
- Changed: `backend/server.py` (upload, decisions, delete, blockers, usage, `_row` offset), `backend/growth_engine.py`
  (`revenue_reconciliation` with `by_month`), `backend/app/structures/__init__.py` (column_mapping_input: undecided columns, 20 rows,
  customer columns), `backend/app/llm/gateway.py` (lock release on cancellation, if the test shows it is needed),
  `backend/tests/test_gateway_data_boundary.py`, `frontend/src/pages/MappingWizard.jsx`,
  `frontend/src/components/Layout.jsx`, `frontend/src/pages/AuditHub.jsx`, `frontend/src/pages/Diagnostics.jsx`
  (reconciliation section), `frontend/src/lib/api.js`, CLAUDE.md
  (§6.4), the demo seed and the tests that delete audits.
- Unchanged: docs/architecture.md.

## 15. Amount columns named turnover or volume (amended 2026-10-09, George)
If the header of a column mapped to an amount field (revenue file `amount`, P&L `revenue`, CRM `amount`) contains
turnover, volume, GMV or TPV, the column waits for one answer, asked once: "Is this money the company earned (revenue)
or the value of transactions processed (volume)?" Until answered it counts as pending, so the mapping does not save.
Revenue: the column maps as before. Volume: the column is Not used and the engine never reads it; the answer
(`money_kind`) is saved with the mapping version and reused for the same file and the same headers. Closed codes only
(revenue, volume): no free text. Decision `{column, action: "confirm", money_kind}`.

## 16. Calculate, the revenue banner and the FX rates (amended 2026-10-09, George)
- A file dropped in the chat (or picked with the paperclip) is only attached: it shows as an attachment, "attached – not read
  yet", with a remove button. Nothing is read, mapped, stored or computed until the analyst presses Calculate. The drop
  zone stays after a drop. Calculate reads the attached files one at a time in drop order, then, if a revenue file is loaded
  and no column waits for a decision, computes the metrics; otherwise it stops and the page says what is left.
- Banner (supersedes the "every audit view" timing of §6.2 and rule 21 for the S16a wording only): "Revenue file missing" (S16a)
  is not shown when the screen opens. It shows after Calculate has been pressed (kept per audit for the browser tab's session;
  it is never reset by a compute) and the server still reports it, on every audit view, until a file is uploaded. "Revenue file
  uploaded – confirm the mapping" (S16d) always shows when the server reports it: a stored file means Calculate was pressed, here
  or in another tab. The flag is set after the last attached file is read, and not while a file still waits for its type or a
  replace answer, so "missing" never shows while a file is being asked about; the banner is refreshed once after the last file
  and again when that answer is read. With no revenue file, one line follows S16a: "The
  revenue file is the only required file. Every metric in the audit (ARR, NRR, churn, CAC payback) is computed from it; without
  it nothing can be calculated or verified." The other two kinds are unchanged. The server's `/blockers` is unchanged.
- FX rates belong to the audit (`audits.fx`, PUT /api/audits/{id}/fx), not to the revenue file. They apply to the uploaded files
  and to the deck claims, need no file, and survive a replaced revenue file. Rates saved with a revenue file before this change
  are still read, under the audit's own rates. Cause found: a re-upload wrote `fx: {}` over the saved rates, and rates could
  only be entered once a revenue file was loaded.
- The header Compute Metrics button is Calculate: it reads the attached files first, then computes under the same conditions. It is
  enabled while a file is attached.
- Saving the FX rates marks a computed audit's metrics stale and recomputes it, as the existing rule does for any input the engine
  reads (PUT /fx). This is the one computation that does not wait for Calculate; "nothing is computed until Calculate" covers files
  attached in the chat. The deck panel reads the claims again after a save, so converted figures replace "FX rate needed". PUT /fx
  saves the whole set the screen shows: rates an older version saved with the revenue file move to the audit and the file's copy
  is cleared, so a removed rate stays removed.
