2026-10-10, claude/festive-bohr-er9wdb
Deleted: the one-cell header-row exception for the single word "raise" in _cue_unit, and "chart title" from the spec and comments.
Decided: a merged title row of a table is a heading, so "raise" counts only in a slide title; test: a Sales table titled "Raise prices next year" keeps sales x2 (fails on the old code with use_of_funds x2). Pptx chart titles are structures, not candidates, so no code path read them as cues.
Slow or unclear: nothing; the review line number (1298) had moved, found by the condition.
Root cause and rule: the spec said "chart title" for a case the code detected by cell count; wording and condition must name the same thing. Prevented by the test on the merged-row shape.
Process change to propose: a review finding should quote the code line, not only its number.
