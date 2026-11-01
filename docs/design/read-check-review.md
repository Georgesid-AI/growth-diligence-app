# Read, check, review

Design note · docs/design/read-check-review.md · 29 October 2026 · status: proposed, awaiting owner approval · PRs 0 to 4 built (section 13); section 12 done, section 16 added in PR 4

## 1. Purpose

The app's reading of files is done by rules today. Rules cannot read a sheet
whose signals are subtle (where a monthly report's actuals end, which rows are
plan, which column is a variance). Every new file needs new rules, and the app
stays unusable.

From this note on: **the model reads, code checks and computes, a second model
call reviews the reading, and the analyst decides only what the first three
could not settle.**

This note covers mapping and checks only. It does not cover labelling or
verifying management claims. See section 14 for what comes after.

## 2. Scope

In scope

- The model reads every uploaded spreadsheet in full and every deck page, after
  masking (section 8), and returns a map of the file (section 4).
- Code checks every cited cell and does all arithmetic (section 5).
- A reviewer call finds reading errors (section 7).
- Figures land on a register automatically; cards only for what cannot be
  settled (section 7.4).
- Readings are stored once and never edited (section 9).
- A fixture set guards every change to the reading path (section 10).
- One screen: file blocks, three result tables (section 11).
- The rules reading machinery is deleted (section 12).

Out of scope, kept in code where it exists but off the default screen

- Evidence labels (Verified, Unverified, Unsupported, Contradicted,
  Inconclusive), value at stake, top-five claims, claim-review conclusion,
  gates, the memo's claim counts.

## 3. Pipeline

1. **Read** — one model call per file. Input: the masked file text. Output:
   the file map, every item with a cell or page reference and its evidence.
2. **Check and compute** — code. Open every cited cell, confirm the value.
   Then all arithmetic. Code never reads, never decides meaning, never
   corrects.
3. **Review** — one model call per audit, fresh context. Input: the maps and
   the computed results, not the reader's reasoning, not the raw files.
   Output: findings about reading errors, each with references. Code checks
   those references too.
4. **Register** — automatic. Unflagged items land as read. A flagged item gets
   one re-read. Reader agrees with the reviewer → corrected, marked
   "corrected on review". Reader disagrees → card.

Plain-language division: the reader is the junior who extracts the numbers,
code is the spreadsheet that does the sums, the reviewer is the senior who
reads the output cold and says "look again", the analyst sees only what the
senior and the junior could not settle.

## 4. The file map

The reader returns a complete map of the sheet, not only what the engine
needs today. Later operations read from the stored map; they never re-read
the file.

Per sheet

- sheet name, header row, label column, first and last period column, period
  granularity of the columns (monthly, quarterly, yearly), currency with the
  cell it was read from
- last actual column, with evidence (section 6)

Per row (or per column where periods run down the sheet)

- `role`: revenue, bookings, contract_value, arr, mrr, churn_rate, growth_rate,
  margin_rate, customers, users, cost_of_revenue, sales_marketing, rnd, ga,
  opex, ebitda, cash, headcount, forecast, variance, other
- `metric`: the fixed metric name the engine uses, or blank for `other`
- `basis`: monthly, quarterly, yearly, cumulative_to_date, last_12_months,
  rate
- `actual_plan`: actual, plan, variance, mixed (with the boundary column)
- `segment`: product, region or customer group if the row is a split; blank
  for a total; `parent` = the row it sums into, if the parts sum to it
- `unit`: money, count, rate; `currency` if money
- `cells`: the range the values occupy
- `evidence`: one line, the reader's reason for role, basis and boundary

Per figure (deck pages, and sheet cells the engine uses directly)

- metric, value, unit, currency, period, basis, actual_plan, segment, source
  (file, sheet, cell | deck, page), evidence

The same schema serves decks and sheets. Deck pages return figures only; the
per-row fields stay blank.

## 5. The checks

Three outcomes, and only three. Code never corrects.

