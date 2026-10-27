# App plan V2 — amendments from the 15 October 2026 review

Date: 15 October 2026
Applies to: growth-diligence-app-plan_15_10_2026.md (P). This file replaces the sections named below. Everything else in P stays as drafted.
Assumption: P was not supplied for this rewrite. The replacements are written from the document facts quoted in the review. Where P says something different, this file wins.

Decision summary (from the review, kept as written):
- Keep D4.
- Keep D3, with the component definitions in section 7.3.
- Amend D5 and D6.
- Rewrite D1 and D2.
- Keep the three-release order.

---

## 1. D1 — Claim-review conclusion (replaces "Underwrite / Underwrite with gates / Re-plan")

**Heading on screen and in the memo:** "Claim-review conclusion — assessment of the five selected claims".

**Outcome values** (exactly one):

| Value | Rule |
|---|---|
| Selected claims supported | All five selected claims are Verified. |
| Selected claims not supported | At least one selected claim is Contradicted. |
| Insufficient evidence | No claim is Contradicted and three or more of the five are untested (Unverified or Unsupported). |
| Selected claims partly supported | Every other case. |

Order of precedence: Contradicted → Insufficient evidence → Supported → Partly supported.

**Always shown next to the conclusion:**
1. The scope sentence: "This assesses the five claims the analyst selected. It is not an investment recommendation."
2. "Other contradictions": every Contradicted claim outside the five, with its metric, gap and source. If none: "None found among tested claims."
3. "Analyst judgment" — two free-text fields the analyst fills, both required before memo export: (a) Reasons, (b) Unresolved questions. The app never pre-fills these and never generates a recommendation word.

**Memo:** the memo prints the conclusion value, the scope sentence, the other-contradictions list and the analyst judgment verbatim. The words Underwrite, Re-plan, invest, pass, proceed do not appear anywhere in app or memo output.

**Acceptance test:** a run with five Verified selected claims and one Contradicted unselected claim must show "Selected claims supported" and the contradiction in the same block, in app and in memo.

---

## 2. D2 — Data integrity: results and coverage (replaces the single integrity verdict)

The integrity screen has two blocks. Neither is folded into the other.

**Block A — Results of completed checks.** One row per check that ran: Check | Result (Green / Amber / Red) | Finding | Source. Only checks that actually ran appear here.

**Block B — Assessment coverage.** One row per check in the method (6 checks: revenue reconciliation, gaps in customer data, quarter-end clustering, smoothness, Benford on transactions, deck-vs-deck figures): Check | Status | Reason.

Status values:
- Completed
- Not applicable (e.g. Benford when no transaction-level file exists by design) — stated reason required
- Blocked — company data missing: names the file or field that would unblock it; this is a data request, not a negative finding
- Not available in the app: product limitation; printed as such, never as a company finding

Denominator: applicable checks only. Display: "Completed x of y applicable checks" plus the list of the blocked ones.

**Overall conclusion.** Values: Reliable / Needs clarification / Material concerns / Insufficient assessment coverage.
- An overall conclusion other than "Insufficient assessment coverage" requires: at least 4 applicable checks completed, and the revenue reconciliation check among them.
- Below that threshold the headline is "Insufficient assessment coverage (x of y)". It is not a negative company finding and the memo says so in one sentence.
- Reliable = all completed checks Green. Material concerns = any completed check Red. Needs clarification = otherwise.

**Acceptance tests:** (1) Two checks completed and Green, four blocked → headline must read "Insufficient assessment coverage (2 of 6)", never "Reliable". (2) Benford not applicable → it is not counted in y. (3) A check blocked by missing company data appears in the data request list.

---

## 3. D5 — Dates and periods (amends P D5)

Four separate fields, always shown separately, never merged into one date:

