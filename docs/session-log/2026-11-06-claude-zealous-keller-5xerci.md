2026-11-06 · claude/zealous-keller-5xerci (sheet type from name or title, reconciliation sources, parts counted twice; contract 26)
Deleted: nothing.
Decided: the sheet type (checks.sheet_type: name first, then the text above the header row) is set on the map at register time by checks.retype_by_sheet, before the label rule and the overrides; a P&L-role row on a cash-flow or balance-sheet sheet becomes `other` with the note, so reconciliation, TOTAL-vs-months and the trend drop it with no extra code; the reconciliation keys a source by file (deck by page), P&L-type sheet first; a file with no stored cells is still returned as stored; "twice" is parts within 5 % of double the total, a flag field `double_counted` that Worth flagging leaves out; contract bumped to 26 (golden regenerated, identical but for the version).
Slow or unclear: the full suite takes about 2 minutes; the cash-flow fixture's cash preference was first untested (file order alone passed it), so a stray cash row was put on the P&L sheet.
Root cause and rule: nothing stopped a cash statement's "revenue" and "opex" lines from reading as P&L lines; sheet type is now a map fact set by code, pinned by tests/test_sheet_types.py, with each rule failing on a deliberate violation.
Process change: none.
Cleanup item added to docs/pr6-cleanup.md: none.
