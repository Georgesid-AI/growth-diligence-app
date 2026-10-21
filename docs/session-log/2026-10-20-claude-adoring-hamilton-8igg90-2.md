2026-10-20, claude/adoring-hamilton-8igg90 (review round 3 of PR 141).
Deleted: the separate "average revenue per" branch of the ARPA/ARPU patterns (folded into the one per-unit phrase).
Decided: the noun after "per" decides (account, client, customer to ARPA; user, subscriber to ARPU; month, quarter, year to Revenue; any other noun to Other; a hyphen, slash or further noun is a breakdown, Revenue); sales, income and spend take "per" only, so "Sales/Marketing" is no phrase; named rows and named bars now cover all six revenue words.
Slow or unclear: "Revenue per segment" is now Other (any other noun), a change from the earlier Revenue; a title with named bars and "by year" is not handled.
Root cause and rule: one regex per family let each fix open a new over-match; every per-unit change now needs a title list in both directions (stays Revenue, becomes ARPA, becomes Other) in tests/test_unit_economics_pipeline.py.
Process change to propose: list the noun classes in the spec before the regex is written, so the reviewer and the code share one table.
