# Spec: Chat-style upload and column mapping
Status: Final (2026-10-08); decisions applied (§12); amended 2026-10-08 for the mapping-screen wording, the delete dialog
and the banner (§12, §13, S5, S9, S15, S16a, S16d, S18, S18b, S23–S25), and 2026-10-09 for §15 and §16, and 2026-10-11 for §17 (claims list and parser), and 2026-10-16 for §19 (file type, every sheet, wide tables, units and the miss message) and §20 (forecast tables read as claims, issue #114), and 2026-10-17 for §21 (deal ID and stage, and a rule confidence of exactly 80) and §22 (every column to the model, and mapping calls
outside the daily spend cap), and the same day for the CRM required fields (§4.1) and the CRM fields box (S29; crm-dedup-clustering.md §6). Location: docs/specs/chat-upload.md.
Replaces the content of the MappingWizard page. Supersedes in part docs/specs/llm-structure-reading.md §1 for
the column-mapping path only: which columns are sent, from how many rows and with which rule hint (§4.2), and, for a column
mapping, the daily spend cap of its circuit breaker (§4.2, 2026-10-17). Everything else in that spec stands, including the
rule-16 shape of what is sent and §9 (sent text is never stored).

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
Out: decks (the deck panel stays as it is, below the chat), data cleaning (a column the engine cannot read stays unreadable; the bubble says so), and any new metric on the
Dashboard.

The request as written crosses the frozen architecture in three places. This spec builds the in-architecture
version of each, as decided on 2026-10-08 (Q1 A, Q2 A):
| Request | Crosses | In-architecture version (decided) |
|---|---|---|
| Sample = headers + 20 masked rows, numeric values kept, names and IDs tokenised | Rule 16: per column, at most 3 sample values (numeric and date columns only) or a profile for text columns. The gateway already refuses more than 3 samples, and refuses text values (test_gateway_data_boundary.py) | The rule-16 shape, built from the first 20 data rows, for the undecided columns only. Every customer column, numeric IDs included, sends a profile only, so no tokens are needed (§4.2) |
| Masked sample stored as a MongoDB document `mapping_sample`; the gateway reads it from MongoDB | Rule 17 and docs/architecture.md "What is stored": model output and metadata, never sent text. llm-structure-reading.md §9: "Sent text is never stored". The Storage row lists every collection, and this would be a new one | The sample is built in memory by a pure function and handed to `gateway.read_structure`, as today; only its content hash is stored. The gateway still never reads the upload, and the boundary test enforces this |
| Usage log as its own collection; a totals page | The Storage row (every collection is listed) and the Frontend row (four pages) | Usage counters on the audit document (`audits.usage`), tokens and cost read from `llm_calls`, and totals as a section of the audit list (AuditHub) |

## 2. Screen
- The MappingWizard page keeps its route, its title and the header bar (Calculate). Below the header, at the top of
  the page, sit the audit's set-up fields (2026-10-09, George): Reporting currency, Target ARR, Target date, As-of month,
  Fiscal year-end and First quarterly review (2026-10-11, George: required, default the audit's creation date plus 90 days, editable; clearing it returns the default; it is stored as the audit's `ic_inputs.first_quarterly_review` and gives the date of every gate prefill), each with one line of help under it, then the FX settings (§16), then the chat panel: a pure white message
  list with the input bar at the bottom. The deck panel stays below the chat panel, unchanged. The page uses the existing
  light theme. The set-up fields save as they change (PUT /audits/{id}); clearing the As-of month sends an explicit null and returns it to the default, the Target date cannot be cleared; a refused save names the field and the reason.
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
  matters" (S25, above the first mapping table of the page only), then, for a CRM file, the info box "Fields used in this
  analysis" (S29, open by default), then the mapping table (§4). For a revenue file,
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
- Sheets and columns (amended 2026-10-16, §19): every sheet of a workbook is read; the best sheet for the role is stored and
  its name is shown in the mapping table. Columns before the first one that has a header or a value are dropped.
- Header row: among the first 10 sheet rows, the header row is the first row that fills at least half of the
  widest row's cells and holds no number other than a year. Rows above it (titles, blanks) are dropped and never
  stored. Header-like rows directly below it join the header stack, as today (at most 3). The file is read without
  a header (`header=None`), with short rows padded and blank lines counted, so a one-cell title row cannot break a
  CSV. Every stored row keeps its sheet row number, and `normalize` uses that number for `_row`, so citations name
  the real sheet rows. Today `_row` assumes the header is on row 1 and that there are no blank lines.
- Type (amended 2026-10-16, §19): the rules give each type a share, and the type with the unique highest share wins
  when that share is at least 80% (it was 50%). Revenue needs customer, date and amount, each header at 80 or more; CRM
  needs four of five signature columns (deal, created, closed or won, stage or status, owner); a P&L is the share of its
  fields the headers match, or two or three cost lines among the headers or the line labels. Headers and line labels are
  read with every run of punctuation as one space, the underscore included, as the mapping reads them (§21; 2026-10-17):
  `deal_id,created_date,close_date,stage,owner` is a CRM file at 100%, and a line `cost_of_sales` is a cost line. Measured
  the same day on sample_data/ and the fixtures in `backend/tests/fixtures/{mapping,messy}/` (12 files): no detected type
  and no share changed. Measured on sample_data/: 3
  of 3 files detected, at 100% (revenue), 80% (CRM, which has no owner column) and 100% (P&L), each against a lower
  share for the other two types. Months found are the distinct months of the date column: invoice date for revenue,
  close date for CRM, month for the P&L. Below 80, with consent, the model is asked once for the file's type (§19).
- Unknown (no type at 80 and no answer from the model: no consent, no prompt loaded, a failure, a timeout or "unknown"):
  nothing is stored. The bubble asks for the type (S6), and the browser sends the same file again with that `dtype`.
- A type that is already loaded: if the hash is the same, the bubble says S14 and there is no prompt. If the hash
  differs, the server stores nothing and answers 409 with the detected type; the bubble asks S8, and Replace sends
  the file again with `replace=true`.

## 4. Mapping rule
### 4.1 Step 1: rules (Python)
- Required fields (`FIELD_DEFS`): revenue customer id, invoice date, amount, currency; CRM deal id, created date, close date,
  stage; P&L month, S&M expense, revenue, cost of revenue. A file is ready for calculation when each is mapped (S13). The CRM
  amount is optional since 2026-10-17 (George; crm-dedup-clustering.md §6): no calculation reads it. It keeps its aliases, its
  numeric kind and the turnover/volume question (§15), and the field list shows it first among the optional fields, after the
  required ones.
- Header score: the existing `_score`, the best over a field's aliases (100, 80, 60, 40 or 30). A header that
  pandas de-duplicated ("Customer ID.1") is scored on its cell text, so duplicate headers tie. An underscore is
  punctuation: "deal_stage" is read as "deal stage" (§21).
- Deal ID (CRM, §21): a header containing stage, status or phase never maps to deal id, and neither does a column whose
  values are a small set of repeated labels (Won / Lost / Engaging / Prospecting). A column of unique codes whose header
  holds id, opportunity, deal or ref is the deal id candidate.
