2026-11-06 · claude/upbeat-bell-r8x9ro (a row's end is strong evidence beside a plan sheet)
Deleted: the null as-of month and the dedicated test I put on the budget_separate_sheet expected map; it is back to 2024-06 and in the generic loop.
Decided: a `row_ends` piece is strong when its column is the sheet's last period column and another sheet of the file has a plan word (budget, plan, forecast, reforecast, projection, outlook, estimate, pro forma, AOP, LRP) in its name or in a text cell of its first three rows; otherwise weak, as are repeated_values, round_values and layout, so "weak evidence only" stays for every other case; the title is the first three rows because the other sheet may not be mapped, and the rule's word list is its own regex (PLAN_SHEET_WORD), apart from the list that decides whether a title supports the boundary.
Slow or unclear: the plan word is looked for in sheet names and title rows, not in every cell, so a plan sheet titled below row 3 stays weak; the live job was not run.
Root cause and rule: weak evidence was decided by kind alone; tests/test_prompt_v5_compat.py now pins both conditions (last period column, plan sheet elsewhere) and fails when either is dropped.
Process change: none.
Cleanup item added to docs/pr6-cleanup.md: none.
