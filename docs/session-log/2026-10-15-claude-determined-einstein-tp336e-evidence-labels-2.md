2026-10-15, claude/determined-einstein-tp336e-evidence-labels (fix on PR 1: decision 2, plan section 5 amended)
Deleted: "growth basis unknown" from the plan's Inconclusive row, and the open "Decisions for you" item in evidence-labels.md.
Decided: Inconclusive requires a test that ran, so every Inconclusive row carries the computed figure, its source and a reason, and no gap; an unknown growth basis is Unverified (no test can run without a basis); the code already did this, so the change is the plan wording, the spec, and one invariant test over the register.
Slow or unclear: nothing.
Root cause and rule: the plan listed one case in two statuses (section 5 vs sections 3 and 7.1); a status definition that names a case is checked against every other section that names the same case before the plan is final.
Process change to propose: the plan's status table and its release tests are read side by side before the specs are written.
