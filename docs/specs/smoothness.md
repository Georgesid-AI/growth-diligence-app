# Spec: Smoothness check (Release 1)
Status: Agreed scope (George, 15 Oct 2026, decision 8: build smoothness as its own spec and PR; quarter-end clustering waits for
the CRM data in Release 3). Location: docs/specs/smoothness.md. Amends integrity-coverage.md §1 (check 4), §8. Stacked on
claim-review-conclusion (PR 5 of 6).

## 0. Challenge and deletions (CLAUDE.md rule 4)
- Needed: the conclusion needs 4 applicable checks completed and only 3 can ever run today, so every audit reads "Insufficient
  assessment coverage". Smoothness is the one missing check the stored data can answer. Simpler version: one pure function
  over the stored `revenue_series`, inside `integrity.py`. No engine field, no stored document, no model call.
- Deleted first: the reason "The app does not compute revenue smoothness yet." and the status Not available for this check.
  Quarter-end clustering keeps its Not available status.

## 1. What is measured
- Series: `revenue_series` totals (reporting currency, one value per month).
- Window: the latest run of consecutive months that each have revenue above zero. A Possibly partial last month
  (dates-and-periods.md §2) is left out, as it is for NRR and gross churn. The window needs 13 months (12 changes), else the
  check is Blocked (§3). The last 12 changes of the run are read.
- Statistic: the standard deviation (population) of the 12 month-on-month growth rates `v(t) ÷ v(t−1) − 1`, in percentage
  points.
- Result: **Amber** when the statistic is below 0.5 points (revenue grows at an almost constant rate, which real billing
  rarely does); **Green** otherwise. Never Red: only the reconciliation's hard blocker is Red (integrity-coverage.md §7).
- Label (George, 15 Oct 2026, decision 3a): the limit stays 0.5 and the finding ends `(provisional threshold, 3 synthetic series)` on
  screen; the memo's data-reliability row adds `Smoothness: {result} (provisional threshold, 3 synthetic series).`
- Finding (word for word): `Month-on-month revenue growth varies by {s} points (standard deviation) over {first}–{last}` and,
  when Amber, `; below 0.5 points is unusually smooth`. `{s}` has one decimal; `{first}`/`{last}` are the first and last month
  of the 13 months read. Source: the `revenue_series` citation (file · sheet · rows).
- The 0.5 limit is provisional: measured on the three series the repo holds (sample TestCo: 0.0 points, an exact 1% a month;
  the two demo audits: 19.5 and 21.9 points, all synthetic), which show where the extremes lie and nothing between. It is a
  named constant (`SMOOTHNESS_LIMIT_POINTS`) so a calibration on real audits changes one line.

## 2. Where it shows
Block A gets a row when the check ran; Block B row 4 reads Completed. The conclusion rule (integrity-coverage.md §2) is
unchanged: with smoothness the applicable checks are 5 and 4 can complete, so an audit with the reconciliation, the gaps, the
smoothness and the deck check completed has a conclusion other than "Insufficient assessment coverage".

## 3. Blocked
No revenue series, or fewer than 13 consecutive months with revenue above zero: Blocked — company data missing, reason
`Revenue file with at least 13 consecutive months of revenue` (a data request, listed in the memo's Appendix B).

## 4. Contract and data boundary
`integrity.py` stays pure (reads stored results, imports nothing from `app.llm`, logs nothing). No engine output field
changes, so `backend/schemas/metrics.py` does not change. The endpoint's log line is unchanged (codes and counts).
The data-integrity narrative's payload (`step_payloads.py`) still lists the smoothness check as "not computed": changing
what the model is told re-keys the stored data-integrity narratives and costs a paid call per regeneration (CLAUDE.md rule
19). Listed under "Decisions for you".

## 5. Tests
| Test | File |
|---|---|
| A series growing exactly 1% a month is Amber (statistic 0.0), the finding names the window; TestCo reads it | `test_integrity_coverage.py` |
| A series with ordinary noise is Green | `test_integrity_coverage.py` |
| 12 months, or a gap leaving fewer than 13 consecutive months: Blocked, with the data request in the API and the memo | `test_integrity_coverage.py` |
| A Possibly partial last month is not read | `test_integrity_coverage.py` |
| With smoothness completed, reconciliation + gaps + smoothness + decks = 4 of 5 give a conclusion other than Insufficient | `test_integrity_coverage.py` |
| Clustering is still Not available | `test_integrity_coverage.py` |
| Older tests: TestCo reads 4 of 5 and "Material concerns" (its reconciliation is Red) | `test_integrity_coverage.py`, `test_ic_memo.py` |

## 6. Decided and open
- Decided by George (15 Oct 2026): the 0.5-point limit stays, labelled provisional (§1). Recalibrate after five real audits.
- Open: whether the data-integrity narrative is told the smoothness result (recommended: yes, with the next prompt release, since
  it re-keys that narrative and costs a regeneration).

## Files
`backend/app/integrity.py`, the tests of §5, `docs/specs/integrity-coverage.md` (amendment lines).

## Done when
§5 passes with the full suite; the TestCo integrity block lists Smoothness as Completed, Amber.
