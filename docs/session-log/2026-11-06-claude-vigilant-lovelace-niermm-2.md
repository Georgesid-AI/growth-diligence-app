2026-11-06 · claude/vigilant-lovelace-niermm (the as-of year before its year end is labelled "2024 (to Nov)")
Deleted: nothing.
Decided: `period` stays the key and a new optional `label` carries "YYYY (to Mon)" on growth by year, trend periods and trend values (contract 24 stays, the PR is unmerged); the trend now lists the as-of year when its TOTAL column states it, as growth by year does; the label is printed in the memo's growth and trend tables, the summary line, the templated plan lines, the Excel trend header and the growth card.
Slow or unclear: the full backend suite takes about 2.3 minutes, the frontend suite with --no-cache about the same (60 files loaded).
Root cause and rule: the partial year was shown as a plain year next to full years; the label is built in one place (role_engine.year_label) and tests/test_board_pack_dating.py pins every print site.
Process change: none.
Cleanup item added to docs/pr6-cleanup.md: none.
