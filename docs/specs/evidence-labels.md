# Spec: Extraction confidence and evidence status (Release 1)
Status: Agreed scope. Source: docs/plans/app-plan_V2_amendments_15_10_2026.md section 5 and 7.1 (decisions of 15 Oct 2026,
final). Location: docs/specs/evidence-labels.md. Amends claim-matching.md §4, §6, §8 and verdict-and-memo.md §3, §7.2.
Implementation order: 1 of 6 (evidence-labels → dates-and-periods → claim-types-and-correction → integrity-coverage →
claim-review-conclusion → access-links).

## 0. Challenge and deletions (CLAUDE.md rule 4)
- Needed: one cell today says both "how well the deck was read" and "whether the claim holds", so a well-read wrong claim
  looks trustworthy. The simpler version: two columns from figures the app already computes (the deck list's confidence,
  the register's label) and one new status. No engine, model or storage change.
- Deleted first: the long Confidence hover of the deck list (replaced by the one-sentence explainer of §1); the register's
  single "Evidence" header (replaced by the two columns).

## 1. Two columns, each with a hover explainer
| Column | Values | Explainer (hover on the header, word for word) |
|---|---|---|
| Extraction confidence | High · Medium · Low · Analyst-entered | How well the app read this figure from the deck. Not a statement about whether it is true. |
| Evidence status (within the supplied evidence) | Verified · Contradicted · Inconclusive · Unverified · Unsupported | How this claim compares with the company data supplied for this audit. Agreement is not independent verification. |

- Claim register (Dashboard, claim-matching.md §8): the columns become `#`, `Claim`, `Segment`, `Observed`, `Gap`,
  `Extraction confidence`, `Evidence status`; widths 4, 30, 14, 18, 12, 10, 12 (fixed layout, sum 100, still no horizontal
  scroll). The header of the last column reads "Evidence status" with "(within the supplied evidence)" in small grey type
  under it. An open Definition check still reads "Definition check" in the status cell (claim-matching.md §4.1).
- Deck list (DeckPanel): the column "Confidence" is renamed "Extraction confidence"; its hover is the explainer above; the
  cell text is unchanged ("High", "Medium – no date", "Analyst-entered").
- New register field `extraction_confidence`: the level of `decks.claims.confidence` for the claim's candidate over the
  candidates of the same deck (deck-parser.md §6), the value the deck list shows: "High", "Medium", "Low", or
  "Analyst-entered" for a claim added with Add claim. A value of a table row takes its candidate's level. Display only:
  no label, gap, rank, gate or count reads it (claim-matching.md §1, "Not inputs", stands). It is a CSV column
  (verdict-and-memo.md §5) after `deck_reading`.

## 2. Evidence status values
| Status | Meaning | Rule in the app |
|---|---|---|
| Verified | Tested against supplied company data; within tolerance | claim-matching.md §4, unchanged: a beat beyond tolerance up to the check limit is Verified, marked "(beat)" and listed under Worth flagging (13 Oct rule) |
| Contradicted | Tested against supplied company data; misses by more than tolerance | claim-matching.md §4, unchanged |
| Inconclusive | A test ran but cannot confirm or contradict the claim. Reason and computed figure shown | new, §3 |
| Unverified | Testable metric, but the supplied files do not cover it, or an analyst answer is pending. Reason shown | claim-matching.md §4, unchanged |
| Unsupported | The app does not compute this metric (product limitation). Never counted as a company finding | claim-matching.md §4, unchanged |

## 3. Inconclusive
A row is Inconclusive when the app computed a figure for the claim but the figure cannot confirm or contradict it. The row
carries `observed_value`, `observed_at` and `observed_source` (the computed figure, shown), a reason, and no gap
(`gap`, `gap_normalised`, `gap_kind`, `gloss` null), so it never ranks as a miss: it ranks with the untested rows
(claim-matching.md §3, "then the rest"). Release 1 cases:

| Case | Built in | Reason (word for word) |
|---|---|---|
| Population differs: a Users claim with a qualifier (deck-parser.md §2, "Registered Institutions", "40 trial accounts") is read against Customer count (paying customers) for its period | this spec | `population differs: deck label '{label}' is not paying customers; the figure shown is paying customers` |
| Population differs: a claim whose population (claim-types-and-correction.md §2) is registered or active users, or a sales population other than the metric's | claim-types-and-correction.md | `population differs: the claim counts {population}; the figure shown counts {metric population}` ("registered users", "paying customers") |
| The claim period is only partly covered (dates-and-periods.md §4) | dates-and-periods.md | `claim period partly covered (months missing: {list})` |

- With no paying-customer figure at all (no revenue series, or a figure that is not a count), the qualified Users claim is
  Unsupported with `population differs: deck label '{label}' is not paying customers`.
- Order inside a row's rules: the period is read first. A qualified Users claim whose period has no Customer count in the
  data is not Inconclusive: it follows dates-and-periods.md §4 (Unverified, not covered).
- Growth basis unknown: plan section 5 lists it under Inconclusive, plan sections 3 and 7.1 say "stays Unverified with a
  one-click Set growth basis task". The release test (7.1) is followed: Unverified (dates-and-periods.md §5). Reported
  under "Decisions for you" (§8).
- An Inconclusive row needs a gate, like Unverified (verdict-and-memo.md §3: `gate_needed` and the prefill cover
  Unverified, Inconclusive, Unsupported and Contradicted). It is never a hard blocker (CLAUDE.md rule 21: only a
  Contradicted top-5 claim is).
- Supersedes claim-matching.md §4's Unsupported rule for a qualified Users claim (2026-10-13): the claim keeps its reason's
  information and gains the computed figure.

## 4. Counts
- Memo summary (verdict-and-memo.md §7.2, item 1): "Claims: {c} Contradicted, {s} Unsupported, {u} Unverified ({i}
  Inconclusive) of {N} in the register." `u` counts Unverified and Inconclusive together; `i` is the Inconclusive count,
  printed in brackets always, also when 0. Appendix A lists each row with its own status.