- Value fit: the share of the column's non-blank values, over all data rows, that the engine can read as the
  field's kind. For a date field, the date parser reads the value; a day/month order it cannot settle still
  counts as a date. For a numeric field, `pd.to_numeric` reads it. For currency, the value is three letters. A
  text field (customer, deal ID, stage, segment, revenue type, founder involved) accepts any non-blank value. A
  column with no non-blank value has a fit of 0.
- Confidence = round(header score × value fit). The rules propose one column per field, using the existing greedy
  `suggest_mapping` order.
- Auto-accepted: confidence above `MAPPING_THRESHOLD = 80` (Q3; a rule mapping at exactly 80 is unsure, §21), and no
  tie. These rows are shown with Correct and need no click. Measured on sample_data/: 16 of 17 columns score 100. "S&M Expense" scores 30 (the
  3-letter alias "s&m"), so it needs one Confirm.
- Unsure: at or below the threshold, or tied. A tie means two columns share a field's best score, or one column shares
  its best score between two fields. The rules' proposal is shown with Confirm and Correct.
- Undecided: a column with no proposal while a field of its type is still open; it needs a decision.
  A column with no proposal and no open field goes to "Not used".
- These states are the outcome when consent is off (the rules alone decide), and when the model cannot be read (§4.2).
  With consent, every column goes to step 2 and §4.2 decides (2026-10-17, §22).

### 4.2 Step 2: the model (only with consent; amended 2026-10-17, §22)
- Every upload with consent sends every column of the sheet to the model in one call (George, 2026-10-17). Not sent: a
  summary table (§19), and a file a saved mapping applies to (§5: the same bytes, or the same headers), which makes no call.
  The column-mapping text (`structures.column_mapping_text`) uses the first 20 data rows and is redacted as today: the
  header stack (at most 3 rows), up to 3 samples for each numeric or date column, and a profile for each text column,
  then one hint line per column the rules propose, `c5 rule: amount 60`: the field and the rules' confidence. The
  gateway refuses a hint that is not one field of the closed list and a confidence from 0 to 100, once per column
  (`bad_hint`). Columns keep their sheet positions (`r1c5`), so replies map back. Every column whose header matches a
  customer alias at any score, and every column tied for `customer_id`, sends a profile only, even when its values are
  numbers.
- The text never touches MongoDB. `llm_structures` and `llm_calls` keep the reply, its content hash, tokens and
  cost, as today.
- A column-mapping call is exempt from the daily spend cap (`guards.check_spend_cap`). It is logged in `llm_calls` and
  counted in the usage like any call, and its cost counts in the day's spend that the cap checks for every other call.
  Deck structure, file-type (§19) and narrative calls stay under the cap. The lock and the per-audit token cap still apply.
