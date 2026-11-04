date 2026-11-01, branch claude/sleepy-heisenberg-zd75qa
deleted: two unused imports (file_of, sheet) in backend/tests/test_memo_role_metrics.py
decided: renamed variable l to line (ruff E741); no other change
slow or unclear: nothing
root cause: test file added with unused imports and an ambiguous name; ruff was not run on backend/ before push. Rule: run ruff check backend/ before every push.
Process change to propose: moved to docs/pr6-cleanup.md or docs/pr6-cleanup-archive.md.
