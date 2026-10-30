2026-10-30, claude/dreamy-volta-i698sn (five review items on PR 205).
Deleted: the per-file entries of the fixture workflow's path filter, replaced by one list (.github/reading-path.txt); the "batch" key of a re-read.
Decided: the filter lists the files the sheet reader reaches (app/llm taken whole); a re-read is keyed on the reading key plus its item keys, the reason is stored and no longer part of the key; the first reading goes into the check's re-read entry only when the re-read is also rejected; the startup check logs one line and never stops the server.
Slow or unclear: test_growth_engine.py::test_all_metrics fails the same way on the PR head before these commits (not touched here).
Root cause and rule: the filter was written by hand beside the imports; a test now derives the reading path from the imports and fails when the list falls behind.
Process change to propose: any workflow path filter that stands for a code path gets a test against that path's imports.
