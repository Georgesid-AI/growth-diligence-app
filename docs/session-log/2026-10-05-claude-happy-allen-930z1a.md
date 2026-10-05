2026-10-05, claude/happy-allen-930z1a.
Deleted: nothing.
Optimized: deck-parser.md §2 now defines the period rules the verifier cites (header stack, two-cell periods, month names in three languages, fiscal and relative columns), and llm-structure-reading.md §1 lets source_cells carry the period and year cells.
Slow/unclear: the new rules clash with older lines in the specs (merged-span notation vs r<row>c<col>, the period enum with no fiscal-year form, "the header row" on the column-mapping path) and with claims.py, which maps FY23 to 2023 today.
Process change: when a rule is added to one spec, list every spec line and code path it contradicts in the same request, so they are settled before the commit.
