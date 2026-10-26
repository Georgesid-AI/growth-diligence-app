# Spec: Source association (one rule for the metric, period and unit of a printed value)
Status: Built 2026-10-26 (George's brief of 2026-10-26). Location: docs/specs/source-association.md.
Scope: section 4 of docs/design/claim-review-simplified-design.md ("Use one source-association rule"), nothing else of that design. The design is not amended
by this file; where it leaves a word undefined (below, "Decided under rule 19") this file says which reading the code takes.
Tests: `backend/tests/test_source_association.py` (written first; the run without the change is in docs/test-runs/2026-10-26-source-association.md).

## 1. Mapping of the design to the schemas and the contract

| Design, section 4 | Where it lands | Contract / schema touched |
|---|---|---|
| A value is accepted with supported associations for metric, period and unit; sources are its cell, a table header or chart axis, a segment label or legend, a heading above | `structures/association.py` (the layout evidence), `page_check.check` (label, unit, period) | none: the page item gains `association` (closed words and cell ids), a server-side key like `checks` and `flags`; `schemas/metrics.py` `DECK_CLAIM_FIELDS` and `CONTRACT_VERSION` are unchanged (no engine output field moves) |
| A valid explicit local association beats a broader heading; disagreement is reviewed | `page_check.period_check` (period), `page_check.check` (label) | new review flag `sources disagree` in `checker.FLAGS`, so in the register's `flags` |
| Rotated text is normalised into the same logic | parser: a turned line is one line with `rot`; `association.Layout.axis_titles` | block field `rot`, cell fields `rot` and `at`; never sent |
| Rectangles and legend colours are layout evidence scoped to the chart; reused colours or several candidate labels are reviewed | parser `layout`; `association.Layout` (bars, swatches, scope) | deck document field `layout`; new review flag `source ambiguous` |
| Layout metadata stays out of model requests | `redact.page_text` is the one builder and writes `p<n>r<row>c<col>: <text>` only | `test_gateway_data_boundary.py` and the new test pin it; no change to what rule 16 allows |
| Heading corrections keep the period token and the source-cell reference, not the heading prose; the actual/forecast marker apart; no year inferred; no marker annotation's date for another figure | `corrections.period_option`, `pages.corrected_row`, `pages._without_text`; `association.period_marker`; `Layout.is_annotation` | correction entries, Diagnostics lines and stored items gain `cells` and `marker` for a period; new review flag `source not associated` |
| A model value with no supported printed source is dropped only when extraction is adequate to establish the absence, with an auditable reason; with incomplete extraction an extraction-review issue is kept; a matching number elsewhere does not establish the metric or period | parser `layout.gaps`; `checker.drop_reason`; `checker.EXTRACTION_INCOMPLETE`; `page_check.check` (a value found only in another cell) | new Diagnostics kind `no printed source`; new review flag `extraction incomplete` |

Nothing in section 4 needed a change of the design or of docs/architecture.md. Evidence tiers, citations and source references are untouched: a model value
still becomes a row only through Python's match to a cell (CLAUDE.md rule 18); this rule adds sources, never a Verified label.

## 2. What the deck reader keeps (`decks/parser.py`)
- **Turned text.** A pdf character that is not upright and whose matrix is a quarter turn is read in the order the file writes it into one line (a run of
  characters in one column, stepping along it without a wide gap). The block keeps `rot`: the clockwise turn, `270` for text that reads upward (a y-axis
  title), `90` for text that reads downward. A pptx shape is turned by its `rotation` and by its text direction (`bodyPr vert`); the block keeps `rot` and the
  place of the frame as it looks on the slide. Text at any other angle is not read as a line. Before, a turned pdf title was read as one line per character.
- **Layout.** `parse_deck` returns `layout`: one entry per slide or page, `{"slide"|"page": n, "rects": [{"at": [l, t, r, b], "fill": key, "scope": n}], "gaps": [...]}`.
  `at` is a share of the page; `fill` is the RGB hex of a solid fill (a theme colour as `theme:NAME:brightness`; a grey or CMYK is converted); white fills, page-sized
  backgrounds (over 35% of the page), stroked-only rectangles and the shaded cells of a pdf table are not kept; at most 400 per page (`shapes` gap above that).
  `scope` is the number of the outermost group a pptx shape is in, 0 outside any group (a pdf has none).
- **A line in a pptx group** keeps `lbbox`, its place on the slide worked out through the group's transform, apart from `bbox`, which stays none for it as before
  (everything that reads `bbox` is unchanged).
- **Gaps** (closed words, `parser.GAPS`): `picture` (a picture over 5% of the page, `PICTURE_SHARE`), `chart` (a native pptx chart: its numbers are not text lines of the page),
  `graphic` (SmartArt or an embedded object), `glyphs` (pdf characters the reader could not decode), `shapes` (more rectangles than the cap), `format` (.docx: a page
  cannot be established). A logo is not a gap. A page with no gap is *measured and complete*.
- The page grid (`decks/pages.page_grids(blocks, layout)`) gives every cell `at` (and `rot`) and the grid `layout` {rects, gaps}. A grid built without the layout
  (a deck stored before this field; a hand-built grid) has no `layout` key: its extraction is **not measured**.

## 3. The rule (`structures/association.py`, `page_check`, `checker`)
Sources of a field, nearest first, as closed words (`association.SOURCES`): `own` (the figure's cell), `header` (a table header, or the label or date beside or above it),
`axis` (a chart's axis title, or the year label under its bar), `legend` (the legend label of the bar's colour), `heading` (the page's title or top band), `other`
(any other cell that states a period), `annotation`.

- **Charts.** A *swatch* is a filled rectangle at most 5% of the page wide and tall, about square, with a line of words (no figure) next to it on its row (at most 6%
  away). Any other filled rectangle is a *bar*. A chart is a pptx group, else the bars within 5% of each other; a swatch inside a chart's margin (5%) belongs to it, any
  other swatch to no chart.
- **Label.** A value printed on a bar (inside it, a tall bar's top within 4% above it, a wide bar's side within 4%) takes the label of the swatch with the bar's colour
  in the same chart (`legend`); a legend of no chart serves the one chart that uses the colour. Several labels (two swatches of the colour in the chart, or one colour in
  two charts with a legend of neither) is **ambiguous**: no label, flag `source ambiguous`. Without a legend entry the rotated lines of words level with the chart and
  within 12% outside its bars are its axis titles (`axis`); two titles with different words are ambiguous. The local label is the cell's `label_cell`; it takes
  precedence over a broader heading the claim cited. A claim that cites *another series' legend entry* is `sources disagree`.
- **Unit.** The unit marks of a value are its cell and the cells beside it (as before) and now the chart's axis titles and its legend label.
- **Period.** The figure's own sources are its own text and the date labels or headers beside it. A period cited from a heading or another cell while the figure's
  own sources state a different one: Python's period is the figure's own, the claim is `sources disagree`, and it waits with one button per candidate (never applied).
  Own sources that state several periods while a heading is cited: `source ambiguous`. A cited heading while the page's heading cells state several different periods:
  `source ambiguous`, nothing selected (the model's period stays, flagged; both headings are the buttons). The year under a bar stays with `year under bar differs`.
- **Marker annotations.** A date printed inside a chart's plot area (above the baseline of its bars, inside its horizontal extent) that is not an axis tick is the date of
  the marker it sits by. It is not a source of another figure's period (the cell and its own text box excepted): `source not associated`, the cited cell sets no period.
  The category labels under the bars are the axis, not annotations.
- **A matching number elsewhere.** The cell tolerance of 2026-10-23 stands (the nearest cell holding the value is taken, `cell corrected`). The metric and period cited for
  the cell the value was *not* in do not follow it: the label stays only if it is next to the cell found, and a period cited from a cell that is no date source of it, nor the
  page's heading, is not carried (`source not associated`, no period cell).
- **Actual/forecast marker.** `association.period_marker`: `forecast` for 2025E, FY26B, Forecast, Plan, Budget, Target...; `actual` for 2024A, Actual(s), Reported; none otherwise.
  A period option keeps `{period, period_cells, marker}`; the marker is never part of the period token. A year that no cell states is never inferred ("Q3 outlook" offers nothing).

## 4. Drop, keep and the reason
`VALUE_NOT_ON_PAGE` on a claim with a value, on a page whose `layout.gaps` is empty (*measured and complete*) is dropped before the register: no row, one Diagnostics line
`{page, kind: "no printed source", metric, value, period}` (the other two kinds, `derived figure, not a claim` and `launch date without product name`, come first). On a page
with a gap the claim is kept, unmatched, with `value not on page` and the review flag `extraction incomplete` (listed under Review). On a page that was not measured nothing is
dropped and no flag is added. A claim with no value is never dropped for this. The drop reason is stored with the checked item (`drop`) and logged; no deck text is in either.

## 5. Flags and words (all closed; `checker.FLAGS`, `test_gateway_data_boundary.py`)
Review flags (the claim is listed under Review): `sources disagree`, `source ambiguous`, `source not associated`, `extraction incomplete`. Drop kind: `no printed source`.
Item key `association`: `{label, period, unit}` each a word of `association.SOURCES` or none, `flags` (the association flags), `options` (period options: token, cell ids, source
word). Present when the grid has the layout or a flag was raised.

## 6. Boundaries (CLAUDE.md rules 16, 17, 18)
- Nothing of the layout is ever sent: `rot`, `at`, `lbbox`, `layout`, `rects`, `fill`, `scope`, `gaps`, `association` are not in `redact.page_text`; a rotated line goes as one
  ordinary line `p<n>r<row>c<col>: <text>`. The page text sent, the 200-character rule, the people and customer redaction and the DECK_PIPELINE switch are unchanged.
- Stored (rule 17): the deck document gains `layout` (numbers, colour hex and closed words, no text); checked items gain `association` and the correction `sources`
  (`{cells, marker}` per period option); Diagnostics lines for a period correction gain `cells` and `marker`. No heading prose, no cell text.
- Rule 18: a source only decides which cell a label, period or unit comes from, and whether a claim is dropped or reviewed; no claim becomes Verified by this rule.

## 7. Decided under rule 19 (engineering)
Geometry constants (`association.py`: swatch 5%, legend reach 6%, bar reach 4%, cluster gap 5%, chart margin 5%, axis reach 12%) and the picture share (5%) are first values
set from the synthetic fixtures; they are measured on the public test decks with `scripts/` before any change. A `format` gap on .docx means a Word document is never dropped.
Group transforms are worked out for the layout only; `bbox` of a grouped line stays none.

## 8. Not built, and why (decisions for George)
1. *The cell tolerance still picks the nearest cell when several hold the number* (George, 2026-10-23, `test_checker_tolerance.py`). The design says only that a number
   elsewhere does not establish metric or period; picking among several equal candidates for review would also be consistent with section 2 of the design. Not changed.
2. *A period stated on the page but not by a source of the figure* ("period on page", `checker.period_on_page`) still passes quietly when the model cited none; only the
   cases above flag. The design's list of candidate sources would make it a review issue; that moves rows, so it is left to you.
3. *A heading as a unit source* ("Revenue ($M)" in the title) is not added to the unit marks: `currency assumed` stays an informational note. Same reason.
4. *The informational acceptance of another cell's period* (2026-10-23, PR 174 decision 2) now yields to the figure's own header or label when that states another period
   (`sources disagree`), as the design's precedence sentence requires; it still holds when the figure has no source of its own.
5. *Dropping rows that were listed.* A value on no cell was a row "AI suggestion, not matched" under Review (George, 2026-10-22, decision 3a). On a page the reader read completely it is now
   dropped, as the design says; on a page with a gap it stays a row. Rows disappearing is a screen change (rule 19.3), built because the brief asks for it.
