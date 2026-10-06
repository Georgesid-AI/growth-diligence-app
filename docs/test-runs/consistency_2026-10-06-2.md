# Consistency run 2026-10-06

Live API. Decks: 10. Passes: 3. Model: claude-sonnet-5-5. Prompt: structure_reading v5. Method: docs/specs/structure-labelling.md sections 6 and 7.

Agreement 97.3% (target 95.0%: met; old method 87.8%); verified 76.9% (financial 78.8%, roadmap 63.6%), unverified 23.1%, 0 not read; roadmap lines: 45, dated by position: 44, same pair and category in every pass: 32, same date and category: 37, date rebuilt from cell: 25; 33 periods corrected; cache hits pass 2 100.0%, pass 3 100.0%; cost $1.0289.

## Agreement per structure type

Items with the same metric and period in every pass / items Python listed, over structures read in every pass. The period is the one the verifier keeps, compared as its start and end dates; not_a_metric counts as a metric. The old method compares metric, period as written, unit and actual or forecast.

| Type | Agreement | Old method |
|---|---:|---:|
| hiring_table | 100.0% | 100.0% |
| kpi_panel | 96.1% | 84.3% |
| roadmap | 100.0% | 88.9% |
| table | 100.0% | 100.0% |
| all | 97.3% | 87.8% |

## Where passes disagree

Structures read in every pass whose labels differ in any field, as the model wrote it (the old method). Labels are lined up by item id; cells and the item count are fixed by code. Each count is a number of structures.

| Type | Structures | Disagreeing | metric | period | unit | actual_or_forecast |
|---|---:|---:|---:|---:|---:|---:|
| hiring_table | 1 | 0 | 0 | 0 | 0 | 0 |
| kpi_panel | 22 | 3 | 2 | 0 | 0 | 3 |
| roadmap | 3 | 1 | 0 | 0 | 0 | 1 |
| table | 1 | 0 | 0 | 0 | 0 | 0 |

| Deck | Page | Type | Fields that differ | Same after normalisation |
|---|---:|---|---|---|
| 01-front-b.pptx | 12 | kpi_panel | actual_or_forecast | yes |
| 01-front-b.pptx | 14 | kpi_panel | metric, actual_or_forecast | no |
| 02-moz.pdf | 2 | roadmap | actual_or_forecast | yes |
| 02-moz.pdf | 21 | kpi_panel | metric, actual_or_forecast | no |

## Verifier

Rates over the labelled items (not_a_metric dropped, roadmap milestones left out), then the match rate apart for the financial items (outside roadmaps) and the roadmap figures. A roadmap line is dated by position when Python gives it a date by its place (its date line, or the date box beside it); same pair compares the model's pairs, same date the milestone the analyst sees (paired or not, the date Python keeps, the category). A roadmap line's date is rebuilt from cell when Python rebuilds its period from its own period cells, whatever the pair says.

- Match rate: 76.9%
- Match rate, financial (outside roadmaps): 78.8%
- Match rate, roadmap (figures in roadmaps, milestones left out): 63.6%
- Unverified rate: 23.1%
- Periods corrected: 33
- Roadmap lines: 45, dated by position: 44, same pair and category in every pass: 32, same date and category: 37, date rebuilt from cell: 25
- Not read: 0; model reads: 81

## Unverified items: reasons