**Confirmed** — the cited cell holds the value within tolerance:
money within 0.5 %, rates within 1 point, counts exact, text exact after
whitespace, dates exact to the month.

**Rejected** — the cell exists but does not hold what the reading says.
Reasons, each written by code, same wording every time:

- "Reading says {value}; cell {ref} holds {cell value}."
- "Reading says {period}; cell {ref} is the header for {header period}."
- "Reading cites {ref}; the sheet ends at column {last}."
- "Variance row {ref} does not equal actual minus budget in {n} of {m}
  periods."
- "Parts {refs} sum to {sum}; the reading names {ref} as their total, which
  holds {value}."

A rejected item is re-read once, automatically, with the reason attached.

**Cannot check** — nothing to compare against. Five cases, each explicit in
code; anything else that fails is a rejection:

- "This describes the layout, not a value; no cell to open."
- "Page {n} has no text layer; figure read from the image."
- "Cell {ref} holds {cell value}; reading says {value}. Unit or scale
  differs; not compared."
- "No cell reference given."
- "Depends on a name that was masked before reading."

A cannot-check item stays on the register, is counted separately, is never
shown as confirmed, and the memo never calls it verified.

Structural claims the reader makes as evidence (a row ends at a column; a
range equals another range; a label contains a word) are checked by code
where a test exists and otherwise marked cannot check.

Arithmetic: growth, variance to plan, payback, reconciliations, sums. Every
computed figure stores the formula with its input cells. Display follows the
rounding rule in section 11.5; stored values keep full precision.

## 6. As-of month

Per file, the reader proposes the last actual column with evidence: rows that
stop at a column, values after a column equal to a plan or sales row, a row
labelled forecast or budget, round or repeated values after a column, a header
or title row marking plan columns.

Code checks each piece of evidence it has a test for. The month stands only if
at least one piece is confirmed.

For the audit, the as-of month is the latest confirmed actual month across all
files. A yearly file with an earlier boundary is not a conflict; that file's
tests run to its own boundary, and each file keeps its own last actual month
on the register.

A typed month wins everywhere, shown as "set by analyst" with the reader's
proposal kept beside it. With no confirmed month in any file, the strip shows
"As-of month: not determined" and one card asks for it; the audit runs
everything that does not depend on it.

Never used: the deck date, the file name, the upload date, the last column
with a number.

## 7. The reviewer

### 7.1 What it is

A second model call per audit, fresh context, same model as the reader to
start. It has no memory of the reading calls.

### 7.2 Input

Masked, already stored:

1. the file maps and figures from every file and deck, as the reader returned
   them, without the reader's reasoning and (PR 4) without the stored series:
   roles, ranges, boundaries and figures only; a cell value of the file went to
   the model once, in the reading
2. the computed results
3. the list of cannot-check items

### 7.3 Job, in this note

Find reading errors only: a row whose values behave like bookings read as
revenue; a cumulative series read as monthly; the actual/plan boundary in the
wrong column; parts that do not sum to their named total; a unit or currency
read inconsistently across a row; a map inconsistent with the chosen as-of
month.

Run audit asks for the review again whenever its last stored status is anything
other than read (refused, cut off, incomplete, not yet made), from whichever
stage it carries on from; a review that read is asked again only when its input
changed. Its allowance is its own (`REVIEWER_TOKEN_CAP`, default 80,000 tokens
per audit). A file reading has a per-file allowance (`FILE_TOKEN_CAP`, default
400,000 tokens per file, counting its reading and its re-reads), which replaces
the per-audit allowance for files; the per-audit 400,000 stays for deck structure
and page calls only. A call a cap refuses logs the one line `ai call refused:
step=… reason=token_cap used=… cap=… input=…` (reason `token_cap` for either
allowance) and writes its `llm_calls` row with `refused_input_tokens`, the input
the call would have sent. There is no "structure not read" line beside it.

Not its job yet: contradictions between sources, plausibility of plan figures,
anything about management claims (section 14).

### 7.4 Output and what follows

