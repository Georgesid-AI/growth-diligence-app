Date and branch: 2026-11-01, claude/clever-turing-3rttfo
Deleted: nothing.
Decided: the "N of M years agree" line counts "Agrees (rounded)" years in both N and M; the rating (result, and whether the check exists) still reads the other years only. Simplest change, one function.
Slow or unclear: if every year is rounded the check still shows no result, so no line appears; left as PR 218 had it.
Root cause and rule: the earlier change filtered rounded years out before building both the rating and the line; the two now read separate lists, and a test pins both.
Process change to propose: none.
