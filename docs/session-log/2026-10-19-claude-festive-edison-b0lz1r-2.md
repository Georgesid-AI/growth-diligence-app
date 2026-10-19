2026-10-19, claude/festive-edison-b0lz1r (follow-up to draft PR 133).
Deleted: the bare "plan" word cue in row_tag.
Decided: "plan" tags a row only when the label starts with plan, planned or business plan, or holds "(plan)" or "plan:"; forecast, budget and target keep their rule; "ARR plan" is now an actual row (an analyst can still set it by hand); §26.15 amended.
Slow or unclear: _norm strips punctuation, so the "(plan)" and "plan:" cues read the raw label.
Root cause: a label word read as a tag without asking what the word means in a KPI sheet; prevented by tests that pair each tag word with its pricing-plan lookalike.
Process change to propose: when a decision lists a heuristic's false positive for George, add the test for it in the same PR.
