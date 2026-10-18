# Spec: Usage on the owner page and the per-tester AI allowance
Status: **Draft, written with its build in one PR (spec first, then code).** Source: George's request of 18 Oct 2026. Location: docs/specs/usage-and-allowance.md.
Builds on docs/specs/access-links.md (tester tokens, owner token) and docs/specs/chat-upload.md §4.2 (mapping falls back to rules).
The architecture and the engine (growth_engine.py, metric fields) do not change.

## 0. Challenge and deletions (CLAUDE.md rule 4)
- Needed: testers share one app-wide daily cap of USD 5, so one tester can starve the rest, and the owner cannot see who uses what.
  Simpler version: one counter per tester link, one number to edit, one check before each model call.
- Deleted first: the "Your usage" fold on the Audit Hub (the tester's own totals nobody asked for, §1) and the "0% Heuristics" header
  badge (a claim the product does not need, §1). Nothing else is removed. `GET /api/usage/totals` becomes owner-only (D3).

## 1. Removals (screen)
1. Layout header: the "0% Heuristics" badge is gone. The header keeps the company line.
2. Audit Hub: the "Your usage" section (`UsageTotals`) is gone for tester links. The owner link never reaches the hub (404 on the audit
   list), so the component is deleted, not hidden.

## 2. The tester ledger
Deleting an audit purges its `llm_calls` and its counters (CLAUDE.md rule 22), so neither can carry a monthly allowance: a tester could
reset it by deleting audits. The ledger is therefore kept on the tester's own record in `access_tokens` (the document that already holds the
link's id, label and expiry), keyed by tester id, not by audit:
`allowance_usd` (default 10) and `ledger = {"all": T, "YYYY-MM": T}` with `T = {files, calls, tokens, cost_usd}`; months are calendar
months in UTC. Counts and USD only. No company name, file name, audit name, audit id or figure is ever written to it.
- **files**: each file accepted by an upload route (dataset or deck). A rejected file does not count.
- **calls**: each model call that was made and billed (cache hits and guard refusals are not calls; a billed call that failed is).
- **tokens**: input plus output tokens of those calls. **cost_usd**: the gateway's own estimate, USD, no conversion.
- Written in the one place every model call is logged (`gateway.log_call`), so mapping, file-type, deck-structure and narrative calls all
  count. A call on an audit with no tester (access control off, local development) is counted nowhere and has no allowance.
- Re-issue and revoke keep the ledger and the allowance (same document). Deleting an audit leaves the ledger untouched.
- **Architecture note (rule 1):** the Storage row of docs/architecture.md describes `access_tokens` as "token hashes with id, label and
  expiry". This adds two fields (the allowance and the counters) to the same collection and no new collection. docs/architecture.md is
  George approved this on 18 Oct 2026 (D1) and the Storage row of docs/architecture.md now says so.

## 3. Owner page: "Usage"
- `GET /api/admin/usage` (owner token only; tester 404, no token 401): `{month, totals: {this_month: T, all_time: T},
  testers: [{id, label, status, allowance_usd, this_month: T, all_time: T}]}`. The only text is the tester label the owner typed.
  The response has no audit field, so it cannot carry a company, file or audit name or a figure.
- `POST /api/admin/testers/{id}/allowance` `{allowance_usd}` (owner only): a number from 0 to 1000, at most two decimals; else 422.
  0 pauses a tester's AI at once.
- Screen: a "Usage" section on the owner page below "Tester links": one totals row (all testers), then one row per tester link
  (revoked ones too): files, AI calls, tokens, cost USD, this month and all time, the allowance with an edit box and Save.
  Costs read `USD 1.23`.
- The owner token still gets 404 on every audit route and on `GET /api/allowance` (tested from the router, as access-links.md §4).

## 4. The allowance
- Default USD 10 per calendar month per tester link, editable by the owner per link (§3). Constant `DEFAULT_ALLOWANCE_USD`.
- Used = this month's `cost_usd` on the ledger. State: `ok` below 80%, `warn` from 80% (used ≥ 0.8 × allowance), `blocked` from 100%
  (used ≥ allowance; an allowance of 0 is blocked). The percentage shown is rounded **down**, so 100% is never shown early.
- Checked **before** each model call (narrative, column mapping, file type, deck structure) in the gateway, as a guard beside the daily
  cap, refusal code `monthly_allowance_reached`. The call is not made and costs nothing; a refusal row is logged with 0 tokens.
  Calls already in flight finish, so one call per concurrent request can overshoot the allowance; the daily cap is the net above it.
- The app-wide daily cap of USD 5 is unchanged and still applies on top, including the existing exemption of the column-mapping call
  (chat-upload.md §4.2). The allowance has no exemption.
- `GET /api/allowance` (tester token; owner 404; no token 401): `{percent, state}` for the caller's month (the USD fields were removed
  from the tester response, §9). With access control off: `{state: "off"}`.

