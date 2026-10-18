date and branch: 2026-10-18, claude/admiring-goldberg-2uponv
deleted: the old order of the hub tile lines, the old drop-zone sentence ("Also useful ... Board decks go to the Deck panel"), the Run audit block's place above the FX settings.
decided: S4 is kept as plain text (placeholder) built from a lead and a bold part, so only ".xlsx or .csv only" renders bold; the empty line in the tile is a spacer grid row, not a margin hack, so a test can find it.
slow or unclear: nothing; the Run audit (deferred) drop-zone text is unchanged, as it is no longer used on the page.
root cause and rule: UI order and wording were asserted only in part; the new tests assert order (tile, page) and the bold span, and failed on the old code first.
process change to propose: when a spec wording edit is given as exact text, store it as a constant pair in the same commit as the test that pins it.
