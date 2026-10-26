# Claim groups and conflict resolution: test run, 2026-10-26

Spec: docs/specs/claim-groups.md (docs/design/claim-review-simplified-design.md sections 1 and 2). Fixture decks only.

## Suites on the branch
- Backend (`python -m pytest`, as configured): 3787 passed, 26 skipped. `ruff check backend/` (0.16.8, ruff.toml): all checks passed.
- Frontend (`yarn test --watchAll=false --no-cache`): 39 test files found, 39 loaded and passed; 625 tests passed.

## The new tests without the change
The new test files copied onto the branch's parent commit (the source files unchanged):
- `backend/tests/test_claim_groups.py`: does not load (`cannot import name 'claim_groups' from 'app'`), so none of its tests runs.
- `backend/tests/test_claim_groups_api.py` with `backend/tests/test_vas_top5_reasons.py`: 21 of 53 tests fail (the groups, the choice endpoints, the run-rate mark); the other 32 are the rows that hold either way.
- Frontend `claimGroups.test.js`, `ClaimRegister.groups`, `NeedsAttention.groups`, `FiveClaims.groups`, `Verdict.conclusion`: 5 of 5 files fail, 11 of 21 tests fail (the remaining 10 are the unchanged conclusion tests and the "nothing grouped, nothing shown" rows).

## The new tests against deliberate violations
Each violation is one change to the source, the new tests run, the file restored.
- Backend, 26 violations, 26 caught: tolerance 5%; segment, currency or scenario dropped from the scope key; kind decided by the claim type; the first of several totals or partitions selected; quarters and halves summed together;
  a balance reconciled with the sum of its observations; a choice not bound to the candidates or the fiscal calendar; a candidate identity that includes the claim id or reads 250000 and 250000.0 apart; a zero total compared in binary floats;
  a verified total hiding a contradicted part; a part keeping its value at stake; a candidate of an open conflict allowed in the five; a group ranked by its total's own shortfall; the banner ignoring a contradicted part; a contradicted part outside
  the five left out of the contradictions; no run-rate mark; a choice not checked against the offered candidates; the conflicts left out of the verdict; reviews not counted as questions; Undo that does not unset.
- Frontend, 8 violations, 8 caught: parts shown as rows of the list; exclude without a reason; a candidate pre-selected; the conflicts missing from the conclusion; the group line missing from the five; a chosen conflict dropped from the card; the counts hidden;
  a table-row figure excludable from the card.

## Existing tests changed
Ten tests that read the TestCo run A fixture changed their expectations, not their intent: the fixture states two FY2023 ARR figures (240,000 and 198,000), which now conflict, so neither can be in the five until one is chosen
(`test_verdict.py`: the proposal, the contradicted count, the sets offered to `check_top5`, the candidate list; `test_ic_memo.py`: the conclusion line, the footnote ranks, the key gates). The VaS test of a short period now expects the run-rate mark.
`test_access_links.py` names the new route parameter; the in-memory Mongo stub removes a dotted `$unset` path as the database does.
