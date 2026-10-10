Date and branch: 2026-10-10, claude/serene-pasteur-f7ncmb.
Deleted: the per-button blue override, the outline/secondary variants on the Revenue / Volume pair.
Decided: the pair reuses CALCULATE_CLASS (Map and Compute); active follows the reason dropdown only; the inactive button is the same class at opacity-50. Disabled logic (answerReady) left as is, so behaviour is unchanged; "Revenue file confirms" keeps both buttons clickable (George confirmed). The suggested-button ring is kept: with no reason chosen both buttons are pale, so the ring is the only sign of the pre-selected one.
Slow or unclear: spec rule 3 says the inactive button is disabled, but "Revenue file confirms" and "Reason…" leave both pale yet clickable-or-not per answerReady; kept function unchanged (rule 5).
Root cause and rule: the pair had its own button styling, so it drifted from Map and Compute; share one exported class for every primary button.
Process change to propose: check UI changes in a real browser via a throwaway harness entry as part of the task template.
