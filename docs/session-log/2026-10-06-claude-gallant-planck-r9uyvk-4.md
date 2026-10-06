2026-10-06, claude/gallant-planck-r9uyvk: spec section 2 date direction no longer follows a title line (own commit): lines dated on one side only must agree, and when they disagree only those holding a figure count; code and tests follow.
Deleted: the first-line rule, and the item list's own copy of the period-header check (now shared with the direction). Optimized: nothing else.
The two rules first asked for (ignore lines before the first date line; count only lines with a figure) each left the dates-below public roadmap with no direction (7 to 0 Verified under --fake); the user chose the agree-then-figures rule. All three public roadmaps and the --fake report are unchanged.
Slow or unclear: the live consistency run could not start; this environment has no API key and no MongoDB.
Process change: check a proposed rule against the public decks with a throwaway script before it goes into the spec, so a conflict shows before the spec commit.
