# Source association (section 4 of docs/design/claim-review-simplified-design.md): test run, 2026-10-26

Branch `claude/gallant-ramanujan-jsrqms`. Spec: docs/specs/source-association.md. Tests: `backend/tests/test_source_association.py` (43) and
`test_the_layout_evidence_is_python_only_stored_without_text_and_never_sent_or_logged` in `test_gateway_data_boundary.py` (rule 14).

## Written first, run without the change
The change is `backend/app/` and `backend/server.py` (stashed, `association.py` moved aside); the tests and `tests/pdf_support.py` stay.
Result: **39 failed, 56 passed** over the 44 new tests and the 6 existing tests the change had to update (the passes are the pins and the unchanged tests of the listing file).

| Acceptance row | Test (new unless marked) | Without the change |
|---|---|---|
| Rotated axes | axis title states the unit and is the label; title not level with the chart; two titles with different words | fail: `currency assumed` still flagged, no `association`, no `source ambiguous` |
| Rotated axes (reader) | pdf: turned text is one line with its turn; pptx: rotation and vertical text; pdf end to end with bars, swatches, legend, rotated title | fail: `KeyError: 'layout'` / one line per character |
| Distant legends | legend label of the bar's colour; local label over heading and over another series' entry; label too far from its swatch; a lone tile and a sentence are no chart and no legend; the label beside the figure stays | fail: label `None`, no `sources disagree` |
| Repeated colours | one colour with two labels; a legend read inside its own group; one colour in two charts with a legend of neither | fail: no `source ambiguous`, labels `None` |
| Repeated numbers | a number found only in another cell does not carry the period or the metric cited for the other cell (two tests) | fail: `period from another cell` accepted, no `source not associated` |
| Attached dates | marker annotation is not another figure's period; own column header over the heading (`sources disagree`, two buttons) | fail: `period from another cell` accepted; the heading's period wins |
| Attached dates, pins | date attached under the figure; category label under the bars; heading that agrees; no year inferred ("Q3 outlook") | pass (the rule keeps them) |
| Ambiguous headings | two headings, two periods: nothing selected, two buttons with cells and markers | fail: no flag, no card |
| Ambiguous headings, pin | one heading stays informational | pass |
| Incomplete extraction | complete page: dropped with `no printed source`; a picture, chart, graphic, glyphs, format or shapes gap (7 cases): kept, `extraction incomplete`; pipeline: one Diagnostics line, no row / row kept | fail: no drop, no flag |
| Incomplete extraction, pins | page not measured: neither dropped nor flagged; a value the page holds is never dropped | pass |
| Correction records | token, cells and marker kept; no heading prose in the row, the Diagnostics line or the stored item; marker apart from the token | fail: no `cells`, no `marker`, `period_marker` missing |
| Model and log boundaries | page text is `p<n>r<row>c<col>: <text>` and nothing else; layout stored as numbers, hex and closed words; closed words; a dropped claim logs no line of the page (`test_gateway_data_boundary.py` and the new file) | fail: `layout` missing, new words missing |
| Updated existing tests | `FLAGS` (23 → 27) in two tests; the bar-year Diagnostics line gains `cells` and `marker`; the table period from another column's header | fail without the change, pass with it |

## Deliberate violations (CLAUDE.md rule 11)
Each patch must make its test fail; all did: a layout field appended to the page text (boundary test and the new page-text test); heading prose as the logged
`corrected` value; a text key in the stored layout; a dropped claim that logs the page's line; a page with a picture treated as complete; a lone tile counted as a chart (`MIN_BARS` 1); a sentence accepted as a legend label (`LABEL_MAX` raised).

## With the change
Backend: 3697 passed, 26 skipped (baseline before the change: 3653 passed, 26 skipped). `ruff check backend/` (ruff 0.16.8, ruff.toml): all checks passed.
Ten public test decks (`detect_candidates`, no network): 212 candidates before and after, identical content hash.
Eight public pptx and pdf test decks (layout; the two .docx files carry the gap `format`): 163 pages, 48 measured and complete, 115 with a picture over 5% of the page
(full-page backgrounds); 4 turned lines, 205 filled rectangles, 7 legend swatches.
