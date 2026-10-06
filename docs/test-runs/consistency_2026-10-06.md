# Consistency run 2026-10-06

Live API. Decks: 10. Passes: 3. Model: claude-sonnet-5-5. Prompt: structure_reading v4. Method: docs/specs/structure-labelling.md sections 6 and 7.

Agreement 88.4% (target 95.0%: missed; old method 67.3%); verified 77.4% (financial 79.8%, roadmap 60.6%), unverified 22.6%, 0 not read; roadmap lines: 76, same pair and category in every pass: 33, date rebuilt from cell: 27; 21 periods corrected; cache hits pass 2 100.0%, pass 3 100.0%; cost $0.9385.

## Agreement per structure type

Items with the same metric and period in every pass / items Python listed, over structures read in every pass. The period is the one the verifier keeps, compared as its start and end dates; not_a_metric counts as a metric. The old method compares metric, period as written, unit and actual or forecast.

| Type | Agreement | Old method |
|---|---:|---:|
| hiring_table | 100.0% | 100.0% |
| kpi_panel | 88.2% | 53.9% |
| roadmap | 72.2% | 94.4% |
| table | 100.0% | 100.0% |
| all | 88.4% | 67.3% |

## Where passes disagree

Structures read in every pass whose labels differ in any field, as the model wrote it (the old method). Labels are lined up by item id; cells and the item count are fixed by code. Each count is a number of structures.

| Type | Structures | Disagreeing | metric | period | unit | actual_or_forecast |
|---|---:|---:|---:|---:|---:|---:|
| hiring_table | 1 | 0 | 0 | 0 | 0 | 0 |
| kpi_panel | 22 | 10 | 4 | 1 | 2 | 7 |
| roadmap | 3 | 1 | 1 | 0 | 0 | 0 |
| table | 1 | 0 | 0 | 0 | 0 | 0 |

| Deck | Page | Type | Fields that differ | Same after normalisation |
|---|---:|---|---|---|
| 01-front-b.pptx | 12 | kpi_panel | metric, unit, actual_or_forecast | no |
| 01-front-b.pptx | 15 | kpi_panel | actual_or_forecast | yes |
| 02-moz.pdf | 20 | kpi_panel | metric | no |
| 02-moz.pdf | 21 | kpi_panel | metric, actual_or_forecast | no |
| 02-moz.pdf | 23 | kpi_panel | actual_or_forecast | yes |
| 03-buffer.pptx | 6 | roadmap | metric | no |
| 04-clevergig.docx | 7 | kpi_panel | metric | no |
| 05-zero2hero.pdf | 11 | kpi_panel | period, actual_or_forecast | yes |
| 05-zero2hero.pdf | 17 | kpi_panel | actual_or_forecast | yes |
| 09-genesisai-2024.pdf | 5 | kpi_panel | actual_or_forecast | yes |
| 10-tea.pdf | 9 | kpi_panel | unit | yes |

## Verifier

Rates over the labelled items (not_a_metric dropped, roadmap milestones left out), then the match rate apart for the financial items (outside roadmaps) and the roadmap figures. A roadmap line's date is rebuilt from cell when Python rebuilds its period from its own period cells, whatever the pair says.

- Match rate: 77.4%
- Match rate, financial (outside roadmaps): 79.8%
- Match rate, roadmap (figures in roadmaps, milestones left out): 60.6%
- Unverified rate: 22.6%
- Periods corrected: 21
- Roadmap lines: 76, same pair and category in every pass: 33, date rebuilt from cell: 27
- Not read: 0; model reads: 81

## Unverified items: reasons

