2026-10-31, claude/keen-franklin-yojqgt
Deleted: the frontend NOTE_MAX constant for the analyst note and the .replace("tokenised"→"coded") shim in deckSummaryLine.
Decided: the counter reads note_max from the verdict response and is hidden if absent (no second constant); counts printed with fmtExact so "0/1000" has no separator and passes the raw-number scan.
Slow or unclear: nothing.
Root cause and rule: summary wording was patched at display time in one place and not at source; wording now lives at source, and a test scans every summary line.
Process change to propose: none.
