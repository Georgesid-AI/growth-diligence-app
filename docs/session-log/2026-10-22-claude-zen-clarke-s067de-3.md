Date and branch: 2026-10-22, claude/zen-clarke-s067de (review of PR 157: four points).
Deleted: the `edited` status from the review page's auto count; the deck list's own count source (`auto_approval` text), both now read approved + `auto_accepted`.
Decided: any status the analyst sets clears `auto_accepted` (single Approve, Approve all, Reject), not only an edit; the send-back runs at the end of every calculation and at the start of the claims stage, with the register's own code, and does nothing without results (no mass revoke on a stale audit); the note is a candidate field `auto_note`, cleared by any analyst status or a new auto-approval.
Slow or unclear: the sandbox ruff is 0.16.9 and the repo pins 0.16.8; a separate venv with the pinned version was needed.
Root cause and rule: a decision (George's comment) was applied to one exclusion path but not to the row-level test and the status writers; rule to add: a decision about who may approve is tested at the candidate test, the row test and every status writer.
Process change to propose: a one-line checklist in the PR template listing every writer of a candidate status when a PR changes what a status means.
