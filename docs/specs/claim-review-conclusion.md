# Spec: Claim-review conclusion (Release 1)
Status: Agreed scope. Source: docs/plans/app-plan_V2_amendments_15_10_2026.md section 1 and 7.1 (D1 rewritten, decisions of
15 Oct 2026, final). Location: docs/specs/claim-review-conclusion.md. Replaces verdict-and-memo.md §6.2 (the rule), W8 and
the "Verdict" wording of §6.4, §7.2 item 1 and W15's verdict line. Implementation order: 5 of 6.

Amended 2026-10-25 (George, review of PR #180, docs/design/simplified-flow.md): the five are the app's selection (value at stake, then
normalised shortfall) and are in force without a confirmation; the conclusion is always computed, never blocked, so the "Conclusion
blocked" and "No conclusion until the top 5 is confirmed" wordings of §1 are not shown; an open question is "1 question open." on the rule
line. The analyst judgment fields of §3 are replaced by the computed Reasons and Unresolved questions and one optional Analyst note
(`ic_inputs.note`, max 1,000 characters, never sent to a model); the memo is not refused for their absence. The key gates are the gates of
the non-Verified claims among the five. The outcome rules of §2, the scope sentence and the contradiction lines stand.

## 0. Challenge and deletions (CLAUDE.md rule 4)
- Needed: "Underwrite" and "Re-plan" read as an investment recommendation drawn from five claims. The simpler version: the
  same pure function over the same confirmed five, with outcome words that describe the claims, the contradictions outside
  the five beside it, and the analyst's own judgment in two fields. No model, no new analysis.
- Deleted first: the outcomes Underwrite, Underwrite with gates and Re-plan, their rule texts (W8) and the "Re-plan by 3
  Unsupported" rule; the heading "Verdict".

## 1. Heading and scope
- Heading, on screen and in the memo: "Claim-review conclusion — assessment of the five selected claims".
- The five are the analyst's confirmed top 5 (verdict-and-memo.md §6.1, unchanged: proposal by shortfall, confirm or
  replace, void when a claim leaves the register). Gates still block (verdict-and-memo.md §6.3), worded "Conclusion
  blocked: set a gate on {ranks} (top-5 claims that are not Verified)." and "Conclusion blocked: answer the definition check
  on {ranks}."; "No conclusion until the top 5 is confirmed."; "No conclusion: the register has no claims." / "No
  conclusion: compute the audit first."

## 2. Outcome (exactly one)
| Value | Rule | Rule text shown under it |
|---|---|---|
| Selected claims not supported | at least one selected claim is Contradicted | "{n} selected claim is (are) Contradicted." |
| Insufficient evidence | no claim is Contradicted and 3 or more of the five are untested | "No selected claim is Contradicted; {u} of {N} are untested (Unverified, Inconclusive or Unsupported)." |
| Selected claims supported | all five selected claims are Verified | "All {N} selected claims are Verified." |
| Selected claims partly supported | every other case | "No selected claim is Contradicted; {v} of {N} are Verified, {u} untested." |

- Order of precedence: Contradicted → Insufficient evidence → Supported → Partly supported.
- Untested = Unverified, Inconclusive or Unsupported (evidence-labels.md §4: Inconclusive counts with Unverified). A beat is
  Verified (claim-matching.md §4). With fewer than 5 register rows, N is the number selected and "3 or more" stays 3; the
  rule text ends "Top {N} (the register has {N} claims)." as today.
- Outcome codes in the API: `not_supported`, `insufficient`, `supported`, `partly_supported`.

## 3. Always shown next to the conclusion
1. The scope sentence, word for word: "This assesses the five claims selected by the app by value at stake; the analyst may change the selection. It is not an investment recommendation."
2. "Other contradictions": every Contradicted register row outside the five, by rank, each with its metric (the claim's
   name, verdict.py `claim_name`), its gap (the gloss) and its source (analysis · source key · file · sheet · rows, and the
   deck page). None: "None found among tested claims."
