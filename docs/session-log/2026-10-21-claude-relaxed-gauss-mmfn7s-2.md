Date and branch: 2026-10-21, claude/relaxed-gauss-mmfn7s (PR 147, decision 1 of George's comment).
Deleted: nothing; the "no figure" check of `confidence` lost its direction-only condition.
Decided: a candidate with no figure is scored Medium "no figure" unless it is a product, break-even (ebitda) or unknown-type milestone line, which are scored as before (decision 2 keeps them as they are); the check is on the claim type, so no new field.
Slow or unclear: the full backend suite runs about 100 s with `-n 4`; serially it exceeds the 120 s default timeout and the harness moves it to the background.
Root cause and rule: the confidence checks skipped every figure-less candidate except directions, so a surviving heading scored High; a rule that keeps a class of candidate lists how that class is scored, in the same spec line.
Process change to propose: the session start hook installs ruff from ruff.toml's pin and pytest-xdist, so the suite fits one foreground call.