- The outcome, per column:
  - A rule confidence of 100, untied, wins: the column is auto (Rules), whatever the model says.
  - A column the model maps to a field takes its confidence from the rules' formula on the model's field (header score ×
    value fit, §4.1), so the number is Python's. It needs no click (auto, Mapped by Rules, its number shown) when the
    rules proposed the same field, untied, above 80; exactly 80 waits (§21). Otherwise (80 or below, a tie, or another
    field than the rules') it is an AI suggestion with Confirm and Correct, and its Confidence cell reads "AI suggestion –
    confirm", not the number (S9; George, 2026-10-17).
  - A column the rules map and the model leaves out is unsure, with the rules' proposal and confidence. When the model
    gave that field to another column, it needs a decision instead.
  - A column neither side maps goes to "Not used".
  Python checks every proposal against the fields of the file's type and the sent cells (`proposed_mapping`, as today);
  a proposal for a column or a field a rule 100 holds is dropped. The output schema stays as it is (Q5).
- A budget of `MAPPING_AI_SECONDS = 20` covers the call (`asyncio.wait_for`). On a timeout, provider error, token cap,
  refusal or parse failure, the rules' outcome stands (§4.1) and the columns they left unsure or undecided become "Needs
  your decision"; the bubble shows S12. The per-audit lock is released on cancellation, and a test covers this. Nothing
  waits for the model.
- Cache by file hash, as before: the same bytes again apply the latest saved version with no rules, model or click (§5),
  and the gateway serves a stored reply for the same text, prompt, model and schema.

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
auto-accepted 100s come last. A row with no score shown (an AI suggestion, whose number stays off screen, §4.2; a
column with no proposal; a row the analyst decided) counts as the lowest. Rows of equal confidence keep the order of the file. The order follows the state, so a
row moves down when its click is made. Unused columns stay in the "Not used" fold.

## 5. Saved mapping
- A version is stored in `column_mappings` with: audit id, type, file hash (sha256 of the bytes), header key (as
  today), version number, field→column mapping, and per column its source, confidence, decision and reason code.
  Earlier versions are kept. Delete audit removes all of them.
- Re-upload with the same file hash: the latest version is applied, with no rules run, no model call and no
  clicks, and the bubble says S14.
- Same headers but a different hash: the latest version counts as confidence 100 for each column it mapped,
  scaled by that column's value fit on the new data, and is accepted at 80 or more (§21 is for rule mappings only).
  No model call is made.

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
file missing") is held back until the first Map; S16d and the other two kinds show whenever the server reports them.
| Kind | Rule (decided 2026-10-08, Q4) | Text |
|---|---|---|
| required file missing | the revenue file (the only file marked required) is not uploaded (S16a), or is uploaded and its mapping is not confirmed (S16d); one blocker of this kind, with the text of the case that applies | S16a or S16d |
| top-5 claim contradicted | a claim-register row ranked 1–5 has evidence label Contradicted, a miss (the label as claim-matching.md §4 defines it; a beat is Verified since 2026-10-13, George) | S16b, with the row's citation |
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
  Amended 2026-10-09 (§16): the revenue-file blocker reads S16a from the first Map (§16; before, the first Calculate) and S16d at all times; the line in
  CLAUDE.md carries that wording. Amended 2026-10-13 (claim-matching.md §4, George): a beat outside tolerance is Verified, so
  the claim blocker is a miss only; the line in CLAUDE.md reads "(a miss)".
- Rule 22: "Delete audit requires typing the company name and removes every document of the audit in every
  collection, saved mappings and stored files included."

## 7. Usage counters (no file names, no values)
- `audits.usage` (Q2) holds: `first_upload_at`, `first_export_at` (the first xlsx export, which carries the IC
  memo), `last_screen` (mapping, dashboard, diagnostics, review or run, sent by each page on mount; any other value is refused);
  `files.uploaded` by type and `files.rejected` by extension; `columns` mapped by rules, saved mapping, the model's
  proposal, confirmed and corrected, with a count per reason code; `other_notes`, the kept "Other" notes (§4.3) as
  `{note, at}`, at most 50 per audit with the oldest dropped first, and with no column, file or field beside them;
  `steps.compute` runs and failures by error type; and `steps.mapping_ai` by status.
- Computed on read, never stored: tokens and cost per step (from `llm_calls`); evidence-label counts (claim
  register labels, and the metrics with status Missing); analyst changes (mapping corrections, plus claims edited
  or rejected, plus register metric or segment overrides).
- `GET /api/usage/totals` returns sums across audits, the median time from first upload to first export, and the
  50 newest "Other" notes across audits. It has no per-audit rows, names or ids. It is owner-token only (a tester gets
  404); no audit screen shows it any more (S19 removed 18 Oct 2026, usage-and-allowance.md §1 and D3).
- Delete audit removes the counters with the audit (§6.3).

## 8. Privacy
There is no admin view of files, audits or results. An "Other" note may contain column header text (§4.3); it is
kept only in `audits.usage.other_notes` and shown only in the usage totals. Logs carry model JSON output and
metadata only: never raw rows, sample text, header text, file names, company names, typed text or "Other" notes,
whether or not the note quotes a header. New log lines carry codes only (type, status, error type, reason code).

## 9. Data boundary (rule 14)
`test_gateway_data_boundary.py` gains these assertions, and each new test is first shown failing on a deliberate
violation:
- The column-mapping text holds every column of the sheet (amended 2026-10-17, §22; before, only unsure and undecided
  columns), built from at most 20 data rows. A hint line holds one field of the closed list and a confidence from 0 to
  100, once per column; anything else is refused (`bad_hint`).
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
Expected outcomes are under threshold 80. The third fixture also runs as an .xlsx file built in the test. Since 2026-10-17
(§22) every column is sent with consent; the last column names the columns the rules leave open.
Tests (backend: `test_chat_upload.py`; frontend: `MappingWizard.test.jsx`, `Layout.test.jsx`, `AuditHub.test.jsx`):
1. For each fixture, the rules map exactly the clean columns, and every column is in the model text with the rules' hints
   (§22; before, only the ambiguous ones).
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
| S2 | explainer, consent ticked | The model reads every column header and a masked sample to propose the mapping. When the rules cannot tell what a file holds, the AI also sees its sheet names and the title rows above each table. (First sentence given by George on 2026-10-17, §22, in place of "Mapping is done by rules first. Where rules cannot decide, the AI sees only those columns' headers, up to 3 example numbers or dates per column and a pattern for text columns – never your full file and never a name – and you confirm those columns."; last sentence added 2026-10-16, §19, its "which can contain the company name" clause removed the same day, because the company name is masked.) |
| S3 | explainer, consent unticked | Mapping is done by rules only: AI-assisted reading is off for this audit. You map the columns the rules cannot decide. |
| S4 | drop zone | Drop files here or use the paperclip. Required: revenue by customer (monthly, 24–36 months). Also useful: CRM export, P&L. Board decks go to the Deck panel. .xlsx or .csv only. |
| S5 | bubble head | Detected: Revenue lines · 1,240 rows · 24 months (Jan 2023 – Dec 2024). Before the date column is confirmed the months are left out: "Detected: Revenue lines · 1,240 rows". |
| S6 | unknown type | Could not tell what this file holds. Pick its type: Revenue lines / CRM deals / P&L (monthly). |
| S7 | refused file | This window takes .xlsx and .csv files. Decks go in the deck panel below. |
| S7b | refused .xls file | Save as .xlsx or .csv and upload again. |
| S8 | replace | A revenue file is already loaded ({file}). Replace it? [Replace] [Keep current] |
| S9 | confidence cell | A rule row: its number, 100 · or, when the fit lowers it: 0 · 0 of 20 values are numbers. An AI suggestion until decided: AI suggestion – confirm, never its number (George, 2026-10-17, §22; decided: confirmed). A column with no proposal, until decided: needs confirmation (decided: confirmed). A saved mapping: reused. A column the rules found no field for: 0. Never a dash. |
| S10 | buttons | Confirm · Correct · Not used (n) |
| S11 | reason codes | Header is misleading · Another column is the right one · Values do not fit this field · Wrong kind of date · Column not needed · Other (opens S20) |
| S12 | model failed | AI reading unavailable – these columns need your decision. |
| S13 | status line | Ready for calculation · {n} columns wait for your decision · Required field not mapped: {field} |
| S14 | same file | Same file as before: saved mapping v{n} applied. |
| S15 | AI row | AI suggestion – confirm (the column "Mapped by", S24; amended 2026-10-08, it was "AI suggestion, not verified"). The label "AI suggestion, not verified" stays on model-read claim values, rule 18. |
| S16a | banner | Revenue file missing: upload and map it to compute metrics. (Only when no revenue file exists; shown from the first Map, §16.) |
| S16d | banner | Revenue file uploaded – confirm the mapping to compute metrics. (A revenue file exists and its mapping is not confirmed; always shown, in every tab and on every day: a stored file means Map was pressed.) |
| S16b | banner | Top-5 claim contradicted: {claim type} {claimed} vs {observed} observed ({deck}, {page}). |
| S16c | banner | Revenue file and P&L differ by {x}% over {first}–{last} ({file total} vs {P&L total}). |
| S17 | narrative failed | Today's text, unchanged: "Narrative could not be generated. The computed metrics below are unaffected — they come from the calculation engine, not the narrative." |
| S18 | delete dialog | Title: Delete {company name}? Body: Deleting this audit with its files, mappings and results cannot be undone. Type **{company name}** to confirm. (the name in bold, in both; body reworded 2026-10-09, George) |
| S18b | delete dialog | Name does not match (under the box, after about a second without typing or when the box loses focus, while the trimmed text is not empty and is not the name exactly) |
| S19 | audit list | **Removed 18 Oct 2026 (usage-and-allowance.md §1).** Was: title (folded): "Your usage" for a tester token; "Usage totals (all testers)" when the server answers `scope: "all"` (the owner token), George 15 Oct 2026; the explainer reads "Totals for your audits since counting began." for a tester and "Totals across all testers since counting began." for the owner token, then, for both: "Counts and costs only — no file names, figures or company names. Kept to improve the app." (George, 15 Oct 2026). Explainer under the title: as just given. Content: files uploaded and refused by type; columns by rules, saved, AI, corrected (by reason); compute runs and failures; evidence labels as five named counts in a row, Verified · Unverified · Unsupported · Contradicted · Metrics missing; analyst changes; median days from first upload to export; tokens and cost by step (cost to 2 decimals); "Other" notes, newest first (at most 50). |
| S20 | "Other" box placeholder | Why? Up to 60 characters; no file names, figures or names. |
| S21 | "Other" note refused | Leave out file names, figures and cell values: this note is kept with the usage counts. |
| S22 | Diagnostics section | Revenue reconciliation · columns: Month · Revenue file · P&L · Gap · Gap % · last row: Window total |
| S23 | mapping table headers | In your file · Means · Confidence · Mapped by (the fifth column, the buttons, has no header). The label "Your decision" is removed. |
| S24 | "Mapped by" values | Rules · AI suggestion – confirm · You · Saved from earlier upload. A column the rules and the model left without a proposal reads "You – choose" until the analyst decides it. A row the analyst confirmed or corrected reads "You". |
| S25 | info box | Title: Why this step matters. A collapsible box, open by default, above the first mapping table of the page (one box, not one per file). Text, word for word, four paragraphs: "Every figure in this audit depends on how the columns are interpreted. If a column is mapped incorrectly—for example, bookings are treated as revenue, or an invoice date as a service date—the resulting calculations may look correct but be wrong." / "The app suggests a mapping for each column and indicates its confidence level. High-confidence mappings are accepted automatically, but you can change them. Low-confidence mappings appear at the top of the table and require your review." / "No calculations begin until all required columns are confirmed." / "Your choices are saved with the audit and automatically reused if you upload the same file again." |
| S26a | bubble, under the head | Type: {Revenue lines / CRM deals / P&L (monthly)} ({by rules / AI suggestion / your choice}) and a Change button that offers the other two types (2026-10-16, §19). |
| S26b | mapping table caption | Sheet "{sheet}" · header on row {n} |
| S26c | bubble, units | Title rows say {EUR }thousands: money figures are multiplied by 1,000. |
| S27 | a miss | Could not read this file as {type}. Missing: {fields}. It looks like {a forecast or summary table: periods (years or quarters) run across the columns and each line is a metric / a table with months across the columns and one line per row / a table of {n} rows and {m} columns}. A "Show columns" link opens the rows. The status line reads "Required field not mapped: {fields}". |
| S26 | file got no answer | The file could not be read. Press Map to try again. (Added 2026-10-10: shown when an upload gets no answer from the server within 120 s or loses its connection; the file returns to "attached – not read yet".) |
| S28a | a miss with periods across the columns (§20) | Read as {N} claims from {sheet}!{range}. Default label: Unverified. ("1 claim" for one) and the link "Show claims" (George, 2026-10-16) |
| S28b | under S28a, over the cap (§20.2) | The table holds {total} claims; the first 60 by row order are read. |
| S28c | the Show claims list (§20.4) | One row per line, a checkbox each, ticked: the line as in the file, then each year and its value, then its cells. Under it the button "Save claims" (George, 2026-10-16; it was "Confirm"), off while no line is ticked |
| S28d | after Save claims (§20.4) | Saved {n} claims as Unverified. ("1 claim" for one) It is the file's status line (S13) from then on, in green (§20.5) |
| S29 | info box, CRM file | Title: Fields used in this analysis. A collapsible box, open by default, above a CRM file's mapping table (George, 2026-10-17, crm-dedup-clustering.md §6). Text, word for word, six paragraphs: "Match Created date, Close date, and Stage / status to calculate sales cycles and win rates." / "Segment is optional. If mapped (for example a plan tier or company size), the sales cycle is also shown per segment with its median, spread and deal count. If not mapped, only the overall sales cycle is shown." / "Founder involved is optional. If mapped, it must hold yes or no per deal (yes / y / true / 1, no / n / false / 0); the app then compares the win rate of deals with and without the founder. Values it cannot read are listed and left out. If not mapped, the founder comparison reads Missing." / "Deal ID is used to remove repeated rows: rows that share a deal ID with the same stage and dates (for example one row per product line) count as one deal, and the number of rows collapsed is reported under Worth flagging." / "Close date is also used for the quarter-end clustering check: the share of won deals closed in the last 10 days of a quarter, by the company's fiscal year-end (needs at least 20 won deals)." / "Amount can be mapped but is not used in any calculation." |

## 12. Decisions of 2026-10-08
| Q | Question | Decision |
|---|---|---|
| Q1 | What the model sees for mapping, and where it is kept | A: the rule-16 shape for the undecided columns, built from the first 20 rows, handed over in memory; nothing stored but the hash (§4.2) |
| Q2 | Usage store and totals | A: counters on the audit document; totals as a section of the audit list (§7) |
| Q3 | `MAPPING_THRESHOLD` | 80 |
| Q4 | Banner rules | The window total of file against P&L, at most the last 12 months, above 2%; the revenue file is the required file; a beat counts as Contradicted (superseded 2026-10-13, George: a beat is Verified, claim-matching.md §4). Per-month gaps are shown in the reconciliation evidence table, never as a blocker (§6.2) |
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
- 2026-10-16 (§19): `backend/app/column_rules.py` (every sheet, leading columns, wide to long, units, type rules, miss), `backend/app/structures/{__init__,redact}.py` (the file-type text), `backend/app/llm/{gateway,schemas,prompt_store}.py` (the `file_type` read and prompt), `backend/server.py` (ingest, the Change endpoint, units in `normalize`), `frontend/src/components/UploadChat.jsx`, `frontend/src/lib/{chatUpload,api}.js`, `backend/tests/fixtures/mapping/*.csv`, `backend/tests/{mapping_shapes,test_mapping_miss}.py`, `backend/tests/fixtures/prompts/file_type.md` (a stub).
- 2026-10-16 (§20): new `backend/app/forecast_claims.py` (pure), `backend/tests/test_forecast_claims.py`, `backend/tests/fixtures/forecast/*.csv`;
  changed `backend/app/column_rules.py` (first column and title currency of a sheet), `backend/server.py` (the view, the Confirm endpoint, the
  year-end re-read), `backend/app/claim_matching.py` and `backend/app/verdict.py` (the untested rows), `backend/app/decks/claims.py` (the type),
  `frontend/src/components/UploadChat.jsx`, `frontend/src/lib/{chatUpload,api,deckClaims,claimRegister,review}.js`.
- 2026-10-17 (§22): `backend/app/column_rules.py` (`apply_model`, `undecided`), `backend/app/structures/{__init__,redact}.py` (every
  column, the hint line and its check), `backend/app/llm/{gateway,guards}.py` (the cap exemption), `backend/server.py` (step 2),
  `frontend/src/lib/chatUpload.js` (S2, S9), `backend/tests/{test_chat_upload,test_gateway_data_boundary,test_mapping_miss,
  test_structure_reading,mapping_shapes}.py`, `frontend/src/pages/MappingWizard.test.jsx`.
- 2026-10-17 (§21): `backend/app/column_rules.py` (underscores, the deal id rules, the threshold), new
  `backend/tests/test_deal_id_rules.py`, `backend/tests/test_money_kind.py` (an 80 row now asks), `frontend/src/pages/Review.jsx` (a test id),
  `frontend/src/pages/{MappingWizard,Review}.test.jsx`.

## 15. Amount columns named turnover or volume (amended 2026-10-09, George)
If the header of a column mapped to an amount field (revenue file `amount`, P&L `revenue`, CRM `amount`) contains
turnover, volume, GMV or TPV, the column waits for one answer, asked once: "Is this money the company earned (revenue)
or the value of transactions processed (volume)?" Until answered it counts as pending, so the mapping does not save.
Revenue: the column maps as before. Volume: the column is Not used and the engine never reads it; the answer
(`money_kind`) is saved with the mapping version and reused for the same file and the same headers. Closed codes only
(revenue, volume): no free text. Decision `{column, action: "confirm", money_kind}`.

## 16. Map, Calculate, the revenue banner and the FX rates (amended 2026-10-09, George)
- A file dropped in the chat (or picked with the paperclip) is only attached: it shows as an attachment, "attached – not read
  yet", with a remove button. Nothing is read, mapped, stored or computed until the analyst presses Map. The drop zone stays
  after a drop.
- **Map** reads the attached files one at a time in drop order and maps them (rules, then the AI for the columns the rules
  cannot decide, then the confirmation list of §4). It never computes. It is enabled when at least one file is attached or
  loaded, and not while a press is being worked.
- **Calculate** computes the metrics. It is enabled only when the mapping is complete: a revenue file is loaded, no attached
  file is unread, and no column of any loaded file waits for a decision or has a required field unmapped. Otherwise it is
  disabled with the tooltip "Map the revenue file and confirm every column that waits for you first." The header button and the
  chat button are both Calculate and share one state: they are always both enabled or both disabled. A second press while a
  press is being worked does nothing.
- Banner (supersedes the "every audit view" timing of §6.2 and rule 21 for the S16a wording only): "Revenue file missing" (S16a)
  is not shown when the screen opens. It shows after Map has been pressed (kept per audit for the browser tab's session;
  it is never reset by a compute) and the server still reports it, on every audit view, until a file is uploaded. "Revenue file
  uploaded – confirm the mapping" (S16d) always shows when the server reports it: a stored file means Map was pressed, here
  or in another tab. The flag is set after the last attached file is read, and not while a file still waits for its type or a
  replace answer, so "missing" never shows while a file is being asked about; the banner is refreshed once after the last file
  and again when that answer is read. With no revenue file, one line follows S16a: "The
  revenue file is the only required file. Every metric in the audit – ARR (see glossary), NRR (see glossary), churn, CAC (see
  glossary) payback – is computed from it; without it nothing can be calculated or verified." (The abbreviations point to
  the glossary at their first use, George 2026-10-09.) The other two kinds are unchanged. The server's `/blockers` is unchanged.
