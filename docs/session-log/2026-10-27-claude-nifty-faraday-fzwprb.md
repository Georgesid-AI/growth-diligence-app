2026-10-27 · claude/nifty-faraday-fzwprb (page-image sections 4 and 5)
Deleted: the abs() rewrite of a value (X2) and the heading-period correction of a model period (C3); nothing else.
Decided: codes handled as two groups (label L1/C4, period P2/C1/C3) with George's definitions in the PR; a model period against a cited heading is kept with the existing flag "sources disagree" (two buttons) rather than a new flag; label_text/segment/share_of are stripped from the stored item (the model reply is kept as it came); is_quote is carried and validated, with no behaviour because the design gives none.
Slow or unclear: the full backend suite takes 3.5 minutes; the contract version is asserted in eight test files; no pie slice builder exists, so the legend test uses the bar-chart builder (same swatch rule).
Root cause and rule: a rule that retyped a field (value, period, label) hid the model's reading; a check may flag a field the model set and fill only a blank one.
Process change to propose: one shared constant for the contract version in tests, so a bump is one edit.
