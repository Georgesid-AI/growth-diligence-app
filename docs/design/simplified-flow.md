# Design note: the simplified flow

Status: draft for decision, 2026-10-24; Audit page order, label definitions, assumptions strip and top-5 ranking added 2026-10-25. Built in part 2 (behaviour, 2026-10-25): the top five selected by the app, claims entered without approval, gates from the claim, computed ratings, no export blockers, the analyst note, the label rules, contract 9. Part 3 (the Upload & Mapping set-up, the question cards' Fix control, the claims table folded into the register) is not built. Source: George's direction of 24 Oct 2026: from now on the
app only removes and simplifies its interface; no computation is lost. The eight removals are decided; this note says what each
one looks like on the screen and what it touches. Every engine field (`backend/schemas/metrics.py`) and every memo section
(verdict-and-memo.md §7.2, Appendices A–D) stays.

**Architecture note (CLAUDE.md rule 1).** Two sentences of docs/architecture.md stand in the way of removal 1: "The analyst
approves, edits or rejects every claim; nothing enters the claim register on its own" (Evidence method) and "Claims within
tolerance are approved by the analyst's Run audit press ... Nothing is approved without that press" (Data boundary). Under the
new flow Python enters every claim it matched to its page and tested against the data; the analyst is asked only where a check
failed or a question is open. Rules 16, 17 and 18 hold as written (Python still matches every value to a source cell; an
unmatched value is a question, never a row). Nothing of removal 1 is built until George rewrites those two sentences (decision 1).

## 0. Challenge and deletions (rule 4)

Needed: a TestCo run takes 23 clicks today, most of them confirmations of things Python already knows (approve a matched
claim, confirm a proposed top 5, fill a gate from prefilled fields, confirm a column mapped at 95). The simpler version: Python
decides where it can, asks where it cannot, and shows its reasons. Deleted first: the Review page, the approval buttons and
counts, the gate form, the top-5 picker (replaced by a one-line change link), the two rating selects, the two judgment fields, the per-column mapping tables.

## 1. Screen by screen

### Upload & Mapping
Set-up: Target ARR, Target date and currency stay visible. Every other control (FX settings and the rest) sits under **"More
settings"**, each with its default. The consent tick and its explainer, the file box, the Run audit button and its three stages
at the bottom are unchanged. Removal 8 changes the file bubbles:
- **P&L**: four lines, one per field the engine needs (`growth_engine.ANALYSIS_NEEDS["cac_payback"]` plus the reconciliation's
  revenue line): Revenue, Cost of revenue, S&M, EBITDA, each as `"{row label}" (row n) read as {field}` with a **change** link
  that opens today's candidate list. The month column and the unit note (x1,000) sit on the caption line. "Show all lines"
  opens the full statement map of §26 unchanged.
- **Revenue file**: one summary line built from today's S31 parts: "Customer revenue · 36 months to Jun 2026 · EUR · revenue row
  'Total revenue' (row 12)", with **change**. "Show all lines" opens S31a–S31l as today.
- **CRM**: unchanged (its table is already one line per required field).
- **Decks**: the deck line "N pages parsed · M with figures · AI read: done, n read" stays; the claims table of the deck panel is
  folded into the register (decision 7); Add claim and Add from deck stay beside the line.
A column, row or type that waits for an answer is not asked here: it becomes a card (§2). The status line S13 reads "Ready –
press Run audit" or "{n} questions wait on the Audit page".

### The question cards
One box at the top of the Audit page, under the hard-blocker lines (rule 21), headed **"{n} claims need a word from you"**
("1 claim", or hidden at 0). Questions appear only when the answer can change a result or resolve a failed check (§2). The box
shows the three questions with the most ARR at stake; the rest sit under an **"n more questions"** link, and there is no link
when there are three or fewer. One card per question, each with the claim as the register prints it, the page reference, the
question in one sentence and its closed answers (the same answers the row offers today: Yes / No, Revenue / Volume, MoM / YoY /
Annualised / Cumulative, a period or metric pick, Keep / Fix / Not a company claim). "Fix" opens the editor of
claim-types-and-correction.md §3 unchanged. A mapping card ("Is 'Cost of sales' the cost of revenue?") sits in the same box
with Yes / No / Change. Cards are ordered by ARR at stake, then by rank. An answer closes the card,
re-matches the claim (as today) and never deletes anything: a rejected claim stays stored, status rejected.

### The Audit page
Order, top to bottom. Nothing is added that the engine does not already compute; no new page, no chat UI, no memo editor.
1. **Hard blockers** (rule 21), when there are any, above everything. The contradiction lines of rule 21 sit next to the
   conclusion (item 3), not above the register; the register is under Supporting detail (item 7) and keeps row labels only.
2. **Assumptions strip** (decision 9): one compact, read-only line above the results with currency, reporting period, target
   ARR, target date, as-of month and FY end, each showing its stored value (a defaulted as-of month is marked "default"). One
   **Change** link opens the settings on Upload & Mapping, where the fields are edited and saved as today; nothing else is added.
3. **Conclusion** (the conclusion screen below): the outcome, the one line that explains it and the scope sentence, then the contradiction lines. When a
   top-5 claim is **Contradicted**, that claim is shown directly next to the conclusion, in the same block, whatever its rank
   in the five.
4. **The five selected claims**, one row each, read **Plan assumes · Evidence shows · Result**: the claimed figure and period;
   the observed figure and month; the status of evidence-labels.md. Each row carries a **source link** (the citation: file,
   sheet, rows; the deck page for the claim) and a **Details** toggle that opens today's second line (segment, metric,
   tolerance, basis and case, flags, VaS, the gate, the lineage). The selection wording is the scope sentence of the conclusion (George, 2026-10-25: said once, no second line under "Other contradictions"); the single **Change** link of the conclusion screen stays. The five are chosen
   by the rule of §3.