- FX rates belong to the audit (`audits.fx`, PUT /api/audits/{id}/fx), not to the revenue file. They apply to the uploaded files
  and to the deck claims, need no file, and survive a replaced revenue file. Rates saved with a revenue file before this change
  are still read, under the audit's own rates. Cause found: a re-upload wrote `fx: {}` over the saved rates, and rates could
  only be entered once a revenue file was loaded.
- Saving the FX rates marks a computed audit's metrics stale and recomputes it, as the existing rule does for any input the engine
  reads (PUT /fx). This is the one computation that does not wait for Calculate; "nothing is read until Map" covers files
  attached in the chat. The deck panel reads the claims again after a save, so converted figures replace "FX rate needed". PUT /fx
  saves the whole set the screen shows: rates an older version saved with the revenue file move to the audit and the file's copy
  is cleared, so a removed rate stays removed.

## 17. Claims list and parser: Approve all, spacing, two categories, Acquisition channels (amended 2026-10-11, George)
The claims list and the deck parser are specified in deck-parser.md and claim-matching.md; this section amends them. The architecture is
unchanged. Challenge and deletions (rule 4): Approve all removes one click per claim, and nothing else is needed for it; the
Acquisition channels type is a copy of the Use of funds rules (Unverified, no VaS, no gate, out of the top 5) with its own cue and
line shape, so no new matching code is written; nothing is deleted.
- **Categories on screen.** The list order is now: 1 Revenue, ARR, MRR and bookings · 2 P&L items · 3 Customers, users, usage,
  retention and sales · 4 Hiring and roadmap · 5 Market size · 6 Unknown – choose type · **7 Acquisition channels · 8 Use of funds** · 9 Other.
  Use of funds leaves Other and has its own section, directly above Other, with the rules of deck-parser.md "Use of funds" unchanged
  (Unverified, no VaS, no gate, out of the top 5). Unknown (6) and Other (9) start collapsed; 7 and 8 start open.
