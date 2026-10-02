Date: 2026-10-02
Deleted: nothing; the guards reuse the existing Missing Data and target-date-error paths, and the log reuses _engine_step.
Optimized: each metric in compute_all runs guarded, so one failing metric becomes Missing instead of failing the whole compute.
Slow or unclear: the suspected cause (PR #26 date order) did not reproduce; a sweep of as-of × target date on demo data found the real trigger. The task's "Data used" field was left unfilled.
Process change: add a demo-data sweep over as-of month and target date to the suite, so short-horizon edge cases are caught before release.
