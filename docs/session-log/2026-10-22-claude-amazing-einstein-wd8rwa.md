2026-10-22 · claude/amazing-einstein-wd8rwa (issue #151)
Deleted: nothing; the old "ARR is never turnover, so Revenue" assertion in test_deck_parser.py now reads "ARR".
Decided: MRR and ARR get their own deck label (the claim type stays Revenue, the register already proposed the MRR metric from the text); "in <year>" on an MRR or ARR figure becomes Dec of that year with a stored note, one helper for the rules read and the panel read, so no prompt change.
Slow or unclear: the live artefact was not supplied, so the "why Revenue won" answer is from a synthetic page; the deck list does not show the period note (register only).
Root cause and rule: deck_label defaulted every revenue-type figure to "Revenue" and the inconsistency key used it; a label now names the metric, pinned by test_issue_151.py.
Process change to propose: a bug issue should attach the stored candidate JSON of the rows concerned, so the "why" is read from the artefact, not reconstructed.
