2026-10-05, claude/peaceful-edison-ucfrl8, PR #41 decisions: output schema hash in the structure cache key, structure prompt v2 (release r5), cost corrected to the live per-read figure.
Deleted: the cost and headroom figures built on the unmeasured ~9,000-token read, and the cap test's claim that 200,000 stopped at the 20th read.
Optimized: the cache key gains one component instead of a new mechanism; the prompt names the 20 codes by reference to the schema, with three examples, not a second list.
Slow/unclear: the release bump that the prompt edit requires also moves every narrative key, so narratives are re-billed once; $0.45 implies about 290 output tokens a read, below the ~400 estimated from the recorded replies.
Process change: report a live per-read figure (input and output tokens) with each cost question, so estimates are not built on an unmeasured number.
