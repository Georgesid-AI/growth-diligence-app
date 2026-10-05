2026-10-05, claude/beautiful-feynman-kjne02 (2).
Deleted: nothing; the narrowed inconsistency rule and the flag kept after an edit were already in the spec and are confirmed.
Optimized: "profitable" counts as EBITDA and a Net profit type (net profit, net income, net loss, a loss stored negative) types two figures correctly; recall 118/121 (97.5%), precision 107/236 (45.3%), to review 236.
Slow/unclear: the recall test matches by value only, so a figure that changes type moves neither recall nor precision; the type fix shows only in the candidate diff.
Process change: let the recall test also report how many matched candidates carry the listed type, so a type change is measured, not only seen in a diff.
