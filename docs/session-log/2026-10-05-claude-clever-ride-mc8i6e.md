2026-10-05, claude/clever-ride-mc8i6e, consistency run follow-up: provider error status and type in llm_calls and the not-read line, retry-after honoured (cap 20 s), --pause 2 s, one not-read line per pass (PR #40).
Deleted: the model call hidden in the pass 2/3 cache lookup (a miss sent the structure twice per pass).
Optimized: 429/529 retry already existed, so only retry-after was added; the breaker was checked with a test instead of a new message; each new test failed first; 802 backend tests pass.
Slow/unclear: the same-day report overwrite did not reproduce (two runs write -2), so it was not changed; "provider_error" can only be a non-retried 4xx, which the next live run's line will name.
Process change: a bug report from a live run carries the exact log line and the command run, so the failing test is built from it and not from a guess.
