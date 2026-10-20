# Spec: Claim types, required fields and the correction path (Release 1)
Status: Agreed scope. Source: docs/plans/app-plan_V2_amendments_15_10_2026.md section 4 and 7.1 (decisions of 15 Oct 2026,
final). Location: docs/specs/claim-types-and-correction.md. Amends deck-parser.md §2, §6, claim-matching.md §1, §2, §4,
§10 (D4, Q1), chat-upload.md §17 (Approve all) and verdict-and-memo.md §6.1. Implementation order: 3 of 6.

## 0. Challenge and deletions (CLAUDE.md rule 4)
- Needed: a claim is matched today from whatever the parser found, so a misread figure type or a missing period becomes a
  test of the wrong thing, and a figure the parser missed can only be typed in by hand. The simpler version: a fixed list of
  fields per type that must be known before matching, three new candidate fields, an edit log, and one endpoint that
  creates a claim from a stored deck line.
- Deleted first: the "Unknown – choose type" section of the deck list (its figures are Other, §4); "no period stated" as a
  tested state (claim-matching.md D4 and Q1: a claim with no period is not matched, §2); the rule that Other and Unknown
  figures wait for a type before approval (they are no longer tasks).

## 1. Claim types and the app's stored types
| Plan type | Stored types | Metric | Value | Unit | Currency | Period | Population | Figure type | Growth basis |
|---|---|---|---|---|---|---|---|---|---|
| Revenue / ARR / MRR / Transaction volume | revenue | R | R | R | R | R | – | R | – |
| Growth rate | revenue_growth, growth, user_growth | R | R | R (%) | – | R | – (user_growth: R) | R | R |
| Customers / users | customers, users | R | R | R (count) | – | R | R (paying / registered / active) | R | – |
| NRR / churn / retention | retention | R | R | R (%) | – | R (window) | R (cohort) | R | – |
| Sales cycle / win rate / pipeline | sales | R | R | R | – | R | R (deals won / all closed / open) | R | – |
| Costs / burn / runway / cash | costs, burn, runway, cash, gross_profit, ebitda, net_profit, gross_margin, months_to_profitability | R | R | R | R for an amount | R | – | R | – |
| Unit economics | ltv, cac, ltv_cac, customer_lifetime, trials_per_day | R | R | R | R for a money value (ltv, cac) | R | – | R | – |
| Headcount / hiring | people | R | R | count | – | R | optional (team) | R | – |
| Launch date | product | item name | date | – | – | – | – | R | – |
| Market size | market | R | R | R | R | optional | – | – | – |
| Use of funds | use_of_funds | category | share % | – | – | – | – | – | – |
| Acquisition channels | acquisition_channels | channel | count | count | – | optional | – | – | – |
| Other | other, unknown | text only | – | – | – | – | – | – | – |

- Unit economics is a row of the plan's table (George, 15 Oct 2026, decision 4): metric, value, unit, period and figure type
  are required, and the currency is required for the money values (`ltv`, `cac`), not for `ltv_cac`, `customer_lifetime`
  or `trials_per_day`. No population. None has an app metric, so each stays Unsupported (claim-matching.md §4); `usage` has
  no row and stays typed as today.
- Every field holds a value, "Unknown" or "Not applicable" (shown "–" in the table). Only R fields are required before
  matching; the others may stay Unknown.

## 2. Required fields before matching
- New candidate fields: `population`, `figure_type` (`actual`, `target`, `unknown`), `growth_basis` (dates-and-periods.md §5).
  Each has a `*_set_by` (`parser`, `python`, `analyst`). The register row carries `population`, `figure_type`,
  `growth_basis` and `required_unknown` (the R fields still Unknown, in table order).
- Where each value comes from:
  | Field | Parser or Python | Unknown when |
  |---|---|---|
  | Metric | claim-matching.md table 2a; the analyst's pick on the register | no app metric: Unsupported "no metric" as today (product limitation, not a task) |
  | Value | the figure; a direction ("Positive EBITDA") has none | a direction: Unverified "direction only" as today |
  | Unit, Currency | the parser; a currency type with no currency | an amount claim with no currency |
  | Period | the stated period (deck-parser.md §2) | no period stated |
  | Population | customers: paying; users: registered when the deck label carries a qualifier (deck-parser.md §2), else Unknown; retention: the register's segment (Whole company or a segment); sales: the metric's population (Median sales cycle: deals won; Win rate: all closed; a "pipeline" keyword: open) | users with no qualifier; sales with no metric |
  | Figure type | the parser: `target` when the claim's line or borrowed label holds a target cue (§2.1); otherwise Python on read: `target` when the period ends after the as-of month, else `actual` | never, once the period is known |
  | Growth basis | dates-and-periods.md §5 | no cue, or cues of two bases |
