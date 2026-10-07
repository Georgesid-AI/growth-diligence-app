# Spec: Structure labelling: Python lists items, the model labels them
Status: Draft; decisions of 2026-10-05 applied. Location: docs/specs/structure-labelling.md. Replaces parts of
llm-structure-reading.md (§8). Implements CLAUDE.md rules 16–18.

**1. Item list (Python, pure).** For every deck type, Python lists every figure in every redacted cell. Dates are
periods and are left out. A digit inside a word is no figure, as in the parser's reader (`claims.figures`; issue #50):
a number with a letter directly before it ("zero2hero", "Web3", "Q1") or an ordinal ending ("1st") gives no item. On
the test decks this removes 7 items: zero2hero p11 "zero2hero", moz p21 "Churn Rate in 1st2 Paid Months" (2), tea
p11 "Go2Market", "Web3 Foundation Open Grant" and "Q1-Q2" (2). A date written with slashes ("5/1/18") is a date
with no period (deck-parser.md §2, issue #53): it gives no item and is no period cell. On the test decks this removes
front-b p16's 12 items (1, 1, 18, 5, 1, 18, 9, 1, 18, 12, 1, 18 from "1/1/18 5/1/18" and "9/1/18 12/1/18") and with
them its panel, which held no other figure (deck-parser.md §7). Each item has:
- `id`: `i1`, `i2`, … in reading order, so the same structure always gives the same list;
- the cell id: a cell with several figures gives one item each, `#n` marking the position (`r6c2#2`);
- the raw text, cut from the redacted cell;
- the value in full units, under today's normalisation (llm-structure-reading.md §2);
- the ids of its header cells (`verify.header_cells`).

Header cells in a KPI panel (issue #50, interim guard): a header cell from another box counts only when it is
directly next to the item's cell, by its `next_to` (deck-parser.md §7: same visual row, or directly above or below
within a tenth of the page, with no box between, measured line to line). The top line of the item's own box always
counts. A cell with no `next_to` has no header from another box. A wrong label is worse than a missing one: the
verifier checks the value and the period, never the metric, so a value citing the wrong box can be Verified under the
wrong claim type. On the test decks 18 items lose a header, all on front-b: p15 "18 months" no longer cites "Cash on
hand" (which sits above "$7m left"); p12's five team-tenure values cite neither "LTV / CAC" nor "Spend as" (nor "On a
sustainable trajectory"); p16's 12 figures read from the axis dates no longer cite the chart legend entry "Cash".

Header cells in a roadmap (issue #56, decision of 2026-10-06): an item's header cells are the top line of its own
text box, and a cell of another box only when that box is a date box (each of its lines is a date or a part of one,
as "2022" / "Q2") and the cell is left of the item in its grid row and in its `next_to` (deck-parser.md §7), as in a
KPI panel. Only header text comes from the item's own box; a date box directly next to a figure may still date it.
In a roadmap the cells to the left in a grid row are other text boxes, such as the neighbouring paragraph, which
the model read as the figure's headers. On the test decks (measured on `89ba331`):
- moz p2: every item loses its headers from other boxes (the neighbouring paragraphs); no date box sits beside a
  moz p2 figure. "1.1M" cited r1c2 and r1c1, the 2004 and 1997 paragraphs.
- tea p11: i4 and i5 ("layer-1 to layer-2") keep 2022-Q2: "Q2" (r10c1) is directly next to their line on the left,
  and "2022" sits above it in its date box. i1, i2 and i3 lose the year they rebuilt from a box that is not their
  date (2021 from r1c2, 2021 from r7c1, 2022 from r9c1). Their own date boxes are directly next to them on the right, and
  a header is read left of the item only, so "Q3" of the 2022 Q3 box, directly right of "layer-1 to layer-2" but
  another bullet's date, stays out.
- buffer p6 is one box: every item cites its top line only, unchanged.
A neighbour's scale in a roadmap follows the same rule, as in a KPI panel: a date box holds no scale word, so a
roadmap figure takes no scale from another box. No roadmap value on the test decks changes. "Date rebuilt from cell"
on the test decks goes from 27 to 25 (tea p11: 21 to 19 lines).

A scale read from a neighbouring cell of its row (`£m`, `'000`; llm-structure-reading.md §2) follows the same rule
(decision of 2026-10-06 on issue #50): in a KPI panel, a neighbouring cell from another box gives its scale only when it
is directly next to the item's cell. Otherwise a headcount "12" in the grid row of a "Revenue £m" label that sits above
another value would read as 12 million. No value on the 10 test decks takes its scale from a neighbour, so they are
unchanged; a built slide shows the case.

An ambiguous reading carries both values, with Python's default first; the model does not choose.
- `dot_reading`: `2.500` defaults to thousands, unless it carries a k/m/bn suffix (`1.250M` → 1.25m).
- `bracket_reading`: a bracketed number after text defaults to negative when the text before it in its cell
  contains loss, deficit, negative or decline (any case). Otherwise it defaults to positive. A level keeps the
  positive reading only (issue #46, decision of 2026-10-06): when the label's metric is `customers`, `users` or
  `people`, the verifier drops the negative reading where the label joins the item, so the item has one value and
  its approval row shows one. `user_growth`, `growth` and every other type keep both readings; brackets around a
  whole cell ("(30K)") stay negative only. The value still comes from the cell (CLAUDE.md rule 18), and the report's
  ambiguous readings, counted on the item list before labelling, are unchanged. On the test decks no row changes:
  zero2hero p17's six bracketed counts are `other` in every pass under prompt v5 (live run of 2026-10-06-2).

The approval row shows both readings. The analyst confirms the default or uses Edit (deck-parser.md §6).

Ranges (decision of 2026-10-06): in `$12 -$13 million` the dash is no sign and the low end takes the high end's scale
(12,000,000 to 13,000,000). The two figures stay two items; both carry `range` (low id, high id, low, high) and make
one approval row (`value`, `value_high`) from the first labelled end, Verified only when both ends have the same
metric and are Verified. The AI-row dedupe (`structures.value_match`) returns exact (same value or range), in range
(one falls inside the other's range) or no match; either match means the cell already lists the row.

**2. Roadmaps.** Python also lists date cells (`d1`…, date labels as in deck-parser.md §7) and text lines (`t1`…,
the other non-empty cells). The model returns pairs (line id, date id) with a category: `launch`, `feature`,
`expansion`, `partnership`, `hiring`, `break_even`, `funding`, `certification` or `other`. Claim types: `hiring` →
people, `break_even` → ebitda, `funding` → other (type Other, §4), the rest → product. Parser rules are unchanged,
except one (issue #49): a paragraph wrapped over the lines of a roadmap text box is one cell (deck-parser.md §7), so it
is one text line and gives at most one milestone row (moz p2: 9 rows, not 40).

Label from (issue #49): a roadmap row takes "Label from" only from a cell of its own text box in its grid row
(`candidate_from_item`), never from a cell of another box. The cells beside it in its grid row belong to other boxes,
such as the neighbouring paragraph (moz p2 showed "index and link graph," as the label of "just “SEO” to social
media,"). Each box is one column of the grid, so a roadmap row has no "Label from". KPI panels keep the label beside
their value. Header cells in the item list follow §1 (issue #56): the top line of the item's own box, and a date box
directly left of it.

A line has at most one pair, and a date may serve several lines. A milestone has no value, so it is never Verified.

Position date (decision of 2026-10-06 on issue #47, option a): Python dates a line by its place on the slide. A
line's position date is its adjacent date line (below), else the date of the one date box directly next to its
text box (`date_box`, deck-parser.md §7). A date box gives a date when its lines are one date ("Nov. 2007") or a year
with a quarter, half or month below it ("2021" / "Q2" → 2021-Q2, the two-cell rule of deck-parser.md §2); otherwise
none. The model still says which lines are milestones, pairs them and gives the category; the prompt and the schema
are unchanged.
- A paired line with a position date takes it: the milestone's period and period cells are the position date's, and
  so is the period of each figure in the line. Python builds that date itself, so the figure is Verified unless it
  is type Other; a model period that differs counts as "period corrected".
- A paired line with no position date keeps the model's date, as before: the milestone's period is the one Python
  rebuilds from the paired date cell, and a figure in the line takes it and is Verified only when §4 rebuilds the
  same period from its own period cells.
- A line the model leaves unpaired is no milestone; its figures are dated by §4 as before.
On the test decks: buffer p6's 6 lines take the date line below them, as its recorded pairs already do (unchanged);
moz p2's 9 paragraphs take their date box (1981 to July 2011); 21 of tea p11's 22 bullet lines take the quarter of
their date box ("Gluon wallet" 2021-Q2, "TEA Party dApp released" 2022-Q1) where the model can pair them with the year
line only ("2021"), and "Mainnet starts" keeps the model's date. tea p11's 5 figures ("Preview 1", "epoch 9",
"Layer-1", "layer-1 to layer-2") can thus be Verified when the model labels them a claim type and pairs their line.

Adjacent date line: a text line takes the date line directly above or below it in the same text box. A line with a
date line on each side takes the one in the timeline's date direction (decisions of 2026-10-06), decided once per
timeline from its lines with a date line on one side only (above or below). When they all name the same side, that
is the direction. When they disagree, only those that hold a figure (one §1 lists) count, and they must all name the
same side. Otherwise the timeline has no direction, and its lines with a date on each side have no adjacent date
line. So a title over the first date of a timeline with dates above does not turn it downwards. That date line is
then a period cell of the line, and Python rebuilds the period itself. This also raises "date rebuilt from cell" on
timelines such as buffer p6, where dates sit below their lines.

**3. Text and reply.** The structure text is unchanged (`r<row>c<col>: <text>`, with spans). Below it comes the line
`items:`, then one line per item, e.g. `i3 r3c2#2 "(30K)" 30000 or -30000 h r3c1 r1c2`. The `h` cells are the
item's header cells (§1): a header the KPI panel or roadmap rule does not count is left out, with no mark, so the line
format is unchanged. A roadmap adds `d1 r2c1` and `t1 r1c1` lines. All deck types share one labelling schema: `{"type", "labels": [...], "pairs": [...]}`. A label
holds exactly `item` (a listed id), `metric` (`CLAIM_METRICS`, `use_of_funds`, `other`, or `not_a_metric` for page
numbers, years and footnote marks), and `period`, `unit`, `unit_other` and `actual_or_forecast` as today. There is no
value, cell id or flag, and each listed id is labelled exactly once. Schema violations (an unknown, duplicate or
missing id; a pair that is not one listed line and one listed date; pairs on a structure not sent as a roadmap) get
one reask, then "Not read by AI".

The reply follows the type Python sent; a corrected type is only logged. Column mapping keeps its own schema. Each
schema's hash enters the cache key. Tie-breaks in the prompt: hours and time figures → `product` unless a user count
is named or a tie-break below names them; "% of marketplace" and market share → `market`; commission and take rate →
`sales`.

Prompt v5, release r8 (issues #45 and #47, decisions of 2026-10-06), one bump for both:
- The new claim types of deck-parser.md §2 are metrics: `cash` (cash balance, in a currency), `burn` (net burn, in a
  currency), `runway` (months), `ltv` (lifetime value), `cac` (customer acquisition cost, cost of paid acquisition),
  `customer_lifetime` (customer life or lifetime, months), `ltv_cac` (LTV/CAC, x), `trials_per_day` (free trials per
  day) and `months_to_profitability` (months until the company is profitable). Each is one tie-break line.
- Monthly revenue, MRR, ARR and revenue run rate are `revenue`. Python rebuilds the period from the cells (§4).
- Social media followers and other social counts, visits, email subscribers and community members on a channel are
  `other`, not `users`, so they are never Verified (zero2hero p17 "Telegram(30K)"; moz p21 "~1.25 million" Monthly
  Visits and "~300K" Email Subscribers).
- Board seats are `not_a_metric`, the whole count (moz p23 "2 Investors (Michelle +1)", "1 Independent (TBD)").
- A team member's tenure is `not_a_metric` ("2 weeks ago", "joined 6 months ago" on front-b p12).
- The share of a market or of a survey that does something is `not_a_metric` (moz p13 "Many (75%+):", "Most
  (~50%):"); the company's own market share stays `market`.
- DAU/MAU and other engagement ratios are `product`, like hours (front-b p18 "64%").
- Integrations and partnerships are `product` (buffer p6 "Integrated in 50 apps").
Other is never Verified, unchanged (§4).

**4. Verifier.** Values and cells are Python's, so value matching is deleted. What is left:
- Period: rebuilt from the item's lowest period header (with the year cell above), from its own cell, or in a
  roadmap from its adjacent date line (§2), under deck-parser.md §2. The rebuilt period replaces the model's, and a
  difference counts as "period corrected". A model period with nothing to rebuild from, or a header period Python
  cannot rebuild, is "period not rebuilt" (an AI suggestion). A null period matches when no header holds a period.
- Separator and sign: recorded as `dot_reading` and `bracket_reading` with the default. Both readings come from the
  item's cell, so the item can be Verified.
- Flags: Python computes `total_mismatch` and `growth_mismatch` over the Verified items (`verify._flag_reproduced`).
- `not_a_metric` items are dropped and counted.
- `other` items are listed as type Other and are never Verified. The server refuses to approve one until its type is
  edited to a `CLAIM_TYPES` value.

Python joins each label to its item, so a checked item keeps today's fields plus its id and position.
`STRUCTURE_UNMATCHED` and the labels are unchanged.

**5. Storage, prompt, cache and cap.** `llm_structures` stores the reply and the item list without raw text (id,
cell, position, values, header ids, a range's low and high), so every label resolves to a value with its cell reference (rule 17) and no deck
text is stored. The prompt becomes v3 and the release r6; the narrative keys move once, as with r5. The key formula
stays; the schema hash and the item list move every key. Cap: 4,000 tokens per structure, on the structure text plus
the item list; a larger structure is "Too large for AI reading". `reverify_audit` skips readings stored under v2, and
their rows keep their labels.

**6. Agreement.** Agreement per type = items with the same metric and period in every pass ÷ items Python listed,
over structures read in every pass. The period is compared as the verifier keeps it (start and end dates), and
`not_a_metric` counts as a metric. Cells and the item count are fixed by code. The ≥95% target applies to this figure
over all deck types. Roadmaps are reported apart: "roadmap lines: N, dated by position: P, same pair and category
in every pass: M, same date and category: D, date rebuilt from cell: K". P counts the lines with a position date
(§2). M compares the model's pairs (the date cell and the category); D compares what the analyst sees: whether the
line is paired, the period Python keeps for it (§2) and the category. K counts roadmap items whose period Python
rebuilds from their own period cells (§4), whatever the pair says. The match rate counts every labelled item, roadmap figures included and milestones left out,
and is also given apart: financial (outside roadmaps) and roadmap (decision of 2026-10-06).

**7. scripts/consistency_run.py.**
- Keys: `_normalised_key` = (item id, metric, kept period range); old method = (item id, metric, period as written,
  unit, actual_or_forecast).
- `FIELDS` = metric, period, unit, actual_or_forecast.
- `REASONS` = period not rebuilt, metric invalid, other.
- New counts per type: `not_a_metric`, `other`, ambiguous readings, flags.
- Diagnostic columns: deck, page, type, item id, cell#position, cell text, Python's values, reason, then per pass the
  model's metric, period, unit and actual_or_forecast and the verifier's result.
- The diagnostic also lists every roadmap line of the roadmaps read in every pass (issue #47, the pairing
  investigation): deck, page, line id, cell, line text, its position date (§2) or none, whether the date and category
  are the same in every pass (D of §6), then per pass the date it is paired with (id, cell and text) and the
  category, or "no pair". The tracked reports
  of 2026-10-06 give only the count, so they cannot say which lines move, or whether the date or the category does.
- The token line gives the average of text plus list against 4,000, and `FakeAdapter` replays the new format.

**8. Replaced in llm-structure-reading.md.**

| Section | What is replaced | Now |
|---|---|---|
| §1 | item fields, output, one schema for all types | §3 |
| §2 | value and period matched against cited cells; model flags | §4 (normalisation moves to §1) |
| §5 | cited-cell check | §3 |
| §7 | 3,000-token cap on the text alone | §5 |
| §9 | what `llm_structures` stores | §5 |
| §11 | agreement, fields, reasons, diagnostic, token and roadmap lines | §6–7 |

Unchanged: §3, §4, §6, §8 and the 400,000-token audit cap.

**9. Tests.** Each is first shown failing on a deliberate violation. Enumeration: several figures per cell, dates
left out, both defaults, stable ids, no figure from a digit inside a word, no figure from a date written with slashes
(front-b p16; issue #53). A level (issue #46): a bracketed `users`
count keeps one positive value, a bracketed `user_growth` both readings, and a whole-cell "(30K)" stays negative. Header cells: in a KPI panel a header from
another box only when directly next to the item (front-b p12, p15 and p16), and a neighbour's scale too (a built
slide); in a roadmap (issue #56) no header from a text box of another box (moz p2), a date box directly left counts
(tea p11 i4 and i5 keep 2022-Q2) and one beside it on the right does not (tea p11 i1–i3 rebuild no period from
another box). Prompt v5 (issues #45, #47): every new claim type and tie-break is named; the recorded replies give
moz p20 "~$900", "~9 Months", "~100" and "~$100" and front-b p15 "$7m left", "18 months" and "Profitable in 10
months" their new types, Verified. Reply: bad, duplicate or missing ids, and bad pairs. Verifier: periods, a
pair-dated figure, the adjacent date line (one above or below counts; one each side takes the timeline's direction, also under a title line), flags. Position
dates (issue #47): each line's date box on moz p2 and tea p11, tea p11's lines dated per quarter, a paired line
taking its position date over the model's (milestone and figure, Verified), and the model's date standing where no
position date exists; buffer p6 unchanged. Roadmaps
(issue #49, moz p2): one milestone row per dated paragraph, and no "Label from" from another box. Other: refused
until its type is edited. The 4,000 cap, with the list counted. Boundary: an item line passes only in format, with
raw text that is a figure inside its cell (else reason `bad_item_line`), and no raw text reaches `llm_structures` or
a log.

**Open questions.** None. The cash, burn and runway claim types are in deck-parser.md §2 (issue #45). Roadmap lines
are dated by position where they can be (§2, issue #47).

**Files.** New: `backend/app/structures/items.py`. Changed: `backend/app/structures/{__init__,verify,redact}.py`,
`backend/app/llm/{schemas,gateway}.py`, `backend/app/llm/prompts/{structure_reading.md,RELEASE.md}`,
`backend/server.py` (refuses to approve an unedited Other), `frontend/src/components/DeckPanel.jsx`,
`frontend/src/lib/deckClaims.js`, `backend/tests/test_structure_{verifier,reading}.py`,
`backend/tests/test_gateway_data_boundary.py`, `backend/tests/fixtures/structure_replies/*.json`,
`scripts/consistency_run.py`, and `docs/specs/llm-structure-reading.md` (a pointer at each replaced section).
