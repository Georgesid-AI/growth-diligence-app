# Consistency run 2026-10-07

Live API. Decks: 10. Passes: 3. Model: claude-sonnet-5-5. Prompt: structure_reading v6. Method: docs/specs/structure-labelling.md sections 6 and 7.

Agreement 97.0% (target 95.0%: met; old method 88.0%); verified 78.2% (financial 80.3%, roadmap 63.6%), unverified 21.8%, 2 not read; roadmap lines: 42, dated by position: 42, same pair and category in every pass: 38, same date and category: 38, date rebuilt from cell: 24; 33 periods corrected; cache hits pass 2 100.0%, pass 3 100.0%; cost $1.0375.

## Agreement per structure type

Items with the same metric and period in every pass / items Python listed, over structures read in every pass. The period is the one the verifier keeps, compared as its start and end dates; not_a_metric counts as a metric. The old method compares metric, period as written, unit and actual or forecast.

| Type | Agreement | Old method |
|---|---:|---:|
| hiring_table | 100.0% | 0.0% |
| kpi_panel | 95.5% | 85.2% |
| roadmap | 100.0% | 100.0% |
| table | 100.0% | 100.0% |
| all | 97.0% | 88.0% |

## Where passes disagree

Structures read in every pass whose labels differ in any field, as the model wrote it (the old method). Labels are lined up by item id; cells and the item count are fixed by code. Each count is a number of structures.

| Type | Structures | Disagreeing | metric | period | unit | actual_or_forecast |
|---|---:|---:|---:|---:|---:|---:|
| hiring_table | 1 | 1 | 0 | 0 | 0 | 1 |
| kpi_panel | 20 | 3 | 1 | 0 | 2 | 2 |
| roadmap | 3 | 0 | 0 | 0 | 0 | 0 |
| table | 1 | 0 | 0 | 0 | 0 | 0 |

| Deck | Page | Type | Fields that differ | Same after normalisation |
|---|---:|---|---|---|
| 01-front-b.pptx | 15 | kpi_panel | actual_or_forecast | yes |
| 02-moz.pdf | 23 | kpi_panel | metric, unit, actual_or_forecast | no |
| 04-clevergig.docx | 7 | kpi_panel | unit | yes |
| 05-zero2hero.pdf | 22 | hiring_table | actual_or_forecast | yes |

## Verifier

Rates over the labelled items (not_a_metric dropped, roadmap milestones left out), then the match rate apart for the financial items (outside roadmaps) and the roadmap figures. A roadmap line is dated by position when Python gives it a date by its place (its date line, or the date box beside it); same pair compares the model's pairs, same date the milestone the analyst sees (paired or not, the date Python keeps, the category). A roadmap line's date is rebuilt from cell when Python rebuilds its period from its own period cells, whatever the pair says.

- Match rate: 78.2%
- Match rate, financial (outside roadmaps): 80.3%
- Match rate, roadmap (figures in roadmaps, milestones left out): 63.6%
- Unverified rate: 21.8%
- Periods corrected: 33
- Roadmap lines: 42, dated by position: 42, same pair and category in every pass: 38, same date and category: 38, date rebuilt from cell: 24
- Not read: 2; model reads: 78

## Unverified items: reasons

One reason per unverified item: period not rebuilt (a model period with nothing to rebuild from, a header period Python cannot rebuild, or a pair date the item's own cells do not rebuild), metric invalid, other (type Other). Counts are over all passes. Metric invalid stays 0 on a live run: the gateway rejects a reply with such a metric whole, and the structure counts as not read.

| Type | period not rebuilt | metric invalid | other | Unverified |
|---|---:|---:|---:|---:|
| kpi_panel | 18 | 0 | 27 | 45 |
| roadmap | 0 | 0 | 12 | 12 |
| all | 18 | 0 | 39 | 57 |

| Deck | Page | Type | Item | Cell | Reason | Passes |
|---|---:|---|---|---|---|---:|
| 01-front-b.pptx | 12 | kpi_panel | i6 | r3c3#1 | period not rebuilt | 3 |
| 01-front-b.pptx | 12 | kpi_panel | i7 | r3c3#2 | period not rebuilt | 3 |
| 01-front-b.pptx | 12 | kpi_panel | i8 | r3c3#3 | period not rebuilt | 3 |
| 01-front-b.pptx | 12 | kpi_panel | i9 | r4c3#1 | period not rebuilt | 3 |
| 01-front-b.pptx | 12 | kpi_panel | i10 | r4c3#2 | period not rebuilt | 3 |
| 01-front-b.pptx | 12 | kpi_panel | i11 | r4c3#3 | period not rebuilt | 3 |
| 02-moz.pdf | 2 | roadmap | i2 | r1c4#1 | other (type Other) | 3 |
| 02-moz.pdf | 2 | roadmap | i3 | r1c4#2 | other (type Other) | 3 |
| 02-moz.pdf | 2 | roadmap | i4 | r1c4#3 | other (type Other) | 3 |
| 02-moz.pdf | 2 | roadmap | i6 | r4c3#1 | other (type Other) | 3 |
| 02-moz.pdf | 21 | kpi_panel | i3 | r3c2#1 | other (type Other) | 3 |
| 02-moz.pdf | 21 | kpi_panel | i4 | r4c2#1 | other (type Other) | 3 |
| 02-moz.pdf | 32 | kpi_panel | i1 | r2c1#1 | other (type Other) | 3 |
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
| kpi_panel | 119 | 27 | 24 | 0 |
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
| 01-front-b.pptx | 5 | 71,496 | 5,754 | 0.2005 |
| 02-moz.pdf | 6 | 78,708 | 8,765 | 0.2451 |
| 03-buffer.pptx | 1 | 13,341 | 3,197 | 0.0587 |
| 04-clevergig.docx | 1 | 12,732 | 1,101 | 0.0365 |
| 05-zero2hero.pdf | 5 | 65,832 | 6,864 | 0.2003 |
| 06-uber.pdf | 0 | 0 | 0 | 0.0000 |
| 07-equals-seed.docx | 0 | 0 | 0 | 0.0000 |
| 08-genesisai-2021.pdf | 2 | 24,237 | 609 | 0.0546 |
| 09-genesisai-2024.pdf | 3 | 36,939 | 1,797 | 0.0918 |
| 10-tea.pdf | 3 | 39,177 | 7,171 | 0.1501 |
| all | 26 | 342,462 | 35,258 | 1.0375 |

## Tokens per call

By the provider's token counter, which bills nothing. The fixed prompt is a call with an empty structure text; its parts are each counted with the empty message, less the empty message alone. The gateway caps the structure text plus its item list at 4,000 tokens.

- Fixed prompt: 3,970 (system prompt 2,704, output schema 1,246, empty message 20)
- Structure text and item list, average of 26 structures: 285.5 against the gateway's 4,000-token cap
- Billed input per model read: 4,390.5
