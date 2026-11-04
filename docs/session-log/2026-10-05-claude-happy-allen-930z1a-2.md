2026-10-05, claude/happy-allen-930z1a.
Deleted: the single source_cells field and the "fiscal periods stay unverified" rule.
Optimized: value and period are now cited by separate fields and checked separately, so a year cell can no longer stand in for a value; the column-mapping header stack is capped at 3 rows in both specs, the boundary test and the test list.
Slow/unclear: how a non-December fiscal year maps to a calendar period, and which 3 rows are sent when a sheet has more header rows, are not yet defined.
Process change to propose: moved to docs/pr6-cleanup.md or docs/pr6-cleanup-archive.md.
