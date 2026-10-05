2026-10-05, claude/lucid-keller-hmzh5f, spec line for the consistency report path (PR #38).
Deleted: the PR note saying the spec did not name docs/test-runs/.
Optimized: llm-structure-reading.md §11 gains one line: the report is written to docs/test-runs/consistency_<date>.md, with -2, -3 suffixes for same-day runs; the other three choices (--fake to temp, --keep-db until the next run, --db pattern) stay as built.
Slow/unclear: nothing.
Process change: when a task names an output path the spec lacks, add the spec line in the same PR instead of flagging it for a second round.
