# Spec: Structure labelling: Python lists items, the model labels them
Status: Draft; decisions of 2026-10-05 applied. Location: docs/specs/structure-labelling.md. Replaces parts of
llm-structure-reading.md (§8). Implements CLAUDE.md rules 16–18.

**1. Item list (Python, pure).** For every deck type, Python lists every figure in every redacted cell. Dates are
periods and are left out. Each item has:
- `id`: `i1`, `i2`, … in reading order, so the same structure always gives the same list;
- the cell id: a cell with several figures gives one item each, `#n` marking the position (`r6c2#2`);
- the raw text, cut from the redacted cell;
- the value in full units, under today's normalisation (llm-structure-reading.md §2);
- the ids of its header cells (`verify.header_cells`).

An ambiguous reading carries both values, with Python's default first; the model does not choose.
- `dot_reading`: `2.500` defaults to thousands, unless it carries a k/m/bn suffix (`1.250M` → 1.25m).
- `bracket_reading`: a bracketed number after text defaults to negative when the text before it in its cell
  contains loss, deficit, negative or decline (any case). Otherwise it defaults to positive.

The approval row shows both readings. The analyst confirms the default or uses Edit (deck-parser.md §6).

Ranges (decision of 2026-10-06): in `$12 -$13 million` the dash is no sign and the low end takes the high end's scale
(12,000,000 to 13,000,000). The two figures stay two items; both carry `range` (low id, high id, low, high) and make
one approval row (`value`, `value_high`) from the first labelled end, Verified only when both ends have the same
metric and are Verified. The AI-row dedupe (`structures.value_match`) returns exact (same value or range), in range
(one falls inside the other's range) or no match; either match means the cell already lists the row.

**2. Roadmaps.** Python also lists date cells (`d1`…, date labels as in deck-parser.md §7) and text lines (`t1`…,
the other non-empty cells). The model returns pairs (line id, date id) with a category: `launch`, `feature`,
`expansion`, `partnership`, `hiring`, `break_even`, `funding`, `certification` or `other`. Claim types: `hiring` →
people, `break_even` → ebitda, `funding` → other (type Other, §4), the rest → product. Parser rules are unchanged.

A line has at most one pair, and a date may serve several lines. A milestone's period is the one Python rebuilds from
its date cell. A milestone has no value, so it is never Verified. A figure in a paired line is dated by its pair: its
period is the one Python rebuilds from that date cell. The pairing is the model's, so the figure is Verified only
when §4 rebuilds the same period from its own period cells.

Adjacent date line: a text line takes the date line directly above or below it in the same text box. A line with a
date line on each side takes the one in the timeline's date direction (decision of 2026-10-06): decided once per
timeline, from the first line in reading order with a date line on one side only (above or below). A timeline with
no such line has no direction, and its lines with a date on each side have no adjacent date line. That date line is
then a period cell of the line, and Python rebuilds the period itself. This also raises "date rebuilt from cell" on
timelines such as buffer p6, where dates sit below their lines.

**3. Text and reply.** The structure text is unchanged (`r<row>c<col>: <text>`, with spans). Below it comes the line
`items:`, then one line per item, e.g. `i3 r3c2#2 "(30K)" 30000 or -30000 h r3c1 r1c2`. A roadmap adds `d1 r2c1`
and `t1 r1c1` lines. All deck types share one labelling schema: `{"type", "labels": [...], "pairs": [...]}`. A label
holds exactly `item` (a listed id), `metric` (`CLAIM_METRICS`, `use_of_funds`, `other`, or `not_a_metric` for page
numbers, years and footnote marks), and `period`, `unit`, `unit_other` and `actual_or_forecast` as today. There is no
value, cell id or flag, and each listed id is labelled exactly once. Schema violations (an unknown, duplicate or
missing id; a pair that is not one listed line and one listed date; pairs on a structure not sent as a roadmap) get
one reask, then "Not read by AI".

The reply follows the type Python sent; a corrected type is only logged. Column mapping keeps its own schema. Each
schema's hash enters the cache key. Tie-breaks in the prompt: hours and time figures → `product` unless a user count
is named; "% of marketplace" and market share → `market`; commission and take rate → `sales`.

**4. Verifier.** Values and cells are Python's, so value matching is deleted. What is left:
- Period: rebuilt from the item's lowest period header (with the year cell above), from its own cell, or in a
  roadmap from its adjacent date line (§2), under deck-parser.md §2. The rebuilt period replaces the model's, and a
  difference counts as "period corrected". A model period with nothing to rebuild from, or a header period Python
  cannot rebuild, is "period not rebuilt" (an AI suggestion). A null period matches when no header holds a period.
- Separator and sign: recorded as `dot_reading` and `bracket_reading` with the default. Both readings come from the
  item's cell, so the item can be Verified.
- Flags: Python computes `total_mismatch` and `growth_mismatch` over the Verified items (`verify._flag_reproduced`).
- `not_a_metric` items are dropped and counted.
- `other` items are listed as type Other and are never Verified. The server refuses to approve one until its type is
  edited to a `CLAIM_TYPES` value.

Python joins each label to its item, so a checked item keeps today's fields plus its id and position.
`STRUCTURE_UNMATCHED` and the labels are unchanged.

**5. Storage, prompt, cache and cap.** `llm_structures` stores the reply and the item list without raw text (id,
cell, position, values, header ids, a range's low and high), so every label resolves to a value with its cell reference (rule 17) and no deck
text is stored. The prompt becomes v3 and the release r6; the narrative keys move once, as with r5. The key formula
stays; the schema hash and the item list move every key. Cap: 4,000 tokens per structure, on the structure text plus
the item list; a larger structure is "Too large for AI reading". `reverify_audit` skips readings stored under v2, and
their rows keep their labels.

**6. Agreement.** Agreement per type = items with the same metric and period in every pass ÷ items Python listed,
over structures read in every pass. The period is compared as the verifier keeps it (start and end dates), and
`not_a_metric` counts as a metric. Cells and the item count are fixed by code. The ≥95% target applies to this figure
over all deck types. Roadmaps are reported apart: "roadmap lines: N, same pair and category in every pass: M,
date rebuilt from cell: K". K counts roadmap items whose period Python rebuilds from their own period cells (§4),
whatever the pair says. The match rate counts every labelled item, roadmap figures included and milestones left out,
and is also given apart: financial (outside roadmaps) and roadmap (decision of 2026-10-06).

**7. scripts/consistency_run.py.**
- Keys: `_normalised_key` = (item id, metric, kept period range); old method = (item id, metric, period as written,
  unit, actual_or_forecast).
- `FIELDS` = metric, period, unit, actual_or_forecast.
- `REASONS` = period not rebuilt, metric invalid, other.
- New counts per type: `not_a_metric`, `other`, ambiguous readings, flags.
- Diagnostic columns: deck, page, type, item id, cell#position, cell text, Python's values, reason, then per pass the
  model's metric, period, unit and actual_or_forecast and the verifier's result.
- The token line gives the average of text plus list against 4,000, and `FakeAdapter` replays the new format.

**8. Replaced in llm-structure-reading.md.**

| Section | What is replaced | Now |
|---|---|---|
| §1 | item fields, output, one schema for all types | §3 |
| §2 | value and period matched against cited cells; model flags | §4 (normalisation moves to §1) |
| §5 | cited-cell check | §3 |
| §7 | 3,000-token cap on the text alone | §5 |
| §9 | what `llm_structures` stores | §5 |
| §11 | agreement, fields, reasons, diagnostic, token and roadmap lines | §6–7 |

Unchanged: §3, §4, §6, §8 and the 400,000-token audit cap.

**9. Tests.** Each is first shown failing on a deliberate violation. Enumeration: several figures per cell, dates
left out, both defaults, stable ids. Reply: bad, duplicate or missing ids, and bad pairs. Verifier: periods, a
pair-dated figure, the adjacent date line (one above or below counts; one each side takes the timeline's direction), flags. Other: refused
until its type is edited. The 4,000 cap, with the list counted. Boundary: an item line passes only in format, with
raw text that is a figure inside its cell (else reason `bad_item_line`), and no raw text reaches `llm_structures` or
a log.

**Open questions.** None. A cash claim type is left to the forecast-claims spec.

**Files.** New: `backend/app/structures/items.py`. Changed: `backend/app/structures/{__init__,verify,redact}.py`,
`backend/app/llm/{schemas,gateway}.py`, `backend/app/llm/prompts/{structure_reading.md,RELEASE.md}`,
`backend/server.py` (refuses to approve an unedited Other), `frontend/src/components/DeckPanel.jsx`,
`frontend/src/lib/deckClaims.js`, `backend/tests/test_structure_{verifier,reading}.py`,
`backend/tests/test_gateway_data_boundary.py`, `backend/tests/fixtures/structure_replies/*.json`,
`scripts/consistency_run.py`, and `docs/specs/llm-structure-reading.md` (a pointer at each replaced section).