A list of findings, possibly empty. Each: what is wrong, which references, the
reviewer's reading, how sure it is. No rewritten numbers.

Code checks each finding's references; a finding citing a cell that does not
exist is dropped. A valid finding triggers one re-read of that item with the
finding attached. Reader agrees → corrected, marked "corrected on review".
Reader disagrees → card with both readings and the evidence for each.

Cards come from three places only: a citation that fails twice, a
reader–reviewer disagreement that survives one re-read, a masked value the
reading needs. Target: zero to three per audit.

## 8. Masking (level A)

Applied to every payload that leaves the server, spreadsheets and deck pages
alike. No new dependency.

- Personal data: removed, never sent, never stored in a payload. Regex for
  emails, phone numbers, IBANs and ID-shaped strings. Spreadsheet columns
  whose header signals people (owner, contact, manager, rep, signatory)
  masked as whole columns. Deck page text never uses the people-header rule:
  a page title such as "Key contacts" blanks nothing below it; page text gets
  the regex removals, first-name personal names and the token map only.
  A column headed name, customer, account, company or client holds company
  names: tokenised, never withheld (George, review of PR 204). A text cell
  under such a header that is not yet in the audit's token map is added to
  it when the payload is masked and gets the next Client-NN, whether or not
  the audit knew the name before. A cell with a digit in it (a label with a
  figure) is not read as a name.
- Company and customer names: replaced by consistent per-audit tokens
  (Client-01, Product-A). Same name → same token in every file of the audit.
  The token map lives on the audit record only. Display un-masks on the
  server.
- Figures and metric labels are sent as they are.
- Counts shown on screen per file: lines sent, names masked, company names
  tokenised, columns withheld.

Level B (a local name detector) only if a tester finds a person's name in a
free-text cell.

The AI-reading explainer on the Upload page changes to say that spreadsheets
are sent in full after masking, as deck pages already are. The ZDR sentence
stays behind the PROVIDER_ZDR flag.

## 9. Readings are immutable

A reading is written once, keyed on account + file hash + a short hash of the reading prompt text as sent
+ model version, and never edited (the prompt version label is a display field only). The account is the tester who owns the audit.

- A reviewer correction or an analyst Change is a separate dated override
  record: reading, item, old value, new value, who, when, why. The register is
  the reading plus its overrides.
- Any change to the prompt text, or a new model version, produces a new reading stored beside the old
  one. Re-reading is an explicit action, never automatic.
- The same file uploaded again, in any audit of the same account, gets the
  stored reading. No second call. The same file in another account is read
  again, and a reading goes with the last audit of its account that uses it.
- The model string in the gateway is a dated version, never "latest".

## 10. Fixture set

A folder of synthetic test files, each with its expected map written out
(as-of month, revenue row, boundary, the key figures with their cells).
Starting set, one per layout:

1. monthly report, metrics down the rows, months across, actuals ending
   mid-year with the plan copied down, a cumulative forecast row
2. yearly P&L, one column per year, the last column a plan with no plan word
   in its header
3. actual | budget | variance columns per month
4. budget on a separate sheet
5. deck with rotated chart-axis labels whose parts sum to a headline figure
6. the existing TestCo files

No file in the set carries a real company's figures or names.

A CI job runs every fixture through the reader and compares with the expected
map. It runs only on PRs that touch the reading path (prompts, model string,
masking, schema, checks) and needs the API key in GitHub Actions secrets.
Rule: no such PR merges without the fixture set passing. A changed expected
map needs the owner's approval, recorded in the PR.

## 11. Presentation

### 11.1 Upload page, top

Unchanged: explainer texts, consent tick, Run audit button at the top.

### 11.2 File blocks

One block per file, in upload order. Spreadsheet summary line:
"{n} period columns · {n} rows mapped · last actual {month} · {n} confirmed ·
{n} rejected · {n} cannot check". Second line: the as-of evidence. Then the
three anchor lines with a Change link each: as-of month, revenue row,
actual/plan boundary. "Show all lines" opens the full map.

