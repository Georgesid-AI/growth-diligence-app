2026-11-06 · claude/zen-cray-3xpa1l (per-sheet reading: sheets line, plan fallback for the last actual column)
Deleted: nothing; `_plan_sheet_elsewhere` is now a wrapper over `_plan_sheet_named`, which also names the plan sheet.
Decided: the line is added to the sent payload only (the sheet's own text, caps, masking and parsing are unchanged) and lists every sheet of the file in order, masked; the fallback runs in code when the sheet maps are merged (so the stored reading and its series carry it) and again on the checked map after a re-read merge, needs a plan word on another sheet, none on the sheet itself, and every mapped row with values ending at the last period column; the column's period comes from its header.
Slow or unclear: the full suite takes about 2.5 minutes, past the foreground tool limit once; the fallback column is now also stored on the reading (George's approval on the PR), so series and exports match the checked map.
Root cause and rule: a sheet read alone could not see the plan sheet beside it; the boundary test pins that the line holds sheet names only and the new fixture test pins the fallback on budget_separate_sheet.
Process change: none.
Cleanup item added to docs/pr6-cleanup.md: the sheet_reading prompt must describe the new first line (prompt store, not the repository).
