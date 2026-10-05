2026-10-05, claude/peaceful-edison-ucfrl8, verifier normalisation: dot before three digits read either way, brackets negative only around the whole figure, a cell's own period (PR #42).
Deleted: nothing; the bullet rule was not built (it does not reproduce on the decks: the only bulleted cell holds three figures).
Optimized: one cell parse gives both dot readings; the cell's own period reuses period_cell and the existing correction path.
Slow/unclear: the diagnostic file is untracked and was not in the checkout, so tests use the same cells parsed from the public decks; the fake run cannot move the match rate (no recorded reply cites these cells), and the live rate needs the live readings.
Process change: attach the diagnostic rows (or commit the public-deck diagnostic) with a verifier task, so tests use the model's actual readings and the new live match rate can be computed in the session.