Deck summary line stays as built: pages parsed, pages with figures, pages sent,
pages skipped and why, figures read, quoted figures skipped. Up to 8 decks per
audit.

### 11.3 Three result tables, across all files

Confirmed is collapsed by default behind its count. Rejected and Cannot check
show every row. Every heading has a hover definition. Source is always the last
column and shows the cell first: "AP11 · Sheet · file…"; the link opens the
cell or page.

**Confirmed**

| Column | Width | Hover |
|---|---|---|
| Metric | 20 % | What the figure measures, e.g. recognised revenue, ARR, customers. |
| Value | 12 %, right | The number as it stands in the file, shown rounded; the full value is kept. |
| Period | 10 % | The month, quarter or year this value belongs to. |
| Basis | 10 % | How the value accumulates: monthly, quarterly, yearly, cumulative to date, or last 12 months. |
| Actual / Plan | 8 % | Whether the cell sits before or after the file's last actual month. |
| Row | 14 % | What the whole row or table was read as: revenue, bookings, ARR, churn rate, customers, forecast, variance, other. |
| Source | 26 % | The file, sheet and cell, or the deck page, the figure was read from. Click to see the cell. |

**Rejected**

| Column | Width | Hover |
|---|---|---|
| Metric | 14 % | What the reading said the figure measures. |
| Reading says | 12 %, right | The value and period the reader recorded. |
| Cell holds | 12 %, right | What the code found when it opened the cited cell. |
| Reason | 22 % | Why the check failed: value differs, period differs, cell does not exist, or a structural check failed. |
| Re-read | 12 % | Result of the automatic second reading: agrees with the cell, repeats the first reading, or gives a third value. |
| Action | 10 % | What happens next: corrected automatically, or a card for you to decide. |
| Source | 18 % | The cited file, sheet and cell, or deck page. Click to see the cell. |

**Cannot check**

| Column | Width | Hover |
|---|---|---|
| Metric | 16 % | What the figure measures. |
| Value | 12 %, right | The value the reader recorded. |
| Period | 10 % | The month, quarter or year it belongs to. |
| Why | 26 % | Why no check was possible: layout description not a value; deck page is an image; unit or scale differs from the cell; no cell cited; depends on a masked name. |
| Used in | 16 % | Which computed figures rely on it, so you know what is affected. |
| Source | 20 % | Where it was read from. For a deck page without text, the page number only. |

Below ~900 px each table becomes a card per row with Source as the last line.
Number columns never wrap and align right; text columns wrap.

### 11.4 Register fields (behind each row, on hover or expand)

metric · value (full precision) · unit, currency · period · basis ·
actual/plan · segment, parent · source · origin (file actual, file plan, deck
actual, deck plan, computed) · row role · check outcome · check reason ·
reading evidence · reader version · override (who, when, why).

Not held: confidence scores, evidence labels, value at stake, the reader's full
reasoning, raw text.

### 11.5 Rounding rule (display only)

Whole numbers everywhere. One decimal only for a single-digit multiple (3.3x),
a single-digit number (1.2) or a single-digit percent (4.5 %). Same rule in
the memo and the export. Stored values are never rounded.

## 12. Removed (done in PR 4)

Done. What was deleted, and what stays in code behind a flag.

Deleted

- The model calls `file_type`, `file_recognition`, `sheet_structure` and the column mapping, with their prompts (`file_type`, `sheet_structure`
  leave the prompt store's list; the repository's stubs go), schemas, masking text builders and the `READER_V1` flag. `structure_reading` stays:
  the deck structures of the rules read (`DECK_PIPELINE=rules`, Add from deck) use it.
- Column mapping by rules as a step: the confidence scores and the auto-accept threshold as a state machine, the "AI suggestion – confirm" rows,
  the per-file mapping table (Line · Role · Meaning · Basis · Used · Confidence · Checks), Confirm all, the file-type picker, the revenue-row
  picker, the "lines wait for your decision" and "answers waiting" lines, the hidden-block safeguard and `?view=legacy`.
