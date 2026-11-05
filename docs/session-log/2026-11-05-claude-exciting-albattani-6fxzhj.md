2026-11-05 · claude/exciting-albattani-6fxzhj (series differences in the Uncertain list)
Deleted: the bare "N periods" wording of a series candidate (a series item never shows the period count alone now).
Decided: series are compared in code with the period normalised ("2021-3" is "2021-03") and a value tolerance of 0.5% or 1 unit, either one; a period only one read gives is a difference; the item carries `series_diff` per field (first period in time, both values, periods differing, periods in both) and the screen words it from that; rows are grouped on the diff too, so two rows with different differences stay apart. Numbers on screen use lib/format.js (a raw toLocaleString failed the no-raw-numbers test).
Slow or unclear: no fixture holds rows 33 and 43 (the Tc shape in the tests is synthetic: rows 10-16, 23, 24 and 20-32, 40-56), so which of value, period or formatting differed in the real file cannot be answered from the repository.
Root cause and rule: series were compared with strict equality, so a number formatted differently or a period written "2021-3" raised an item; the compare tests in test_reading_series_diff.py now pin the tolerance and the period form.
Process change: none.
Cleanup item added to docs/pr6-cleanup.md: none.