5. **Needs your attention**: the question box above, at most three questions, each answerable in place, with the "{n} more"
   link to the rest. At 0 it is hidden. Top-5 questions come first, so the count never hides one.
6. **Download report** (the IC memo) with one optional **Analyst note** beside it (max 1,000 characters, stored as
   `ic_inputs.note`, never sent to a model).
7. **Supporting detail**, one collapsed section holding all other detail, in today's order: metric cards · **Claim register** · **Data gaps** · **Verdict detail** · narratives · Data integrity · analysis cards ·
   glossary.

- **Claim register** (removal 5, inside Supporting detail): four columns, Claim (rank, name, claimed figure, period; page in
  grey) · Observed (figure, month; citation on hover) · Result (the five statuses of evidence-labels.md, "(beat)" kept) · Why
  (one plain sentence: the gloss where a gap exists, else the reason). A **details** toggle per row opens the second line of
  today: segment, metric, tolerance, extraction confidence, basis and case, flags, VaS, overlaps, the gate, and the lineage
  (analysis · source key · file · sheet · rows · rule). Every row carries **wrong? fix**, which opens the same editor. Rows with
  a card are listed in the cards, not here. "Download baseline (CSV)" stays; the CSV keeps every field.
- **Verdict detail** (removals 2, 3, 6, 7, inside Supporting detail): the five claims with their results; the three reasons
  (W11); **Key gates**: the gates of the non-Verified top-5 rows, each ending "(proposed)" until the analyst edits it here
  (threshold, date, metric, direction; the edited gate reads "set by the analyst"). Every non-Verified claim has one gate; the
  gates of rows outside the five are in the register's details. Gates are edited in this section only. The budget-decision field
  is available there and never required before the analysis is shown; "Deal terms" W13; the top three data gaps; **Ratings**,
  computed automatically, two lines "Data reliability: Strong (Reliable; 4 of 5 checks)" and "Growth engine: Adequate (NRR 104%,
  gross churn 11%, CAC payback 14 months)" or "not rated – data missing"; any rating that uses an industry threshold carries the
  label **"benchmark, not company data"**, and the definitions and method sit under **details**; **Reasons** and **Unresolved
  questions** as computed lists.