- Recognition (`recognition.py`), the statement reader (`structures/sheet.py`, `structures/pnl_lines.py`) and the forecast-table reader
  (`forecast_claims.py`). The header-period parser the cell checks need moved to `app/periods.py`, the stored-sheet packing to
  `app/stored_sheets.py`.
- As-of detection and all its fallbacks: the audit's month is the latest confirmed actual month of the readings, or the analyst's. Nothing is
  read from rows, from the last column with a number, from a file name or from a deck.
- The label-correction startup migration and the Diagnostics page's deck lines.
- The "possibly partial" and "Needs your review" gating: Run audit never waits for a confirmation. Its mapping stage is done once a file is
  stored and read ("The files are still being read" while a read runs); its engine stage always calculates; a deck never waits for a file.
- The claim questions on the Audit page.

Behind `OLD_CLAIMS` (default off, `backend/app/flags.py`; the audit says `old_claims` to the screen)

- The claim register, the five-claims conclusion, the three reasons, the key gates, the claim labels, "claim questions open" and the
  contradicted-claim blockers. Off, none of them is on the Audit page, in the blockers or in the downloaded report: the report holds no verdict,
  no reasons, no claim counts, no key gates (the section is "Deal terms"), no claim appendix ("Not part of this report.") and no claim
  glossary terms. On, everything is as before PR 4. The code and its tests stay.

Kept on purpose

- `column_rules.suggest_mapping` and `server.normalize`: the header rules that turn a customer-level or CRM export into the engine's frames. No
  upload calls them. The demo companies and the engine's tests use them as an adapter until ledger mode (section 14) replaces them.
- The label-correction branch of `structures/corrections.py` (period and label options of a deck claim): the deck claims are still read, and
  the claim register behind `OLD_CLAIMS` still lists them.

## 13. Build plan

Each PR from main, in sequence. Owner merges after CI. Any architecture change
is named in the PR description and needs the owner's approval before merge
(CLAUDE.md rule added in PR 0; the "never challenge the frozen architecture"
line is removed).

| PR | Content | Model | Review |
|---|---|---|---|
| 0 | this note; CLAUDE.md rule change | — | owner |
| 1 | masking module on every outbound payload, sheets and deck pages; counts on screen; explainer text | Sonnet | short Opus (privacy) |
| 2 | sheet reader with the file map schema; cell checks with reasons; as-of per file and per audit; immutable readings; `sheet_reading` v1 prompt (owner pastes); fixture set and CI job; engine contract bump; old mapping path kept behind a flag for this PR only | Sonnet | Opus |
| 3 | reviewer call; re-read; automatic register; cards; `reviewer` v1 prompt (owner pastes); three result tables | Sonnet | Opus |
| 4 | the engine reads the stored map by role (section 16); delete the rules reading (section 12), claims behind `OLD_CLAIMS`; the reviewer runs again whenever its last status is not read, reads maps without their series, and refusals log the input estimate; a per-file reading cap replaces the per-audit cap for files | Sonnet | none |

Emergent updates after PR 2 and after PR 4 (built; the owner's first run on the current test company's three files is the update). First run on the current test
company's three files, expected: as-of month read from the monthly file with
confirmed evidence, revenue row confirmed, plan-to-date variance computed, zero
to three cards. Then the second company's files, before any prompt or rule
change.

Owner actions in parallel: ZDR confirmation from Anthropic in writing; paste the
two prompts; add the API key to GitHub Actions secrets.

Cost accepted by the owner on 29 October 2026: roughly two to three times
today's model cost per audit, plus a few cents per fixture CI run.

## 14. Later stages, each its own design note

1. Contradictions between sources, actuals only: same metric, same period, two
   sources, different numbers; list with both references and the gap.
2. Plan plausibility: for every figure after the as-of month, what it requires
   against what the company has done, variance to date, what is missing.
3. The cross-referencing model: the engine relating every figure to every
   other that should agree with it, as a standing structure.

Claim labelling returns only after these, as a report on 1 and 2.

