# Spec: CRM de-duplication and quarter-end clustering
Status: Agreed scope (George, task of 17 Oct 2026; this file is the brief written out). Location: docs/specs/crm-dedup-clustering.md.
Amends integrity-coverage.md §1 (check 3), §7 and §8, and interface-contracts.md (`contract_version` 4). One PR, one contract change.
Amended 17 Oct 2026 (George, follow-up to PR 123, §6): the repeated rows on screen, Not applicable below 20 won deals, the CRM
amount optional and the CRM fields box (chat-upload.md §4.1 and S29).

## 0. Challenge and deletions (CLAUDE.md rule 4)
- Needed: a CRM export with one row per line item counts a deal once per line, so the win rate and the sales cycle count it
  several times; and quarter-end clustering is the one applicable integrity check the app still cannot complete. Simpler
  version: one collapse after the as-of cut, one count per close month in the engine, the rule and the result in
  `integrity.py`. No amount, no model call, no mapping or frontend change.
- Deleted first: the reason "The app does not compute quarter-end clustering of deals yet." and the status Not available for
  check 3; the data-integrity payload's "Quarter-end clustering of deals: not computed, the engine does not store this check".

## 1. De-duplication (growth_engine.py)
- Where: after the as-of cut (`cut_deals_at_as_of`) and before the sales cycle, the win rate, the anomaly flags and the
  won-deal counts of §2; the same in compute-before-Missing (`_run_analysis`), so a figure read from another upload follows the
  same rule.
- Rule: when `deal_id` is mapped, rows with the same deal ID, stage, created date and close date are one deal; the first row is
  kept. Rows with the same deal ID and a different stage or date are all kept. A blank deal ID is never a repeat. The stage is
  compared as the engine reads it (lower case, trimmed), dates as dates, a blank as equal to a blank.
- Flag: `anomalies.deals_duplicate_id` = `{rows, distinct_ids, collapsed, rows_list}`: the rows whose deal ID appears on more
  than one row, the number of such IDs, the rows removed as repeats, and the sheet rows of the first (`rows_list[:200]`). Zero
  counts when no CRM is uploaded or `deal_id` is not mapped.
- Shown like `deals_close_before_created` in the data-inventory payload's CRM quality issues, which the narrative's Worth
  flagging reads: `{rows} CRM row(s) share a deal ID with another row ({distinct_ids} deal ID(s)); {collapsed} exact repeat(s)
  counted once`, only when `rows` is above zero. Since §6 the Dashboard anomaly card, the Diagnostics page, the xlsx Anomalies sheet
  and the memo's anomaly count show it too.

## 2. Quarter-end clustering (integrity.py)
- Input: the de-duplicated won deals (`WON_ALIASES`) closed by the as-of month, with a close date; a deal closing before it was
  created is left out, as for the sales cycle and the win rate. The engine stores them as `won_deal_closes` = `{by_month:
  [{month, won, last_10_days}], source}`: per calendar month the won deals that closed in it and those that closed in its last 10
  days, and the citation of their sheet rows. Counts only, no amount. `null` when no CRM is uploaded or the stage or the close
  date is not mapped.
- Quarters follow the audit's fiscal year-end: a quarter ends in the year-end month and every third month from it. The last 10
  days of a quarter are the last 10 calendar days of its final month. `integrity.py` reads the year-end at request time, so a
  change of year-end needs no recompute.
- Statistic: share = won deals closed in the last 10 days of a quarter ÷ all won deals, as a whole percent (half up); the result
  is read from that percent, so the screen never shows a percent whose colour belongs to another band.
- Result: **Green** below 20%, **Amber** 20% to 35%, **Red** above 35%. Red is a completed check's result like the
  reconciliation's (integrity-coverage.md §2: any Red is Material concerns); it is not a hard blocker and does not reach the
  banner (CLAUDE.md rule 21).
- Fewer than 20 won deals: Not applicable, reason `Fewer than 20 won deals ({n})` (§6; it was Blocked, "Not enough deals ({n})").
- No `won_deal_closes`: Blocked — company data missing, reason `CRM file mapped (stage, close date)`.
- Finding (word for word): `{share}% of {n} won deals closed in the last 10 days of a quarter (chance: 11%)`. Source: the
  `won_deal_closes` citation (file · sheet · rows).
