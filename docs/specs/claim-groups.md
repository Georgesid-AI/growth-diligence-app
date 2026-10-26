# Spec: Claim groups and conflict resolution
Status: Agreed scope, the task of 2026-10-26: sections 1 and 2 of docs/design/claim-review-simplified-design.md (that design note is not amended).
Location: docs/specs/claim-groups.md. Code: `backend/app/claim_groups.py`. Sections 3 to 6 of the design note (forecast diagnostics, source association,
annual payback, the four-column rendering) are other changes and are not built here.
No architecture change: the module is pure like `claim_matching`, nothing reaches a model, and the engine output (`schemas/metrics.py`) is unchanged.

## 0. Challenge and deletions (CLAUDE.md rule 4)
- Needed: a deck states a year and its quarters; the register tests both and the top 5 can hold the year and a quarter that is part of it, so one economic
  issue is counted twice, and a verified year can sit beside a contradicted quarter. The simpler version: relate the register's rows on read, store nothing
  about a relationship, and change no claim, label or gap.
- Deleted first: any stored group, any new collection, any new label, any automatic choice, any hidden claim. A relationship is computed from the rows; the only
  thing stored is an analyst's decision, as a hash.

## 1. Map of the design note to what exists
| Design note | Existing | Built here |
|---|---|---|
| Preserve value, source, period, evidence test, corrections, edits | the register row (`claim_matching.FIELDS`), the candidate, `edit_log`, `corrections` | nothing changes on a claim |
| Compute relationships on read; persist only explicit decisions | `build_register` is computed on read; analyst decisions sit on the audit (`turnover_choices`) or the candidate (`claim_inputs`) | `claim_groups.relate` on the rows; decisions in `audits.group_choices` |
| Match metric definition, entity/segment, currency, unit, fiscal calendar, scenario | `claim_type`, `metric`, `population`, `segment`, `currency`, `unit`, `figure_type`, `basis`, `scenario`; the audit's `fiscal_year_end` | the scope key of section 2 |
| Flows: annual total and a complete, non-overlapping set | `period_start`, `period_end` (resolved for the fiscal year-end by `decks.claims.period_range`) | section 3 |
| Balances and counts: the year-end observation | `claim_type` arr, mrr, cash, customers, users | section 3 |
| 2% tolerance, zero total exact | `claim_matching` tolerances are per metric (±5%, ±1 pp); none for a relationship | `claim_groups.TOLERANCE` |
| Group presentation, parts under Details | the claims list, `overlaps_with` (rows that share a month, used by the memo's "counted in #n") | `group_id`, `group_role`, `relationship` on the row; the list shows the total, the parts under Details |
| Contradicted part affects the conclusion | `verdict.verdict`, `other_contradictions`, the banner | section 4 |
| At most one top-five item per group | `verdict.proposal`, `top5_state`, `sortable` | section 4 |
| Run-rate marking | `claim_matching._value_at_stake` (annualised, capped at Target ARR) | `vas_reason` "run-rate: {period} × {multiplier}" |
| Existing review interaction; edit, exclude, Undo | Needs your attention cards (`NeedsAttention`), `PUT /decks/candidates/{id}` (edit, `status: rejected`, `undo`), `PUT /claims/{id}` (segment) | one card kind; one choice endpoint; Undo of a choice |
| Bind a saved choice to the full context and the candidate identities | `claim_matching.definition_basis` (an answer holds only for the figures it was given against); `turnover_key` (term and period hash, the insufficient example) | `claim_groups.context_hash` |

## 2. What may be related (the scope key)
Two rows are related only when every part of this key is equal and known; a row with an unknown part is never assumed equal to another.
- Kind: flow or balance. The metric the register tests the claim against decides it: Revenue is a flow; ARR, MRR and Customer count are balances (so a claim typed revenue whose words say ARR is a balance);
  any other metric (New MRR, volume, rates, growth) is never related. With no metric, the claim type: `revenue`, `costs`, `gross_profit`, `ebitda`, `net_profit` are flows; `arr`, `mrr`, `cash`, `customers`, `users`
  are balances; `burn`, `sales`, `pricing` and every other type are never summed or related.
- Metric definition: `metric` (the claim type only when the row has no metric, so "ARR FY2023" typed revenue and "Dec 2023 ARR" typed arr relate) and `population`. A row that still asks the
  analyst a question never relates until it is answered: an open Definition check, a turnover claim still asking Revenue or Volume, an unknown growth basis, a field the claim editor asks for
  (`required_unknown`, a period not read). Its control stays on its own row and is never hidden under a total's Details. An untested row and a best or worst case never relate either. Entity or segment: `segment`; `currency`; `unit`; scenario: `figure_type` (actual or target, not unknown), `basis` and `scenario`.
- Fiscal calendar: the audit's own. Periods are resolved to dates before the register (dates-and-periods.md; `period_range` with the audit's year-end), so a March
  year-end year is April to March and its fiscal quarters are the parts that tile it; calendar quarters do not.
