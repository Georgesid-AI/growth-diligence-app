2026-10-05, claude/intelligent-bell-qf13i6.
Deleted: whole-word customer matching on the structure path, and sending deck structures before the revenue file is mapped.
Optimized: one rule (substring, any case, 4+ characters) covers samples, deck structures and deal names; decks wait in a queue instead of going out with unknown customer names.
Slow/unclear: substring matching needed three guards the decision did not name (numeric names, the target's own name, pseudonyms on the second pass), added and flagged for confirmation.
Process change: for any text-replacement rule, list in the spec what it must never touch, next to what it replaces.
