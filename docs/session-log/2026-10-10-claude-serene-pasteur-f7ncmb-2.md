Date and branch: 2026-10-10, claude/serene-pasteur-f7ncmb (restarted from main after PR 88 merged).
Deleted: the ring on the suggested Revenue / Volume button.
Decided: the file note is renamed in both backend NO_FILE_PERIOD and the frontend constant (the frontend compares them to hide "Revenue file confirms"); the two spec quotes in claim-matching.md follow, applied as given. aria-pressed on the suggested button is kept (not a ring, tests rely on it).
Slow or unclear: with no reason chosen both buttons are pale and the suggested one is no longer marked visually; the analyst now sees no pre-selection hint (George's call).
Root cause and rule: one display string lived in two languages with an equality check between them; any string used for logic should be exported once and tested on both sides.
Process change to propose: send file_note's code, not its text, from the backend so the frontend need not compare strings.
