2026-10-15, claude/determined-einstein-tp336e-claim-types (fix on PR 3: decisions 4 and 5)
Deleted: the "no row in the plan's table" paragraph and the two open decisions in claim-types-and-correction.md.
Decided: Unit economics is a row of the plan's table (ltv, cac, ltv_cac, customer_lifetime, trials_per_day): metric, value, unit, period and figure type required, no population, currency required for the money values only (ltv and cac join the amount types; a ratio, a lifetime and a count do not need one); a figure the parser cannot type is Other and never a task, which the existing unknown-type test already pins.
Slow or unclear: nothing; all five types stay Unsupported (no app metric), so the row changes what Edit asks for, not a label.
Root cause and rule: the requirements were implied by the Costs row, so ltv and cac asked for no currency; a type listed in the plan's table has its own test row for every required field it names.
Process change to propose: the type table in the plan and the type groups in code are compared by a test, so a stored type with no table row fails the suite.
