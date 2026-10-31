2026-10-31 · claude/gracious-brown-j00g24
Deleted: nothing.
Decided: the deck box returns as DeckPanel in a compact mode (upload box, scope text, per-deck summary line; claims list stays legacy); summary and tables count figures only, other outcomes are notes (row notes in the lines table, file notes under the summary); the strip's period comes from the register (first series month to last actual month), then the engine period, then the as-of month.
Slow or unclear: "company names coded" (reading screen) and "tokenised" (deck panel) were two words for one count; the new line says coded.
Root cause and rule: PR 206 hid the whole deck panel behind legacy instead of only its claims list, and counted every check item, not figures; a screen change that removes a block needs a test that the block it keeps is still there.
Process change to propose: a spec line listing what stays on each default screen, checked by one render test per screen.
