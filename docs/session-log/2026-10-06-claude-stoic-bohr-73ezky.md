2026-10-06, claude/stoic-bohr-73ezky: issue #48, KPI panels keep label boxes, value boxes and a title as label; spec, failing tests, code as three commits. Same 22 KPI panels on the test decks, 13 gain cells; timelines unchanged.
Deleted: the KPI branch's duplicate figure filter; KPI_LABEL_MAX renamed KPI_LINE_MAX (it never was the label length). Optimized: axis ticks reuse section 2's rule (claims.tick_lines) instead of a second copy.
Measured: longest label 39 characters, limit 59. Applying 59 to KPI box lines too would add 20 prose panels, so it applies to labels only (flagged for decision).
Slow or unclear: decision 2 says "directly above", but its own moz p20 example sits beside the value; "holds only a figure" needed "one figure" to keep "3/1/15" axis dates out.
Process change: when a recorded decision cites an example, check the example's geometry on the deck before writing the rule.
