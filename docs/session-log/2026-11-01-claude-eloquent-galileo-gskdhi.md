2026-11-01, branch claude/eloquent-galileo-gskdhi
Deleted: nothing.
Decided: the Upload page fires the existing blockers-changed event when sheet_reads_pending falls to 0, so the banner reloads without a page reload; nav tab renamed to "Upload".
Slow or unclear: the backend suite takes over two minutes and was moved to the background by the tool timeout.
Root cause: the blocker banner only reloaded on its own events, and the background reader fired none; rule: any background job that changes server state the banner reads must fire the event when it ends.
Process change to propose: have the test runner script wait in the foreground with a longer timeout.
