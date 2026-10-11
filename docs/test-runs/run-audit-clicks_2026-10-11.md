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

## After gate prefill (feat/gate-prefill)

Fake provider, same fixture. Full TestCo: **22 clicks** (was 38); goal 20. Limit for the full run is `MAX_CLICKS_FULL = 20` in
`test_run_audit.py`; the test that enforces it is `xfail(strict)` until the gap below is decided.

Gates now: budget decision per gate (first typed after Other, the next four picked from the list) 5, the one gate whose claim
has no period (no first quarterly review is set in this flow) needs its date 1, Save all gates 1. Key marks 0 (pre-marked).
Gap: the floor with the date prefilled is 21: the other 15 clicks are unchanged and the five budget decisions cannot be prefilled.
