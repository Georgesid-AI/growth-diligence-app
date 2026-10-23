# CLAUDE.md — working rules

## Architecture
1. The architecture (docs/architecture.md) is frozen. Never change it; only execution steps may
   change. If a fix needs an architecture change, stop and report it as an "Architecture note".
3. Do not confuse rigor with dumb. Evidence tiers, citations and source references
   (docs/architecture.md) are the core of the audit method. Challenge how they are built, never
   whether they exist.
16. The gateway may read selected deck structures (tables, charts with data labels, KPI
    panels, roadmaps/timelines, hiring tables, unit-economics boxes, use-of-funds
    tables) and spreadsheet sheet names, title rows and header rows with, per column, either up to 3 sample values
    (numeric and date columns only) or a profile (distinct count, typical length, shape
    pattern) for text columns — only after redaction, only with per-audit consent, only
    as extracted text with cell positions. Never raw files, full pages or prose slides.
    For the sheet_structure step only (approved by George, 2026-10-18), the model may receive
    every text cell of a sheet (title rows, headers, row labels, indents, num/blank markers),
    after redaction and the withhold rule; never any figure; cap 400 labelled rows per sheet.
    For the file_recognition step only (approved by George, 2026-10-19), the model may also receive the row labels of a sheet the rules read as
    metric names (revenue, ARR, MRR, customers, churn, bookings, forecast, budget, cost, margin, cash and common variants), after redaction; every
    other sheet's labels go as "Row 1", "Row 2"; on every sheet the 3 sample values of a column come from different rows chosen from the file hash, never the
    same row in two neighbouring columns; never a figure beyond the per-column sample; at most 400 rows with text.
    For the page_claims step only (approved by George, 2026-10-22, PR #158 decision 1b; the default path since 2026-10-22,
    DECK_PIPELINE=ai, docs/design/ai-reads-rules-check.md), the
    model may receive the redacted text lines of a deck page that carries a figure written in digits, prose lines included, as
    extracted text with cell positions, at most 5 pages per call; a page with no such figure never goes, and number-words do not
    count as figures. Prose lines pass the people-name rule as well as the customer rule before they go.
    Amended 2026-10-22 (George, review of PR #159): the gateway refuses the step unless DECK_PIPELINE is "ai"; a line over 200
    characters is left out by the sender and refused by the gateway, as a structure cell is; a line that is only the page's own
    number ("3", "Slide 3", "3/25") is no figure; the role words of the people-name rule match in any case; with no customer
    list, a customer-type header blanks the cells under it in its own box or table column and the lines directly under it in
    its column before the first figure line, not the rest of the page.
    Amended 2026-10-22 (George, the build of docs/design/ai-reads-rules-check.md): the page read replaces the rules read as the
    source of deck claims (the rules read stays for Add from deck and under DECK_PIPELINE=rules). It uses the `deck_reading`
    prompt of the store (the repository holds a test stub only) and answers claims in the register's fields plus `basis`
    (actual, projection, scenario) and `scenario` (best, realistic, worst, none); replies are cached per audit by the hash of the
    page text. Python checks each claim (backend/app/structures/checker.py): the value on the page, the unit or currency in or
    next to its cell (else "currency assumed"), the scenario or period label on the page when the model set one, the page within
    the document, and the former parser rules (use-of-funds cues, acquisition-channel cues, turnover, the year label under a
    bar, the pipeline column) as post-checks. A failed check flags the claim and never deletes or retypes it; a flagged claim is
    listed in the review tab, not in the main claims list. A page call is outside the USD 5 daily cap and inside the tester's
    monthly allowance, as a mapping call is. The consent explainer on the Upload page says: "The AI reads every page of uploaded
    decks to find plan figures." The logging rule (17) is unchanged: no deck text in logs; model JSON output may be stored.
    All other steps keep the boundary above.
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
27. Never subscribe to PR or CI events and never schedule timed check-ins; George checks the PR's
    Checks tab himself. Report once when the work is pushed, then end the session.
28. Open the PR as draft, report once, end the session. Never wait for, poll or subscribe to CI.
29. Run test suites in the foreground and wait for them. Never start background monitors,
    watchers, timers or "notify me when done" tasks: each one wakes the session later and
    spends usage on nothing. A session ends when its report is posted; nothing may keep it
    alive after that.
    
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
21. All hard blockers render at the top of every audit view, except on the Audit page, where the contradiction lines sit directly above the claim register table.
22. Delete audit requires typing the company name and removes every document of the audit in every
    collection, saved mappings and stored files included.
23. Any change to engine output fields changes backend/schemas/metrics.py and the contract test
    (backend/tests/test_interface_contracts.py) in the same PR. Spec: docs/specs/interface-contracts.md.
24. A PR is not ready for review until the checks (.github/workflows/tests.yml) are green.

## Testing
25. Frontend suite is run with --no-cache. Report the number of test files found and loaded, not only tests
    passed. A test file that fails to load is a failure.

## Prompts
26. Prompt text is never committed to the repository: the repository is public and the prompts are the methodology. They live
    in the server-side prompt store (MongoDB `prompts`, docs/specs/prompt-store.md), uploaded on the owner page; the gateway
    reads them from there only. The repository holds stubs only: short texts marked "test only" in
    backend/tests/fixtures/prompts/, which tests load into a fake store. Tests do not assert a prompt's wording.
