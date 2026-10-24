2026-10-24 · claude/trusting-ptolemy-lhwq5y (George's decision comment on PR 177: reporting currency and "Last month is complete" also mark results stale; no setting recomputes on its own)
Deleted: `RECOMPUTE_TRIGGER_FIELDS` and the recompute call in the audit update; the old test that pinned the two fields as self-recomputing.
Decided: the two fields join `STALE_ON_CHANGE_FIELDS`; the tick compares as a boolean (missing reads unticked) so a save of the same value marks nothing; the spec text of chat-upload.md §30 and interface-contracts.md §7 follows the comment.
Slow or unclear: the pinned ruff version (0.16.8) differs from the one in the session image (0.16.9); linted with the pinned one in a scratch venv.
Root cause and rule: my first build read George's item 6 narrowly and left two inputs on the old path; when a decision names a rule for set-up inputs, apply it to every input of the same list, and say in the report which were left out and why.
Process change to propose: pin ruff in the session start hook so the lint step runs with the CI version.
