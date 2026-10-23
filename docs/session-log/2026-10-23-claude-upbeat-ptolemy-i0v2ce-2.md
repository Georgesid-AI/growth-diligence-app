2026-10-23, claude/upbeat-ptolemy-i0v2ce (PR #166 CI fix).
Deleted: the unused `import server` in test_page_reads_speed.py.
Decided: the import was load-bearing (it put `server` into sys.modules for `_deck_fields`), so `_deck_fields` now uses importlib.import_module("server"); plain removal made the test fail when run alone.
Slow or unclear: nothing; ruff 0.16.8 clean, backend suite 3396 passed, 26 skipped.
Root cause: an import kept only for its side effect, flagged by F401 and not run through ruff 0.16.8 before the push; prevention: run ruff on backend/ before every push.
Process change to propose: run the CI ruff version locally in the pre-push checklist.