1. **Requested analysis date** — set by the analyst (defaults to today). Used only for the memo date and the "as of" label on the analyst's own text.
2. **Latest valid source period** — the last month in the revenue file with a valid date and at least one non-zero revenue row. Marked "Complete" only if the audit's As-of month is later than that month, or the analyst ticks "Last month is complete". Otherwise marked "Possibly partial" and excluded from growth and NRR calculations (shown, not used).
3. **Period and gaps per metric** — for every computed metric: first month, last month, and the list of missing months inside that range (a list, not a count). A metric with gaps inside the claim's period is shown with the gap list next to the value.
4. **Claim-period coverage** — for every matched claim: "Covered", "Partly covered (months missing: …)" or "Not covered". Only "Covered" claims can be Verified or Contradicted. Partly covered → Inconclusive (section 5). Not covered → Unverified with reason "claim period not in supplied data".

**Override rule.** The analyst may change the requested analysis date. The override never changes any metric's period label and never produces a value for a period the data does not cover. Every metric value carries its own period label on screen and in the memo; the requested analysis date is never printed next to a value.

**Growth definitions.** Before a growth claim is matched, its basis must be one of: month-on-month, year-on-year, annualised (from the stated window), cumulative over the stated window. The parser sets the basis from cues (MoM, m/m, monthly; YoY, y/y, annual, per year; CAGR, annualised; "since", "over"). No cue → basis Unknown → the claim stays Unverified with a one-click "Set growth basis" task. The engine computes all four bases for the period and shows the one matching the basis.

**Regression test (required in Release 1):** revenue file ending June 2019, machine date October 2026. Expected: latest valid source period "June 2019 (Complete)", every metric labelled to June 2019, memo header "Evidence to June 2019", the string "2026" appears only in the requested analysis date and the memo date. The original failure (June 2026 shown against June 2019 data) is the failing case.

---

## 4. Claim types, required fields and the correction path

**Required fields by claim type.** Every field holds a value, "Unknown" or "Not applicable". Only fields marked R are required before the claim can be matched; the others may stay Unknown.

| Claim type | Metric | Value | Unit | Currency | Period | Population | Figure type (Actual / Target) | Growth basis |
|---|---|---|---|---|---|---|---|---|
| Revenue / ARR / MRR / Transaction volume | R | R | R | R | R | – | R | – |
| Growth rate | R | R | R (%) | – | R | – | R | R |
| Customers / users | R | R | R (count) | – | R | R (paying / registered / active) | R | – |
| NRR / churn / retention | R | R | R (%) | – | R (window) | R (cohort) | R | – |
| Sales cycle / win rate / pipeline | R | R | R | – | R | R (deals won / all closed / open) | R | – |
| Costs / burn / runway / cash | R | R | R | R | R | – | R | – |
| Unit economics (ltv, cac, ltv_cac, customer_lifetime, trials_per_day) | R | R | R | R for a money value | R | – | R | – |
| Headcount / hiring | R | R | count | – | R | optional (team) | R | – |
| Launch date | item name | date | – | – | – | – | R | – |
| Market size | R | R | R | R | optional | – | – | – |
| Use of funds | category | share % | – | – | – | – | – | – |
| Acquisition channels | channel | count | count | – | optional | – | – | – |
| Other | text only | – | – | – | – | – | – | – |

**Other:** a figure the parser cannot type is Other and never a task (decision of 15 Oct 2026). Claims typed Other (e.g. "15 months", "3 tiers") are excluded from matching, value at stake, top-5 candidates, review tasks and the hard-blocker banner. They are shown collapsed as a count ("12 other figures") and never generate a task. Retyping a claim out of Other puts it back into matching.

**Editor.** The inline editor edits every field in the table above, including Figure type (Actual / Target) and Growth basis. Each change keeps the reason code and records who changed it and the previous value (provenance unchanged).

**Recovery of a missed claim ("Add from deck").** The analyst opens the deck page view, selects a sentence, table cell or chart label, and clicks "Add from deck". The app creates the claim with source deck, page and the selected text stored verbatim as its source, tagged "Added from deck by analyst". It is then typed, matched and labelled like any other claim. The existing "Add claim" (manual entry for figures in pictures) stays and keeps its "Added by analyst" tag. Free typing of a claim with no source remains impossible.

**Acceptance tests:** (1) A claim extracted as Target but actually Actual can be corrected in the editor and re-matched. (2) "15 months" typed Other creates no task and does not appear in the review list. (3) A sentence missed by the parser can be added from the deck page and shows its page as source.

---

## 5. Labels: extraction confidence and evidence status (replaces "Read: High/Medium/Low")

