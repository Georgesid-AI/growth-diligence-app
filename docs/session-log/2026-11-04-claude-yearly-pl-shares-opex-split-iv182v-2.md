2026-11-04, claude/yearly-pl-shares-opex-split-iv182v (review of PR 232, second session).
Deleted: an unused import of the estimate label in the memo module and the memo's own ", estimate" literal (the trend tables now read the one constant of plan_lines).
Decided: the six review points hold as built (the three-way gate, checks (a) and (b) on every plan year with the split, flag and label in every output, no rating input, pooled shares on sum_role with every plan cell cited, contract 18 complete); two regression tests added for the points the suite did not pin (two plan S&M rows pooled on their sum with both cells cited; a year that states R&D or G&A gets no three-way split), each failed on a deliberate violation first; no engine logic changed.
Slow or unclear: the PR's backend check was red on a lint error (ruff: an unused import and two f-strings without placeholders), reported in the PR as a green suite because the suite was run without the lint step.
Root cause and rule: the lint step of .github/workflows/tests.yml is not part of "python -m pytest"; rule 24 (checks green before review) is met only when ruff is run too.
Process change to propose: moved to docs/pr6-cleanup.md.
