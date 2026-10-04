2026-10-04, claude/beautiful-feynman-kjne02 (3).
Deleted: the per-deck file lines under the panel heading; the deck name, pages and Remove deck now sit with the selected tab.
Optimized: one tab per deck plus All, opening on the newest deck; remove deck with a confirm step deletes its text and all its claims; within a deck, to review first, then by slide or page, set at load so rows do not jump.
Slow/unclear: two probes missed at first: parse order already matched slide order, so the order test could not tell; a sed probe never applied and passed silently.
Process change: probe with an exact string replacement that asserts it matched, never a sed pattern that can silently miss.