- A claim states one figure: a range (`claimed_high`) and a claim with no figure never relate. The figure is the stated one (`claimed_value`), not the converted one.

## 3. Reconciliation
- An annual total is a claim whose period is twelve months. A flow reconciles with one partition: every month, every quarter or every half of that year, one figure each,
  a complete set. A set that mixes granularities (two quarters and a half) is no partition. Quarters and halves are never summed together.
  When more than one partition reconciles, the finer set (months, then quarters, then halves) is the group's parts by default and the coarser set is listed under the total's Details
  (role `also`, "Halves also reconcile with this total; shown under its Details"); there is no card and no choice, and the coarser set adds no exposure of its own.
- A balance reconciles with the observation of the last month of the year (a claim whose period is that month). Earlier snapshots and a quarter-end are not
  duplicates of it and are not related.
- Reconciles: `abs(parts - total) <= 0.02 × abs(total)`, in decimals (the figures as stated, so 0.1 + 0.2 - 0.3 is zero). A zero total accepts equality only; no rounding
  allowance is documented. A negative total reconciles with negative parts. The test identifies a relationship; it verifies neither figure.
- Two figures for one scope and period are the same figure when they differ by at most 2% of the larger. Otherwise they conflict (section 5).
- Incomplete, non-reconciling or ambiguous parts stay independent claims; the total's `relationship` says which and why ("Quarters: 3 of 4 stated; kept as independent
  claims", "Quarters sum to €1,040,000, outside ±2% of €1,000,000; kept as independent claims").
- The same figure stated again (the same scope and period, within the tolerance) folds into the row of its first statement, the lead: the repeat has role `repeat`, the lead's `group_id` (the group's, or, when no
  group forms or the lead is a conflict candidate, an id of the two statements), the note "Same figure as #{rank} ({page}); counted once" and no value at stake. Both sources stay visible under the lead's
  Details ("Also stated: ..."). The fold applies to every annual figure, also when no group forms, and to a part stated twice inside a formed group.

## 4. Group presentation
- `group_id`, `group_role` (`total`, `part`, `also`, `repeat`, `pending_part`, `candidate`, `alternative`, or null) and `relationship` (text) are register fields, last in `claim_matching.FIELDS`; the baseline CSV and the memo's
  Appendix A (new column Relationship) carry every claim with them. No other field changes; no claim, label, gap or reason changes.
- The claims list shows the total once; its parts (`part`), the parts of another reconciling set (`also`) and the figures stated again (`repeat`) are under Details with their own period, label and reason.
  The collapsed line carries the contradiction of a member, as the five do: "Details · 4 parts · 1 contradicted". A line says "{n} items shown for {m} claims; {k} annual total(s) stand
  for their parts." only when something is grouped; the memo's summary says the same ("Grouping: ...").
