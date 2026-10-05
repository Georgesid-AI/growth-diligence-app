# CLAUDE.md — working rules

## Architecture
1. Architecture is frozen. Never change it. Only execution steps may change.
2. Do not challenge the frozen architecture when questioning requirements. Only
   execution steps are open.
3. Do not confuse rigor with dumb. Evidence tiers, citations and source references
   are the core of the audit method. Challenge how they are built, never whether
   they exist.
9. If a fix needs an architecture change, stop and report it as an
   "Architecture note". Do not change it.
16. The gateway may read selected deck structures (tables, charts with data labels, KPI
    panels, roadmaps/timelines, hiring tables, unit-economics boxes, use-of-funds
    tables) and spreadsheet header rows with, per column, either up to 3 sample values
    (numeric and date columns only) or a profile (distinct count, typical length, shape
    pattern) for text columns — only after redaction, only with per-audit consent, only
    as extracted text with cell positions. Never raw files, full pages or prose slides.
    The deck parser has no direct link to the gateway.
17. Logs and MongoDB store model JSON output (values with cell references), prompt
    version, model version, content hash, token counts and cost. Never deck text sent to
    the model. Delete audit removes model outputs.
18. Model output never becomes Verified on its own. Python must match every value to a
    source cell. Unmatched values are shown as 'AI suggestion, not verified' or dropped.

## Before and during coding
4. Before coding, in max 5 lines: (a) challenge the requirement: is it needed, who
   needs it, what is a simpler version; (b) list what can be deleted first.
5. Only then optimize what remains. Automate last, and only if it repeats.
6. Keep changes small. No new features unless asked.
12. If docs/specs/<feature>.md exists for the task, it is the agreed scope. Do not
    add to it. If it is unclear or conflicts with the code, stop and ask.
13. A bug task starts with a failing test built from the supplied artefact (run id, stored
    as-of month and whether it was defaulted, target date, P&L present, anonymised upload
    or server log line). Missing or not reproducing: stop and ask. Never fix a suspected cause.
14. What may reach the model or the logs is enforced in backend/tests/test_gateway_data_boundary.py.
    A PR that adds a results key, a reason string, a log line or a guard word extends that file.
15. Never commit client decks or client data to the repo, including as test files.

## Finishing a task
7. A task is finished when the change is committed and pushed. Then create
   docs/session-log/YYYY-MM-DD-<branch>.md with max 5 lines: date, what was
   deleted, what was optimized, what was slow or unclear, one process change to
   propose. If that file already exists, add a number to the name
   (YYYY-MM-DD-<branch>-2.md, ...). Then commit and push the log. Pushing the log
   itself does not count as a finished task. Never log the log.
8. Never write client names or data into the log.
10. Log only in docs/session-log/. Never write to, edit or delete memory/PRD.md.
11. Before reporting, fix any leftover risk you find that is inside the task's
    scope, with a test. A new test counts only after it has failed on a deliberate
    violation. Report only what needs my decision. If a fix goes beyond the task,
    list it under "Decisions for you" and do not build it.
