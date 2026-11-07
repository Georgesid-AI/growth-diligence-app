2026-11-07, branch claude/hopeful-davinci-m80p2h (PR 250: finding strings).
Deleted: the "cells skipped by a total formula" / "hardcoded cells in formula rows" wording and its cleanup-list note.
Decided: strings now name what is counted ("N formula rows with hardcoded cells", "N total formulas that omit cells", singular forms), per George; Green strings unchanged.
Slow or unclear: nothing.
Root cause and rule: a count changed unit (cells to rows / SUM cells) while its label stayed; when a check's counting unit changes, grep its label in app, tests and both specs in the same commit.
Cleanup item added to docs/pr6-cleanup.md: none (one line removed, now done).