- Value at stake: the total keeps its own (the stated annual figure); a part's and a coarser set's is none, `vas_reason` "counted in the annual total: its parts add no separate exposure"; a repeat's is none
  ("the same figure as another claim: counted once"); so is the part of a set that reconciles with an annual figure still in conflict (section 5). An independent
  short-period claim keeps the capped annualisation and says so in `vas_reason`: "run-rate: {period} × {multiplier}" (a quarter × 4, a month × 12; ARR as stated and MRR × 12, which is the metric's definition, are not marked).
  A non-reconciling annual claim takes nothing from it: the exposure is cut only for the parts of a group that formed.
- Top five: a group is one item, its total. Parts, the parts of another set, repeats, the parts waiting for a conflict, and the annual figures of an unresolved conflict that are not the preferred one, are never selected (`verdict.sortable`). The
  item's priority is the total's value at stake, then the largest shortfall among the members. A set the analyst stored that holds such a row no longer fits and the app's selection stands.
- The conclusion: an item's label is Contradicted when any member is (a verified total cannot hide a contradicted quarter); the item's reason and the first reasons name the contradicted
  part; the summary item carries `group` {id, parts, contradicted}. A Contradicted member of a group whose total is among the five is not repeated under "Other contradictions"; one of a
  group outside the five is listed there, as any Contradicted row outside the five. The banner (CLAUDE.md rule 21) names a contradicted part of a selected group.
- Key gates: a group's item has the gate of its total; when the total is Verified (it has none), the gate of its Contradicted member, the lowest rank first, is the item's key gate (`key_gate` is set on that
  row, the verdict's key gates, the memo and the thesis condition read it). The thesis never says every selected claim is Verified while a member is Contradicted.
- A figure listed once: a Contradicted figure passed over for the preferred one is listed under Unresolved conflicts only, not under "Other contradictions" as well; a Contradicted repeat is listed with the
  statement it repeats, once (in the conclusion, the banner and "Other contradictions").

## 5. Conflicts and choices (design note section 2)
- Several annual figures that differ for one scope and period are a conflict. Nothing is selected for the analyst, whatever the parts say: the card "Which annual figure should the
  audit use?" lists each candidate with its source, and, as a hint, the partition that reconciles with it. While none is chosen, no candidate is a group's total, none enters the top five,
  and the conflict is listed beside the conclusion ("Unresolved conflicts", also in the memo's summary) and in Needs your attention.
- While an annual conflict is open, the parts of every candidate's reconciling set are subordinate: role `pending_part`, no top-five slot and no run-rate value at stake (their exposure is the headline's, whichever
  figure is chosen), still listed in the claims list with the note "Part of a set that reconciles with one of the annual figures still in conflict; no exposure of its own until one is chosen". When a figure is
  chosen the sets of the preferred one form its group and the others are independent claims again.
- A choice picks the figure to use and does nothing else: the other figures stay claims, are not made segments and are not marked false because they were not
  chosen; they stay in Needs your attention and the conclusion as an unresolved conflict until the analyst corrects one (the claim editor), identifies its scope (the segment control), or
  excludes it with a reason (the existing "Not a company claim", sent with one of the edit reasons, stored as `excluded_reason`; Undo restores it, as today).
  A figure of a table row cannot be excluded from the card (it would drop its other periods); the claim editor edits its value.
- The choice is `PUT /audits/{id}/claim-groups/{question id}` `{choice}`: the candidate's identity. The server offers the candidates again and refuses anything else.
  `DELETE` undoes it (the question is asked again; no claim changes). It is stored under `audits.group_choices.{question id}` = `{kind, chosen, context, saved_at}`: hashes only, no deck text
  (CLAUDE.md rule 17); deleted with the audit.
- A choice holds only while its context holds: the hash covers the question, the whole scope key, the period, the audit's fiscal year-end, the identity of every candidate and the identities of the parts of every reconciling set at the time of the choice
  (the hint the analyst chose on). A candidate's identity is its
  source (deck file and page), stated figure, currency, unit, period, type, metric, segment, basis, scenario and figure type; not its claim id, rank or label. So the choice survives every read, a new
  run, a page read again, another order and an unrelated claim, and expires when any candidate or its scope is edited, one is added or removed, the parts of a reconciling set are edited, added or removed, or the calendar changes. A choice binds to its context, not to
  its history: restoring the edited value restores the choice.
- Ambiguous labels and periods keep their existing review (claim-matching.md section 33: candidates, one button each); this change adds no second control for them.

## 6. Contract and data boundary
- `schemas/metrics.py` and `CONTRACT_VERSION` (9) do not change. The three row fields are register fields (claim-matching.md section 6), not engine output.
- `claim_groups` imports nothing from the gateway and logs nothing. The two endpoints log `group choice saved|undone: run_id=... kind=...` (a closed word). `group_choices`, the three field names and
  the note texts join the boundary lists of `test_gateway_data_boundary.py` (CLAUDE.md rule 14).

## 7. Tests (the acceptance table, this scope)
| Capability | Check | File |
|---|---|---|
| Complete, partial and mixed partitions | halves and months; 3 of 4 quarters; a set that does not reconcile; quarters with halves (the quarters group, the halves under Details); a mix of granularities; a row with an open question stays out | `test_claim_groups.py` |
| Negative and zero totals | negative parts; the other sign; zero with equality only; decimals | `test_claim_groups.py` |
| Different scopes and scenarios | segment, currency, unit, figure type, basis, case, metric, population, unknown scope, range | `test_claim_groups.py` |
| Balances | year-end observation; earlier snapshots independent; quarter-end not related | `test_claim_groups.py` |
| March year-end | April to March year and its fiscal quarters group; calendar quarters do not | `test_claim_groups.py` |
| Edit and Undo | an edited part dissolves the group, restoring it forms it again; excluding a part and Undo; a part moved to another segment | `test_claim_groups_api.py` |
| Contradicted part | verified total, contradicted quarter: not supported in the verdict and the banner, the part's gate is the item's key gate, the thesis does not say Verified; outside the five it is listed; a passed-over or repeated figure is listed once | `test_claim_groups.py`, `test_claim_groups_api.py` |
| No invented segment | the passed-over figure keeps its segment and its label; scoping it resolves the conflict | both |
| Choices survive and expire | repeated reads, new run, new claim ids, float values, unrelated claim; any candidate or scope edit, an edit to the parts of a reconciling set, added or removed candidate, fiscal calendar | both |
| No duplicate exposure | the headline once, parts none, the parts of an open conflict none, a repeat none; run-rate for what is independent, none for MRR × 12; one group is one top-five item and ranks by its worst member | `test_claim_groups.py`, `test_vas_top5_reasons.py` |
| Screens | the list, the card, the conclusion, the five | `ClaimRegister.groups.test.jsx`, `NeedsAttention.groups.test.jsx`, `Verdict.conclusion.test.jsx`, `FiveClaims.groups.test.jsx`, `claimGroups.test.js` |
| Boundary | no gateway module names the fields; no gateway read asks for `group_choices`; log arguments | `test_gateway_data_boundary.py` |

## 8. Decided (engineering, rule 19)
- Materiality: a conflict is material when its figures differ by more than the 2% tolerance; a contradiction is material when its label is Contradicted (the metric's own tolerance already decided).
- The group's priority is its total's value at stake, then the largest shortfall among its members; the label of the item is Contradicted when any member is, otherwise the total's own (an untested part does not
  lower a verified total).
- Two partitions that reconcile (George, 2026-10-26, decision 2 of PR 187): the finer set is the group, the other is under Details, no card.
- The same figure stated again (George, 2026-10-26, decision 3 of PR 187) folds into the row of its first statement, also when no group forms, for the candidates of a conflict and for a part stated twice.
- The review of PR 187: a row with an open question is not grouped until answered (the controls of a part would be hidden); the grouping key holds the metric, not the claim type.
- Part-level conflicts (a quarter stated twice with different figures) block that partition and are noted on the total; the card and the choice are for annual figures.

## Files
`backend/app/claim_groups.py`, `backend/app/claim_matching.py` (`FIELDS`, `build_register`, run-rate), `backend/app/verdict.py`, `backend/app/ic_memo.py`, `backend/server.py` (`choose_group`,
`undo_group_choice`, the conflicts in the verdict, the banner, the open-question count), `frontend/src/lib/claimGroups.js`, `ClaimRegister.jsx`, `NeedsAttention.jsx`, `Verdict.jsx`, `FiveClaims.jsx`, the tests of section 7.

## Done when
Section 7 passes in the full backend and frontend suites, and each new test has failed on a deliberate violation (docs/test-runs/claim-groups_2026-10-26.md).