3. "Analyst judgment": two free-text fields the analyst fills, (a) "Reasons", (b) "Unresolved questions", each at most 1,000
   characters, stored in `audits.ic_inputs.judgment` (`reasons`, `unresolved_questions`), never pre-filled, never sent to a
   model or written to a log, deleted with the audit (CLAUDE.md rule 22). Both are required before memo export: "Memo not
   exported: write the analyst judgment: {Reasons, Unresolved questions}." The app never generates a recommendation word.
These three show whenever the section shows (before confirmation too: the scope sentence, and the other contradictions
against the proposed five); the outcome shows only when the conclusion is reached.

## 4. Memo
The summary (verdict-and-memo.md §7.2, item 1) opens with the heading's text as a line, then "Conclusion: {value} – {rule
text}", the scope sentence, "Other contradictions:" with one list item per row (or "None found among tested claims."),
and "Analyst judgment (analyst's text, as of {requested analysis date})" with "Reasons: {text}" and "Unresolved questions:
{text}" verbatim (dates-and-periods.md §2). Numbers in the judgment are the analyst's (verdict-and-memo.md §7.4
(d)), cited "set by the analyst". W24 stays.

## 5. Words that never appear
"Underwrite", "Re-plan", "invest", "pass" and "proceed" (whole words, any case) appear nowhere in app output (API responses,
screen text) or memo output. "investment" in the scope sentence and the memo title is another word. A test scans the memo,
the conclusion endpoint's response, the rendered section and the frontend's source strings.

## 6. Contract and data boundary
- No engine output field changes; `backend/schemas/metrics.py` does not change. The verdict log line keeps its format with
  the new outcome codes (`outcome=supported` ...).
- `judgment`, `reasons`, `unresolved_questions` and `other_contradictions` join the boundary lists of
  `test_gateway_data_boundary.py` (rule 14): never in a gateway payload, a log line or a gateway collection.

## 7. Tests
| Test | File |
|---|---|
| Plan 1 and 7.1: five Verified selected claims and one Contradicted unselected claim show "Selected claims supported" and the contradiction in the same block, in the app and in the memo | `test_conclusion.py`; `Verdict.test.jsx` |
| Each outcome and the precedence, Inconclusive counted as untested, fewer than 5 rows | `test_verdict.py` (rewritten from the Underwrite / Re-plan cases) |
| The scope sentence and "None found among tested claims." | `test_conclusion.py`; `Verdict.test.jsx` |
| The memo refuses without both judgment fields; prints them verbatim; never pre-fills them | `test_conclusion.py`, `test_ic_memo.py` |
| The five words never appear (§5) | `test_conclusion.py`; `Verdict.test.jsx` |
| Boundary | `test_gateway_data_boundary.py` |

## 8. Decided (engineering, rule 19)
- The rule texts of §2 name counts, as W8 did, so the memo's number check reads them as register counts.
- 1,000 characters per judgment field: the memo's 1,500-word limit (verdict-and-memo.md §7.5) still applies to the whole.
- Inconclusive counts as untested here, as in the memo's counts (evidence-labels.md §4). Confirmed by George, 15 Oct 2026.
- The two judgment fields show on the Dashboard (inside the conclusion block) and on the Review page (section 8, after the
  ratings, before Write all narratives), the same component and the same stored text. Decided by George, 15 Oct 2026
  (decision 11). The Generate IC memo button on the Review page keeps its rule (both ratings); the server's refusal names a
  missing judgment field, and the fields sit directly above the button.
- The full TestCo run takes 23 clicks (`MAX_CLICKS_FULL`); the limit of 21 is raised to 23 and the note stays (George,
  decision 10, 15 Oct 2026).

## Files
`backend/app/verdict.py`, `backend/app/ic_memo.py`, `backend/server.py`, `frontend/src/components/Verdict.jsx`,
`frontend/src/lib/verdict.js`, the tests of §7.

## Done when
§7 passes with the full suite; no file of `frontend/src` or `backend/app` holds one of the five words in user-facing text.