- **Spacing.** Between two sections, a gap of about twice the old one (28 px, was about 14) with a light divider line (`#E5E7EB`) in the
  middle of it; none above the first section. The background stays white.
- **Approve all.** A button "Approve all" in the header row of every open section and another after its last claim. It approves every
  claim of that section with status "To review". It is off when the section has none. One call per click:
  `POST /api/audits/{id}/decks/candidates/approve-all` `{group, deck_id?}` (`group` is the number above; `deck_id` is the deck tab, left out
  under All). The server approves each claim as a single Approve does (status "approved", or "edited" for a claim that carries the parser's
  values under `parsed`), so the register and the CSV record the same thing. It skips, and leaves "To review": a turnover claim whose Revenue /
  Volume answer the analyst has not given, a claim whose type is still to be chosen (Other, Unknown: a single Approve refuses it too), and a
  claim whose save fails. Reply: `{approved, skipped, approved_ids, skipped_ids, open_definition}`. Toast, word for word: "Approved X claims, Y skipped (need
  Revenue / Volume or failed to save)" ("1 claim" for one). The log line holds the run, the group number and two counts, nothing else
  (boundary test, rule 14). Amended 2026-10-14 (claim-matching.md §4.1): a claim with an open Definition check is approved like any other, and
  counted apart in the reply as `open_definition` (not in `skipped`): the toast adds ", Y with open definition check" when Y is
  above 0, and on the upload page, which cannot answer it, " – answer on the review screen" after it.
- **Acquisition channels** (stored `acquisition_channels`): the figure per platform on a user-acquisition slide, such as a funnel listing social
  platforms, each with a number in brackets. Parser trigger: the slide or page needs a cue, as whole words in any case: acquisition,
  acquisition channel(s), channels, funnel, traffic source(s), user acquisition. It counts in the slide's title, in a heading or a chart title (a
  short line with no figure and at most 3 other words, above the first platform line, not starting with a bullet, dash or asterisk) and in a table's
  header row; body text and footnotes never carry a cue. Without a cue the platform counts stay as before (typed by their heading if it names a type,
  else Other, and the model's reading keeps labelling them `other`). Each platform line is one claim: the whole line is a name and one plain
  number in brackets ("Telegram(30K)", "Facebook (12,500)", "YouTube [1.2M]"), with or without K, M or B; a bracket holding a currency, a percentage,
  a word, a date or a range is no channel figure. Metric "Acquisition channels", `channel` = the platform name (shown under the type in the
  list), value = the number in brackets, unit "count", no currency, no period. Two platforms with the same number are two claims; the same
  platform with the same number twice is one claim with both sources.
- Acquisition channels in the register: Unverified, reason "acquisition channels: a count per platform, no engine metric to test it against",
  no metric, gap, VaS or gate, ranked after every other claim (with Use of funds), and out of the top 5, the banner, the replace dropdown and the
  verdict. The platform name is deck text: it stays on the candidate and in the list, and never reaches the register row, a log or the gateway.
- Type dropdowns. "Acquisition channels" is in the Type list of the edit form and of Add claim (not Use of funds, as before). Choosing it makes the
  figure a count with no currency. Add claim then asks for the platform (required, up to 40 characters) in place of the metric tested; the server
  refuses a metric for this type and a platform for any other.
- Glossary: "Acquisition channels – claims about how many users, visits or followers each channel brings (a social platform, a referral source), one
  claim per platform. They are not tested against the data: always Unverified, with no value at stake or gate, and never in the top 5." (frontend
  glossary.js and backend formatting.py, kept equal by a test).
- Out of scope (decided by George, 2026-10-11): the model's labelling (prompt, schema, cache keys) is untouched, so a funnel read from a chart or table
  structure still comes back `other`. No prompt change now; George tests the real Zero2Hero deck after import and comes back if p17 lands in Other.
- Decided (George, 2026-10-11): Use of funds, Acquisition channels and every other real category start open; only Other and Unknown start collapsed.
- Tests: `test_approve_all.py` (the endpoint), `test_deck_parser.py` (the cues and the line shape), `test_claim_matching.py`, `test_verdict.py`,
  `test_analyst_claim.py` (register, top 5, Add claim), `test_gateway_data_boundary.py` (the reason, the platform name and the log line),
  `DeckPanel.test.jsx` and `deckClaims.test.js` (buttons, toast, sections, spacing, forms).

