2026-10-05, claude/clever-ride-mc8i6e, PR #40 decisions applied: full report printed after the summary line, cap refusals log reason=spend_cap or reason=token_cap, spec §9 and §11 updated.
Deleted: nothing; the -2 suffix logic stays, the lost report was removed by a re-import, not overwritten.
Optimized: the cap line maps the guard's code to a closed word (llm_calls keeps the code); the spec names only the not-read paths that log a line; each new test failed first; 804 backend tests pass.
Slow/unclear: nothing; the lock-busy path still logs no line (not asked, cannot occur in the single-process script).
Process change: a manual paid run prints its whole report to stdout, so an environment that discards untracked files never loses it.