One reason per unverified item: period not rebuilt (a model period with nothing to rebuild from, a header period Python cannot rebuild, or a pair date the item's own cells do not rebuild), metric invalid, other (type Other). Counts are over all passes. Metric invalid stays 0 on a live run: the gateway rejects a reply with such a metric whole, and the structure counts as not read.

| Type | period not rebuilt | metric invalid | other | Unverified |
|---|---:|---:|---:|---:|
| kpi_panel | 21 | 0 | 28 | 49 |
| roadmap | 0 | 0 | 12 | 12 |
| all | 21 | 0 | 40 | 61 |

| Deck | Page | Type | Item | Cell | Reason | Passes |
|---|---:|---|---|---|---|---:|
| 01-front-b.pptx | 12 | kpi_panel | i6 | r3c3#1 | period not rebuilt | 3 |
| 01-front-b.pptx | 12 | kpi_panel | i7 | r3c3#2 | period not rebuilt | 3 |
| 01-front-b.pptx | 12 | kpi_panel | i8 | r3c3#3 | period not rebuilt | 3 |
| 01-front-b.pptx | 12 | kpi_panel | i9 | r4c3#1 | period not rebuilt | 3 |
| 01-front-b.pptx | 12 | kpi_panel | i10 | r4c3#2 | period not rebuilt | 3 |
| 01-front-b.pptx | 12 | kpi_panel | i11 | r4c3#3 | period not rebuilt | 3 |
| 01-front-b.pptx | 14 | kpi_panel | i1 | r1c1#1 | other (type Other) | 1 |
| 01-front-b.pptx | 14 | kpi_panel | i2 | r1c3#1 | other (type Other) | 1 |
| 01-front-b.pptx | 14 | kpi_panel | i3 | r2c5#1 | other (type Other) | 1 |
| 02-moz.pdf | 2 | roadmap | i2 | r1c4#1 | other (type Other) | 3 |
| 02-moz.pdf | 2 | roadmap | i3 | r1c4#2 | other (type Other) | 3 |
| 02-moz.pdf | 2 | roadmap | i4 | r1c4#3 | other (type Other) | 3 |
| 02-moz.pdf | 2 | roadmap | i6 | r4c3#1 | other (type Other) | 3 |
| 02-moz.pdf | 20 | kpi_panel | i3 | r2c2#1 | period not rebuilt | 3 |
| 02-moz.pdf | 21 | kpi_panel | i3 | r3c2#1 | other (type Other) | 3 |
| 02-moz.pdf | 21 | kpi_panel | i4 | r4c2#1 | other (type Other) | 3 |
| 02-moz.pdf | 21 | kpi_panel | i1 | r1c2#1 | other (type Other) | 1 |
| 05-zero2hero.pdf | 17 | kpi_panel | i1 | r1c1#1 | other (type Other) | 3 |
| 05-zero2hero.pdf | 17 | kpi_panel | i2 | r2c1#1 | other (type Other) | 3 |
| 05-zero2hero.pdf | 17 | kpi_panel | i3 | r3c1#1 | other (type Other) | 3 |
| 05-zero2hero.pdf | 17 | kpi_panel | i4 | r4c1#1 | other (type Other) | 3 |
| 05-zero2hero.pdf | 17 | kpi_panel | i5 | r6c1#1 | other (type Other) | 3 |
| 05-zero2hero.pdf | 17 | kpi_panel | i6 | r7c1#1 | other (type Other) | 3 |

## Labels per type

Over all passes: labels not_a_metric (dropped) and other (type Other, never Verified), items Python listed with two readings, and Verified items with a flag Python computed.

| Type | not_a_metric | other | ambiguous readings | flags |
|---|---:|---:|---:|---:|
| hiring_table | 0 | 0 | 0 | 0 |
| kpi_panel | 156 | 28 | 24 | 0 |
| roadmap | 21 | 12 | 0 | 0 |
| table | 0 | 0 | 0 | 0 |

## Cache hit rate

| Pass | Hit rate |
|---|---:|
| 2 | 100.0% |
| 3 | 100.0% |

## Tokens and cost per deck

| Deck | Structures | Input tokens | Output tokens | Cost USD |
|---|---:|---:|---:|---:|
| 01-front-b.pptx | 6 | 74,766 | 9,109 | 0.2406 |
| 02-moz.pdf | 6 | 77,250 | 8,863 | 0.2431 |
| 03-buffer.pptx | 1 | 13,098 | 1,482 | 0.0410 |
| 04-clevergig.docx | 1 | 12,489 | 1,101 | 0.0360 |
| 05-zero2hero.pdf | 5 | 64,617 | 6,831 | 0.1975 |
| 06-uber.pdf | 0 | 0 | 0 | 0.0000 |
| 07-equals-seed.docx | 0 | 0 | 0 | 0.0000 |
| 08-genesisai-2021.pdf | 2 | 23,751 | 609 | 0.0536 |
| 09-genesisai-2024.pdf | 3 | 36,210 | 1,797 | 0.0904 |
| 10-tea.pdf | 3 | 38,622 | 4,936 | 0.1266 |
| all | 27 | 340,803 | 34,728 | 1.0289 |

## Tokens per call

By the provider's token counter, which bills nothing. The fixed prompt is a call with an empty structure text; its parts are each counted with the empty message, less the empty message alone. The gateway caps the structure text plus its item list at 4,000 tokens.

- Fixed prompt: 3,889 (system prompt 2,623, output schema 1,246, empty message 20)
- Structure text and item list, average of 27 structures: 288.2 against the gateway's 4,000-token cap
- Billed input per model read: 4,207.4
