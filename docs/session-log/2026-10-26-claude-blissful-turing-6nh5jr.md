2026-10-26, claude/blissful-turing-6nh5jr
Deleted: nothing.
Decided: ruff==0.16.8 pinned in backend/requirements.txt (the only requirements file; it already holds the test tools), installed in the venv; the one finding fixed with no rule change and no new noqa.
Slow or unclear: the backend suite takes about 90 s with -n 4 and passes the 120 s tool limit only when run with a longer timeout; there is no separate dev requirements file.
Root cause: a truncated import line in backend/tests/test_claim_corrections.py (trailing comma, `stored` missing) was a syntax error for ruff 0.16.8; ruff was not in the venv, so nobody ran it locally. Rule that prevents it: ruff is now in requirements.txt, so the session hook installs it and `ruff check backend` runs as CI does.
Process change to propose: add `ruff check backend` to the session start hook's checks so a lint failure shows before the push.
