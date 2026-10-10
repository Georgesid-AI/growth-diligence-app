2026-10-10, claude/sleepy-fermat-b494vb
Deleted: nothing; one workflow file, no separate lint or build jobs.
Decided: two parallel jobs (backend pytest, frontend yarn test) on pull_request and push to main; Python 3.13 and Node 22 copied from the dev environment because the repo pins neither; REQUIRE_LIVE_BACKEND left unset so tests/backend_test.py skips itself; no secrets.
Slow or unclear: the repo pinned no Python or Node version before this task (only yarn 1.22.22 via packageManager); the full local pytest run took over two minutes.
Root cause and rule: nothing enforced the tests before merge; new CLAUDE.md rule 24 says a PR is not ready for review until the checks are green.
Process change to propose: point the dev container at the same two files so all three read one source.
