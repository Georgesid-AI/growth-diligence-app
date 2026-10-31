date and branch: 2026-10-31, claude/friendly-ritchie-urp1t3
deleted: nothing; the preflight's early `return 1` is gone, replaced by a report-only deck path.
decided: the preflight line now ends with [binary, exit code, pdf produced or not, first stderr line] from one extra conversion run only on failure; the deck fixture's differences are printed and not counted (issue #207), sheets still fail the job.
slow or unclear: the CI line itself is not captured yet, issue #207 holds the line the code prints locally with an empty PATH; replace it with the first CI run's line.
root cause and the rule that prevents it next time: render.PageImageError carries a closed reason by design, so the install failure was invisible in CI; a preflight in CI must log its cause where the closed reason is deliberately blind.
process change to propose: when a CI step is allowed to fail, open its tracking issue in the same PR and name the issue number in the summary line.
