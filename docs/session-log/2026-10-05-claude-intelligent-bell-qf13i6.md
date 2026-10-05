2026-10-05, claude/intelligent-bell-qf13i6.
Deleted: the deck-parser.md §4 rule that the gateway never reads parsed text (replaced by rule 16); spec draft cut from 1,693 to 1,148 words to fit 2 pages.
Optimized: rules 16–18 added to CLAUDE.md and deck-parser.md §4; new spec docs/specs/llm-structure-reading.md reuses the existing guards, cache, fake adapter and purge_run instead of new ones.
Slow/unclear: the "architecture document" did not exist under that name (closest was deck-parser.md §4); temperature 0 is rejected by claude-sonnet-5-5; no run log screen exists.
Process change: keep one docs/architecture.md that CLAUDE.md rules 1–3 and 16–18 point to, so "the architecture document" names a file.
