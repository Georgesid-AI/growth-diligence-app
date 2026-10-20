2026-10-20, claude/nifty-babbage-062v5q (two findings on a real audit: per-column table periods, fiscal-year window of a bare-year claim)
Deleted: nothing.
Decided: neither finding reproduces on main, so no engine or parser code changed (rule 13); one test file pins both behaviours on synthetic data (a four-quarter table in one-figure-per-cell and one-cell shapes with the Contract value row; a bare-year claim over three years of actuals, plus the December fallback of a missing year-end setting), each shown to fail on a deliberate violation.
Slow or unclear: the artefact is a description, not a run id: no stored as-of, no server log line, no upload, so the 5.9x and 3.9x year totals cannot be traced from the code alone; the window (period_range, December when the setting is missing) is right, so the cause sits in the stored series or in a run made before PR 137.
Root cause and the rule that prevents it next time: not found; rule 13 applies, nothing was fixed on a suspected cause.
Process change to propose: a finding on a real file names the run id and the register rows (claim id, observed_at, observed_source rows) so the first test is built from them.
