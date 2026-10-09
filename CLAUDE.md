# CLAUDE.md — working rules

## Architecture
1. The architecture (docs/architecture.md) is frozen. Never change it; only execution steps may
   change. If a fix needs an architecture change, stop and report it as an "Architecture note".
3. Do not confuse rigor with dumb. Evidence tiers, citations and source references
   (docs/architecture.md) are the core of the audit method. Challenge how they are built, never
   whether they exist.
16. The gateway may read selected deck structures (tables, charts with data labels, KPI
    panels, roadmaps/timelines, hiring tables, unit-economics boxes, use-of-funds
    tables) and spreadsheet header rows with, per column, either up to 3 sample values
    (numeric and date columns only) or a profile (distinct count, typical length, shape
    pattern) for text columns — only after redaction, only with per-audit consent, only
    as extracted text with cell positions. Never raw files, full pages or prose slides.
    The deck parser has no direct link to the gateway.
17. Logs and MongoDB store model JSON output (values with cell references), prompt
    version, model version, content hash, token counts and cost. Never deck text sent to
    the model. Delete audit removes model outputs. Rules 16–18: see docs/architecture.md.
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
   docs/session-log/YYYY-MM-DD-<branch>.md (-2, -3, ... if the name exists) with six lines: date
   and branch; deleted; decided (what and why, optimizations included); slow or unclear; root cause
   and the rule that prevents it next time; one process change to propose. Run figures go to docs/test-runs or the PR, never the log. Commit
   and push the log. Neither the log nor a spec wording edit applied as given is a task: the
   edit rides the next commit on its branch and that task's log.
8. Never write client names or data into the log.
10. Log only in docs/session-log/. Never write to, edit or delete memory/PRD.md.
11. Before reporting, fix any leftover risk you find that is inside the task's
    scope, with a test. A new test counts only after it has failed on a deliberate
    violation. Report only what needs my decision. If a fix goes beyond the task,
    list it under "Decisions for you" and do not build it.

## Rule: which decisions to bring to George
19. Decide engineering questions yourself: rule wording, limits measured from data, test design,
    code structure, commit order, naming, and anything cheap to change later. Stop and ask
    George only for these three kinds of decision:
    1. What counts as a metric, and when a figure may be labelled Verified. Examples:
       whether followers are users, whether a price is a metric, whether a range is one
       figure.
    2. Anything that costs money or touches client data: a live API run, sending deck text
       outside the app, storing anything about a client.
    3. Anything that changes what the analyst sees on screen: a new or removed column, a
       changed label, rows appearing or disappearing.

    When you ask, put the question first, in one sentence, then the options with your
    recommendation. One message, all open decisions together, not one at a time.
20. Degrade, don't die: if the LLM gateway fails or times out anywhere, every computed metric still renders
    with its citation and a 'narrative unavailable' note.
21. Three hard blockers, and nothing else, render at the top of every audit view: the revenue file Missing
    (S16a, from the first Calculate; a revenue file uploaded with its mapping unconfirmed, S16d, always;
    docs/specs/chat-upload.md §16), a top-5 claim Contradicted (a miss or a beat), and a revenue reconciliation gap
    above 2% over the window of docs/specs/chat-upload.md §6.2. Per-month gaps go in the reconciliation evidence
    table, never in the banner.
22. Delete audit requires typing the company name and removes every document of the audit in every
    collection, saved mappings and stored files included.
23. Any change to engine output fields changes backend/schemas/metrics.py and the contract test
    (backend/tests/test_interface_contracts.py) in the same PR. Spec: docs/specs/interface-contracts.md.