#### The conclusion screen
The conclusion is the wording of docs/specs/claim-review-conclusion.md §2 (15 Oct 2026), the same words in the app and the memo.
It is always computed and shown; an open question is a count on the explanation line, not a state. The screen has these elements:
1. **The outcome**, one of: **Selected claims supported** (all five Verified) · **Selected claims partly supported** (every other
   case) · **Selected claims not supported** (at least one selected claim is Contradicted) · **Insufficient evidence** (no claim
   Contradicted and 3 or more of the five untested). Precedence: Contradicted, Insufficient evidence, Supported, Partly
   supported. Untested = Unverified, Inconclusive or Unsupported. The phrases "Evidence supports the plan", "Evidence supports
   the plan with conditions" and "Evidence does not support the plan" are not used anywhere.
2. **One explanation line**, the spec's rule text: "{n} selected claim is (are) Contradicted." · "No selected claim is
   Contradicted; {u} of {N} are untested (Unverified, Inconclusive or Unsupported)." · "All {N} selected claims are Verified." ·
   "No selected claim is Contradicted; {v} of {N} are Verified, {u} untested." Add "1 question open." only when a question is
   open. Then the scope sentence, word for word: "This assesses the five claims selected by the app by value at stake; the analyst may change the selection. It is not an investment recommendation."
