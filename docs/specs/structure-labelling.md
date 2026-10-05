# Spec: Structure labelling: Python lists items, the model labels them
Status: Draft. Location: docs/specs/structure-labelling.md. Replaces parts of llm-structure-reading.md (§8).
Implements CLAUDE.md rules 16–18.

**1. Item list (Python, pure).** For `table`, `hiring_table` and `kpi_panel`, Python lists every figure in every
redacted cell. Dates are periods and are left out, as in the verifier. Each item has:
- `id`: `i1`, `i2`, … in reading order (row, column, position), so the same structure always gives the same list;
- the cell id: a cell with several figures gives one item each, `#n` marking the position (`r6c2#2`);
- the raw text, cut from the redacted cell (`£1.2m`);
- the value in full units, under today's normalisation (llm-structure-reading.md §2);
- the header cells `verify.header_cells` gives.

An ambiguous reading (`dot_reading` for `2.500`, `bracket_reading` for a bracketed number after text) carries both
values, with Python's default first. The model does not choose. The approval row shows "<default> or
<alternative>", and the analyst confirms it or uses Edit (deck-parser.md §6).

**2. Roadmaps.** Python lists date cells (`d1`…, date labels as in deck-parser.md §7) and text lines (`t1`…, every
other non-empty cell). The model returns pairs (line id, date id) with a category: `launch`, `feature`, `expansion`,
`partnership`, `hiring`, `break_even` or `other`. Python maps `hiring` to people, `break_even` to ebitda and the rest
to product. A line has at most one pair, and a date may serve several lines. The period is Python's, rebuilt from the
date cell. A milestone has no value, so it is never Verified (as today).

**3. Text and reply.** The structure text stays as it is (`r<row>c<col>: <text>`, with spans). Below it comes the
line `items:`, then one line per item, e.g. `i3 r3c2#2 "(30K)" 30000 or -30000 h r3c1 r1c2`. A roadmap lists
`d1 r2c1` and `t1 r1c1`. The reply is `{"type", "labels": [...], "pairs": [...]}`. Each label holds exactly:
- `item` (a listed id);
- `metric`: `CLAIM_METRICS`, `use_of_funds`, `other`, or `not_a_metric` (page numbers, years, footnote marks);
- `period` (as today, or null);
- `unit` and `unit_other` (as today);
- `actual_or_forecast`.

The reply has no value, no cell id and no flag. Each listed id is labelled exactly once. An unknown, duplicate or
missing id, a pair that is not one listed line and one listed date, or labels on a roadmap (pairs on a table) is a
schema violation: one reask, then "Not read by AI". Tie-breaks in the prompt: hours and time figures → `product`
unless a user count is named; "% of marketplace" and market share → `market`; commission and take rate → `sales`.

**4. Verifier.** Values and cells are Python's own, so matching a value against a cited cell is deleted. What is left:
- Period: rebuilt from the item's lowest period header (with the year cell above it) or from its own cell
  (deck-parser.md §2). The rebuilt period replaces the model's, and a difference counts as "period corrected", as
  today. A model period with nothing to rebuild from, or a header period Python cannot rebuild, makes the item an AI
  suggestion ("period not rebuilt"). A null period matches when no header holds a period.
- Separator and sign: `dot_reading` and `bracket_reading` are recorded with the default. Both readings come from
  the item's cell, so the item can be Verified.
- Flags: Python computes `total_mismatch` and `growth_mismatch` over the Verified items, with today's rules
  (`verify._flag_reproduced`). A flag no longer makes an item unverified.
- `not_a_metric` items are dropped and counted, and `other` items are never Verified.

Python joins each label to its item, so a checked item has today's fields (`value_cell` = its cell) plus its id and
position. The approval list, the labels and `STRUCTURE_UNMATCHED` are unchanged.

