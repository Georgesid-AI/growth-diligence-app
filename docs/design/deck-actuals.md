# Deck figures: actuals, plan and segments

Addendum to the adopted spec and to segment-partitions.md. Date: 28 Oct 2026.
The adopted spec is not amended.

## 1. Period sort

Every deck figure is sorted by its own period against the audit's as-of
month. The deck's date is never used.

- Period ends on or before the as-of month: an actual, from the deck. It is
  data prepared by management, not a claim.
- Period starts after the as-of month: plan. It is a claim and follows the
  existing forecast rules (never Verified or Contradicted).
- No readable period: one card for the analyst, "Set the period".

The period alone decides. A figure the page reader marked a projection or a
scenario, with a period that has ended, is still a deck actual; the mark is
shown as a note on the row. (Best and worst cases keep their own rule: listed,
never matched.)

## 2. What happens to a deck actual

a) The files hold the same metric and period: reconcile. Within tolerance,
   the figure is Verified and the deck is consistent with the files. Beyond
   it: the figure is Contradicted (the data shows it false) with the reason
   "deck differs from file", shown in the register and under Worth flagging.
   (Amended 2026-10-29, George: Contradicted, not Unverified. Built for
   page-read figures only; the rules read and the analyst's own claims keep
   their existing test.) This check runs before the Definition check: a figure
   far off the file is Contradicted on its own, with no card and no answer
   needed, and its details block says "differs from File <cell> by X%", never
   "matches".
b) The files hold nothing for it: use it. The engine computes what the
   figures allow (customer count, concentration, growth by customer, stated
   NRR or churn). The result is labelled Unverified and carries the tag
   "deck only".
c) The deck actual is a split whose parts sum to a file total: the total is
   reconciled as in (a), the parts are used as in (b).

Source rank for any number: Excel raw data, then deck actuals, then deck
plan. The source column shows "File <sheet>!<cell>" or "Deck p<n>".

## 3. The "deck only" tag and the details block

The tag opens a block with four parts, same layout for every metric:

- Inputs: each deck figure used, with page and label as printed.
- Formula: the calculation with the numbers filled in.
- Checked against files: what matched, with the file cell, or "nothing in
  the files for this period".
- Not checked: the inputs no file confirmed, by page.

The same block, with cell references, is shown for metrics computed from
files. It is built from stored data; no model call. It goes into the memo as
Appendix C. When a later file lets the engine recompute the metric from raw
data, the tag drops on the next run.

## 4. Segments on a page

Two or more figures on one page that sum to a third figure on the same page,
within the money tolerance, are segments of that figure. They take its period
and its metric, and sit under it in the register as a split
(segment-partitions.md). A period or label disagreement on a segment is
resolved by the sum; no card is raised.

Two limits. Figures that each carry a period of their own, and differ from
one another, never form a split: a revenue table of 2019, 2020 and 2021 is
three totals, whatever the arithmetic. A part with no label of its own, or the
same label as the total, stays a segment under the total named "Unlabelled
part"; it is never a rival total for the total's period and raises no card.

Segment names are read from the nearest label, including rotated chart
labels and legend text, not from the page heading.

## 5. Folding two readings of one figure

When two readings on one page fold into one row (same metric, same period,
value within tolerance), the row keeps the more specific label and all page
references. A metric name (a label the mapping recognises as a metric:
"Recognised Revenue", ARR, customers, growth) always wins over a heading
("FINANCIAL HIGHLIGHTS", "2021 REVENUE"), whatever its length or digits;
between two metric names the longer wins; between two headings the one
without digits.

## 6. Data requests

Where a deck actual is used because the files hold nothing, the data request
names the table: "revenue by customer and month behind page 12". Cohorts,
sales cycle and win rate still need a customer file or CRM; a deck never
carries row-level data for them.

## 7. Test case: page 3 of the real deck

Page text holds: heading "2021 REVENUE"; a stacked bar with "NEW BUSINESS
€ 482,475" and "COMMITED FROM 2020 € 18,903" totalling "€ 501,378"; a table
"Recognised Revenue" 2019: 170,044.11, 2020: 151,056.65, 2021: 501,378.04;
multiples "0.9 x" (2019 → 2020) and "3.3 x" (2020 → 2021). As-of month Dec
2021. The same table appears on page 12.

Expected result, with the yearly P&L mapped:

- Revenue FY 2019, FY 2020, FY 2021: deck actuals, reconciled with the P&L
  revenue row, Verified (the P&L holds 501,378.04 for FY 2021).
- 501,378 and 501,378.04 fold into one row, label "Recognised Revenue", pages
  3 and 12.
- 482,475 and 18,903 are segments of the FY 2021 total, period 2021, labels
  "New business" and "Committed from 2020". No card.
- 0.9x and 3.3x: growth multiples, deck actuals, checked against growth
  recomputed from the P&L (0.89x, 3.32x), Verified within tolerance.
- Eight figures, zero cards, zero rows marked "Needs your attention".
