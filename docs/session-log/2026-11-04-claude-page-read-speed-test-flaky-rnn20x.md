2026-11-04, claude/page-read-speed-test-flaky-rnn20x
Deleted: nothing.
Decided: the timeout test now uses a 2.0 s page timeout and a 5.0 s slow page (was 0.2 s and 0.6 s), so a loaded runner cannot push the other pages past the timeout; it still proves that only the slow page is asked again. A fake clock was not needed.
Slow or unclear: the test now takes about 8 s because the slow page's thread sleeps 5 s before the loop exits.
Root cause and prevention: a wall-clock timeout of 0.2 s is too tight for a shared runner; timing tests keep at least a 10x margin between the timeout and normal call time.
Process change: none. Cleanup item added to docs/pr6-cleanup.md: none.