One reason per unverified item: period not rebuilt (a model period with nothing to rebuild from, a header period Python cannot rebuild, or a pair date the item's own cells do not rebuild), metric invalid, other (type Other). Counts are over all passes. Metric invalid stays 0 on a live run: the gateway rejects a reply with such a metric whole, and the structure counts as not read.

| Type | period not rebuilt | metric invalid | other | Unverified |
|---|---:|---:|---:|---:|
| kpi_panel | 9 | 0 | 38 | 47 |
| roadmap | 0 | 0 | 13 | 13 |
| all | 9 | 0 | 51 | 60 |

| Deck | Page | Type | Item | Cell | Reason | Passes |
|---|---:|---|---|---|---|---:|
| 01-front-b.pptx | 12 | kpi_panel | i6 | r3c3#1 | period not rebuilt | 3 |
| 01-front-b.pptx | 12 | kpi_panel | i7 | r3c3#2 | period not rebuilt | 3 |
| 01-front-b.pptx | 12 | kpi_panel | i8 | r3c3#3 | period not rebuilt | 3 |
| 01-front-b.pptx | 12 | kpi_panel | i9 | r4c3#1 | other (type Other) | 3 |
| 01-front-b.pptx | 12 | kpi_panel | i10 | r4c3#2 | other (type Other) | 3 |
| 01-front-b.pptx | 12 | kpi_panel | i11 | r4c3#3 | other (type Other) | 3 |
| 01-front-b.pptx | 15 | kpi_panel | i3 | r5c2#1 | other (type Other) | 3 |
| 01-front-b.pptx | 15 | kpi_panel | i4 | r5c3#1 | other (type Other) | 3 |
| 01-front-b.pptx | 15 | kpi_panel | i5 | r6c5#1 | other (type Other) | 3 |
| 02-moz.pdf | 2 | roadmap | i2 | r4c4#1 | other (type Other) | 3 |
| 02-moz.pdf | 2 | roadmap | i3 | r4c4#2 | other (type Other) | 3 |
| 02-moz.pdf | 2 | roadmap | i4 | r5c4#1 | other (type Other) | 3 |
| 02-moz.pdf | 2 | roadmap | i6 | r11c3#1 | other (type Other) | 3 |
| 02-moz.pdf | 20 | kpi_panel | i5 | r4c2#1 | other (type Other) | 2 |
| 02-moz.pdf | 20 | kpi_panel | i6 | r5c2#1 | other (type Other) | 3 |
| 02-moz.pdf | 21 | kpi_panel | i1 | r1c2#1 | other (type Other) | 3 |
| 02-moz.pdf | 32 | kpi_panel | i1 | r2c1#1 | other (type Other) | 3 |
| 02-moz.pdf | 20 | kpi_panel | i7 | r6c2#1 | other (type Other) | 2 |
| 03-buffer.pptx | 6 | roadmap | i3 | r7c1#1 | other (type Other) | 1 |
| 04-clevergig.docx | 7 | kpi_panel | i1 | r1c1#1 | other (type Other) | 1 |
| 04-clevergig.docx | 7 | kpi_panel | i3 | r3c1#1 | other (type Other) | 1 |
| 04-clevergig.docx | 7 | kpi_panel | i5 | r5c1#1 | other (type Other) | 1 |
| 04-clevergig.docx | 7 | kpi_panel | i7 | r7c1#1 | other (type Other) | 1 |
| 08-genesisai-2021.pdf | 13 | kpi_panel | i1 | r1c1#1 | other (type Other) | 3 |

## Labels per type

Over all passes: labels not_a_metric (dropped) and other (type Other, never Verified), items Python listed with two readings, and Verified items with a flag Python computed.

| Type | not_a_metric | other | ambiguous readings | flags |
|---|---:|---:|---:|---:|
| hiring_table | 0 | 0 | 0 | 0 |
| kpi_panel | 154 | 38 | 24 | 0 |
| roadmap | 21 | 13 | 0 | 0 |
| table | 0 | 0 | 0 | 0 |

## Cache hit rate

| Pass | Hit rate |
|---|---:|
| 2 | 100.0% |
| 3 | 100.0% |

## Tokens and cost per deck

| Deck | Structures | Input tokens | Output tokens | Cost USD |
|---|---:|---:|---:|---:|
| 01-front-b.pptx | 6 | 63,912 | 7,549 | 0.2033 |
| 02-moz.pdf | 6 | 68,163 | 11,355 | 0.2499 |
| 03-buffer.pptx | 1 | 11,289 | 3,160 | 0.0542 |
| 04-clevergig.docx | 1 | 10,680 | 1,097 | 0.0323 |
| 05-zero2hero.pdf | 5 | 55,572 | 6,836 | 0.1795 |
| 06-uber.pdf | 0 | 0 | 0 | 0.0000 |
| 07-equals-seed.docx | 0 | 0 | 0 | 0.0000 |
| 08-genesisai-2021.pdf | 2 | 20,133 | 609 | 0.0464 |
| 09-genesisai-2024.pdf | 3 | 30,783 | 1,797 | 0.0795 |
| 10-tea.pdf | 3 | 33,294 | 2,678 | 0.0934 |
| all | 27 | 293,826 | 35,081 | 0.9385 |

## Tokens per call

By the provider's token counter, which bills nothing. The fixed prompt is a call with an empty structure text; its parts are each counted with the empty message, less the empty message alone. The gateway caps the structure text plus its item list at 4,000 tokens.

- Fixed prompt: 3,286 (system prompt 2,093, output schema 1,173, empty message 20)
- Structure text and item list, average of 27 structures: 308.9 against the gateway's 4,000-token cap
- Billed input per model read: 3,627.5
