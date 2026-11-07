2026-11-07, branch claude/hopeful-davinci-m80p2h (PR 250 follow-up from the Opus review).
Deleted: the remainder-keeping of a partly claimed total, the own-row seed test, Red for the two formula checks (STRUCTURE_AMBER_MAX).
Decided: a relation needs 2+ agreeing formula cells and no single-cell range; facts are matched by workbook position (`Sheet.workbook_index`); hardcoded counts rows (leading constant run exempt, which covers the seed), omits counts SUM cells (walk stops at formula/blank/text, percent rows and non-period columns exempt); contract stays 27 (unmerged), golden unchanged.
Slow or unclear: the finding strings still say "cells" while counts are rows / SUM cells; no on-screen label change made (rule 19.3).
Root cause and rule: heuristics were written against one fixture family and counted cells; next time a new check gets a synthetic layout per false positive named in review before it feeds any rating.
Cleanup item added to docs/pr6-cleanup.md: Diagnostics-note display, Red thresholds and plug-inside-formula miss (three lines).
