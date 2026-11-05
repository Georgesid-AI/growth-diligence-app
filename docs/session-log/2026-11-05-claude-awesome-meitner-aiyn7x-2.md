2026-11-05, claude/awesome-meitner-aiyn7x (George's answers on the review of commit 2 of PR 237).
Deleted: nothing.
Decided: the row compare of the consistency pass takes unit, currency and basis beside role, metric, series, segment flag and parent row (three parametrised tests, each failing first with no item produced); the candidate buttons name the differing value ("currency EUR" / "currency USD"), with a frontend test that failed first, because two readings of one role with only the currency apart read the same before; the sheet-level hold stays; the reviewer input is unchanged; the PR body now describes the branch as it is.
Slow or unclear: nothing.
Root cause and rule: the compare listed the fields of the brief and the button words listed the fields of the first design; when a compared field is added, the words that tell the candidates apart are extended in the same change, with a test on the words.
Process change: cleanup item added to docs/pr6-cleanup.md: none.