- The verdict until claim-review-conclusion.md lands: an Inconclusive top-5 claim counts with the Unverified ones
  ("Underwrite with gates": "{n} is/are Unverified or Unsupported" counts it). claim-review-conclusion.md §2 counts it as
  untested.
- Log lines: `label_counts` has an "Inconclusive" key like any label; counts only (rule 17).

## 5. Shared schema and contract
- `frontend/src/lib/evidence_labels.json` is the one list both sides read: the five statuses in screen order, the two
  explainers, and the memo grouping `{"Unverified": ["Unverified", "Inconclusive"]}`. The frontend imports it for the
  headers, the hovers and the label styles; `backend/tests/test_interface_contracts.py` pins it to
  `app.claim_matching.EVIDENCE_STATUSES`, `app.claim_matching.MEMO_GROUPS` and the explainer constants, and builds a memo
  whose summary reads "Unverified ({i} Inconclusive)" (shown failing on a deliberate violation).
- No engine output field changes, so `backend/schemas/metrics.py` does not change for this spec.

## 6. Data boundary (CLAUDE.md rules 14, 17)
No register field reaches a narrative slice or a gateway payload (claim-matching.md §9). `extraction_confidence`, the
Inconclusive reasons and `EVIDENCE_STATUSES` join `REGISTER_NAMES` in `test_gateway_data_boundary.py`, so the gateway may
never name them.

## 7. Tests
Every new test is first shown failing on a deliberate violation (rule 11). Plan tests are committed first as strict
expected failures and turned into plain tests by the code PR.
| Test | File |
|---|---|
| Plan 5 (required, replaces label-placement-only tests): a claim with High extraction confidence Contradicted by the revenue file shows "High" in one column and "Contradicted" in the other, with the computed figure and the gap | `test_evidence_labels.py`; `ClaimRegister.test.jsx` |
| The register has seven columns, the two headers carry the explainers word for word; the deck list's column reads "Extraction confidence" with the same hover | `ClaimRegister.test.jsx`, `DeckPanel.test.jsx` |
| A qualified Users claim is Inconclusive, shows paying customers for its period and no gap, needs a gate, and ranks after every tested row | `test_evidence_labels.py`, `test_claim_matching.py` (fixture row updated) |
| The memo summary counts Inconclusive under Unverified with the count in brackets, also "(0 Inconclusive)" | `test_interface_contracts.py`, `test_ic_memo.py` |
| `evidence_labels.json` equals the backend constants | `test_interface_contracts.py`; `claimRegister.test.js` |
| The CSV round-trips with `extraction_confidence` | `test_claim_register_api.py` |
| Boundary: the new names never appear in the gateway | `test_gateway_data_boundary.py` |

Tests replaced (plan 5: "replaces any test that only checks label placement"): a test that asserts only where a label sits
(the cell, the chip) without the figure and the gap is rewritten to assert the two columns, the computed figure and the gap.

## 8. Decided (engineering, rule 19) and open
- Decided: the Inconclusive row has no gap, so it neither ranks as a miss nor reads as a test result; the computed figure
  and its source are shown. The confidence is computed on read from the candidates (no stored copy that could go stale).
- Decisions for you (plan conflict, not built differently from the release test): growth basis unknown is Unverified
  (plan 3 and 7.1), not Inconclusive (plan 5). Recommendation: keep Unverified and drop "growth basis unknown" from the
  Inconclusive list, because no test can run without a basis.

## Files
`backend/app/claim_matching.py`, `backend/app/ic_memo.py`, `backend/app/verdict.py`, `backend/server.py` (`_claim_rows`),
`frontend/src/lib/evidence_labels.json`, `frontend/src/lib/claimRegister.js`, `frontend/src/components/ClaimRegister.jsx`,
`frontend/src/components/Verdict.jsx` (label style), `frontend/src/components/DeckPanel.jsx`, `frontend/src/lib/deckClaims.js`,
the tests of §7.

## Done when
§7 passes with the full suite; the run A register shows both columns and the memo summary line of §4.
