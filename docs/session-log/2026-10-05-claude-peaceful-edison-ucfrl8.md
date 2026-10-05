2026-10-05, claude/peaceful-edison-ucfrl8, consistency_run.py --diagnostic (public decks only), 400,000-token audit cap, 20-currency output schema (PR #41).
Deleted: 135 unlisted ISO codes from the schema sent on every call (kept server-side only to check unit_other).
Optimized: output schema 2,560 to 1,703 characters; the diagnostic reuses the run's own readings, with no new report keys.
Slow/unclear: the schema token count and today's output tokens per read could not be measured (no API key); the cache key does not include the schema, so "invalidates the cache" holds in content, not by key.
Process change: a task that changes the output schema should say whether stored readings must miss, since the structure cache key does not cover the schema.
