2026-10-06, claude/gallant-planck-r9uyvk: spec section 2 now gives each timeline one date direction, from its first line dated on one side only (own commit); verifier and tests follow, with one timeline dated below and one dated above.
Deleted: the rule that left a line with a date line on each side undated. Optimized: one date_direction helper on the existing adjacency, no new data or keys.
Result under --fake: the dates-below public roadmap goes from 0 to 7 of 7 figures Verified (roadmap rate 100%); the other two public roadmaps pair every line as before. Live cost estimated, no live run.
Slow or unclear: "first dated line" read as the first line with a date on one side only; a dates-above timeline whose title sits right over its first date line would take "below".
Process change: have --fake print the estimated live cost from its own character counts, so a cost question needs no separate script.
