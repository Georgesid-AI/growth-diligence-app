2026-10-05, claude/peaceful-edison-ucfrl8, PR #42 decisions: a bracketed number after text matches either sign, recorded in bracket_reading; bullet rule dropped.
Deleted: the one-sign rule for text-before brackets and its tests (it made "Net loss (1,200)" positive only); the open bullet decision.
Optimized: one list of cell readings (number, dot reading, bracket reading) replaces the separate thousands value, so dot and bracket ambiguity combine without new code paths.
Slow/unclear: nothing.
Process change: when a normalisation rule picks one sign or scale on a guess, ask up front whether to accept both readings and record which, as dot_reading and bracket_reading now do.
