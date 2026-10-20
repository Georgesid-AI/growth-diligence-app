Date and branch: 2026-10-20, claude/sleepy-goodall-wm0cnh.
Deleted: nothing.
Decided: a Revenue or revenue-growth claim with no `revenue_series` is Unverified "Not computed – revenue series not available" (one constant, one place, where the register finds the engine holds no figure), so it can never carry an observed figure, gap or Definition check; other metrics keep their reasons. The wrong-observed-figure cause was not fixed: it did not reproduce from words alone (rule 13).
Slow or unclear: with an empty or absent series the register already gave no observed figure (probe), so the reported €2,976,920 came from a non-empty series; "No usable recurring revenue rows" is the ARR/MRR missing line, written whenever there are no customer rows, and says nothing about `revenue_series`.
Root cause and rule: reading "No usable recurring revenue rows" as "revenue_series is empty"; the rule is that a bug report names the row's citation (`observed_citation`: sheet and rows) so the series that produced a figure is read, not inferred.
Process change to propose: a Diagnostics line for ARR/MRR should say which series is present, so a missing MRR is not read as a missing revenue series.