Two labels, shown as two separate columns, each with a hover explainer.

**Extraction confidence: High / Medium / Low.** How reliably the parser read the figure, label and date from the deck. Says nothing about whether the claim is true. Explainer text: "How confidently the app extracted and linked the figure to its source. This does not verify the company’s claim."

**Evidence status (within the supplied evidence).** Explainer text: "How this claim compares with the company data supplied for this audit. Agreement is not independent verification."

| Status | Meaning |
|---|---|
| Verified | Tested against supplied company data; within tolerance (beat shown as "(beat)" and flagged, per 13 Oct rule). |
| Contradicted | Tested against supplied company data; claim misses by more than tolerance. |
| Inconclusive | A test ran but cannot confirm or contradict the claim: claim period only partly covered, or population differs (e.g. registered vs paying). A row is Inconclusive only when a test ran: it always shows the computed figure and the reason. Amended 15 Oct 2026 (George, decision 2): an unknown growth basis is Unverified, because no test can run without a basis (section 3). |
| Unverified | Testable metric, but the supplied files do not cover it (company data gap) or an analyst answer is pending. Reason shown. |
| Unsupported | The app does not compute this metric (product limitation). Never counted as a company finding. |

Memo summary counts Inconclusive together with Unverified under "Unverified claims", with the Inconclusive count in brackets.

**Acceptance test (required):** a claim with High extraction confidence that is Contradicted by the revenue file must show "High" in one column and "Contradicted" in the other, with the computed figure and gap. This test replaces any test that only checks label placement.

---

## 6. D6 — Access and deployment (amends P D6 and the deployment instruction)

**Access model (tester phase, on Emergent).** Identity = possession of a per-tester token link. This is stated on the tester page: "Your link is your login. Anyone with the link can open your audits." Ownership = the token that created the audit. Magic-link accounts replace tokens at the AWS move (unchanged).

Token rules: random, 32 bytes, stored hashed; one token per tester; expiry 30 days; the owner token can revoke or re-issue any tester token; a revoked or expired token is refused on every route.

**Authorization matrix.** Every API route checks that the audit belongs to the request token: list audits, read audit, read results, upload file, download or view a file, edit claim, edit mapping, edit set-up, run calculation, run narratives, generate memo, export CSV/xlsx, delete audit. A wrong token gets 404 (never reveals that the audit exists). No token or an invalid token gets 401. The owner token sees usage totals only and cannot open any audit, file or result (product stance "we cannot see your deals" is unchanged).

**Tests required before tester deployment:**
1. No token → 401 on every route above.
2. Tester A's token on tester B's audit id → 404 on every route above, including file download, memo and export.
3. Expired token → 401; revoked token → 401.
4. Owner token on any audit route → 404.

**Deployment instruction.** Decision (George, 15 Oct 2026): the repository stays public. Emergent imports from GitHub only and cannot push back, so the repo holds source code only. Standing rules that make this safe remain: no .env, no client data, no methodology prompt text in the repo (CLAUDE.md). The review's request to remove the public-repo step is noted and declined on these grounds.

**Data inventory before deployment.** "Nothing real is in the app yet" must be confirmed, not assumed: list every audit in the deployed app and every stored file, confirm all are synthetic (TestCo) or public-deck (Zero2Hero) data, delete them, and record the result in the session log before testers receive links.

---

## 7. Release acceptance criteria

Each release is accepted on observable outcomes. Click counts stay as secondary measures only.

### 7.1 Release 1 — correct numbers, correct labels, correct access

Required tests, in addition to the existing calculation cases:
- Date regression: the June 2019 / June 2026 case (section 3).
- Sparse integrity coverage: 2 of 6 checks completed → "Insufficient assessment coverage" (section 2).
- Contradicted unselected claim shown next to "Selected claims supported" (section 1).
- High-confidence but Contradicted claim (section 5).
- Growth-period ambiguity: "15% growth" with no cue → Unverified with "Set growth basis"; with "YoY" cue → matched on the year-on-year basis only.
- Wrong-token, no-token, expired-token and owner-token access tests (section 6).
- Other-typed claims create no tasks (section 4).

