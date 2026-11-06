2026-11-06 · claude/upbeat-bell-r8x9ro (one list of plan words)
Deleted: PLAN_SHEET_WORD, the second plan-word regex.
Decided: `PLAN_WORDS` is the one list (budget, plan, forecast, reforecast, FC, estimate, projection, outlook, pro forma, AOP, LRP and their plain forms) behind `PLAN_WORD` (another sheet named or titled for a plan) and `PLAN_WORD_CHECK` (a title that supports the boundary); the year mark (FY24E, 2025F) stays a title pattern added to the second only, since a sheet is not named "2025F"; the union means AOP and LRP now also support a boundary as a title, and FC now also names a plan sheet.
Slow or unclear: none.
Root cause and rule: two lists drifted apart by construction; test_both_rules_read_one_list_of_plan_words pins that the second contains the first.
Process change: none.
Cleanup item added to docs/pr6-cleanup.md: none.
