2026-11-07 · claude/hopeful-davinci-m80p2h (structure-aware spreadsheet reading)
Deleted: nothing; no prompt text, no new model call, no new card.
Decided: facts extracted once at upload (openpyxl) and kept on the dataset; the block sits after the "sheets in this file" line, outside the 40,000-token cell cap and inside the file and audit caps (they count the whole call); the formula, not the reader, sets parent rows on the effective map (the stored reading is untouched); the two new checks are Not applicable, not Blocked, when no workbook has a formula; the cell checks now date a year-less month header under a merged year (check_periods and last_actual used header_period alone).
Slow or unclear: the live job needs the repository secrets, so the model has not read the new block yet; the quarter-subtotal variant moves the monthly report's columns, so its expected map is the same in facts, not in cell letters; openpyxl writes formulas with no cached value, so fixtures patch the values in.
Root cause and rule: two cell checks used a narrower header reader than the figure check did, so a layout the file states was rejected; a perturbed-layout fixture per stated structure finds this offline.
Process change: none.
Cleanup items added to docs/pr6-cleanup.md: files uploaded before this change have no structure facts; the model has not yet read a file with SUM subtotal columns.