- Data-integrity payload (`step_payloads.py`): `Quarter-end clustering of deals` reads `computed` with the source key S2, the
  finding as a closed sentence and the result, all from `integrity.clustering` (the one calculation, as for smoothness); else
  `not computed` with the closed reason "the CRM export has fewer than 20 won deals with a close date" or "no CRM export with a
  stage and a close date". The gateway reads the audit's year-end beside the results; the year-end never goes out. The payload
  changed, so a stored data-integrity narrative of an audit with a CRM is not found under the new key and is offered for
  regeneration (one paid call each, on the analyst's click); nothing is regenerated by the change.

## 3. Contract and data boundary
- `backend/schemas/metrics.py`: `Anomalies.deals_duplicate_id` (`rows` Plain, as `DateOrder.rows`; `distinct_ids`, `collapsed`
  Count; `rows_list` list of Plain) and the top-level `won_deal_closes` (Optional, cited). `contract_version` 4: results stored
  under version 3 hold double-counted deals and no `won_deal_closes`, so they are recomputed on first read (interface-contracts.md
  §7); `SEED_VERSION` 10 reseeds the demo audits.
- `won_deal_closes` is server-only; the payload field `finding` is added to the gateway allowlist; `test_gateway_data_boundary.py`
  gains the key, the field and the module's new names (rule 14). `integrity.py` stays pure and logs nothing.

## 4. Tests
| Test | File |
|---|---|
| Line-item repeats: the deal is counted once in the win rate and the sales cycle, the flag shows the counts | `test_crm_dedup_clustering.py` |
| Same deal ID with a different stage: both rows kept, flagged | `test_crm_dedup_clustering.py` |
| Clustering Red (40%), Green (an even spread), 8 won deals: Not applicable, Fewer than 20 won deals (8), no data request, out of the denominator (§6) | `test_crm_dedup_clustering.py` |
| The memo leaves the check out of Appendix B below 20 won deals, reads 4 of 4 and still exports (§6) | `test_crm_dedup_clustering.py` |
| Repeats that would push a Green file to Amber if not collapsed | `test_crm_dedup_clustering.py` |
| A fiscal year-end other than December moves the quarter ends | `test_crm_dedup_clustering.py` |
| sample_data unchanged: no repeat, the same sales cycle and win rate; TestCo's clustering is Green | `test_crm_dedup_clustering.py` |
| The payload's closed sentence and reasons; the inventory's quality issue | `test_step_payloads.py` |
| The contract declares both fields; version 3 results are recomputed | `test_interface_contracts.py` |
| Boundary: server-only key, allowlisted field, module names | `test_gateway_data_boundary.py` |
| Older tests: clustering Completed, TestCo reads 5 of 5 with a deck | `test_integrity_coverage.py`, `test_ic_memo.py` |

## 5. Decided (engineering, rule 19)
- Fewer than 20 won deals was Blocked — company data missing; George decided Not applicable on 17 Oct 2026 (§6).
- The engine stores counts per calendar month and `integrity.py` applies the fiscal year-end, so the engine stays free of the
  year-end and its stored output is a fact about the file.
- Measured on the repo's files (as-of cut applied): sample TestCo 5 of 36 won deals (14%, Green); demo audits 14 of 133 (11%) and
  7 of 98 (7%), Green; no repeated deal ID in any of them.

## 6. Follow-up (George, 17 Oct 2026, after PR 123)
1. **Repeated rows on screen.** One row "CRM rows sharing a deal ID", after "Deals closed before created", on the Dashboard anomaly
   card, the Diagnostics page and the xlsx Anomalies sheet: the count is `collapsed`, the detail `{distinct_ids} distinct deal IDs`.
   The memo's anomaly count adds `collapsed`, as the screen lists it. Results stored before the flag existed show no row, never 0.
2. **Fewer than 20 won deals.** The clustering row reads Status "Not applicable", Reason "Fewer than 20 won deals ({n})"
   (`CLUSTERING_FEW`). It is no data request and is out of the denominator, so it counts neither as completed nor as missing. The
   data-integrity payload keeps its closed reason, "the CRM export has fewer than 20 won deals with a close date".
3. **CRM amount optional.** `FIELD_DEFS["crm"]`: required `deal_id`, `created_date`, `close_date`, `stage`; optional `amount`,
   `segment`, `founder_involved` (amount first, so the field list keeps its order). Aliases, the turnover/volume question
   (chat-upload.md §15) and the numeric kind stay. A CRM file without an amount column is ready for calculation. The Missing Data
   line for absent CRM deals asks for "deal ID, created date, close date and stage".
4. **CRM fields box.** S29 (chat-upload.md §11), word for word, above a CRM file's mapping table, open by default.

| Test | File |
|---|---|
| The xlsx row after the deals closed before created; the memo count adds `collapsed` | `test_crm_dedup_clustering.py` |
| The anomaly row with its counts; no row for older results | `anomalyFlags.test.js`, `Diagnostics.test.jsx` |
| 8 and 19 won deals: Not applicable, no request, out of the denominator; the memo reads 4 of 4 | `test_crm_dedup_clustering.py` |
| Required and optional CRM fields and their order; `missing_required` and `is_miss` without an amount; a CRM file without an amount column is ready, computes and reapplies its saved mapping; a mapping saved with an amount still applies | `test_chat_upload.py` |
| A CRM volume answer leaves the file calculable | `test_money_kind.py` |
| S29 word for word on the CRM panel only; the CRM field list order | `MappingWizard.test.jsx` |

## Files
`backend/growth_engine.py`, `backend/schemas/metrics.py`, `backend/app/integrity.py`, `backend/app/llm/step_payloads.py`,
`backend/app/llm/gateway.py`, `backend/app/ic_memo.py`, `backend/server.py`, the tests of §4, `docs/specs/integrity-coverage.md`,
`docs/specs/interface-contracts.md`; §6: `backend/app/column_rules.py`, `frontend/src/lib/gapLists.js`, `frontend/src/pages/Diagnostics.jsx`,
`frontend/src/lib/chatUpload.js`, `frontend/src/components/UploadChat.jsx`, `docs/specs/chat-upload.md` and the tests of §6.

## Done when
§4 passes with the full suite.