## 5. What the tester sees
- `warn`: one line at the top of every tester screen, under the header and apart from the three blockers of rule 21 (it is not a blocker):
  `You have used X% of this month's AI allowance.` X is the rounded-down percent. No amount (§9, amended 18 Oct 2026).
- `blocked`: the message below replaces the line, word for word:

> You’ve reached your monthly AI allowance.
>
> AI features are paused for now, including column suggestions, reading board decks, and writing narratives.
>
> Everything else still works at no extra cost: all metrics (revenue, NRR, churn, CAC payback, sales cycle, and win rate), data checks, saved mappings, review, and exports.
>
> You can still upload new files. The app will match columns using its built-in rules and ask you to confirm any uncertain matches.
>
> Need a higher allowance? Contact the app owner.

- At 100% only new AI calls stop. Never blocked: uploads, rules mapping, saved mappings, all metrics, data checks, review, exports,
  stored narratives (read from cache, no call).
- **Mapping at 100%:** the rules decide alone. Every column the rules cannot map at 81 or more (the existing threshold: above 80,
  `MAPPING_THRESHOLD`) is left open and needs an analyst click. This is the existing "model could not be read" path
  (`apply_model_failure`): the gateway answers `not_read`, as for the daily cap; no new mapping logic and no new status.
- Narratives and deck structures at 100%: the existing "narrative unavailable" / "structure not read" note, with every computed metric
  and its citation still shown (rule 20).
- The banner reads the allowance when a screen opens and again after an upload; it does not poll.

## 6. Data boundary (rule 14)
New closed strings, added to `test_gateway_data_boundary.py`: guard code `monthly_allowance_reached`; cap reason word `allowance` (the
"structure not read" log line); the admin usage and allowance response key sets. No new log line carries a tester id, label or amount.

## 7. Tests
| Test | File |
|---|---|
| Ledger: a billed call adds calls, tokens, cost to this month and all time; a cache hit and a refusal add nothing; a deleted audit leaves it | `test_usage_allowance.py` |
| Check: ok / warn at 80% / blocked at 100%, allowance 0, month rollover, rounded-down percent | `test_usage_allowance.py` |
| At 100% no provider call is made for narrative, mapping, file type or deck structure; the daily cap still refuses on top | `test_usage_allowance.py` |
| At 100% an upload still works and every column below 81 is left for a click | `test_usage_allowance.py` |
| Owner usage: totals equal the per-tester sums; response holds only the closed keys, no company, file or audit name | `test_usage_allowance.py` |
| Allowance edit: owner only, range, 422; tester 404; no token 401; the owner token 404 on every audit route and on `/api/allowance` | `test_usage_allowance.py`, `test_owner_page_api.py` |
| Banner: nothing below 80%, the one line at 80% with the exact words, the six-paragraph message at 100% | `AllowanceBanner.test.jsx` |
| Header has no "Heuristics" badge; the hub has no "Your usage" | `Layout.test.jsx`, `AuditHub.test.jsx` |
| Owner page shows totals and per-tester rows, saves an allowance | `OwnerPage.test.jsx` |

## 8. Decisions (George, 18 Oct 2026, on PR #126)
| # | Decision | Outcome |
|---|---|---|
| D1 | Allowance and usage counters live on `access_tokens` records. | **Approved.** The Storage row of docs/architecture.md now reads: hashes, id, label, expiry, and per-link AI usage counters and allowance (counts and costs only, no names or figures). |
| D2 | The column-mapping call stays exempt from the USD 5 daily cap (chat-upload.md §4.2). | **Approved.** The per-tester allowance limits it. |
| D3 | `GET /api/usage/totals` and tester access. | **Decided:** remove tester access in this PR. Owner token only; a tester gets 404 (access-links.md §3 updated). The route and its owner reading stay. |
| D4 | The 80% line is a separate component, not in the blocker list (rule 21). | As built. |
| D5 | The month resets at 00:00 UTC on the 1st. | **Approved:** UTC. |

