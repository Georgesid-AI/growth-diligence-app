1. 2026-11-01, claude/clever-albattani-vwbk8v.
2. Deleted: the compact upload's per-file mapping bubble (frontend only; code stays for ?view=legacy).
3. Decided: a file the old path waits on shows one line (count = pending columns/lines, +1 for an open currency, minimum 1) linking to ?view=legacy; billing terms stay in "More settings" because they are not the mapping block.
4. Slow or unclear: no count of "answers" exists on the file view for blocks without a pending number (missing required field); shown as 1.
5. Root cause and rule: the compact flag still rendered the full bubble while a file waited; tests now assert the default page holds no old mapping block, and fail if it returns.
6. Process change to propose: name the screen-removal test (default page vs ?view=legacy) in each spec so the legacy tests are never the only guard.