## 15. Test list for PR 2 and PR 3

Each a failing test before a fix, on synthetic fixtures:

1. right cell, wrong role (bookings row read as revenue) — caught by the
   reviewer, not the cell check
2. structural evidence partly wrong (one of the "rows that stop" continues) —
   that piece rejected, month stands on the remaining evidence
3. wrong as-of month proposed — every plan-side test flagged by the reviewer
   as inconsistent with the map
4. merged quarter headers, date serials, percentages stored as fractions —
   read correctly or cannot check, never confirmed wrongly
5. two reads of one file — second upload returns the stored reading, no call
6. value within tolerance (447,223 vs 447,223.43) — confirmed, no card
7. column off by one — rejected with the header-period reason
8. masked name in a citation — compared in masked space, confirmed
9. a check that would "fix" a citation — does not exist; only three outcomes
10. a figure with no reference — cannot check, never confirmed

## 16. Engine inputs by role

From PR 4 every engine input comes from the stored map and its stored series (sections 4 and 9), by the role the reader gave the row. Code
picks a row by role, a total (no segment) before a split, the granularity the metric needs, and does arithmetic on the cells the series holds. A
row whose check was rejected is not an input. A metric runs when the rows it needs exist; otherwise its entry reads "needs a <role> row" and
names the roles. It never reads "no S&M line" or the like. The results carry the entries in `role_metrics` (contract 16, server-only); the blocks
the map feeds (`arr`, `mrr_series`, `revenue_series`, `customers_series`, `yearly_basis`) keep their shape.

| Metric | Roles it needs | Basis | Rule |
|---|---|---|---|
| Ending ARR | arr, or mrr | monthly | the arr row at the latest actual month, else the mrr row × 12 |
| MRR series | mrr | monthly | the mrr row month by month to the as-of month |
| Monthly churn | churn_rate | monthly | the churn_rate row at the latest actual month, as the file states it (a fraction) |
| Customer count | customers | monthly | the customers row at the latest actual month |
| Growth | revenue, else arr, else mrr | monthly or yearly | month on month and year on year of a monthly flow row; year on year of a yearly row; a cumulative or last-12-months row gets no month-on-month |
| Plan to date | revenue, forecast | monthly | actual to the as-of month against the plan row to the same month; cumulative only where the plan row is cumulative (actual accumulated over the plan row's own span); a full-year plan row is never compared with actual-to-date |
| Yearly revenue | revenue | yearly | the revenue row of the fiscal year, labelled yearly |
| Gross margin | revenue, cost_of_revenue | yearly | (revenue − cost of revenue) ÷ revenue |
| S&M share | revenue, sales_marketing | yearly or monthly | S&M ÷ revenue in the latest period both rows hold |
| CAC payback (yearly) | revenue, cost_of_revenue, sales_marketing | yearly | 12 × S&M ÷ (revenue growth × gross margin), labelled "yearly, revenue-based"; the net-new-ARR proxy also needs an mrr row |
| R&D, G&A, opex share; EBITDA margin | revenue and rnd, ga, opex or ebitda | as the rows | the line ÷ revenue |
| Bookings, cash, headcount | bookings, cash or headcount | as the row | the row at the latest actual month |
| Reconciliation | any role stated by two sources | as the sources | the same metric and period from two or more of: a file's row, the sum of its twelve months for a year, a deck figure (not a plan figure, not a rejected one); sources on another basis or in another currency are not compared; money within 0.5 %, counts exact |

Not in this PR, each its own change: ledger mode (customer-level and CRM files read into the engine; until then NRR, gross churn, Path to
Plan, segment paths, cohorts, the quarterly CAC payback, sales cycle and win rate say "needs customer-level revenue lines" or "needs CRM
deals"), `rate_scale` (a rate is used as the file states it), timestamps, card layout, formatters and fixtures.

An entry whose calculation stops on an unexpected error reads "the calculation stopped on an unexpected <error type>; reported as Missing, not
estimated" and the other metrics are unaffected (rule 20).