### 7.2 Release 2 — the analyst understands what they see

Tester tasks (each pass/fail, observed on a TestCo run by a tester who has not seen the app):
1. State the reporting period of the evidence and whether the last month is complete.
2. Explain in one sentence the difference between extraction confidence and evidence status for one claim.
3. Correct a mistyped claim (type, figure type and growth basis) and see it re-matched.
4. Locate the deck page for any claim in under 30 seconds.
5. Reach the memo without being asked for a rating before the narratives are written. Scorecard ratings default to "Not rated" and are requested only after "Write all narratives" has run.
6. Change one claim, one mapping or the As-of month and see every dependent result and memo section marked "Stale — recalculate"; memo export is blocked until recalculation.

Click count on a clean TestCo run is recorded, not a pass criterion.

### 7.3 Release 3 — growth drivers with defined inputs (D3 component definitions)

Build nothing until these definitions are in docs/specs/.

**MRR bridge.** Inputs: the mapped revenue file, with per-customer monthly amounts.
- Recurring eligibility: a row counts as recurring if its mapped revenue type is recurring, or, when the file has no type column, if the same customer has revenue in at least 2 consecutive months. One-off rows are excluded from the bridge and shown as a separate line.
- Customer identity: the mapped customer ID; if absent, the normalised customer name (trimmed, case-folded). The identity rule in use is printed on the bridge.
- Components, per month, in reporting currency: Opening MRR + New + Expansion − Contraction − Lost (churned) + Reactivated = Closing MRR.
- Lost = customers with MRR > 0 in the prior month and 0 in this month (whole balance).
- Contraction = decrease in MRR for customers present in both months.
- Reactivated = customers with 0 MRR for 3 or more consecutive months who show MRR again; shown as its own component, never as New.
- Contraction and Lost reconcile to the bridge in currency and as percentage points of Opening MRR. Customer counts (number lost, number contracted) are shown as context next to the amounts, never as the headline.
- Gross revenue churn = (Contraction + Lost) ÷ Opening MRR over the window; the window is stated.

**Sales metrics.** Data requirement: CRM export with deal id, created date, close date, stage, amount, owner, founder-involved flag. Definitions: median sales cycle = median calendar days from created to closed-won, won deals closed in the window only; win rate = won ÷ (won + lost) for deals closed in the window, open deals excluded; founder win rate = the same split by the founder-involved flag. A missing flag → founder win rate is Unverified with the flag named as the data request.

**Acceptance tests:** bridge components sum to Closing MRR for every month of the TestCo file; a reactivated customer appears under Reactivated, not New; Contraction and Lost amounts match the percentage points shown.

### 7.4 Scenarios

Purpose: let the analyst change one input (target ARR, target date, FX rate, growth basis, last-month-complete flag) and see which results change. Minimum behaviour: each scenario shows the changed input and the before/after values of affected metrics; labelled "Scenario — not evidence" on every screen; held in the browser only, reset on reload, never stored, never reachable from the memo (storage rule unchanged).

### 7.5 End-to-end verification (before the real-data pilot)

One fresh run on a clean deployment: create audit → upload TestCo files → map → calculate → review claims → write narratives → conclusion → memo export, performed by the engineering owner and repeated by an analyst tester, with the result recorded in the session log. The review notes this was not completed on 14 October because the backend became unavailable; it is a release condition, not optional.

---

## 8. Mapping to the review

| Review item                                   | Section here                                                                                                                                   |
| --------------------------------------------- | ---------------------------------------------------------------------------------------------------------------------------------------------- |
| 1. D1 verdict words                           | 1                                                                                                                                              |
| 2. D2 false reassurance                       | 2                                                                                                                                              |
| 3. D5 date semantics                          | 3                                                                                                                                              |
| 4. Typed claims and correction path           | 4                                                                                                                                              |
| 5. Label meanings                             | 5                                                                                                                                              |
| 6. D6 access and deployment                   | 6                                                                                                                                              |
| Release sequencing and acceptance             | 7                                                                                                                                              |
| Uncertain items (methodology, PR, code, cost) | Cost: "no additional model calls" is not a cost claim; the per-audit cost panel remains the measure and is read before and after each release. |
