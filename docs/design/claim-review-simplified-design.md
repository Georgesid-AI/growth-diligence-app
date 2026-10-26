# Simplified design: claim review and forecast diagnostics

**Status:** proposed replacement, 26 October 2026. **Evidence label:** analyst inference / design recommendation throughout, except where stated otherwise. These recommendations have not been approved or implemented.

**Provenance:** review of the two supplied design notes dated 26 October 2026. The companion review (not in the repository) identifies source sections, calculations, and remaining gaps. Referenced application code and tests were not supplied or inspected.

## Outcome

Show each economic issue once, preserve every source claim, and distinguish evidence about actual results from calculations about a plan. Use the same computed result for the register, attention list, top five, memo, and export.

## 1. Preserve claims; group their presentation

Keep each claim's value, source, period, evidence test, correction history, and analyst edits. Compute relationships on read; persist only explicit analyst decisions.

Group only claims with matching metric definition, entity/segment, currency, unit, fiscal calendar, and actual/forecast scenario. Unknown scope must not be assumed equal.

- **Flows:** an explicitly stated annual total reconciles with a complete, non-overlapping set of quarters, halves, or months. Choose one partition; never sum quarters and halves together.
- **Balances and counts:** an annual figure reconciles with the matching year-end observation, not the sum of observations. Do not treat earlier snapshots as duplicates of the year-end balance.
- Use the draft's 2% reconciliation tolerance provisionally: `abs(parts − total) <= 0.02 × abs(total)`. For a zero total, accept exact equality unless a documented rounding allowance exists. This tolerance identifies a relationship; it does not verify either figure against company data.
- Incomplete or non-reconciling parts remain independent claims, with a relationship note where useful.

Show a reconciled annual total once, with its parts under Details. Preserve every part's test. A material contradiction in a part appears on the group summary and remains eligible to affect the conclusion. A verified annual total cannot hide a contradicted quarter.

Select at most one top-five item for a reconciled group. Its priority reflects the most material unresolved issue among its members; value at stake counts overlapping exposure once. Report displayed groups separately from underlying claim counts. Include all claims in the appendix/export with their relationships.

For the annual headline, show its stated value at stake; its parts add none. An independent short-period claim retains the existing capped annualisation, clearly marked “run-rate”, with its period and multiplier. An unrelated or non-reconciling annual claim must not silently suppress that calculation. This closes the draft's undefined case where an annual row exists but grouping fails.

## 2. Resolve ambiguity without inventing meaning

Use the existing review interaction for ambiguous totals, labels, and periods: show candidates, sources, the reason for review, and any reconciliation hint. Select nothing automatically when several candidates remain.

Choosing a preferred total does not make another figure a segment. Keep the alternative and its unresolved conflict until the analyst explicitly corrects it, identifies its scope, or excludes it with a reason. Do not mark it false solely because it was unchosen. Unresolved material conflicts stay visible in attention and the overall conclusion, even when no single figure can enter the top five.

Reuse existing edit, exclude, and Undo controls. Bind a saved choice to the full claim context and candidate identities; invalidate it when relevant inputs change. A metric-and-period hash alone is insufficient.

## 3. Analyse forecast assumptions separately from actual evidence

Determine whether a figure is actual or forecast from its source classification. A period later than the available data means missing coverage; it does not by itself make a claim a forecast.

For a forecast, show the required growth, historical comparator, difference in percentage points, and calculation basis. Future outcomes remain unverified. Historical growth neither verifies a plan nor contradicts an acceleration assumption. Remove the proposed 5-point pass/fail rule and “beat” label; keep the numerical comparison.

Calculate `required annual growth = (forecast / base)^(12 / elapsed months) − 1` only when the amounts are comparable and the base, forecast, and elapsed months are positive.

| Metric | Comparable base |
|---|---|
| Annual revenue | Latest complete actual fiscal year; otherwise complete trailing 12 months. Identify the exact window. |
| Quarter/month revenue | Actual revenue for the same fiscal quarter/calendar month in an earlier year. If unavailable, show the target and the specific missing comparator; never divide a quarter by an annual total. |
| ARR, MRR, customers | Latest actual observation of the same metric and scope; use elapsed months to the forecast endpoint. |

Prefer historical growth between comparable annual windows. When only monthly endpoint growth is available, retain it as a separately named pace indicator, showing its dates and elapsed interval. It is not equivalent to annual revenue growth. Under 12 elapsed months, mark the history as limited; distinguish observation count from elapsed time.

Show ranges as ranges rather than selecting the endpoint that gives the most favourable comparison. Preserve stated growth-claim tests on their stated basis. When actuals cover part of a forecast year, retain the remaining amount needed, clearly labelled as a calculation.

