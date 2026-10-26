# Forecast diagnostics, annual payback and the four-column presentation: test run, 2026-10-26

Spec: docs/specs/forecast-and-payback.md (docs/design/claim-review-simplified-design.md sections 3, 5 and 6, and the conclusion with open conflicts). Fixture companies only: synthetic names, synthetic figures.

## Suites on the branch
- Backend (`python -m pytest`, as configured): 3952 passed, 26 skipped. `ruff check backend/` (0.16.8, ruff.toml): all checks passed.
- Frontend (`yarn test --watchAll=false --no-cache`): 43 test files found, 43 loaded and passed; 647 tests passed.

## The new and changed tests without the change
The test files of the branch copied onto its parent commit (the source files unchanged):
- Backend `test_forecast_calc.py` (48 tests) and `test_annual_payback.py` (55 tests): neither loads (`cannot import name 'forecast_calc'`, `'payback_definition'`), so none of their tests runs. `test_gateway_data_boundary.py` does not load either (it imports `forecast_calc`).
- Backend, the other new and changed files (18 files): 61 tests failed, 788 passed, 1 file did not load (the boundary file). Of the failures 21 of 21 are `test_forecast_register.py`, 9 of 10 `test_consistent_outputs.py`, 5 of 7 `test_conclusion_conflicts.py` and 26 are existing tests whose expectation changed (below).
  The tests that pass either way are controls: an empty register still reads "No testable claims", choosing a figure ends the special case, and the existing rows that hold under both readings.
- Frontend, the ten new and changed files: 9 of 10 files fail (`claimColumns.test.js`, `ClaimRegister.forecast`, `FiveClaims.forecast` do not load: `Cannot find module './claim_columns.json'`); 10 tests fail in the files that load. `Verdict.conclusion.test.jsx` passes with and without the change
  (new control: the conclusion block already renders a conclusion with an empty five; the fix is the server's).

## The new tests against deliberate violations
Each violation is one change to the source, the new tests run, the file restored.
- Backend, 33 violations, 33 caught: the annual base not the latest complete fiscal year; the elapsed months ignored in the exponent; a quarter taking the annual path (divided by an annual total); a pace indicator given a difference in points;
  a range reduced to its low end; no remaining amount; a base that is not positive still given a growth; a limited history never marked; observations taken for elapsed months; a hole in a window ignored (a partial window summed);
  the period alone making a forecast; the basis ignored; a forecast labelled Verified; the calculation lines left off the row; a definition the claim does not state assumed equal; the claim's cost basis ignored; an unknown S&M scope taken for
  total S&M; a marketing-only line read as total S&M; the claim compared with the revenue proxy whatever it states; the Missing Data link dropped for a claim the annual figure does not answer, and kept for one it answers; net new ARR from the wrong
  prior year-end; S&M that is not positive and an invalid denominator giving a payback; an annual comparison for a payback plan after the data; the conclusion still reading "No testable claims"; the open conflicts counted twice on the rule line; the memo's Evidence, Source and Result cells
  ignoring the calculation lines, the deck page or the reason; the forecast note printed with no forecast; a rank prefix back in a reason and in the repeat note.
- Frontend, 15 violations, 15 caught: the forecast note missing from the register and under the five, or on every row; the columns reordered; a rank prefix in a claim's name; Details open by default; a question a row asks hidden under Details; the calculation lines and the
  formula inputs not shown; a later period alone making a forecast; the five without the calculation; the net-new-ARR column, the S&M scope and the reason a proxy has no value missing from the Years table; the rule line of an Insufficient evidence conclusion hidden.

## Existing tests changed
- 26 backend tests changed their expectation, not their intent: the contract is 10 (six files pin it; the stale-version list gains 9); the repeat note names a page, not a rank (3 in `test_claim_groups.py`); the reasons, the flagged lines and the data-gap lines name the claim, no `#rank` (`test_verdict.py`,
  `test_ic_memo.py`, `test_definition_check.py`); the memo's Appendix A opens with the four columns and carries the rank in "Ref" (`test_ic_memo.py`, `test_pr164_review.py`, `test_claims_enter_on_their_own.py`, `test_issue_136.py`, `test_conclusion.py`); the yearly-basis block names its S&M scope and "CAC payback (monthly timing)"
  (`test_sheet_structure.py`); the register row has two more fields (`test_claim_matching.py`, `test_claim_groups.py`); a forecast reads "Forecast: ..." instead of the repeated sentence, and the three TestCo claims typed as plans carry `basis` "projection" (the source classification the page reader gives), because a period after the data alone is no longer a forecast
  (`test_claim_matching.py`, the fixture `testco_claims.json`, `test_gateway_data_boundary.py`).
- Frontend: the register tests read four columns, open Details before the corrections, the overlaps name the other rows, the five read the four columns (`ClaimRegister.test.jsx`, `ClaimRegister.labels.test.jsx`, `claimRegister.test.js`, `Dashboard.simplifiedFlow.test.jsx`, `Dashboard.test.jsx`).
