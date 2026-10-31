# CLAUDE.md — working rules

## Architecture
3. Do not confuse rigor with dumb. Evidence tiers, citations and source references
   (docs/architecture.md) are the core of the audit method. Challenge how they are built, never
   whether they exist.
16. The gateway may read selected deck structures (tables, charts with data labels, KPI
    panels, roadmaps/timelines, hiring tables, unit-economics boxes, use-of-funds
    tables) and spreadsheet sheet names, title rows and header rows with, per column, either up to 3 sample values
    (numeric and date columns only) or a profile (distinct count, typical length, shape
    pattern) for text columns — only after redaction, only with per-audit consent, only
    as extracted text with cell positions. Never raw files, full pages or prose slides, except the page_claims step below.
    For the sheet_structure step only (approved by George, 2026-10-18), the model may receive
    every text cell of a sheet (title rows, headers, row labels, indents, num/blank markers),
    after redaction and the withhold rule; never any figure; cap 400 labelled rows per sheet.
    For the file_recognition step only (approved by George, 2026-10-19), the model may also receive the row labels of a sheet the rules read as
    metric names (revenue, ARR, MRR, customers, churn, bookings, forecast, budget, cost, margin, cash and common variants), after redaction; every
    other sheet's labels go as "Row 1", "Row 2"; on every sheet the 3 sample values of a column come from different rows chosen from the file hash, never the
    same row in two neighbouring columns; never a figure beyond the per-column sample; at most 400 rows with text.
    For the page_claims step only (approved by George, 2026-10-22, PR #158 decision 1b; the default path since 2026-10-22,
    DECK_PIPELINE=ai, docs/design/ai-reads-rules-check.md; rewritten 2026-10-27, docs/design/page-image.md), the model may receive,
    as printed and with no redaction (no customer-name masking, no people-name, e-mail or phone rule), every deck page that carries
    a figure written in digits: the page's text lines, prose lines included, as extracted text with cell positions, at most 5 pages
    per call, and in the same request one PNG of each whole page (1,568 px on the long edge, no crops), with no cap on images per
    call. The reading instructions say that printed values only are read and that no value is estimated from an unlabelled bar,
    point or slice. A page with no such figure never goes, and number-words do not count as figures. The consent text says that
    deck pages go to the model as printed, as text and as an image, with no redaction, and the Upload page explainer carries the
    disclosure line word for word: "Deck pages are processed by Anthropic under a zero-data-retention arrangement. Nothing is
    retained after the reply and nothing is used for training."
    Amended 2026-10-22 (George, review of PR #159): the gateway refuses the step unless DECK_PIPELINE is "ai"; a line over 200
    characters is left out by the sender and refused by the gateway, as a structure cell is; a line that is only the page's own
    number ("3", "Slide 3", "3/25") is no figure.
    Amended 2026-10-22 (George, the build of docs/design/ai-reads-rules-check.md): the page read replaces the rules read as the
    source of deck claims (the rules read stays for Add from deck and under DECK_PIPELINE=rules). It uses the `deck_reading`
    prompt of the store (the repository holds a test stub only) and answers claims in the register's fields plus `basis`
    (actual, projection, scenario) and `scenario` (best, realistic, worst, none); replies are cached per audit by the hash of the
    page text. Python checks each claim (backend/app/structures/checker.py): the value on the page, the unit or currency in or
    next to its cell (else "currency assumed"), the scenario or period label on the page when the model set one, the page within
    the document, and the former parser rules (use-of-funds cues, acquisition-channel cues, turnover, the year label under a
    bar, the pipeline column) as post-checks. A failed check flags the claim and never deletes or retypes it; a flagged claim is
    listed in the review tab, not in the main claims list. A page call is outside the USD 5 daily cap and inside the tester's
    monthly allowance, as a mapping call is. The logging rule (17) is unchanged: no deck text, no page image in logs or MongoDB;
    model JSON output may be stored. The owner page shows image tokens and image cost apart from text tokens and cost.
    Amended 2026-10-29 (George, docs/design/read-check-review.md section 8, PR 1): masking is one module (structures/redact.py), run by the
    gateway on every payload that leaves the server. The page text of a page_claims call is masked, no longer "as printed": emails, phone
    numbers, IBANs, ID numbers and first-name personal names removed, columns headed owner, contact, manager, rep or signatory masked
    whole in spreadsheets only (deck page text never uses that rule; a title such as "Key contacts" blanks nothing below it), company and
    customer names (the target's too) replaced by per-audit tokens Client-01, Client-02 ... that are the same in every file of the audit;
    a text cell under a header that holds name, customer, client, account or company and is not yet in the map is added to it at
    masking time and gets the next Client-NN, never [person] and never as printed (George, 2026-10-29, PR 204 review); figures and metric
    labels unchanged. The page image goes unmasked (option A). The token map lives on the audit record only (`token_map`), never in a
    log, a payload or an API response, and goes with the audit; the provider adapter refuses a payload that still holds an email, IBAN,
    ID number or "+" phone number. Counts per file on screen: lines sent, personal items removed, company names coded, columns
    withheld.
    Amended 2026-10-29 (read-check-review.md sections 3, 4, 8 and 9, PR 2; for George's approval before merge, rule 32): a new step
    `sheet_reading`. With the audit's consent, one call per uploaded spreadsheet, the model may receive every non-empty cell of every
    recognised sheet (a ledger of more than 40 rows, one per invoice, is not one) as `A1 ref: value` lines under `sheet n: name` lines, figures included,
    after the masking of PR 1 (name learning included; a metric vocabulary the masker never tokenises: revenue, ARR, churn and the
    like), no sampling and no truncation; above 40,000 tokens of cells the file is refused with a message. It runs on an exact Sonnet or
    Opus id from an allow-list only (`gateway.SHEET_READER_MODELS`; `SHEET_READER_MODEL` picks one, default the structure model; never an alias, never "latest"; George, 2026-10-30), with the `sheet_reading` prompt of the store (rule 26). The
    model returns the file map (`FileMap`, schemas/metrics.py); Python opens every cited cell (app/checks.py) and decides what the cell
    cannot show to be unchecked. The spreadsheet calls of rule 16 above (file_type, structure_reading, column mapping) are unchanged,
    still learn no names, and stay behind `READER_V1` (off turns them off; default on) for PR 2 only.
    Amended 2026-10-30 (read-check-review.md sections 7, 9 and 13, PR 3; for George's approval before merge, rule 32): a new step `reviewer`. One
    call per audit, with the audit's consent, on the sheet reader's model allow-list, with the `reviewer` prompt of the store (rule 26). It may
    receive the stored file map of every spreadsheet with its stored series (period, value, cell) and without the readers' evidence lines, the
    deck figures (page, metric, value, unit, period; never a line of page text), the computed results as the narratives see them, and the
    cannot-check list, every string masked by the one module (company tokens first, then the personal rules). It returns findings as plain JSON
    validated in code; Python opens every reference, drops a finding that cites what does not exist, and a valid finding sends one re-read of
    that item through the sheet reader's recheck path with the finding attached (the finding's text masked like any payload).
    All other steps keep the boundary above.
    The deck parser has no direct link to the gateway.
17. Logs and MongoDB store model JSON output (values with cell references), prompt
    version, model version, content hash, token counts and cost. Never deck text sent to
    the model. Delete audit removes model outputs. The one stored copy of client data is the uploaded deck file, collection
    `deck_files`, kept only while consent is ticked and DECK_PIPELINE is "ai", so that page images can be drawn from it
    (docs/design/page-image.md); it is deleted with its deck and with the audit (rule 22). Amended 2026-10-29 (PR 2, for George's approval): a reading of a
    spreadsheet is stored once in `readings`, keyed on file hash + prompt version + model version, never edited, with the names restored
    (display un-masks on the server); a second upload of the same file, in any audit, gets it with no model call. Its automatic second
    reading, an analyst's Change and a reviewer's correction are records of their own (`reading_rereads`, `reading_overrides`). Amended 2026-10-30 (PR 3, for
    George's approval, rule 32): the reading also holds, beside each row's map entry, the series code read from the file's cells (period, value at full
    precision, cell reference; cells after the actual/plan boundary in a separate plan series), written once with the reading and never edited; the
    only place a cell value sits in MongoDB besides the dataset itself. The reviewer's findings, the cards and the analyst's decisions are records of
    their own (`reading_reviews`, `reading_cards`, `reading_overrides`) and go with the audit. A reading
    is kept only while an audit uses it and goes with the last audit that does (rule 22). Rules 16–18: see docs/architecture.md.
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
30. Never commit local file paths, user names or machine folder names. Before every commit, run git grep --cached -iE '/Users/|/home/[a-z]|Mobile Documents|\.codex' -- . ':(exclude)CLAUDE.md' (the staged files; CLAUDE.md itself is excluded because this rule names the strings) and remove any match.
    
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
21. Hard blockers render at the top of every audit view, except the contradiction lines. On the Audit page the contradiction lines sit
    directly under the conclusion (the outcome, its explanation line and the scope sentence), as docs/design/simplified-flow.md describes;
    the claim register keeps row labels only. A top-5 claim that is Contradicted is shown in the conclusion block, whatever its rank in the five.
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
31. The page reader (`page_claims`) runs only on a ZDR-eligible model (Sonnet or Opus, never Fable or Mythos), because deck pages go to
    it as masked text plus the unmasked page image, under the API organisation's zero-data-retention arrangement
    (docs/design/page-image.md). The gateway refuses the step on any model outside the allow-list of Sonnet and Opus families
    (gateway.PAGE_READER_MODELS). A model off the list is logged as an error at startup and the server stays up; every page read is then
    blocked before anything is converted, drawn or sent, and the panel says "AI read: blocked – model not permitted".
32. Any change to the architecture (components, what crosses the server boundary, what the model sees, storage of readings) is named in the PR description under a heading "Architecture change" and needs George's approval before merge.
