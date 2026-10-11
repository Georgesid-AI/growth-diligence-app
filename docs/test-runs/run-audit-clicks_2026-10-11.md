# Run audit: clicks from upload to the IC memo (2026-10-11)

Fake provider, in-memory Mongo, sample_data files and the TestCo claim fixture
(`backend/tests/test_run_audit.py`). A click is a click, a choice in a list, a field typed into, or one pick in the file
picker. Counted from the file picker; creating the audit and the set-up fields are not counted. Limit: 15.

| Audit | Clicks | Within 15 |
|---|---|---|
| Clean TestCo (the claims within tolerance) | 11 | yes |
| Full TestCo (33 claims, top 5 all contradicted) | 38 | no: five gates are human decisions |

Clean: file picker 1, Run audit 1, Confirm the one column the rules could not settle 1, Confirm top 5 1, thesis 3,
ratings 2, Write all narratives 1, Generate IC memo 1.

Full: as above, plus Approve all per category with claims left, and for each of five gates threshold, budget decision, date
and Save (4), then three key marks.

## After gate prefill and the first quarterly review set-up field (feat/gate-prefill)

Fake provider, same fixture. Full TestCo: **21 clicks** (was 38). Limit for the full run is `MAX_CLICKS_FULL = 21` in
`test_run_audit.py` (George's decision, option A); the clean audit keeps its limit of 15 (11).

Full: as above up to Confirm top 5 (8 clicks counting the file picker, Run audit, one column, four Approve all); then the budget
decision on each of five gates (the first typed after Other, the next four picked from the list) 5, Save all gates 1, key marks 0
(pre-marked), no date to type (the first quarterly review is a set-up field, default creation date + 90 days, so every claim without
a period is dated); thesis 3, ratings 2, Write all narratives 1, Generate IC memo 1. Entering the review date at set-up is not counted:
it has a default and set-up fields are not counted.
