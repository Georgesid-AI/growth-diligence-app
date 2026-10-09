# Spec: Gates, verdict and IC memo (method A9, A10, A11)
Status: Final (2026-10-08). Every decision is in §12 and every wording item in §11 is approved.
Location: docs/specs/verdict-and-memo.md. Follows claim-matching.md (the register) and interface-contracts.md
(MetricsPayload). The method's lists (evidence categories, appendices, thesis labels, rating scale) are as given on
2026-10-08; the method text itself stays out of the repo.

## 0. Challenge and deletions (CLAUDE.md rule 4)
- Needed: the register stops at gates today. The analyst still has to turn it into a decision for the investment
  committee. The simpler version built here adds no page, no collection, no stored memo, no model call and no new
  analysis. The verdict is a pure function of the top 5 the analyst confirms. The memo is Markdown, built on request
  from the same functions.
- Deleted first: the gate date default (claim-matching §5: "the app proposes nothing"); "for every row with an observed
  value" (§5: a gate can now be set on every row); "Not shown: value at stake" (§8: the column now reads "not yet
  computed"); the register-only CSV (§7: replaced at the same URL by the baseline with gaps, §5 below).

## 1. Scope and architecture
In: register columns for value at stake, overlaps and evidence; gates on every row that is not Verified; key gates;
data gaps; the baseline CSV; the analyst's top 5; the verdict; the IC memo; the cost panel.
Out: the ARR bridge (#6) and every value at stake or value at risk figure; cash analysis; the strategic coherence,
forecast track record, execution capacity and defensibility analyses; ingesting categories 4, 5 and 7 of §7.2; any new
prompt, step or model call; editing the memo in the app; PDF or docx output.

No architecture change:
| Part | Where |
|---|---|
| Register extras, gate check, data gaps, top 5, verdict | new pure module `backend/app/verdict.py`. It reads register rows, `audits.results` and the analyst's inputs, and imports nothing from `app.llm` |
| IC memo, number check, word count | new pure module `backend/app/ic_memo.py`. It is handed the register, the verdict, the results, the audit, the stored narratives and the usage. The server reads the narratives through `llm_gateway.narratives_for_run`, which only reads; a memo never generates a narrative |
| Endpoints (`server.py`) | `GET /audits/{id}/verdict`; `PUT /audits/{id}/claims/{claim_id}` gains `key_gate`, `gate_metric_name` and `gate_direction`; `PUT /audits/{id}/ic-inputs`; `GET /audits/{id}/claims.csv` (the baseline); `GET /audits/{id}/memo.md`; `GET /runs/{id}/llm-usage` gains `by_step` |
| Screens | Dashboard. The "Claim register" section gains columns, and three sections are added: "Data gaps", "Verdict", "AI usage and cost". The Frontend row of docs/architecture.md names four pages, so no page is added |
| Storage | existing documents only. The gate's new fields sit on `deck_candidates.claim_inputs[claim_id]`, beside the gate. `audits.ic_inputs` holds `top5`, `first_quarterly_review`, `gap_target_dates`, `ratings` and `thesis`. Delete audit removes both with their documents, as it already does (rule 22). The memo is never stored |

## 2. Claim register (A9)
### 2.1 Columns
| Column | Fields | Rule |
|---|---|---|
| Claim | as today (rank, claim, period, segment, page, deck reading, observed, gap, gloss) | claim-matching §3, §8. The rank is the pre-sort by shortfall (§6.1) |
| Value at stake | `value_at_stake_arr` (null until #6); `shortfall` = `gap_normalised` when `gap_kind` is miss, else null | W1. Never estimated |
| Overlaps with | `overlaps_with`: claim ids, shown as ranks | §2.2; W2 |
| Evidence label | `evidence_label`, `reason` | as today (claim-matching §4) |
| Evidence | `evidence_analysis`, `evidence_source_key`, `observed_at`, `observed_source` | §2.3; W3 |
| Gate | gate fields + `gate_metric_name`, `gate_direction`, `key_gate`, `gate_needed` | §3 |

### 2.2 Overlap
Two rows overlap when all three hold: (a) their metrics are the same, or are ARR and MRR (ARR is MRR × 12); (b) they
have the same segment, or either one is Whole company; (c) their observed periods share a month (a quarter is its three
months; an as-of figure is the as-of month). A row with no observed figure overlaps with nothing. The relation is
symmetric. It is used only to count value at risk once (§7.2); until #6 it is shown and nothing more.

### 2.3 Evidence
| Metric | Analysis (Dashboard name) | Source key: whole company; by segment |
|---|---|---|
| Revenue | Revenue by month | `revenue_series.data.total`; `revenue_series.data.*` |
| ARR, MRR | Monthly MRR by Segment | `mrr_series.data.total`; `mrr_series.data.*` (× 12 for ARR) |
| Customer count | Customers | `customers_series.data.total`; `customers_series.data.*` |
| New MRR | New MRR by quarter | `new_mrr_by_quarter.*.new_mrr` |
| NRR (12-month) | NRR | `nrr.series.nrr_pct`; `nrr.by_segment.*.nrr_pct` |
| Gross revenue churn | Gross revenue churn | `gross_churn.series.churn_pct` |
| ACV | Path to Plan | `acv_path.acv`; `acv_path.by_segment.*.acv` |
| Median sales cycle | Sales cycle | `sales_cycle.median_days`; `sales_cycle.by_segment.*.median_days` |
| Win rate | Win rate | `win_rate.win_rate_pct` |
| Gross margin | CAC Payback by Quarter | `cac_payback.quarters.*.gross_margin_pct` |
| CAC payback | CAC Payback by Quarter | `cac_payback.quarters.*.L{default_l}.months` |
| a "Missing:" reason | the Missing Data item's metric | `missing_data` |
| no figure (any other row) | — | — |

Source keys are paths that MetricsPayload declares. Lists are transparent, and `*` stands for a data key (a segment
or a quarter). The contract test pins every key (§9).

## 3. Gates
- A gate is a metric, a threshold, a date and a budget decision. The analyst sets the threshold, the date and the
  decision; the app proposes nothing, so the date field also starts empty. A gate is saved when the threshold, the
  decision (max 200 characters) and the date are all filled.
- A row with no app metric (reason "no metric", or "metric does not fit the claim's unit") also needs the metric and
  the direction (W22, decision Q3). The analyst types the metric (max 100 characters) and picks at least or at most.
  The threshold is in the claim's unit. The metric name is stored beside the budget decision, never sent to a model
  or written to a log, and deleted with the audit.
- `gate_needed` is true on every row labelled Unverified, Unsupported or Contradicted until its gate is saved (W4). A
  Verified row may also carry a gate.
- A row with no observed figure gets the sentence of W6. Rows with an observed figure keep claim-matching §5.
- Key gate (decision Q2): any saved gate, on a Verified row too, may be marked key. At most 5 can be marked; a sixth
  is refused (W5). The memo needs 3–5 key gates. When the register has fewer than 3 saved gates, every saved gate
  counts as key and the memo says so (W25).

## 4. Data gaps
- One row per `missing_data` item with status Missing whose metric names an analysis: ARR / MRR; NRR (12-month); NRR by
  segment; Gross revenue churn; CAC payback (with its quarter items); Sales cycle & win rate; Sales cycle; Sales cycle
  by segment; Win rate by founder involvement; Required vs observed net-new customers; Observed net-new customers;
  Segment paths to target ARR. Row-quality items (blank amounts, unmapped currencies, date formats, unrecognised
  values), settings (as-of month, target date) and calculation errors are fixes for the analyst, not something the
  company cannot measure. They stay in the Missing Data card, and in Appendix B as requests.
- V6 rule: before a gap is listed, the supplied files are tested. For the six analyses of
  `growth_engine.ANALYSIS_NEEDS`, the engine's V6 pass has already tested every upload: an item still Missing names
  its absent fields per file, and an item computed from another file is a management question (a request, §7.2), not
  a gap. The other items each need a field that only one upload type carries. NRR by segment needs a segment per
  revenue customer, and CRM deals carry no customer ID. Sales cycle by segment needs deal dates with a segment, which
  only CRM deals have. The rest need revenue history. So no other upload can answer them; a test pins this against
  `FIELD_DEFS`.
- Columns: what the company cannot measure (the item's metric) · why it matters (W7: the analyses and register claims
  it blocks, then the engine's reason) · requested (the engine's `unlocked_by`) · target date.
- Target date: set by the analyst, on or before the audit's first quarterly review. That date is also set by the
  analyst, once per audit. A gap date after it is refused, and so is a review date before a saved gap date (W7).
- Order: by the top-5 claims it blocks (the confirmed top 5, or the pre-sorted one before confirmation), then all
  register claims it blocks, then engine order. The "top data gaps" are the first three.

## 5. Baseline CSV (monitoring after completion)
`GET /audits/{id}/claims.csv`, same URL and button. One CSV. Its header is `row_type`, then the register fields
(claim-matching §6 and §2 above, plus `in_top5`), then `gap_item`, `gap_why`, `gap_requested`, `gap_target_date`,
`first_quarterly_review`. `row_type` is claim or data_gap. Cells follow claim-matching §7, and lists are joined by
"; ". Round trip: read with each column's type, the CSV gives back every field of every row, and writing those rows
again gives the same bytes.

## 6. Verdict (A10)
### 6.1 Top 5 (decision of 2026-10-08)
- The app pre-sorts by shortfall, which is the register's rank (claim-matching §3). It proposes rows 1–5 as the top 5,
  or every row when there are fewer than 5.
- The analyst confirms the proposal, or replaces any of its rows with another register row, and confirms. The set
  always holds min(5, register rows) claims. It is stored as an analyst decision in `audits.ic_inputs.top5`: the claim
  ids, in pre-sort order, and when they were set.
- There is no verdict until the top 5 is confirmed (W23). A confirmed set is void when one of its claims leaves the
  register (rejected, or its table row re-read) and must be confirmed again (W23). A new rank order alone does not
  void it.
- The memo and the Verdict section state "Top 5 set by the analyst pending ARR bridge" (W24).
- The banner (rule 21, chat-upload §6.2) keeps rows 1–5 of the pre-sort, so an analyst's choice never removes a hard
  blocker.

### 6.2 Rule
The outcomes are checked in this order over the confirmed top 5, and the first that matches wins:
1. Re-plan: a top-5 claim is Contradicted (a miss or a beat), or 3 or more top-5 claims are Unsupported.
2. Underwrite: every top-5 claim is Verified.
3. Underwrite with gates: anything else. No top-5 claim is Contradicted, at least one is Unverified or Unsupported,
   and at most two are Unsupported.

The order matters only when 3 or more claims are Unsupported and none is Contradicted. The request's rules match both
1 and 3 then, and Re-plan wins. An audit with no results or no register rows has no verdict (W10).

### 6.3 Blocked
The verdict is blocked while any top-5 claim that is not Verified has no saved gate. A blocked verdict shows no
outcome, only the claims that need a gate (W9). The memo refuses while the verdict is blocked.

### 6.4 Verdict section (Dashboard)
| Part | Content |
|---|---|
| Top 5 | the proposed or confirmed five, with a pick per row from the register, and Confirm (W23); once confirmed, W24 |
| Outcome | the outcome and the rule that fired (W8) |
| Five claims | rank, claim, evidence label and reason |
| Three reasons | the top-5 claims that made the rule fire, by rank: Contradicted then Unsupported (Re-plan); Unverified and Unsupported (Underwrite with gates); Verified (Underwrite). Then the other top-5 claims by rank. The first three, each citing its evidence (W11) |
| Key gates | the key gates' sentences (W12 when none, W25 when fewer than 3 gates are saved) |
| Deal terms | from the execution capacity review where it exists. The app does not run it (W13) |
| Top data gaps | the first three of §4 |
| Gates still needed | how many rows outside the top 5 need a gate (W14) |
| Inputs | first quarterly review; the two ratings, Strong · Adequate · Weak; the thesis: Plan · Evidence · Condition, each max 300 characters; "Download IC memo" (W21) |

No new analysis: every part is a register row, a gap row or a stored input.

## 7. IC memo (A11)
### 7.1 File
`GET /audits/{id}/memo.md` downloads `{company}_ic_memo.md` (text/markdown). It is built on request and never stored.
It is refused, nothing is written and the reason is named (W19) when: the top 5 is not confirmed; the verdict is
blocked; the key gates are not 3–5 (and the fewer-than-3 case of §3 does not apply); a rating or a thesis sentence is
missing; the results fail MetricsPayload (§9); a number is not in the stored data (§7.4); or the text has more than
1,500 words (§7.5).

### 7.2 Sections, in this order (W15)
Title "Investment committee memo: {company}" and a date line. The date is the export date; it is the only line the
number check skips.
1. Summary. The verdict and its rule, then W24. Files reviewed (data files and decks). Evidence categories covered,
   x of 7 (table below). Counts of Contradicted, Unsupported and Unverified claims over the whole register. Value at
   risk, ARR and cash separately, de-duplicated across overlaps, with the method stated: both "not yet computed"
   until #6 (W16).
2. Deal thesis. Three sentences labelled Plan, Evidence and Condition, written by the analyst (decision Q4). They are
   stored in `audits.ic_inputs.thesis`, never sent to a model or written to a log, and deleted with the audit.
3. Scorecard. Six rows: data reliability, growth engine, strategic coherence, forecast track record, execution
   capacity, defensibility. Each has a rating, a headline and key evidence.
   - Data reliability (assessed). Rating set by the analyst: Strong, Adequate or Weak (decision Q5); Python never
     rates. Headline: the revenue reconciliation gap and its window, the anomaly flag count, and Verified claims of
     all claims (W17). Evidence: `revenue_reconciliation`, `anomalies`, the register.
   - Growth engine (assessed). Rating set by the analyst, as above. Headline: the growth-engine narrative's headline
     when it is current and ok. Otherwise ARR, NRR and gross churn with the S17 note (rule 20). Evidence: `arr`,
     `nrr`, `gross_churn`, `cac_payback`, `acv_path`.
   - The other four: "Not assessed – {data not ingested}" (W17) in the rating column; the headline and evidence cells
     stay empty, and no rating is ever shown, even if one is stored.
4. Key gates and deal terms. The key gates' sentences (or W25), then W13.
5. Worth flagging. The banner's hard blockers when present, in their S16a–d texts. Then the `worth_flagging` items of
   the growth-engine narrative when it is current and ok, or the S17 note.
6. Data gaps and requests. Up to five gap rows ("and {n} more in Appendix B"), then the management questions (V6
   requests).

Evidence categories. A category is covered when a stored file of the type in the right-hand column exists. The app
ingests four types, so x is at most 4 today. Where a category is only partly met, Appendix D says what is missing.
| # | Category | Covered when |
|---|---|---|
| 1 | Monthly revenue by customer | a revenue file is mapped |
| 2 | CRM export | a CRM file is mapped |
| 3 | P&L and budget vs actuals | a P&L file is mapped; Appendix D notes that budget vs actuals is not ingested |
| 4 | Headcount history and hiring plan | not ingested by the app |
| 5 | Product usage data | not ingested by the app |
| 6 | Board decks, last 6–8 quarters | at least one deck is parsed; Appendix D notes that the app does not check which quarters the decks cover |
| 7 | Roadmap and hiring budget by segment/product | not ingested by the app |

Appendices:
- A. Claim register and gates. Every row, with value at stake (column "VaS"), overlaps, evidence, its gate and the
  key-gate mark, and the top-5 mark.
- B. Data gaps and data request list. Every gap with its target date and the first quarterly review. Then the
  requests: each gap's `unlocked_by`, the management questions, and each Missing Data item that is not a gap, with
  its `unlocked_by`.
- C. Detailed analysis tables. The xlsx export's data tables except Missing Data (that is in B), built by the same
  row code, plus revenue reconciliation by month when a P&L exists. Each table's caption carries its block's footnote.
- D. Source key list and value-at-risk de-duplication. Files reviewed, by evidence category, with the notes of the
  table above. Every footnote: analysis · source key · file · sheet · rows · rule. The overlap groups (§2.2) and the
  de-duplication method (W16). Then the AI usage and cost table (§8), the disclosure block (`app/disclosure.py`) and the
  glossary (`formatting.GLOSSARY`, as on the screen and in the export), which the "(see glossary)" pointers name.

### 7.3 Numbers and citations
- Format: `app/formatting.py` by the field's kind in the schema. Currency is whole with separators and the code,
  percents are whole, ratios have 2 decimals, days are rounded up at write time, CAC payback months have one decimal
  (`fmt_months`). Register figures are formatted by their unit. Cost is in USD with 2 decimals (W20).
- Citation: every number in sections 1–6 carries a Markdown footnote `[^n]`, resolved in Appendix D. A footnote names
  one of: analysis · source key · file · sheet · rows · rule; "claim register, #r"; "set by the analyst"; or "AI call
  log". A count's footnote names the register.

### 7.4 Number check
Every numeric token in the memo, appendices included, must be one of these, as stored or as `formatting.py` writes it:
(a) a value in `audits.results`, read with its kind; (b) a value of the audit document (target ARR, target date, as-of
month, company name); (c) a value of a register or gap row, computed on read by `claim_matching` and §4 from the
stored claims and results; (d) a stored structured analyst input (thresholds, dates) or a number in the analyst's
budget decision or gate metric name, which are the analyst's deal terms and are cited "set by the analyst"; (e) tokens
and cost from `llm_calls`; (f) a count of (c)–(e) the memo states (labels, files, gates, categories); (g) the fixed
numerals 5 (top 5), 7 (categories) and 12 (12-month). A number in a thesis sentence must be one of (a)–(c) or (e).
A table cell of Appendix C that the stored data does not hold passes only as the sum or the difference of two other cells of its row that it does hold (the export's totals and changes); a ratio or any other derived figure refuses the export. Any other number refuses the export. The refusal lists each such number for the analyst; the log line holds only
their count.

### 7.5 Word count
Words are whitespace-separated tokens holding a letter or a digit, counted from the title to the end of section 6.
Table pipes and heading marks are not words; a footnote marker counts as one word; appendices are excluded. 1,500
words pass; 1,501 are refused, and the refusal shows the count (W19).

## 8. Cost panel
`GET /runs/{id}/llm-usage` gains `by_step`. Each step has billed calls, cache hits, input tokens, output tokens and
cost. The steps are each narrative step by name, plus `structures` split into deck reading (`deck_id` set) and column
mapping (no `deck_id`). The steps sum to the existing totals. The Dashboard section "AI usage and cost" and Appendix D
show the same table (W20). The memo makes no call. On the Dashboard the section is the very end of the page, after every
analysis, the memo section (Verdict), the glossary and the disclosure (George, 2026-10-09).

## 9. Contract and data boundary
- MetricsPayload (H2 of interface-contracts.md): the verdict and the memo validate `audits.results` with
  `contract.validate_for_export` and the §3 unit check before they read a figure. A failure names the field paths and
  writes nothing. No engine output field changes, so `schemas/metrics.py` does not change. The contract test gains:
  a memo is built from the sample_data engine run; NRR written as 106.41 refuses the memo; every source key of §2.3
  is a declared path, shown failing on a deliberate wrong key.
- Data boundary (rule 14): no field of this spec enters a narrative slice or a gateway payload. The new log lines
  carry codes and counts only: `verdict: run_id outcome=<code> blocked=<bool> top5=<label counts> confirmed=<bool>`
  and `memo export: run_id status=<ok|refused> reason=<code> words=<n> unmatched=<count>`. They never hold a value,
  gate or thesis text, a gate metric name, a company name or a file name. `test_gateway_data_boundary.py` is extended
  for each.

## 10. Tests
Every new test is first shown failing on a deliberate violation (rule 11).
| Test | File |
|---|---|
| Each outcome: Underwrite; Underwrite with gates; Re-plan by a Contradicted claim (a miss, and a beat); Re-plan by 3 Unsupported; 3 Unsupported and 1 Unverified gives Re-plan; fewer than 5 rows; no rows gives no verdict | `test_verdict.py` |
| Top 5: no verdict before confirmation; the proposal is rows 1–5; a replaced row counts and the replaced one does not; a set of the wrong size is refused; a confirmed claim leaving the register voids the set; a new rank order does not; the banner still uses rows 1–5 after a replacement | `test_verdict.py`, `test_chat_upload.py` |
| Blocked: a non-Verified top-5 claim without a gate blocks; saving its gate unblocks; a Verified top-5 claim without a gate does not block; the memo refuses while blocked | `test_verdict.py` |
| Gate: the date starts empty and the gate is not saved without it; a no-metric row needs the metric name and direction; a sixth key gate is refused; a key gate on an unsaved gate is refused; with fewer than 3 saved gates every gate is key | `test_verdict.py` |
| Gaps: the gap list; an item computed from another file is a request, not a gap; the single-type table against `FIELD_DEFS`; a date after the review is refused | `test_verdict.py` |
| The memo refuses a number absent from the stored results (a narrative paragraph and a thesis sentence carrying "37%") and lists it; a number in a budget decision passes, cited "set by the analyst" | `test_ic_memo.py` |
| The memo refuses 1,501 words, shows the count and passes 1,500; appendices are not counted | `test_ic_memo.py` |
| Four "Not assessed" rows, never a rating, even when one is stored | `test_ic_memo.py` |
| Evidence categories: revenue, CRM, P&L and a deck give 4 of 7; revenue only gives 1 of 7 | `test_ic_memo.py` |
| W24 in the summary; the appendix titles A–D; every number in sections 1–6 has a footnote resolved in Appendix D | `test_ic_memo.py` |
| Rule 20: with no narrative, or a flagged one, the memo carries every figure with its footnote and the S17 note | `test_ic_memo.py` |
| The CSV round-trips (§5) | `test_claim_register_api.py` |
| `by_step` sums to the totals | `test_llm_gateway.py` |
| Contract and boundary (§9) | `test_interface_contracts.py`, `test_gateway_data_boundary.py` |
| Screen: the register columns, the Verdict section (top 5 pick and confirm, outcome, blocked, no verdict), Data gaps, AI usage and cost | `ClaimRegister.test.jsx`, `Dashboard.test.jsx` |

Measured on this branch with the claim-matching fixture (no network, no MongoDB), with the proposed top 5 confirmed:
run A gives Re-plan (rows 1–5 all Contradicted); run B gives Underwrite with gates (one row, Unverified, so blocked
until it has a gate); runs C and D give Re-plan. The outcome tests use subsets of the fixture's claims.

## 11. Screen wording (approved 2026-10-08: W1–W23 and W25 as drafted, W15's appendix titles per Q1, W24 as given)
Abbreviations (George, 2026-10-09): "Value at stake" reads "VaS" on the screen and in the memo (the register column, the
glossary). The first use of VaS, ARR, MRR, NRR or CAC in a text block (a help text, a note, a sentence, a memo paragraph
or list item) reads "ARR (see glossary)"; later uses in that block are plain. Labels, headings, column headers, table
cells, figures and footnotes are not text blocks and stay as they are. One helper on each side applies it at display
(`formatting.see_glossary`, `seeGlossary` in `frontend/src/lib/glossary.js`); the stored rows, the register and the CSV
are unchanged. So W16 and W24 below read "ARR (see glossary)" at their first ARR.
| Id | Where | Text |
|---|---|---|
| W1 | value at stake | not yet computed · shortfall {x}% (no shortfall: "not yet computed") |
| W2 | overlaps with | #3, #7 · none: — |
| W3 | evidence | {label} · {reason}, then {analysis} · {source key} ({observed at}); hover: file, sheet, rows, rule |
| W4 | gate needed | Gate needed |
| W5 | key gate | checkbox "Key gate"; a sixth: At most 5 key gates. |
| W6 | gate sentence, no observed figure | Before {decision}, {metric} must be at least (at most) {threshold} by {date}. Not yet observed: {reason}; claimed {value} ({period}). |
| W7 | data gaps | Title: Data gaps · columns: What the company cannot measure · Why it matters · Requested · Target date · field: First quarterly review · why: Blocks {analysis}; claims #{ranks}. {engine reason} · refusals: The target date must be on or before the first quarterly review ({date}). / Set the first quarterly review first. / The first quarterly review cannot be before a gap's target date ({date}). |
| W8 | verdict | Title: Verdict · Underwrite: All top-5 claims are Verified. · Underwrite with gates: No top-5 claim is Contradicted; {n} is (1) or are (2 or more) Unverified or Unsupported. · Re-plan: {n} top-5 claim(s) Contradicted. / {n} top-5 claims Unsupported (3 or more). · fewer rows: Top {n} (the register has {n} claims). |
| W9 | blocked | Verdict blocked: set a gate on #{ranks} (top-5 claims that are not Verified). |
| W10 | no verdict | No verdict: the register has no claims. / No verdict: compute the audit first. |
| W11 | reason | #{rank} {claim}: {label}, {observed} against {claimed} ({gap in app format}). Evidence: {analysis} · {source key} ({file} · {sheet} · {rows}). Unsupported: #{rank} {claim}: Unsupported, {reason}. No figure in the supplied files. |
| W12 | key gates | No key gates marked. |
| W13 | deal terms | Deal terms: not available – the execution capacity review has not been run. |
| W14 | other gates | {n} other claims still need a gate. |
| W15 | memo | Investment committee memo: {company} · Date: {YYYY-MM-DD} · Verdict: {outcome} – {rule} · headings: Summary · Deal thesis · Scorecard · Key gates and deal terms · Worth flagging · Data gaps and requests · Appendix A – Claim register and gates · Appendix B – Data gaps and data request list · Appendix C – Detailed analysis tables · Appendix D – Source key list and value-at-risk de-duplication · thesis labels: Plan · Evidence · Condition · ratings: Strong · Adequate · Weak |
| W16 | value at risk | Value at risk: ARR not yet computed (ARR bridge not run); cash not yet computed (no cash analysis). Overlapping claims are counted once, at the largest value in their group. |
| W17 | scorecard | Data reliability: Revenue file and P&L differ by {x}% over {first}–{last}; {n} anomaly flags; {v} of {N} claims Verified. (no P&L: "no P&L to reconcile") · Not assessed – strategy documents not ingested · Not assessed – past budgets and forecasts not ingested · Not assessed – hiring plan and organisation data not ingested · Not assessed – market and competitor data not ingested |
| W18 | narrative missing | S17, unchanged |
| W19 | memo refused | Memo not exported: {n} words; the limit is 1,500. / … {n} numbers are not in the stored results: {list}. / … the verdict is blocked. / … mark 3 to 5 key gates. / … rate {rows}. / … the stored results fail the contract: {fields}. |
| W20 | cost panel | Title: AI usage and cost (this audit) · columns: Step · Calls · Cache hits · Input tokens · Output tokens · Cost (USD), 2 decimals · last row: Total · steps: Narrative – {step} · Deck structure reading · Column mapping |
| W21 | button | Download IC memo (Markdown) |
| W22 | gate, no app metric | Metric (max 100 characters) · At least / At most |
| W23 | top 5 | Heading: Top 5 · proposed: Proposed by shortfall – confirm or replace. · per row: Replace with… (a register pick) · button: Confirm top 5 · no verdict: No verdict until the top 5 is confirmed. · void: A claim of the confirmed top 5 left the register – confirm the top 5 again. · memo refused: … confirm the top 5. |
| W24 | top 5 (as given) | Top 5 set by the analyst pending ARR bridge. |
| W25 | fewer than 3 gates | {n} gates set; all are key gates. |

## 12. Decisions of 2026-10-08
| # | Question | Decision |
|---|---|---|
| Q1 | The method's lists | The method text stays out of the repo. Categories, appendices, thesis labels and rating scale as given (§7.2, W15) |
| Q2 | What counts as a key gate | Any saved gate, Verified rows included; the analyst marks 3–5; fewer than 3 saved gates: every saved gate is key and the memo says so (§3) |
| Q3 | A gate on a claim with no app metric | The analyst types the metric and picks at least or at most; stored beside the budget decision, never sent to a model or a log, deleted with the audit (§3) |
| Q4 | Who writes the thesis | The analyst, max 300 characters each; a number in it must be in the stored results; budget-decision numbers are the analyst's deal terms (§7.2, §7.4) |
| Q5 | Who sets the ratings | The analyst, Strong · Adequate · Weak, on the two assessed rows; the memo refuses without them (§7.2) |
| Q6 | Wording W1–W22 | Approved as drafted |
| R | Ranking | The app pre-sorts by shortfall; the analyst confirms or replaces the top 5, stored as an analyst decision; the memo states "top 5 set by the analyst pending ARR bridge" (§6.1) |
| D1 | Banner and the analyst's top 5 | Approved: the banner keeps the pre-sort's rows 1–5 (§6.1) |
| D2 | Evidence categories covered | Approved: counted from the stored file types; partial coverage noted in Appendix D (§7.2) |
| D3 | Where the cost table goes | Approved: Appendix D, with the disclosure block (§7.2) |
| D4 | When a confirmed top 5 is void | Approved: only when one of its claims leaves the register (§6.1) |
| W | W23, W25 | Approved as drafted |

## 13. Decided (engineering, rule 19)
- Re-plan is checked first (§6.2). With fewer than 5 rows, the top 5 is every row. With no rows there is no verdict.
- The confirmed top 5 always holds min(5, rows) claims. A claim leaving the register voids it; a new rank order does
  not. The banner keeps the pre-sort's rows 1–5, so an analyst's choice never hides a hard blocker.
- A category counts as covered from the stored file types (§7.2). Partial coverage (P&L without budget vs actuals,
  decks of unknown quarters) is noted in Appendix D, not counted as half.
- Appendix D also carries the cost table and the disclosure block, since the request put the cost there. Appendix C
  reuses the xlsx export's table code.
- The order of the three reasons (§6.4), the overlap rule (§2.2), the gap list and its single-type proof (§4), and the
  gap order.
- Value at risk would be counted once per overlap group, at the group's largest value. Nothing is computed until #6.
- Citations are footnotes, so the 1,500 words hold the text and Appendix D holds the sources. The word rule is §7.5.
- The number check accepts counts and register figures computed on read from stored data (§7.4 c, f), because the
  register is never stored (claim-matching §6).
- The verdict, the gaps and the cost table are Dashboard sections, not a page (§1).

## 14. Consequences to know
- The pre-sort puts every row with a gap first, so Unsupported rows and forecasts ("to go") rank after every tested
  row. Measured: run A without its 8 Contradicted rows proposes a top 5 that is all Verified. Its 7 Unverified rows
  (the FY2026 ARR forecast among them) and 8 Unsupported rows rank 12 to 25. They reach the top 5 only through the
  analyst's replacement (§6.1).
- Every memo reads "not yet computed" for value at risk until #6, "Not assessed" on 4 of the 6 scorecard rows, and
  at most 4 of 7 evidence categories.
- Run B (a single Unverified claim) is blocked until its gate is saved.

## Files
`backend/app/verdict.py`, `backend/app/ic_memo.py`, `backend/app/claim_matching.py` (fields, gate),
`backend/server.py`, `backend/app/llm/gateway.py` (`by_step`); `frontend/src/components/ClaimRegister.jsx`,
`frontend/src/lib/claimRegister.js`, `frontend/src/pages/Dashboard.jsx`, and new `Verdict.jsx`, `DataGaps.jsx`,
`UsagePanel.jsx`; the tests of §10.

## Done when
- §10 passes, and so does the full suite.
- The run A fixture, with its top 5 confirmed, its gates, key gates, ratings and thesis set, exports a memo of 1,500
  words or fewer in which every number in sections 1–6 has a footnote.
