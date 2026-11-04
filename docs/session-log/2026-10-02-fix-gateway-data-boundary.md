Date: 2026-10-02
Deleted: file/sheet/column/raw-value fields, run_id and computed_at from the LLM payload; plain str.replace matching.
Optimized: one allowlist in build_outbound; segment labels reuse pseudonym_map; one token regex shared by redact, restore and leak check.
Slow or unclear: the task's "requirements-dev" did not exist (pytest is already in requirements.txt); free-text scrub of headers was dropped as it hit ordinary words.
Process change to propose: moved to docs/pr6-cleanup.md or docs/pr6-cleanup-archive.md.
