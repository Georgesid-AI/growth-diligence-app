# Spec: Data integrity, results and assessment coverage (Release 1)
Status: Agreed scope. Source: docs/plans/app-plan_V2_amendments_15_10_2026.md section 2 and 7.1 (D2 rewritten, decisions of
15 Oct 2026, final). Location: docs/specs/integrity-coverage.md. Amends verdict-and-memo.md §7.2 (scorecard, data
reliability; Appendix B) and the use of the data-integrity narrative's verdict (A2). Implementation order: 4 of 6.

## 0. Challenge and deletions (CLAUDE.md rule 4)
- Needed: one integrity verdict read "Reliable" or "Needs clarification" whatever share of the method had run, so checks
  that never ran looked passed. The simpler version: a pure Python module that lists what ran and what did not, and a
  conclusion Python computes by a fixed rule. No model call, no new engine metric, no stored document.
- Deleted first: the A2 narrative's verdict as the integrity conclusion (the memo scorecard's "Data integrity verdict:
  {verdict}"; the narrative itself stays as an explanation, its verdict is no longer printed as the conclusion); building
  any of the missing checks (they are listed as "Not available in the app").

## 1. Two blocks, never folded into each other
Dashboard section "Data integrity", above the data-integrity narrative. API: `GET /api/audits/{id}/integrity`.

Block A, "Results of completed checks": one row per check that ran, `Check | Result | Finding | Source`; Result is Green,
Amber or Red. A check that did not run never appears here.

Block B, "Assessment coverage": one row per check of the method, `Check | Status | Reason`, always these six, in this order:
| # | Check | Completed when | Result |
|---|---|---|---|
| 1 | Revenue reconciliation | the engine's `revenue_reconciliation` is available (a P&L with a revenue line and a month in common with the revenue file) | Green: the window and every month within tolerance; Amber: the window within tolerance, a month beyond it; Red: the window beyond tolerance (the hard blocker of CLAUDE.md rule 21). Finding: "Revenue file and P&L differ by {x}% over {first}–{last}". Source: the block's citation |
| 2 | Gaps in customer data | the engine's `anomalies` block exists (a mapped revenue file) | Green: no customer whose revenue stops for over two months and resumes, no revenue line without a customer ID; Amber: any. Finding: the two counts. Source: `anomalies` citation |
| 3 | Quarter-end clustering | never in Release 1 | – |
| 4 | Smoothness | never in Release 1 | – |
| 5 | Benford on transactions | never: not applicable by design | – |
| 6 | Deck-vs-deck figures | at least one deck is parsed | Green: no figure of the audit's decks (claims not rejected) differs from another figure of the same type, label and stated period (deck-parser.md §2 inconsistency rule, read across all the audit's decks); Amber: any. Finding: the count and the first pair's pages. Source: deck file · page |

Status values, with the reason the row prints:
| Status | Meaning | Reason (word for word) |
|---|---|---|
| Completed | the check ran | – (its result is in Block A) |
| Not applicable | the check cannot apply to this company by design; a stated reason is required | Benford: "No transaction-level file: the app ingests revenue by customer and month, not transactions." |
| Blocked — company data missing | names the file or field that would unblock it; a data request, not a negative finding | 1: "P&L with a revenue line, overlapping the revenue file's months"; 2: "Revenue file mapped (customer ID, invoice date, amount)"; 6: "At least one board deck" |
| Not available in the app | product limitation; printed as such, never as a company finding | 3: "The app does not compute quarter-end clustering of deals yet."; 4: "The app does not compute revenue smoothness yet." |

Denominator: applicable checks only (every status but Not applicable). Display: "Completed {x} of {y} applicable checks",
then "Blocked: {names}" when any is blocked.

## 2. Overall conclusion
Values: Reliable · Needs clarification · Material concerns · Insufficient assessment coverage.
1. Fewer than 4 applicable checks completed, or revenue reconciliation not among the completed: "Insufficient assessment
   coverage ({x} of {y})". It is not a negative company finding; the memo says so in one sentence: "Insufficient assessment
   coverage is not a finding about the company: {y−x} of the {y} applicable checks could not be completed."
2. Otherwise: Material concerns when any completed check is Red; Reliable when every completed check is Green; Needs
   clarification otherwise.
A reconciliation beyond tolerance stays a hard blocker in the banner whatever the conclusion (CLAUDE.md rule 21).

## 3. Data request list
Every Blocked check's reason is a data request: it is listed under Block B ("Data requests") and in the memo's Appendix B
"Requests" (verdict-and-memo.md §7.2), after the gaps' requests, as "{check}: {reason}". A Not available or Not applicable
check is never a request.

## 4. Memo
Scorecard, data reliability (verdict-and-memo.md §7.2, item 3): the headline is the overall conclusion and "Completed {x} of
{y} applicable checks", then the sentence of §2.1 when it applies; key evidence "Data integrity conclusion: {conclusion};
revenue_reconciliation, anomalies, claim register". The rating stays the analyst's. The A2 narrative's headline and verdict
are no longer printed there. On the Dashboard the data-integrity narrative no longer shows its "Verdict:" line either (George,
15 Oct 2026, decision 1a): Python's conclusion is the only one shown. The narrative text stays; no model call changes.

## 5. Contract and data boundary
- A pure module `backend/app/integrity.py` reads `audits.results`, the audit's deck count and the stored candidates'
  inconsistency flags; it imports nothing from `app.llm` and logs nothing. No engine output field changes, so
  `backend/schemas/metrics.py` does not change.
- The endpoint logs one line: `integrity: run_id=%s conclusion=%s completed=%d applicable=%d` (codes and counts only);
  `test_gateway_data_boundary.py` gains the format and the module's names (rule 14).

## 6. Tests
| Test | File |
|---|---|
| Plan 2 (1) and 7.1: two checks completed and Green, four blocked → "Insufficient assessment coverage (2 of 6)", never "Reliable" | `test_integrity_coverage.py`; `IntegrityCoverage.test.jsx` |
| Plan 2 (2): Benford not applicable is not counted in y | `test_integrity_coverage.py` |
| Plan 2 (3): a check blocked by missing company data appears in the data request list (API and memo Appendix B) | `test_integrity_coverage.py` |
| Each status and result of §1; Material concerns on a Red reconciliation; Reliable needs 4 completed with reconciliation | `test_integrity_coverage.py` |
| The memo scorecard reads the conclusion and the coverage, not the narrative's verdict | `test_ic_memo.py` |
| Boundary and log line | `test_gateway_data_boundary.py` |

## 7. Decided (engineering, rule 19)
- Results thresholds: Green means nothing found, Amber anything found, Red only the reconciliation's hard blocker; no
  count threshold is invented for gaps in customer data.
- Deck-vs-deck reads the parser's own inconsistency rule over all the audit's decks, so one deck's figures are compared with
  each other and with the other decks'.

## 8. Consequences to know
- With today's app, checks 3 and 4 are Not available and 5 is Not applicable, so at most 3 of 5 applicable checks can be
  completed: every audit reads "Insufficient assessment coverage ({x} of 5)" until the app computes quarter-end clustering
  or smoothness. Building them is outside this spec (see "Decisions for you").

## Files
`backend/app/integrity.py` (new), `backend/server.py`, `backend/app/ic_memo.py`, `frontend/src/components/IntegrityCoverage.jsx`
(new), `frontend/src/lib/integrity.js` (new), `frontend/src/lib/api.js`, `frontend/src/pages/Dashboard.jsx`, the tests of §6.

## Done when
§6 passes with the full suite.