3. **Contradiction lines** (rule 21), directly under the explanation: a Contradicted top-5 claim, and "Other contradictions"
   (every Contradicted register row outside the five, by rank, with its metric, gap and source; none: "None found among tested
   claims."). The register under Supporting detail repeats none of this: it keeps row labels only.
4. **One "Change" link**, which opens today's replace list for the top 5 (item 4 above carries the selection wording).

Top-5 block: one plain sentence explaining the selection ("Selected by the app by value at stake; the analyst may change the
selection"), then the single "Change" link; a changed set reads "Top 5 changed by the analyst — reset".

When the register is empty (no testable claims found) the screen shows no outcome and one message: "No testable claims found.
Upload a deck or plan with revenue targets."

**details** (on the conclusion screen) holds one sentence of the outcome rule.

**Evidence labels.** Five labels keep their names everywhere: Verified, Unverified, Unsupported, Contradicted, Inconclusive. One
standard definition each, from one shared string that the frontend and the memo import (decision 10):
- **Verified** — the raw data confirms the claim.
- **Unverified** — management stated it in the deck or plan; the data to test it is not in the data room.
- **Unsupported** — the plan depends on it, but nobody has stated it and nothing backs it.
- **Contradicted** — the raw data shows the claim is false.
- **Inconclusive** — a test ran but cannot confirm or contradict the claim (evidence-labels.md §3).

Every label shows its definition on hover, wherever it appears (the five rows, the register's Result column, the cards, the
memo's Summary and Appendix A). All five definitions are printed in full once, under the five findings. Unverified never counts
as Unsupported; Inconclusive counts as untested.

### The memo
Sections and appendices unchanged. The lines that change: Summary prints "Verdict: {conclusion wording} – {rule}" with the
same four outcomes as the conclusion screen; the glossary carries the five label definitions above; the Scorecard's two rated rows print the computed rating, then the
rule line with its figures ("Strong: every completed check Green, 4 of 5 completed"), "not rated – data missing" with the missing input
named; Key gates prints the gates with "(proposed)" or "set by the analyst"; the 3-sentence deal thesis is generated automatically as an
editable draft and no writing is required before export; Analyst judgment prints the computed Reasons
and Unresolved questions, then "Analyst note: {text}" when one exists. Appendix A's Approval column reads "auto" for a row
Python entered and "analyst" for a row the analyst answered or fixed. Refusals that go: top 5 not confirmed, verdict blocked,
3–5 key gates, ratings missing, judgment missing, thesis missing. Refusals that stay: the number check, 1,500 words, the contract.

## 2. The rule for which questions reach the user

A claim or column raises a card when, and only when, one row of this table holds. Everything else is decided by Python and shown read-only.

| Source | Card when | Answers | Closes with |
|---|---|---|---|
| Page read (`checker.REVIEW_FLAGS`) | the claim is "AI suggestion, not matched", or carries a review flag (value, sign or period not on page, period is a range, growth dated to start year, scenario label not on page, use-of-funds share, acquisition channel, turnover not revenue, year under bar differs, pipeline column, axis tick, not a plan line, basis and scenario disagree) | Keep · Fix · Not a company claim | status approved / edited / rejected |
| Page read, a correction (claim-matching.md, Amended 2026-10-26) | a check offers more than one candidate for the field it failed on (a period the page's headings state twice); with exactly one the app applies it ("Corrected: ..." with Undo, no card) | one button per candidate · Keep · Not a company claim | the field set, status approved |
| Population (Users, User growth) | the label names none or several of paying, registered, active | Paying customers · Registered users | the stored population |
| Informational flags (`INFORMATIONAL_FLAGS`, "year label below") | never: a note in the row's details | – | – |
| Matching (claim-matching.md) | Definition check open (§4.1); turnover Revenue / Volume (§11); churn rate unclear; FX rate needed; required field unknown (period, currency, population); growth basis unknown after the text default | the row's closed answers of today; FX opens the FX settings | the stored answer, as today |
| Scenarios (`best`, `worst`) | never: listed in the register as Unverified, as today | – | – |
| Column mapping | a required field of `ANALYSIS_NEEDS`, the revenue essentials or the four P&L lines has no proposal, two candidates, or a proposal under 80 whose name differs from the field (§18's name test) | Yes · No · Change | `action: confirm` or `correct` |
| Recognition (S31) | a "choose" reason (`no_candidate`, `tie`, `after_as_of`, `not_a_period`, `rules_and_model_disagree`, `type_unsure`, `turnover_question`) | the S31 candidates | as today |
| Confirm-only reasons (`confidence_80`, `no_as_of_month`), a saved mapping, a rules match at 80 or more | never: accepted silently, listed under "show all lines" | – | – |

"Changes a result" means: the answer can change an engine block, a register row's status, the top 5 or the verdict. A question
that cannot (an informational flag, a confirm-only reason) is never asked.

## 3. Engine outputs behind each computed element

| Element | Reads | Rule |
|---|---|---|
| Top 5 ("the five selected claims") | register rows: `claim_type` in `verdict.PLAN_TYPES`, `value_at_stake_arr`, `claimed_converted`, `claimed_value`, `evidence_label` | ranking = value at stake (VaS) first, then normalised shortfall (decision 11, reversed); memo wording "Selected by the app by value at stake; the analyst may change the selection"; the set is in force without confirmation; the banner reads the five in force (the app's selection or the analyst's changed set) |
| Verdict | the five rows' `evidence_label` | always computed, never blocked; wording of the 15 Oct conclusion spec (claim-review-conclusion.md §2): Selected claims not supported (any Contradicted) · Insufficient evidence (no Contradicted, 3 or more of the five untested) · Selected claims supported (all five Verified) · Selected claims partly supported (else); codes `not_supported`, `insufficient`, `supported`, `partly_supported`. Untested = Unverified, Inconclusive or Unsupported. An open question is an "n question open" count on the explanation line, not a state. Empty register: no outcome, one message |
| Gate (template) | per non-Verified claim: `metric` (else `claim_name`), `direction` (higher → at least, lower → at most; none → at least, at most for churn, cost, burn, CAC, payback, sales-cycle types), `claimed_converted` or `claimed_value` in the claim's unit, `period_end`, `ic_inputs.first_quarterly_review` | status proposed; date = period end, else the review date, never later than it; sentence W6 without "Before {decision}"; `gate_needed` is always false; an analyst edit stores the gate as today (`claim_inputs`) and wins |
| Gates | one per non-Verified claim (all rows) | the template above |
| Key gates | the gates of the non-Verified top-5 rows | never padded: a Verified top-5 row has none, and gates of rows outside the five are not promoted; fewer than 3 prints W25 as today |
| Reasons | `verdict.reason_text` of the lead rows (W11), then `other_contradictions` | the three reasons, then "Other contradictions: ..." |
| Unresolved questions | `verdict.top_gaps` (from `missing_data`), open cards (count and claims), `integrity` Blocked checks, `questions_for_management` | one list, in that order, five lines then "and n more in Appendix B" |
| Rating, data reliability | `integrity.conclusion` | Reliable → Strong · Needs clarification → Adequate · Material concerns → Weak · Insufficient assessment coverage → not rated – data missing |
| Rating, growth engine (carries "benchmark, not company data") | `nrr.overall_pct`, `gross_churn.overall_pct`, `cac_payback` headline months (`metric_periods` for each figure's month) | the Dashboard's own thresholds: green = NRR ≥ 100%, churn ≤ 8%, payback ≤ 12 months; red = churn > 15% or payback > 18; Strong = NRR, churn and CAC payback all present and green · Weak = churn or payback red · Adequate = else (CAC payback absent is never Strong); NRR or churn absent → not rated – data missing (decision 5) |
| Data gaps (memo) | `missing_data` gaps, then the never-tested register rows (`claim_matching.is_untested`: use of funds, acquisition channels, pricing, unit economics, pipeline, best and worst cases, forecast-file figures) | every never-tested row is a row of the memo's Data gaps table (Appendix B) as "#{rank} {claim}" with "Cannot be measured: {the row's reason}", and one line in section 6 counts them; they carry no gate, no request and no target date; the screen's Data gaps table is unchanged |
| Growth basis | the claim text (chat-upload.md §29 point 5) | built; a basis still unknown is a card |

## 4. Specs and CLAUDE.md rules that change

| Document | Section | Change |
|---|---|---|
| docs/architecture.md | Evidence method; Data boundary (Run audit press) | the two sentences above (decision 1) |
| CLAUDE.md | – | no rule changes wording. Rule 14: the new reason strings, card texts and log lines extend the boundary test. Rule 19.3: the eight removals are George's screen decisions of 24 Oct. Rule 23: unchanged; rule 21 is rewritten in the build PR (§9) |
| deck-parser.md | §6 Approval | Approve / Edit / Reject, Add claim text, status column, the claims table → the register and the cards |
| chat-upload.md | §17 Approve all; §18 mapping summary; §24 Review tab; §28 "Claims (n) / Review (m)" views, Approve all on flagged, S26 lines; §19 and §26 P&L table | removed or replaced by §1 above; the Review route redirects to the Audit page |
| claim-matching.md | §4.1 within-tolerance step and `auto_approval` meaning; §5 gate; §8 screen; §11 point 8 deck-list control | every matched, clean claim enters; `auto_approval` = "auto" for a Python-entered row; gate template; four columns and details; turnover asks in a card |
| verdict-and-memo.md | §3 gates (prefill, budget decision, Save all gates, key-gate mark); §6.1 confirm (W23, W24); §6.3 blocked (W9, W9b); §6.4; §7.1 refusals; §7.2 scorecard (Q5); W5, W6, W21–W25 | as §1 and §3 above; W24 goes ("set by the analyst pending ARR bridge" is false once the app picks) |
| claim-review-conclusion.md | §2 outcomes; §3 judgment fields and scope sentence; §5 five words | the 15 Oct wording is the wording of the conclusion screen and the memo; the scope sentence stays beside the outcome; the computed block replaces the judgment fields |
| backend/app/ic_memo.py (lines 399–408) | analyst judgment fields | **Build task, not in this PR:** the fields become optional and the memo exports without them. No code changes here |
| evidence-labels.md | §1 seven columns | four columns plus details; the two explainers move to the Result header and the details |
| integrity-coverage.md | §4 "The rating stays the analyst's" | computed from the conclusion |
| revenue-file-recognition.md | §7 S31 lines; one Correct button | one summary line; confirm-only parts accepted silently |
| dates-and-periods.md | §5 one-click task | the card |
| claim-types-and-correction.md | §3 editor | unchanged; reached through "Fix" and "wrong? fix" |
| prompt-store.md, llm-structure-reading.md | – | unchanged |
| interface-contracts.md | §1 version | built 2026-10-25: contract version 9 (the task of part 2 asked for the bump), so §5 below applies: results stored under 8 read "Stale – re-run audit" |

## 5. Stored audits on upgrade

Built with a contract bump (version 9, 2026-10-25) and a demo reseed: results stored under 8 read "Stale – re-run audit" until Run audit calculates again. The server shows the rest on every read of an audit without writing (a pending claim that qualifies reads as approved, "auto"); Run audit stores the entry, never a read.

| Stored | Becomes |
|---|---|
| `deck_candidates` status pending, matched, no review flag, no open question | approved, `auto_accepted` true: the register reads it at once; Run audit stores it, a read never does |
| pending with a review flag or an open question; approved, edited, rejected | unchanged; the first group is the cards |
| `claim_inputs` gates saved by the analyst, `definition_check`, turnover and growth-basis answers, metric and segment picks | kept; a saved gate wins over the template |
| `ic_inputs.top5` confirmed | kept as "changed by the analyst" when it differs from the proposal; equal → the proposal line |
| `ic_inputs.ratings` | kept in the document, no longer read; the computed rating shows |
| `ic_inputs.judgment` (reasons, unresolved_questions) | copied once into `ic_inputs.note` as "Reasons: ... Unresolved questions: ..."; the two fields stay stored |
| `ic_inputs.thesis`, `first_quarterly_review`, `gap_target_dates` | kept; the thesis is generated as an editable draft when empty |
| `audits.results`, `llm_*`, `column_mappings`, `prompts`, `access_tokens` | untouched; the stale rules of interface-contracts.md §7 apply as today |

## 6. Tests: retire and stay

| File | Retire | Stay or rewrite |
|---|---|---|
| `test_approve_all.py`, `AutoApproval.test.jsx`, `Review.test.jsx`, `review.test.js` | all: the endpoint, the toasts, the page | the mapping-card rule and the register-entry rule get new tests, failing first (rule 11) |
| `test_gate_prefill.py` | prefill, "prefilled – confirm", Save all gates, budget decisions | rewritten as the template's tests (threshold, date cap, direction, proposed → set by the analyst) |
| `test_verdict.py` | confirm, void, wrong size, blocked (W9, W9b), sixth key gate, key mark on an unsaved gate, ratings and thesis refusals | outcomes (the four of the 15 Oct spec), proposal, banner rows 1–5, gaps, CSV round trip, delete audit |
| `test_conclusion.py`, `Verdict.conclusion.test.jsx` | the five-words scan, the two required fields | the scope sentence, other contradictions, "Selected claims supported" cases kept as written |
| `test_ic_memo.py` | refusals for top 5, blocked, 3–5 key gates, ratings, judgment | number check, 1,500 words, Not assessed rows, categories, footnotes, VaS column, rule 20; new: rating line and figures, "not rated" |
| `test_issue_155.py`, `test_run_audit.py` (claims stage) | the "within tolerance only" narrowing, auto-revoke to To review | the claims stage counts; auto-revoke becomes "re-opened as a card" |
| `test_definition_check.py`, `test_turnover*.py`, `test_claim_types.py` | "Approve all approves an open check"; the Review-page paths | the answer paths, the editor, Add from deck |
| `ClaimRegister*.test.jsx` | seven columns, Set gate, Save all gates, Key gate checkbox | four columns, details toggle, wrong? fix, labels, widths at 1280 px |
| `DeckPanel*.test.jsx` | Approve / Edit / Reject, Approve all, the two views, the counts line | the deck line, Add claim, Add from deck, View page (decision 7) |
| `MappingWizard.test.jsx`, `RecognitionLine.test.jsx` | the S31 line set, the full P&L table by default | the four P&L lines, the summary line, show all lines, S13 |
| Engine, matching, checker, page check, gateway boundary, contracts, integrity, dates, recognition, allowance, access | none | all stay; `test_gateway_data_boundary.py` gains the card texts and the new log lines |

## 7. Acceptance criteria

1. A user reaches the result and the draft memo without confirming facts the app already established.
2. Every existing analysis stays accessible.
3. Questions appear only when the answer can change a result or resolve a failed check.
4. An edit updates the affected results without repeating completed work.

## 8. Open decisions for George

1. **Architecture note.** Rewrite the two sentences of docs/architecture.md (Evidence method; Data boundary) so Python may enter a
   matched, tested claim. Options: (a) "Python enters every claim it matched to its page and tested; the analyst answers the
   questions Python cannot" (recommended); (b) keep the sentences and keep approval, dropping removal 1.
2. **Verdict words.** Decided: the 15 Oct conclusion spec wording (Selected claims supported / partly supported / not supported /
   Insufficient evidence) on the conclusion screen and in the memo (§1); the "Evidence supports the plan" phrases and the A10 names
   are not used.
3. **"Insufficient evidence".** Decided: 3 or more of the five untested and no claim Contradicted (claim-review-conclusion.md §2); see
   the conclusion screen and §3 (Verdict row).
4. **Open Definition check.** Decided: the row counts as untested and the explanation line adds "1 question open."; the outcome is
   never blocked. See the conclusion screen.
5. **Rating rules.** The thresholds of §3 are the Dashboard's own colours, so nothing is invented. Confirm them, or name others.
   **Decided:** see ratings, §1 The Audit page (Ratings) and §3 (the two Rating rows).
6. **Deal thesis.** It stays a memo section and is the one typed input left. Options: (a) default the three sentences from
   computed text (Plan: Target ARR by Target date; Evidence: the verdict rule; Condition: the first key gate), editable
   (recommended); (b) keep it analyst-written and required.
   **Decided:** see the memo, §1 The memo.
7. **Deck panel claims table.** Options: (a) fold it into the register, the deck line and the add controls stay (recommended);
   (b) keep it read-only behind "show all claims".
   **Decided:** (a), the deck claims table folds into the register; the deck line and the add controls stay.
8. **Gates "editable in the memo only".** Read as: edited in the Verdict section that carries "Download IC memo", nowhere else.
   Confirm.
   **Decided:** see gates, §1 The Audit page (Verdict detail, Key gates) and §3 (Gate and Key gates rows); key gates are those of the top five, never padded.
9. **Assumptions strip.** Decided: read-only on the Audit page, with one "Change" link to the settings on Upload & Mapping (§1,
   item 2).
10. **Label definitions.** Decided: the definition on hover on every label, and all five in full once under the five findings (§1,
    Evidence labels).
11. **Top-5 selection.** Decided: ranking by VaS, then normalised shortfall (§3, Top 5 row). Reversed 2026-10-25 (review of PR #180): the
    Contradicted-above-Unverified key is removed; every Contradicted claim is shown in the contradiction lines, so the ranking needs no label.

## 9. Build PR: documents rewritten with the code

Rule 21 (CLAUDE.md) and the two claim-approval sentences of docs/architecture.md (Evidence method; Data boundary) are rewritten
in the build PR, not here. Rule 21 changes to: contradiction lines render next to the conclusion on the Audit page; other hard
blockers stay at the top of every audit view.