## 9. Cost is hidden from testers; per-audit cost list for the owner (2026-10-18, George)
Decided by George with the task. The app keeps calculating and storing tokens and cost (`llm_calls`, the ledger); only what a tester
token receives or sees changes. The architecture and the engine are unchanged.

**Screens.** Removed: the "AI usage and cost" table of the Audit page (`UsagePanel`) and its request; the cost estimate on "Write all
narratives" (the line "Estimated cost: up to ..." and the estimate in the API); the "Cost:" line of a deck's AI log. The
narrative helper wording "Costs one AI request" stays, without an amount. The 80% line reads `You have used X% of this month's AI
allowance.` and the 100% message is unchanged. No tester screen mentions that cost figures exist or can be requested.

**Memo and exports.** Appendix D of the IC memo no longer carries "AI usage and cost (this audit)" (verdict-and-memo.md §8 and W20 are
withdrawn for the memo and the Audit page); the disclosure block stays. The xlsx export has no usage sheet and stays without one; a test
holds that. `build_memo` no longer takes the usage.

**API.** A tester token (and a request with access control off) never receives a cost, token or USD field, on any route: one filter on
the JSON of the response removes the closed key set `input_tokens, output_tokens, estimated_cost_usd, ai_cost_usd, cost_usd,
estimate_usd, total_usd, structure_tokens, structure_token_cap, tokens, allowance_usd, used_usd`, at any depth. `GET /runs/{id}/llm-usage` stays and
returns calls, cache hits and caps only; `GET /runs/{id}/narratives/estimate` returns the steps (label, cached, available) and no
amount; `GET /allowance` returns `{percent, state}`. The owner token keeps `/admin/usage`, `/admin/audit-costs` and `/usage/totals`.
A new key that carries a cost, a token count or USD is added to the set and to `test_gateway_data_boundary.py` in the same PR (rule 14).
Test: `test_tester_cost_hidden.py` calls every tester route that can carry them with a tester token and fails on any key matching
`cost|usd|token` outside a short list of names that are not AI figures.

**Owner page: "Cost per audit".** `GET /api/admin/audit-costs` (owner token only; tester 404; no token 401):
`{audits: [{tester, created_at, calls, tokens, cost_usd}]}`, newest first, one row per stored audit. `tester` is the tester link label
(`null` for an audit with no tester, shown as "no tester"); `created_at` is the audit's creation time (ISO, UTC), shown in the viewer's
local time as on the Audit Hub tile; `calls` are billed model calls of that audit (cache hits and refusals are not calls),
`tokens` input plus output, `cost_usd` the sum, shown `USD 1.23`. No audit id, company name, file name or audit name is in the row or
the response. The numbers come from `llm_calls`, which deleting an audit purges, so a deleted audit leaves the list; the tester ledger
(§2) keeps the totals. The owner token still gets 404 on every audit route.

| Test | File |
|---|---|
| No tester-token response holds a cost, token or USD field (every route that could); the owner routes still do | `test_tester_cost_hidden.py` |
| Memo and xlsx hold no usage table; `/allowance` has percent and state only; the estimate has no amount | `test_ic_memo.py`, `test_tester_cost_hidden.py`, `test_usage_allowance.py` |
| Audit costs: one row per audit with tester label, time, calls, tokens, cost; no name or id; owner only | `test_usage_allowance.py`, `test_owner_page_api.py` |
| Screens: no usage table, no estimate, no USD in the banner, no deck cost line; owner list renders | `Dashboard.test.jsx`, `Review.test.jsx`, `AllowanceBanner.test.jsx`, `DeckPanel.test.jsx`, `OwnerPage.test.jsx` |

## Files
`backend/app/allowance.py` (new), `backend/app/llm/guards.py`, `backend/app/llm/gateway.py` (log_call, two checks, cap word),
`backend/app/access.py`, `backend/server.py` (routes, upload counts), `frontend/src/components/AllowanceBanner.jsx`, `OwnerUsage.jsx` and `lib/allowance.js` (new),
`Layout.jsx`, `AuditHub.jsx`, `OwnerPage.jsx`, `lib/api.js`, `lib/chatUpload.js`, and the tests above. §9 adds `backend/app/tester_view.py`
(the filter), `OwnerAuditCosts.jsx`, and removes `UsagePanel.jsx`.

## Done when
§7 passes with the full suites (frontend with --no-cache), and the checks of .github/workflows/tests.yml are green.