## 18. Mapping summary on the review screen (amended 2026-10-14, George)
Replaces the flat "N columns mapped" count with a Show link and its list of every column. The Open mappings table above it is unchanged (columns that wait for a decision).
- Matched columns = every used column of every loaded file that does not wait for a decision. A matched column is **unsure** when the analyst has not decided it and its confidence is under 100, or its name in the file and the app's field name differ (compared lower case, letters and digits only: "S&M Expense" and "sm expense" are the same; "Amount (EUR)" and "amount" differ). A column with no score is unsure only by the name test.
- Top line, bold, green: "✓ {n} columns matched – nothing to do." With unsure columns it is "{n} columns matched – {k} to check." (bold, not green). "1 column" in the singular.
- Under it, the file type labels (Revenue · CRM · P&L, George 2026-10-14) as small grey chips: no file names, no extension, no counts.
- One row per unsure column, plain text: `{CRM | Revenue | P&L}  "{column}" read as {field}`, with two small buttons on the right. **Correct** confirms the proposal (the same decision as Confirm: `action: confirm`); the row leaves the list and the count drops. **Change** opens the field and reason dropdowns of §4.3 and sends `action: correct`. No icons, arrows or warning signs.
- "Show details", a plain text link, collapsed by default (it reads "Hide details" when open): per file, every matched column as `"{column}" read as {field}`.
- Layout: one font size, bold only on the top line, generous line spacing, no boxes or borders. Rows alternate page colour and 3–4% grey, both the unsure rows and the rows inside Show details.
- Tests: `Review.test.jsx` (headline, chips, unsure rows by confidence and by name, Correct and Change calls, collapsed details, alternating rows).

## 19. File type, every sheet, wide tables, units and the miss message (amended 2026-10-16, George)
Cause found (3 workbooks missed their mapping; shapes in `backend/tests/mapping_shapes.py`): (1) the revenue rules scored a CRM tracker as
revenue because "Account ID" scores 80 as a customer and "MRR EUR" scores 60 as an amount, and the type needed only half of the
fields; (2) the model runs only for columns the rules left `unsure` or `needs`, and a column in state `unused` (no proposal, or left out of
the model's reply, §4.2) shows "Rules", confidence 0 and is never sent; a mapping version that mapped nothing was saved (nothing
pending) and reused for the same headers, so no rules and no model ran again (§5). Architecture note: rule 16 and
docs/architecture.md now read "spreadsheet sheet names, title rows and header rows" (George, 2026-10-16), the same words as here and in
the boundary test.

Challenge (rule 4): needed, because three files could not be mapped and the screen gave no reason. Simpler: one message on a miss and rules
for the type, no second model call. Deleted first: the "first sheet only" rule, the 50% type threshold, and the reuse of a saved mapping that
maps nothing.

- **Reading.** Every sheet is read. Columns before the first one with a header or a value are dropped (no "Unnamed: n" rows for them). Per
  role the best sheet is stored: the one whose headers match most required fields at 80 or more, then the higher type share, then more
  rows, then the earlier sheet. Its name and header row show as the table caption (S26b).
- **Wide to long.** Three or more headers that are periods (2023, Q1:24, 2024 YTD, FY2024, H1 2024, Jan-24, 2024-01, 01/2024, dates) are melted into
  `Period` and `Value`, one row per number, each keeping the sheet row of its line; the other columns stay beside them. Only the first
  table of the sheet is read (a blank row followed by a row with no number ends it, as does a repeated period header). With three or more
  months only the months are kept and the column is `Date`; otherwise (years, quarters, years to date) the sheet is a summary or forecast
  table: `looks.shape` is `summary` and it is always a miss. A wide table with lines down the rows is not pivoted into a monthly P&L.
- **Units.** "EUR thousands", "EUR 000", "k EUR", "EURk", "(€k)", "in thousands", "'000" in the title rows above the header: the money
  fields (`amount`, `revenue`, `sm_expense`, `cost_of_revenue`) are multiplied by 1,000 when the engine reads the rows (`normalize`); the stored
  rows keep the file's own figures; S26c shows the note. Millions are not read.
- **Type, rules first.** §3. Header synonyms: headers are read with punctuation as one space ("Deal - ID", "*InvoiceDate"), and the synonyms of
  Stripe, Xero, HubSpot and Pipedrive exports were added to FIELD_DEFS (created, contact name, record id, deal stage ...). The type rules read
  the same way (2026-10-17): the CRM signature words and the cost lines are matched on each header and line label with every run of punctuation,
  the underscore included, read as one space ("created_date" is "created date", "cost_of_sales" is "cost of sales").
- **Type, the model, once per file.** Only when the rules give no type at 80, the audit has consent and the file's hash has no answer yet.
  The text, built in memory and never stored or logged: per sheet (at most 6) its name, the title rows above the header (at most 6 rows, cells
  cut at 200 characters), the header row (at most 40 columns) and the masked sample of §4.2 (3 numbers or dates per numeric or date column, a
  profile per text column; a wide sheet sends its header as written and the profile of its first column only). Nothing else: no data row text,
  no file name. Redaction is the one of §4.2 and the gateway runs it again (the client name becomes [redacted], addresses and phone numbers
  are masked, customer names take their pseudonyms, and the target company's own name becomes [redacted] in the sheet names, title rows and
  headers, so it never reaches the model in clear text; unit markers such as "EUR thousands" are left as written, and the x1,000 scaling reads
  the stored title rows, not the masked text). The reply is one closed word: revenue, crm, pnl or unknown (`FileTypeReply`). Its own prompt, `file_type` (prompt-store.md; the
  owner uploads it; until then no call is made and the analyst picks the type, S6). `llm_calls` rows carry `structure_type: "file_type"`.
  The answer is kept in `column_mappings` as `{audit_id, kind: "file_type", file_hash, file_type, saved_at}` and used again for the same bytes. A
  failure, a timeout (`MAPPING_AI_SECONDS`), no consent or "unknown" leaves the type to the analyst (S6). A log line holds codes only: the
  type, the source (rules, ai, you) and the status; never a sheet name, title or header.
- **Change.** The bubble shows the type and how it was found (rules, AI suggestion, your choice) and a Change button. `POST
  /api/audits/{id}/datasets/{dtype}/type {to, replace}` reads the stored sheet again as the new type (rules, then the model for the columns they
  cannot decide) and stores it under the new type; a type already loaded answers 409 as in §3 and needs `replace`. No model is asked what the
  file is.
- **A miss** is a file that cannot supply the type's required fields: a summary table, or at most half of the required fields mapped (proposals
  that wait for a click count as mapped). The bubble then shows S27 in place of the mapping rows, with "Show columns" to open them. The message
  holds closed words and counts only. A summary table is not sent to the model for its columns.
- **Saved mappings.** A saved mapping version that is itself a miss is not reused: the rules and the model run again for the file (§5).
- **"Read as claims"** was not built with this section; George decided it on 2026-10-16 and it is §20.
- **Tests.** `test_mapping_miss.py` (the three shapes, each rule, the units, the miss, the file-type call, Change, and one test per export layout
  in `backend/tests/fixtures/mapping/`: Stripe invoices, Xero invoices, HubSpot deals, Pipedrive deals, an accountant P&L with the header on row 5
  in EUR thousands, a wide monthly revenue table), `test_gateway_data_boundary.py` (rule 14: the file-type text, its refusals, no stored text, no log
  line, the closed reply), `MappingWizard.test.jsx` (type line, Change, caption, units note, miss message, S2).