Retain revenue/customer cross-checks in Details only when definitions align. Annual revenue divided by year-end customers is “revenue per year-end customer”, not automatically ACV. Compare ARR per customer with a matching recurring-value measure; otherwise explain the mismatch.

## 4. Use one source-association rule

Accept a printed value only with supported associations for its metric, period, and unit. Candidate sources are its own cell, an associated table header/chart axis, a containing segment label or legend, and an applicable heading above the figure. A valid explicit local association takes precedence over a broader heading; disagreement requires review.

Normalise rotated text into the same association logic. Use rectangles and legend colours as local layout evidence, scoped to the relevant chart. Reused colours or multiple candidate labels require review. Keep layout metadata out of model requests.

For heading corrections, retain the period token and source-cell reference, not heading prose in correction records or diagnostics. Preserve any actual/forecast marker separately. Do not infer a missing year or borrow a marker annotation's date for another figure. Do not change the existing boundary for page text sent to the model.

Drop a model-produced value with no supported printed source only when extraction is adequate to establish that absence; retain an auditable drop reason. With incomplete extraction, keep an extraction-review issue. A matching number elsewhere on the page does not establish its metric or period.

## 5. Support annual payback with an explicit basis

Retain annual analysis when monthly P&L data is unavailable. Calculate `12 × S&M / (incremental annual recurring value × gross margin)` when its inputs and definition are supported. The numerator must match the stated S&M scope; a marketing-only line must not silently become total S&M.

Year-end ARR minus prior year-end ARR is **net new ARR**. Annual revenue growth is a different denominator. Preserve both available calculations as explicitly named proxies; neither automatically verifies a differently defined CAC payback claim. Compare a claim only with a matching definition, period, and cost basis.

Show the value, fiscal year, denominator basis, and source. Missing/non-positive denominators or margin produce a specific unavailable reason. Suppress the monthly-P&L request only for the question and year the annual calculation answers. Keep requests needed for the claimed definition, another year, or monthly timing.

## 6. Render once; reuse everywhere

Use four columns: **Claim and period · Evidence / calculation · Result · Source**. A forecast's calculation cell shows required growth, historical comparator, and gap. Put formula inputs, component claims, cross-checks, and corrections in Details.

Use one short note whenever forecasts appear: “Forecast calculations describe assumptions; future outcomes are unverified.” Remove the all-five-forecasts branch and repeated disclaimers. Remove visible rank prefixes while preserving stable claim references for audit and export.

Reuse one backend evaluation result across views. Prefer existing fields plus the minimum relationship and calculation basis needed; do not introduce separate verdict logic or duplicated flags per screen. Preserve existing export compatibility deliberately; flatten the same result where a flat format is required.

## Acceptance and delivery

| Capability retained | Required check |
|---|---|
| Grouping and no duplicate exposure | Complete/partial/mixed partitions, negative and zero totals, different scopes/scenarios, March year-end, edit and Undo |
| Contradiction visibility | A contradicted part remains visible and affects the conclusion despite a verified annual total |
| Conflict resolution | No invented segment; choices survive valid reads and expire after relevant edits |
| Forecast diagnostics | Like-duration bases, insufficient history, missing periods, zero/negative inputs, ranges, remaining target, no verification of future outcomes |
| Chart/heading checks | Rotated axes, distant legends, repeated colours/numbers, attached dates, ambiguous headings, incomplete extraction, model/log boundaries |
| Annual payback | Matching and mismatching definitions, net-new-ARR/revenue proxies, missing years/costs, invalid denominator, correctly scoped data requests |
| Consistent outputs | Same values, status, relationships, and sources in screen, memo, and export |

**Suggested sequence:** source association → grouping/conflicts → forecast/payback calculations and shared presentation. Keep separate reviewable changes where interfaces differ; no fixed PR count is required.

**Owners and deadlines:** George/product owner: settle the evidence semantics before implementation. Engineering owner: map this proposal to existing schemas before coding, then demonstrate the acceptance cases before merge. Specific people and calendar deadlines: **Not provided**.

## Established, uncertain, next steps, recommendation

**Established — verified fact:** both notes cover grouping, forecast analysis, source association, annual payback, and presentation; see the companion review's source map.

**Uncertain — missing:** current code behaviour, referenced contracts, and prior approvals were not provided. Capability preservation here is a design mapping, not a tested software guarantee.

**Next steps — recommendation:** resolve the evidence semantics, map existing interfaces, and verify the acceptance cases against the application.

**Recommendation — analyst inference:** adopt the shared rules above; retain detailed examples and source history as an appendix, with one authoritative behaviour specification.
