2026-10-08 · claude/determined-brown-logxag
Deleted: the "metrics missing" tail on the evidence-labels text and raw cost decimals; no code removed otherwise.
Decided: usage totals wording per request (S19); polls stop on any silent error, not only 404, since a stopped poll costs nothing and the panel reloads on the next action. Leftover risks closed: blocker banner kept listening after a 404, usage totals set state after unmount, deck load toasted after unmount.
Slow or unclear: the request named three polls; only the deck AI-reading check is a timer poll, the other two are event or open fetches, so they were hardened rather than given timers.
Root cause: background fetches were written without a "still mounted / still exists" check; rule going forward: spec §13 now requires every background request to stop on delete or leave, with a test.
Process change to propose: a shared useBackgroundFetch helper if a fourth poll ever appears (not built now).