## 20. Forecast tables read as claims (2026-10-16, George; issue #114)
Decided by George with the task (rules 19.1, 19.2, 19.3): a claim is one forecast line × one period; only plan lines count; the annual
figure is read; at most 60 claims per file; what is stored; the screen; no model call. This section amends claim-matching.md §4 and §6 for
these claims, as §17 did for Acquisition channels. The architecture is unchanged: the claims are `deck_candidates` rows in the table-row
shape of deck-parser.md §2 and use the register's untested path; no collection, component or boundary changes (docs/architecture.md stays).

Challenge (rule 4): needed, because a forecast table ends in the miss of §19 and its plan figures are lost unless the analyst types each one
with Add claim. Simpler: no new screen; the miss message gains one line and a checkbox list, storage is the deck's table row (one candidate per
line, its values by period), and the register treats the claims as it treats Use of funds. Deleted first: the "Not built" paragraph of §19.

- **20.1 What is a claim.** A file is read as claims when it is a miss (§19) with periods across the columns (`looks.shape` summary or
  monthly_wide). Only the first table of the stored sheet is read (§19, wide to long). A line is a row of that table; its label is its first
  column, as written. A claim is one plan line × one year. Plan lines are found by header synonyms, as in column_rules.py, over the label read
  as the headers are (punctuation as one space, a bracket's content left out), first match in this order:
  ARR (arr, annual recurring revenue) · MRR (mrr, monthly recurring revenue) · gross margin (gross margin, gross profit) · EBITDA (ebitda) ·
  bookings (booking, bookings) · revenue (revenue, revenues, net sales; the whole label sales or total sales) · cash balance (cash balance,
  closing cash, ending cash, cash at end of period or year, cash at year end, cash position, cash on hand, cash and cash equivalents; the whole
  label cash) · headcount (headcount, head count, fte, ftes, employees, team size) · installed units (installed units, installed base, units
  installed, installations) · customers (customer, customers, client, clients, subscribers). Each synonym counts as whole words. Not claims: a
  label with a cost word (cost, costs, cogs, expense, expenses, opex, capex, spend, marketing, payroll, salaries: the cost sub-lines), a change or
  a per-unit word (growth, yoy, cagr, change, variance, per, average, arpu, churn, churned, new, lost, added, flow, burn, deferred, ltv, cac,
  lifetime, retention), and a rate (a "%", or margin, ratio or rate outside "gross margin") on any line but gross margin. Turnover, GMV and
  volume are not revenue synonyms here: they are ambiguous (claim-matching.md §11). A gross margin line is a rate (unit %) when its label holds
  "%" or every value is between −1 and 1 (a fraction, read ×100); otherwise it is an amount and its type is gross profit.
- **20.2 Years, roll-up, cap.** A year column (2025, FY2025, 2025E) is read as stated; a year-to-date column never. A year with no column is
  rolled up from its quarters (4), halves (2) or months (12): a flow (revenue, bookings, gross margin as an amount, EBITDA) is the sum, read only
  when every part of the year is in the table; a balance or a count (ARR, MRR, cash balance, headcount, installed units, customers) is the
  year's last part, read when that part is in the table. A rate is read from year columns only. Months are grouped by the audit's fiscal
  year-end, a year named by the calendar year it ends in (deck-parser.md §2); a quarter or half label names its fiscal year. When the year-end
  changes, rolled-up month claims already saved are read again from the stored file under the new year-end. Claims are ordered by sheet row,
  then year; the first 60 are kept and the rest dropped, and the bubble says so (S28b).
- **20.3 What is stored, and where it shows.** Nothing until the analyst confirms: the list is computed on read from the stored file rows. On
  Save claims, one `deck_candidates` row per ticked line, in the table-row shape of deck-parser.md §2: `claim_type` (revenue for ARR, MRR, bookings
  and revenue; gross_margin or gross_profit; ebitda; cash; people; customers; `installed_units`, a new type shown "Installed units" and not offered
  in the type lists), `snippet` = the metric name as in the file (at most 300 characters), `unit`, `currency`, and `by_period` with per year:
  `value`, `target_date`, `period` (the header, or "first–last" of the parts rolled up), `period_text` (the header as stated, none when rolled up),
  `period_start`, `period_end` and `source` {file, sheet, cell, kind "sheet"} (a range "D7:O7" for a sum). The value is the file's, ×1,000 for a
  money line when the title rows say thousands (§19 units); the unit after that scaling is the currency code (title rows, else the label) with
  no unit, "%" for a rate, and "customers", "people" or "units" for a count. The row also holds `origin` "forecast_file", `file_hash`,
  `dtype`, `sheet_row`, `status` "approved" and no deck. Added fields: `sheet` and `cell` in a source, `origin` "forecast_file", `file_hash`,
  `dtype` and `sheet_row` (the line's row, for the year-end re-read); the dataset keeps `first_col` and `title_currency` for the cells and the unit.
  In the register (claim-matching.md §6) each value is one row, `#n` as for any table row: evidence label Unverified, reason "Read from the
  forecast file, not yet tested against data" (George, 2026-10-16), no metric, observed figure, gap or gate, `value_at_stake_arr` null and `overlaps_with`
  null; ranked after every other row, with Use of funds; out of the top 5, the banner and the verdict; `deck_reading` "forecast-file", shown
  "Read from forecast table"; `page_ref` "{sheet}!{cell}". Once a deck is uploaded the deck list shows them under All, the source as
  "{file} · {sheet}!{cell}"; the IC memo lists them in its register appendix and the baseline CSV carries them. A second
  Save claims for the same file answers 409. Delete audit removes them with the other candidates (§6.3).
- **20.4 Screen and data boundary.** Under the miss message the bubble shows S28a with "Show claims", and S28b over the cap. Show claims opens
  the list of S28c: one row per line with its checkbox, ticked by default; unticking a line drops all its claims. Save claims sends the sheet rows
  of the ticked lines, `POST /api/audits/{id}/datasets/{dtype}/forecast-claims {rows}`; the server reads the claims again from the stored file
  (the browser sends no value), refuses a row that is not a line of the list (400), stores the ticked lines and answers `{saved, lines}`; the
  file's view is then read again, the list is gone and the status line shows S28d (§20.5). A file whose claims are saved shows S28d on reload. No model call is made: the reading is rules
  only, nothing new reaches the gateway (`GATEWAY_READABLE_FIELDS` unchanged), and the log line holds the run and two counts.
- **20.5 After review (2026-10-16, George).** (1) A file read as claims (one whose bytes have saved forecast-table claims) no longer counts
  toward Calculate: compute does not read it (it is no engine input), Run audit's mapping stage and the review screen's counts and mapping
  summary leave it out, and the revenue banner treats a revenue-typed file read as claims as no revenue file (S16a). Its view carries
  `read_as_claims` {lines, claims} with nothing pending and no required field missing; the miss message stays, and its status line reads S28d.
  Saving claims brings a computed audit up to date (the stale rule of §16). (2) Forecast-table claims selectable for the top 5 once the
  analyst enters a value at stake: not a small change (an analyst-entered value at stake, the top-5 rule, gates on these rows), so not built;
  issue #117. (3) The button is "Save claims" and the register reason "Read from the forecast file, not yet tested against data".
- **Decided (engineering, rule 19).** Exact synonyms and exclusion words (20.1, measured on the three fixtures below); a flow needs all parts of
  its year, a balance its last part; a rate is never rolled up (no weights); a cut line keeps the years before the cap; one Save claims per file.
- **Tests.** `test_forecast_claims.py` on `backend/tests/fixtures/forecast/`: `annual_forecast.csv` (an appendix P&L, EUR thousands, actual and
  forecast years: plan lines read, cost sub-lines dropped, ×1,000, cells), `monthly_model.csv` (60 months, July start: rolled up to years, sums
  and year-ends, partial years dropped, a June year-end re-reads) and `eighty_lines.csv` (80 plan lines, capped at 60), the endpoint (nothing
  stored before Save claims, unticked lines dropped, 400, 409), the register row, the memo and the CSV; `test_gateway_data_boundary.py` (no model
  call, the reason, the log line, nothing gateway-readable); `MappingWizard.test.jsx` (S28a–S28d, the list, Save claims with unticked lines),
  `deckClaims.test.js` (the sheet source, the type), `claimRegister.test.js` (the reading); for 20.5 `test_forecast_claims.py` (compute, Run
  audit, the review counts, the banner, a Save with no line), `MappingWizard.test.jsx` (Calculate, the status line, Save claims off with no
  line) and `review.test.js` (the mapping summary).

## 21. Deal ID and stage, and a rule confidence of exactly 80 (2026-10-17, George)
Cause found (a CRM export headed opportunity_id, sales_agent, product, account, deal_stage, engage_date, close_date,
close_value; a synthetic file with these headers and 20 rows is in `backend/tests/test_deal_id_rules.py`): the rules mapped
deal_stage to deal id at 80, accepted it without a click and left opportunity_id unmapped. A wrong label is worse than a
missing one. (1) An underscore was read as a letter, so "deal_stage" never met the stage synonym "deal stage" (100) but
began with the deal id synonym "deal" (80), and "opportunity_id" met only "id" (60); (2) 80 was accepted; (3) no value
was checked for a deal id. The architecture is unchanged.

Challenge (rule 4): needed, because a wrong field that needs no click reaches the engine unchecked. Simpler: two header
words and one value check for the deal id, and no auto-accept at 80. Deleted first: nothing.

- **Underscores.** A header is read with every run of punctuation as one space, the underscore included (§19 already said
  punctuation): "deal_stage" is "deal stage", "opportunity_id" is "opportunity id".
- **A stage is never a deal id.** A header containing stage, status or phase (any case, anywhere in the header) scores 0 for
  deal id. A column whose values are a small set of repeated labels scores 0 for deal id: every value is text with a letter
  and is not a code, there are at most 12 distinct labels (`LABEL_SET_MAX`; 1 to 4 in sample_data/ and the fixtures), and each
  is used twice on average. Such a column stays a candidate for stage through its header; its values alone never propose a
  field (agent, product and account columns are label sets too).
- **The deal id candidate.** A column of unique codes whose header holds the word id, opportunity, deal, ref or reference
  (words as the header is read, camel case split: "OpportunityID") scores at least 80 for deal id, so it is proposed and,
  unless its header scores 100, waits for a click. A code is one token with a digit ("1C1I7A6R", "OPP-0042") or a whole
  number (5001), never a date or a decimal; unique means two or more values and no two the same.
- **Exactly 80.** A rule mapping whose confidence is exactly `MAPPING_THRESHOLD` (80) is unsure: it is shown for
  confirmation and, with consent, goes to step 2 like every unsure row (§4.2), where it still waits when the model agrees
  (George, 2026-10-17, §22). Above 80 and untied it is accepted as before. A saved mapping on new data keeps 80 or more (§5).
- **Measured.** On sample_data/ and the nine fixture files (87 columns), no column changes its field, state or confidence,
  and none was accepted at exactly 80 before. The reported file: opportunity_id → deal id (100, accepted), deal_stage →
  stage (100, accepted), close_date → close date (100, accepted), close_value → amount (60, unsure); sales_agent, product,
  account and engage_date have no proposal.
- **Reason codes.** "Values do not fit this field" (`values_do_not_fit`) is offered and accepted when a rule mapping is
  corrected to a field of another kind, on the mapping table (§4.3) and in the review screen's Change (§18).
- **Tests.** `test_deal_id_rules.py` (the reported file by rule and through upload, underscores, each rule and its limits,
  80 and 85, the reason through the decisions endpoint and the usage counters), `test_money_kind.py` (a turnover or GMV
  header scores 80, so its row waits for a click and is sent to the model), `MappingWizard.test.jsx` and `Review.test.jsx`
  (the reason offered and sent for a number field corrected to a date field).

## 22. Every column to the model, and mapping calls outside the daily spend cap (2026-10-17, George)
Decided by George with the task: with consent, every upload sends all columns in one call, with the rules' proposal and
confidence as a hint; a rule 100 wins; otherwise the model's proposal waits for a click below 80, or where the rules and the
model disagree; columns both sides leave out are Not used; mapping calls are exempt from the daily spend cap and still logged
and counted; structure and narrative calls stay under it; cache by file hash as before; S2's first sentence. Without consent
the rules alone decide, as before. The architecture is unchanged: what is sent keeps the rule-16 shape per column
(docs/architecture.md, "Data boundary"), and the confidence is Python's.

Decided by George on review (2026-10-17): (1) a model proposal's confidence is the rules' formula on its field, not a number
the model reports, and an AI suggestion's Confidence cell reads "AI suggestion – confirm" instead of the number (rule rows keep
theirs); (2) the file-type call (§19) stays under the cap: it is not a column mapping; (3) the same headers on new bytes keep the
saved mapping with no call (§5), because the analyst's decisions rank above both sides; (4) a tie waits even when the model
picks the rules' column, because two columns read equally well; (5) §21 stands: exactly 80 waits, and agreement needs no click
only at 81 or more.

Challenge (rule 4): needed, because the rules accept 81–99 alone and the model saw only the columns the rules could not
decide. Simpler: no new output field; the confidence of a model proposal is the rules' own formula on its field. Deleted
first: the undecided-only filter of the text (`only`), and the boundary assertion that decided headers are absent.

- **Decided (engineering, rule 19).** The server keeps an AI suggestion's confidence (it decides the click and is saved with
  the mapping version); the screen hides it and orders the row as one with no score (§4.4), so a hidden number never moves it.
  A column the rules map whose field the model gave to another column needs a decision, so no two rows wait on one field.
  When the model cannot be read, the rules' outcome stands, as before this section.
- **Tests.** `test_chat_upload.py`: every column sent with the rules' hints on the three fixtures; each branch of the outcome
  (a rule 100 against the model, agreement at 90, at exactly 80 and at 60, another field, a contested field, a tie, both
  sides silent); consent off decides by rules and sends nothing; the 22 columns of a synthetic HubSpot deals export
  (`mapping_shapes.hubspot_synthetic_crm`, invented values) in one call, masked; on a day over the cap the mapping call goes
  out, is logged and counted, and a deck structure and a file-type call are refused. `test_gateway_data_boundary.py`: the text
  holds every column, the masked samples and closed hints; a bad hint is refused. `MappingWizard.test.jsx`: S2, an AI
  suggestion's confidence cell ("AI suggestion – confirm" with or without a number from the server), and its row order.
