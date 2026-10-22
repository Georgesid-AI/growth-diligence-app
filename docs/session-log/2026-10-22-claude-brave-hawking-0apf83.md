2026-10-22 · claude/brave-hawking-0apf83 (follow-up to PR for issue #151)
Deleted: nothing.
Decided: the unit decides what is a run rate (a figure with any unit gets no MRR/ARR label), the simplest rule that covers percentages, counts and multiples; a Sales metric is the first Sales word in the figure's own text, kept out of `deck_label` so no label changes on screen; the note sits in the existing Period cell, no new column.
Slow or unclear: "metric" for the Sales family is read from the family's own keywords, so win rate and conversion (both %) are also kept apart; the panel read has no model-given unit for a count other than what the item carries.
Root cause and rule: the inconsistency key held the claim type and the revenue deck label but nothing for Sales, and the MRR label ignored the unit; both are pinned by test_issue_151_followup.py.
Process change to propose: when a PR adds a label to a family, list in the PR which other families share its key, so the next family is a decision before the artefact shows it.
