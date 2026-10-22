# Design note: the AI reads every page, the rules check each claim

Status: for decision, 2026-10-22. No code, test or spec change.

**Architecture note (CLAUDE.md rule 1).** The inverted design sends every page of a deck, prose included, to the model. CLAUDE.md rule 16 and docs/architecture.md ("Never raw files, full pages or prose slides") forbid that. Nothing below is built until George changes the rule (decision 1).

## 1. Today's pipeline and this week's errors

Evidence: issues #143, #148, #151, #154; PRs #144, #149, #152, #153, #156 (seven parser rules in four days); the live "€27K" finding.

| Stage | Code | Produces | This week's errors |
|---|---|---|---|
| 1 Parse | `decks/parser.py` | lines with box, position, title flag | "€27K" → claims "2" and "7". Both readers (`claims.find_numbers`, `verify.figures`) give 2 and 7,000 from `€2 7K`; letter-spaced digits split by the pdf word reader are the one input that reproduces it (rule 13: the stored lines would confirm) |
| 2 Rules read | `decks/claims.py` §2: keywords, nearest heading, borrowed label and date, bars, drops | candidates typed and dated by position | 7 of 9. #143: far bars took the page title, staggered axis ticks; #148: "2022 -2024" read as 2022, "FY22–24" left a 24, a bar off its label got no year; #154: one figure over three labels got none, a year from a sentence; #151: MRR labelled Revenue |
| 3 Structures + item list | `parser.py` §7, `structures/items.py` | KPI panels, roadmaps, tables as cell grids; `next_to`, `bar_year` | panel bars had no axis year until `bar_year` (#148 c) |
| 4 Panel read + verifier | `gateway.read_structure`, `structures/verify.py` | metric and period per item, period rebuilt from cells | none: no error this week was the model's label |
| 5 Merge | `structures/__init__.py`: `value_match`, `same_claim`, `rules_copy` | one row per figure across both reads | €5.3MM listed twice, FY2022 and 2024 (#154) |
| 6 Inconsistency check | `claims.py`: `deck_label`, `sales_metric` | "Deck inconsistency" pairs | MRR vs annual revenue, ARPA bar vs revenue (#151, #143): wrong types from stage 2 |

Eight of nine errors are stage 2 reading positions; one is stage 5 reconciling stage 2 with stage 4. Stage 2 is 2,100 lines of rules each fixed on one page of one deck.

## 2. The inverted design

The model reads each page as redacted cell lines with ids (the structure-text format of today) and returns claims. Each claim: `metric` (CLAIM_METRICS or `other`), `value`, `value_high`, `unit` (today's closed list), `period` (today's closed forms or null), `actual_or_forecast`, `value_cell`, `label_cell`, `period_cell`. No free text: the label is a cell id and Python reads its text, so rule 17 holds. Rules extract nothing. Python checks each claim:

1. **Figure present**: `value_cell` holds the value after today's normalisation (`verify.figures`, scale from an adjacent cell).
2. **Unit present**: the currency, %, x or count noun is in the value cell or one directly next to it.
3. **Period present**: null, or rebuilt from a date source of that cell: its own text, column header, box period line, bar axis label, or an adjacent heading. A sentence is no source (#154 stays).

All three pass → "Matched to page", in the register without a click. Otherwise "AI suggestion, not matched", listed collapsed, approved by a click. The metric is never checked by Python, as today; Confidence keeps "no heading" when the label cell holds no keyword of the type. Deck inconsistency, cross-page dedupe (`same_claim`), the register and the within-tolerance step are unchanged.

## 3. Removed, kept, missing

**Removed** (~3,500 lines): §2 candidate detection (keyword typing, nearest heading, borrowing, bar typing, use-of-funds cues, qualifier); §7 structure detection (KPI, label, value and title boxes, roadmaps, date boxes); the item list and labelling schema; the three merge paths and "period corrected"; the candidate pin.

**Kept**: date borrowing and bar-axis rules, as the period check's allowed sources rather than extraction; heading drop (a figure-less claim whose label cell a valued claim cites); page drops (Problem/Why now titles, cited research, funds raised) as filters on the model's claims; inconsistency check; redaction; boundary tests; period rebuilding; the register.

**Missing**: a page grid giving every line of every page a cell id and `next_to` (only §7 structures have them); a per-page figure and date index; redaction over prose, including lines over 200 characters (excluded today); the `page_claims` prompt in the store and its schema; a `page_check` module; the compare script (§7).

## 4. Token cost

From docs/test-runs/consistency_2026-10-07.md (Sonnet 5.5, $2/$10 per MTok): fixed prompt 3,970 tokens, structure text 285, output 452 → 4,390 input and $0.0133 per read; 26 structures on 163 pptx/pdf pages → ~3 structures on a 20-page deck. Inverted: prompt ~5,000 (closed lists, period rules), page text ~150 tokens (266 chars/page on the fixtures), 350 output.

| 20-page deck | Calls | Input | Output | Cost | Decks per 400K cap |
|---|---:|---:|---:|---:|---:|
| Today | 3 | 13,200 | 1,400 | **$0.04** | 27 |
| Inverted, one call per page | 20 | 103,000 | 7,000 | **$0.28** (7×) | 3 |
| Inverted, 5 pages per call | 4 | 23,000 | 7,000 | $0.12 | 13 |
| 5 pages per call + prompt caching ($0.20/MTok cache read) | 4 | 23,000 | 7,000 | **$0.09** (2×) | 13 |

Time: one call at a time per audit, ~6 s each: 2 min per deck per-page, 30 s batched (today ~20 s).

## 5. Privacy

What leaves the server grows from redacted structure cells to every redacted text line of every page: bios, customer quotes, strategy prose. Today's redaction runs over all of it; a known limit grows: a prospect named only in prose goes as written. Consent text and rule 16 are reworded.

Boundary tests to extend (`test_gateway_data_boundary.py`): the cell-lines-only and rule-16 refusal tests (a page text passes; a line over 200 characters only redacted; a file name, an unredacted name or a figure outside a cell line fail); the "gateway names/reads no deck text" tests (page cells come through one builder, never `blocks` or `snippet`); the no-sent-text-in-logs test (`label_cell` text is never stored); a new test that every reply field is a closed word, a number or a cell id.

## 6. Risks and controls

| Risk | Control |
|---|---|
| Non-determinism: the same page gives different claims | cache key (page text, prompt tag, model, schema hash) as today; 3-pass run, ≥95% agreement on (value cell, metric, period) before the switch; an unmatched claim never enters without a click |
| Misread the check passes: the MRR figure gets the page's "2021 Revenue" period, an ARPA bar is called Revenue | the check is cell-level: figure in its cell, period from that cell's own sources, unit adjacent; the metric stays the analyst's; the inconsistency check and the tolerance test still catch it |
| Cost and time, 7× per-page | 5-page batches and prompt caching (2×); per-deck cost shown as today; cap unchanged |
| Gateway failure: no claims at all | rule 20 concerns metrics, unaffected; the deck panel shows "AI reading unavailable – retry" and Add claim (decision 6) |
| A parse error survives (`€2 7K`) | the check fails 27,000 against the page: one right row to confirm, not two wrong rows to reject |

## 7. Migration

**PR A** (flag `DECK_PIPELINE=rules`, default; no screen change): page grid and page redaction; prompt stub and schema; gateway step `page_claims` with cap, cache and the §5 boundary tests; `page_check` with fail-first tests (figure moved to another cell, unit removed, period from a sentence, label not adjacent); `compare_pipelines.py` on recorded replies. Blocked on decision 1.

**PR B** (live run, decision 5): `consistency_run.py --pages`, 3 passes, recorded replies committed; the compare table in the PR and docs/test-runs; prompt tuned in the store until recall ≥95% against the answer file and agreement ≥95%.

**PR C** (the switch): default `ai`; stage 2, 3 and 5 code and the candidate pin deleted in one commit (one revert restores); deck-parser.md, llm-structure-reading.md and structure-labelling.md rewritten; badge texts exist (#150).

**Side by side**: `compare_pipelines.py` runs `detect_candidates` and `page_claims` on the ten fixture decks and prints per deck: pages, rows A, rows B, B matched and unmatched, recall and precision of each against the answer file, rows only in A, rows only in B; a diagnostic (public decks only) lists each differing row; the synthetic pages of `test_issue_143/148/151/154.py` run through B.

## 8. Open decisions for George

1. **May every redacted text line of a deck page leave the server?** Changes rule 16, docs/architecture.md and the consent text. (a) every page; (b) only pages with a figure (~30% fewer calls); (c) no, stop here. **Recommend b.**
2. **What may be labelled "Matched to page"?** (a) figure in the cited cell, unit in it or adjacent, period from that cell's sources; (b) figure anywhere on the page. **Recommend a.** The metric stays the analyst's.
3. **Unmatched claims**: (a) listed collapsed, approved by a click; (b) dropped with a count. **Recommend a.**
4. **Cost**: (a) one call per page, $0.28/deck, 3 decks per cap; (b) 5-page batches with caching, ~$0.09, 13 decks. **Recommend b**; raise the cap only if the live run needs it.
5. **Approve PR B's live run**: three passes on the ten public decks, ≈ $2.5 batched, ≈ $7 per-page.
6. **Gateway failure**: (a) no claims, retry button and Add claim; (b) keep the rules read as fallback. **Recommend a**: b keeps the code this design deletes.
7. **Prompt text**: George uploads it to the store (rule 26); the repository holds the stub and schema.