**5. Storage, prompt and cache.** `llm_structures` stores the reply and the item list without raw text (id, cell,
position, value, alternative, header ids). Every label then resolves to a value with its cell reference (rule 17), and
no deck text is stored. The prompt becomes v3 and the release r6 (as with r5, narrative keys move once). The key
formula stays; the new schema hash and the item list move every key. The 3,000-token cap counts the item list.
`reverify_audit` skips readings stored under v2, and their rows keep their labels.

**6. Agreement.** Agreement per type = items with the same metric and period in every pass ÷ items Python listed,
over structures read in every pass. The period is compared as the verifier keeps it (start and end dates), and
`not_a_metric` counts as a metric. The cell and the item count are fixed by code and are not compared. The ≥95%
target applies to this figure, over tables, hiring tables and KPI panels. Roadmaps are reported apart: "roadmap
lines: N, same pair and category in every pass: M".

**7. scripts/consistency_run.py.**
- `_normalised_key` = (item id, metric, kept period range). The old-method column = (item id, metric, period as
  written, unit, actual_or_forecast).
- `FIELDS` = metric, period, unit, actual_or_forecast. `REASONS` = period not rebuilt, metric invalid, other ("value
  not in cell" and "lowest-header rule" are deleted).
- New counts per type: `not_a_metric`, `other`, ambiguous readings, and flags raised.
- Diagnostic columns: deck, page, type, item id, cell#position, cell text, Python's value (and alternative), reason,
  then per pass the model's metric, period, unit and actual_or_forecast and the verifier's result.
- `FakeAdapter` replays the replies in the new format.

**8. Replaced in llm-structure-reading.md.**
- §1 item fields and output → §3 here;
- §2 value and period matching against cited cells and model flags → §4 here (its normalisation moves into §1);
- §5 cited-cell check → §3 here;
- §9 `llm_structures` content → §5 here;
- §11 agreement, differing fields, reasons, diagnostic and roadmap line → §6–7 here.

Unchanged: §3, §4, §6, §7 and §8.

**9. Tests.** Each is first shown failing on a deliberate violation:
- enumeration: several figures per cell, dates left out, defaults, stable ids;
- reply: unknown, duplicate or missing ids, and bad pairs;
- the verifier: the period from headers or its own cell, corrections, flags;
- boundary: an item line passes only in its format, with raw text that is a figure inside its cell line (else reason
  `bad_item_line`), and no raw text reaches `llm_structures` or a log.

**Open questions.**
1. Scope. Proposed: charts, unit-economics and use-of-funds tables take the table path (they are cell grids);
   column mapping keeps today's reply and schema (it only pre-fills a screen the analyst confirms). Until decided,
   those types keep today's schema, chosen by the type Python sent.
2. Defaults. Proposed: `2.500` → thousands, unless the figure has its own k/m/bn suffix (`1.250M` → 1.25m); a
   bracketed number after text → positive (`Telegram(30K)`), so `Net loss (1,200)` is left to the analyst.
3. A roadmap line with a figure (`55,000 users`, buffer p6). Proposed: it is also a figure item, dated by its pair.
   The alternative is a milestone only.
4. `other` items. Proposed: they are listed as type Other and can be approved only after the type is edited to a
   `CLAIM_TYPES` value. The alternative is to count them without listing them.
5. The roadmap categories and their mapping.

**Files.** New: `backend/app/structures/items.py`. Changed: `backend/app/structures/{__init__,verify,redact}.py`,
`backend/app/llm/{schemas,gateway}.py`, `backend/app/llm/prompts/{structure_reading.md,RELEASE.md}`,
`frontend/src/components/DeckPanel.jsx` and `frontend/src/lib/deckClaims.js` (alternative reading, Other type),
`backend/tests/test_structure_{verifier,reading}.py`, `backend/tests/test_gateway_data_boundary.py`,
`backend/tests/fixtures/structure_replies/*.json`, `scripts/consistency_run.py`, and
`docs/specs/llm-structure-reading.md` (a pointer here at each replaced section).