- Order on a register row: direction only; turnover question; use of funds and acquisition channels (unchanged); no app
  metric (Unsupported); then the R fields: any Unknown → Unverified, reason `required field unknown: {fields}; set it with
  Edit in the claims list`; a period Unknown reads `Period not read – set it in the claim row` first, the other fields after it
  (George, 2026-10-19, issue #136; a date the parser could not read is the same case, no longer Unsupported "period not readable")
  (growth basis alone keeps its own reason and one-click task, dates-and-periods.md §5); then the
  matching of claim-matching.md with coverage (dates-and-periods.md §4).
- Figure type Target: a period after the as-of month is a forecast, as today (claim-matching.md table 2b). A period that is
  not after the as-of month: Unverified, reason `target figure: the deck states a plan for this period, not a result`; the
  computed figure is shown, no gap. Figure type Actual is matched as any claim.
- Users and user_growth claims are read against Customer count and Customer growth (paying customers): the population
  decides. Paying: tested as any claim. Registered or active (customers, users, user_growth), or a sales population other
  than the metric's: Inconclusive (evidence-labels.md §3), reason `population differs: the claim counts {population}; the
  figure shown counts {metric population}` ("registered users", "paying customers"; "deals won", "all closed deals"), the
  computed figure shown. A qualified Users claim keeps the reason of evidence-labels.md §3.
- Replaces claim-matching.md D4 ("a claim with no period: tested at the as-of figure") and Q1 ("no period stated"): a claim
  with no period is Unverified with `required field unknown: period`.

### 2.1 Target cues
Whole words, any case: target, targets, targeted, planned, forecast, forecasts, forecasted, budget, budgeted, goal, goals,
projected, projection, projections, expected, guidance, outlook, aim, aims, aiming. "plan" and "plans" are not cues
("Free to Paid plans"). Measured on the 10 public test decks on this branch (`python -I` over `detect_candidates`, no
network): 4 of 225 candidates carry a cue: front slide 16 "Aiming for $xx ARR by end of 2018", moz page 18 "our current
(2011-13) targets", buffer slide 7 "our projected revenue is $3.6M" (two candidates).

## 3. Editor
- The deck list's inline editor edits every field of §1 for the claim's type: type, value (and the high end of a range),
  unit, currency, period, population, figure type (Actual · Target · Unknown) and growth basis (MoM · YoY · Annualised ·
  Cumulative · Unknown, growth types only). The metric is edited where it is today, on the register row
  (claim-matching.md §8). Every select offers "Unknown" and, where the table has "–", "Not applicable".
- Each change keeps a reason code and records who changed it and the previous value: the candidate's `edit_log` gains one
  entry per changed field, `{"field", "previous", "value", "by", "at", "reason"}`; `by` is "analyst" until access-links.md
  names the tester; `reason` is one of `parser_misread` ("Parser misread the deck", the default), `deck_context` ("Deck
  context says otherwise"), `other` ("Other"), chosen in the editor. The provenance (deck, page, snippet, `parsed`) is
  unchanged. The Status cell's hover lists the log: "Figure type: Target → Actual · analyst · 15 Oct 2026 · Parser misread
  the deck".
- A change re-matches the claim (the register is computed on read) and clears a Definition check answer, as a re-type does
  today (claim-matching.md §4.1).

## 4. Other
- Types `other` and `unknown` are Other (the label reads "Other"). They are excluded from matching, value at stake, top-5
  candidates, review tasks and the hard-blocker banner: never in the register, never counted as claims to review (the
  review summary's `open`, Run audit's counts, the deck list's "to review" count), never approved or counted by Approve
  all, never a task.
- The deck list shows them in one collapsed section, headed "{n} other figures" ("1 other figure"), with no review count.
  Each row offers Edit (to retype) and Reject; no Approve.
- The analyst may type a claim Other in the editor (it leaves the register). Retyping a claim out of Other with Edit makes it
  "edited" and puts it back into matching.

## 5. Add from deck (recovery of a missed claim)
- Page view: `GET /api/audits/{id}/decks/{deck_id}/pages/{page}` returns `{"deck_id", "file", "page_unit", "page", "pages",
  "lines": [{"ref", "kind", "text"}]}`: the page's stored text lines, notes lines and table cells (`ref` "b{n}", the block's
  index in the stored deck) and its chart labels (`ref` "c{structure}:{cell}"), in the stored order. The deck panel shows
  it under a "View page" control (page number and "Show page"); the analyst selects one line, cell or label and clicks "Add
  from deck".
- `POST /api/audits/{id}/decks/{deck_id}/add-from-deck` `{"page", "ref"}`: the server reads the text of that line from the
  stored deck (the client never sends claim text) and creates a candidate: `snippet` the text verbatim (refused over 300
  characters: "Select a shorter passage (300 characters at most)"), `sources` the deck, page and cell of the line,
  `origin` "deck_analyst", status "pending", and the fields the parser reads from that text (deck-parser.md §2: the first
  figure's value, unit, currency, period and type); with no figure or no type it is Other with no value, opened in the
  editor. It is then typed, matched and labelled like any other claim. Its tag reads "Added from deck by analyst" (the
  deck list and the register's reading line); its extraction confidence is scored as for any parsed claim.
- Add claim (manual entry for figures in pictures, deck-parser.md §6) stays, with its "Added by analyst" tag. No endpoint
  takes free claim text: a claim always has a deck, a page and a source.

## 6. Data boundary (CLAUDE.md rules 14, 17)
The page view returns stored deck text to the analyst's browser only, as the deck list's snippets do; nothing reaches the
gateway. `population`, `figure_type`, `growth_basis`, `required_unknown`, `edit_log`, `deck_analyst` and the new reasons
join `REGISTER_NAMES` in `test_gateway_data_boundary.py`; the two new endpoints log nothing but their run id and a count.

## 7. Tests
| Test | File |
|---|---|
| Plan 4 (1): a claim extracted as Target but actually Actual is corrected in the editor (figure type) and re-matched; the edit log holds the previous value, who and the reason | `test_claim_types.py`; `DeckPanel.test.jsx` |
| Plan 4 (2) and 7.1: "15 months" typed Other creates no task (review summary `open`, Approve all, deck-list count) and is not in the review list or the register | `test_claim_types.py`; `DeckPanel.test.jsx` |
| Plan 4 (3): a sentence the parser missed is added from the deck page and shows its page as source and the "Added from deck by analyst" tag | `test_claim_types.py`; `DeckPanel.test.jsx` |
| Required fields: a claim with no period is Unverified "required field unknown: period"; users with no qualifier need the population; a population of registered gives Inconclusive | `test_claim_types.py`, `test_claim_matching.py` (fixture rows with no period updated) |
| Retyping out of Other puts the claim into the register | `test_claim_types.py` |
| The page view returns the stored lines only for the audit's deck; Add from deck refuses a ref that is not on the page | `test_claim_types.py` |
| Boundary | `test_gateway_data_boundary.py` |

## 8. Decided (engineering, rule 19)
- Python derives the figure type from the period when no cue says Target, so no claim waits on a field the data already
  answers; a cue is read only from the claim's own line and label (measured above).
- Population defaults follow what the type's keyword already means (a customers keyword counts paying customers,
  deck-parser.md §2; a qualifier names people who are not paying, 2026-10-13) and the metric's own definition for sales.
- Add from deck takes a reference to a stored line, never text, so a claim with no source cannot be created through it.
- The edit log is per field with a closed reason code, like the turnover answer's codes (claim-matching.md §11).

## 9. Consequences and open decisions
- Every undated claim with an app metric becomes Unverified "required field unknown: period" (claim-matching fixture rows 2,
  3, 6, 22, 25, 36 and run B row 11), where it was tested at the as-of figure. Each is a task until the analyst sets its
  period.
- Decided by George (15 Oct 2026): the Unit economics row (decision 4); a figure the parser cannot type, such as "15 months",
  is Other and never a task (decision 5).

## Files
`backend/app/decks/claims.py`, `backend/app/claim_matching.py`, `backend/app/verdict.py`, `backend/server.py`,
`frontend/src/components/DeckPanel.jsx`, `frontend/src/lib/deckClaims.js`, `frontend/src/lib/api.js`,
`frontend/src/components/ClaimRegister.jsx`, `frontend/src/lib/claimRegister.js`, the tests of §7.

## Done when
§7 passes with the full suite; the three plan tests pass as plain tests.
