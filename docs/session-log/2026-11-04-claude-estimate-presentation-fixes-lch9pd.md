2026-11-04, claude/estimate-presentation-fixes-lch9pd.
Deleted: the estimate's use of the "split only in plan years" reason and the per-year ordering of plan cells; the estimate rows no longer carry another role's total-row note.
Decided: an estimate's reason is one constant (`ESTIMATED_REASON`) set in the engine, so the Data gaps row and the report page read the same and the Requested text is untouched; plan cells are regrouped row by row (`by_row`) and printed with the existing `cell_ranges`, in the method text too; the estimate keeps only the notes of its own role's rows (`notes_of_role`). No engine value, status or contract field changed.
Slow or unclear: a range can join the actual OPEX cell to the plan cells of the same row when the two sit in neighbouring columns (D16:H16, not D16, E16:H16); decided not to split them, the cells cited are the same.
Root cause and rule: cells were collected year by year across all rows, so no run of one row was ever consecutive; a citation list is ordered by row before it is printed.
Process change to propose: moved to docs/pr6-cleanup.md or docs/pr6-cleanup-archive.md.
