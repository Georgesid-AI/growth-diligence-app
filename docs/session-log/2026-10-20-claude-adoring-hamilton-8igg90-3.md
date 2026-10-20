2026-10-20, claude/adoring-hamilton-8igg90 (correction to round 3).
Deleted: the "any other noun is Other" pattern and the unused period-noun constant.
Decided: Other is a closed list (employee, FTE, order, transaction, store, seat, licence/license); every other noun after "per" (segment, product, region, country, geography, market, channel, type, cohort, line, use case, vertical...) stays Revenue.
Slow or unclear: "other" in George's list read as "etc"; an unlisted unit such as "head" stays Revenue until named.
Root cause and rule: I generalised "any other noun" from a rule that listed examples; when a rule gives example lists, code a closed list and ask before widening.
Process change to propose: put noun classes as tables in the spec so tests are generated from the table.
