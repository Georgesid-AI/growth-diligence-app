2026-10-30, claude/dreamy-volta-i698sn
Deleted: plan-side figures from the expected maps of yearly_pnl (F4), actual_budget_variance (R5, S5) and budget_separate_sheet (Budget G3).
Decided: expected figures cover only what the prompt requires (latest actual); plan cells stay covered by the row entries. The comparison already loops over expected figures only, so extra returned figures are no difference; a test now pins it. JSON edited by hand because the builder had drifted from the committed maps (variance_columns).
Slow or unclear: the builder script and the committed expected JSON disagree on variance_columns; rebuilding would change the maps beyond this task.
Root cause: expected maps were generated from the ideal reading, so they asserted everything in it. Rule: expected = what the prompt requires; the ideal reading (file_map) may hold more.
Process change: a test that the builder reproduces the committed expected JSON.
