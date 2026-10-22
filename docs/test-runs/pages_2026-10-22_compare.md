# Compare: rules read (A) against the page read (B), recorded replies of pages_2026-10-22

scripts/compare_pipelines.py --recorded: B replays the model's recorded replies of each pass through the gateway and page_check; A is the rules read (claims.detect_candidates). Recall and precision against the answer file (tests/fixtures/decks/expected_claims.json). Dropped: claims page_check drops before any check (an axis tick, a line the rules read drops, a cell not on the page).

## Per deck and pass

| Deck | Pass | Pages | Sent | A rows | A recall | A precision | B rows | Matched | Unmatched | Dropped | B recall | B precision | Only A | Only B |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| 01-front-b.pptx | 1 | 23 | 9 | 46 | 94% | 33% | 11 | 2 | 9 | 0 | 50% | 82% | 36 | 0 |
| 01-front-b.pptx | 2 | 23 | 9 | 46 | 94% | 33% | 11 | 2 | 9 | 0 | 50% | 82% | 36 | 0 |
| 01-front-b.pptx | 3 | 23 | 9 | 46 | 94% | 33% | 17 | 8 | 9 | 2 | 67% | 71% | 31 | 0 |
| 02-moz.pdf | 1 | 36 | 15 | 43 | 96% | 49% | 34 | 14 | 20 | 1 | 86% | 53% | 16 | 7 |
| 02-moz.pdf | 2 | 36 | 15 | 43 | 96% | 49% | 33 | 14 | 19 | 1 | 86% | 55% | 15 | 5 |
| 02-moz.pdf | 3 | 36 | 15 | 43 | 96% | 49% | 37 | 16 | 21 | 1 | 86% | 49% | 16 | 10 |
| 03-buffer.pptx | 1 | 12 | 6 | 24 | 100% | 83% | 21 | 15 | 6 | 1 | 85% | 81% | 5 | 2 |
| 03-buffer.pptx | 2 | 12 | 6 | 24 | 100% | 83% | 21 | 15 | 6 | 1 | 85% | 81% | 5 | 2 |
| 03-buffer.pptx | 3 | 12 | 6 | 24 | 100% | 83% | 20 | 15 | 5 | 1 | 85% | 85% | 5 | 1 |
| 04-clevergig.docx | 1 | 13 | 5 | 21 | 93% | 62% | 17 | 10 | 7 | 1 | 86% | 71% | 8 | 5 |
| 04-clevergig.docx | 2 | 13 | 5 | 21 | 93% | 62% | 20 | 12 | 8 | 1 | 100% | 70% | 5 | 5 |
| 04-clevergig.docx | 3 | 13 | 5 | 21 | 93% | 62% | 17 | 10 | 7 | 1 | 86% | 71% | 8 | 5 |
| 05-zero2hero.pdf | 1 | 22 | 6 | 44 | 94% | 75% | 6 | 0 | 6 | 0 | 0% | 0% | 39 | 1 |
| 05-zero2hero.pdf | 2 | 22 | 6 | 44 | 94% | 75% | 6 | 0 | 6 | 0 | 0% | 0% | 39 | 1 |
| 05-zero2hero.pdf | 3 | 22 | 6 | 44 | 94% | 75% | 6 | 0 | 6 | 0 | 0% | 0% | 39 | 1 |
| 06-uber.pdf | 1 | 25 | 15 | 28 | 100% | 14% | 7 | 6 | 1 | 1 | 75% | 43% | 21 | 1 |
| 06-uber.pdf | 2 | 25 | 15 | 28 | 100% | 14% | 9 | 8 | 1 | 1 | 75% | 33% | 19 | 1 |
| 06-uber.pdf | 3 | 25 | 15 | 28 | 100% | 14% | 7 | 6 | 1 | 1 | 75% | 43% | 21 | 1 |
| 07-equals-seed.docx | 1 | 10 | 3 | 3 | 100% | 33% | 1 | 1 | 0 | 1 | 100% | 100% | 2 | 0 |
| 07-equals-seed.docx | 2 | 10 | 3 | 3 | 100% | 33% | 1 | 1 | 0 | 1 | 100% | 100% | 2 | 0 |
| 07-equals-seed.docx | 3 | 10 | 3 | 3 | 100% | 33% | 1 | 1 | 0 | 1 | 100% | 100% | 2 | 0 |
| 08-genesisai-2021.pdf | 1 | 14 | 4 | 0 | - | - | 4 | 1 | 3 | 1 | - | 0% | 0 | 4 |
| 08-genesisai-2021.pdf | 2 | 14 | 4 | 0 | - | - | 4 | 0 | 4 | 1 | - | 0% | 0 | 4 |
| 08-genesisai-2021.pdf | 3 | 14 | 4 | 0 | - | - | 4 | 1 | 3 | 1 | - | 0% | 0 | 4 |
| 09-genesisai-2024.pdf | 1 | 14 | 5 | 7 | 100% | 29% | 6 | 0 | 6 | 1 | 100% | 33% | 3 | 2 |
| 09-genesisai-2024.pdf | 2 | 14 | 5 | 7 | 100% | 29% | 6 | 2 | 4 | 1 | 100% | 33% | 3 | 2 |
| 09-genesisai-2024.pdf | 3 | 14 | 5 | 7 | 100% | 29% | 6 | 1 | 5 | 1 | 100% | 33% | 3 | 2 |
| 10-tea.pdf | 1 | 14 | 4 | 16 | 100% | 44% | 0 | 0 | 0 | 5 | 0% | - | 16 | 0 |
| 10-tea.pdf | 2 | 14 | 4 | 16 | 100% | 44% | 0 | 0 | 0 | 5 | 0% | - | 16 | 0 |
| 10-tea.pdf | 3 | 14 | 4 | 16 | 100% | 44% | 0 | 0 | 0 | 5 | 0% | - | 16 | 0 |
| all | 1 | | | 232 | | | 107 | 49 | 58 | 12 | 51% | | | |
| all | 2 | | | 232 | | | 111 | 54 | 57 | 12 | 52% | | | |
| all | 3 | | | 232 | | | 115 | 58 | 57 | 14 | 53% | | | |

## Agreement across passes

Claims (value cell, metric, period) found in every pass / found in any pass, from the recorded replies. Disagreeing claims by kind: metric (the cell is claimed in every pass, with another metric in some), period (cell and metric in every pass, another period in some), presence (the cell is claimed in some passes only). Pages differ: a pass read pages another did not.

| Deck | Agreed | Union | Agreement | Metric | Period | Presence | Pages differ |
|---|---:|---:|---:|---:|---:|---:|---|
| 01-front-b.pptx | 11 | 19 | 57.9% | 0 | 0 | 8 | yes |
| 02-moz.pdf | 30 | 43 | 69.8% | 5 | 0 | 8 | yes |
| 03-buffer.pptx | 20 | 23 | 87.0% | 2 | 0 | 1 | yes |
| 04-clevergig.docx | 13 | 26 | 50.0% | 6 | 6 | 1 | no |
| 05-zero2hero.pdf | 6 | 6 | 100.0% | 0 | 0 | 0 | no |
| 06-uber.pdf | 8 | 9 | 88.9% | 0 | 0 | 1 | yes |
| 07-equals-seed.docx | 2 | 2 | 100.0% | 0 | 0 | 0 | no |
| 08-genesisai-2021.pdf | 3 | 7 | 42.9% | 4 | 0 | 0 | no |
| 09-genesisai-2024.pdf | 4 | 10 | 40.0% | 2 | 4 | 0 | no |
| 10-tea.pdf | 5 | 5 | 100.0% | 0 | 0 | 0 | no |
| all | | | 68.0% | | | | |

## Claims by cause

Over all passes. A cause names the checks that failed (value, unit, period), the metric other (never matched by design), no value (a milestone), or why the claim was dropped.

| Cause | Claims | Share |
|---|---:|---:|
| matched | 161 | 43% |
| other | 101 | 27% |
| dropped: not_plan | 38 | 10% |
| period | 25 | 7% |
| period+other | 14 | 4% |
| value | 13 | 4% |
| unit+period | 9 | 2% |
| value+period | 4 | 1% |
| value+other | 3 | 1% |
| unit | 3 | 1% |

## Unmatched and dropped rows

One line per deck, page, cell, cause, metric and value; passes: in how many passes it appears.

| Cause | Deck | Page | Cell | Metric | Value | Passes |
|---|---|---:|---|---|---:|---:|
| other | 01-front-b.pptx | 13 | r7c1 | other | 3.9 | 3 |
| other | 01-front-b.pptx | 13 | r8c1 | other | 4.9 | 3 |
| other | 02-moz.pdf | 2 | r15c1 | other | 500000 | 1 |
| other | 02-moz.pdf | 3 | r5c1 | other | 1100000 | 1 |
| other | 02-moz.pdf | 9 | r5c1 | other | 5000000000 | 1 |
| other | 02-moz.pdf | 13 | r4c1 | other | 75 | 1 |
| other | 02-moz.pdf | 13 | r4c2 | other | 50 | 1 |
| other | 02-moz.pdf | 13 | r4c3 | other | 10 | 1 |
| other | 02-moz.pdf | 18 | r4c1 | other | 55 | 3 |
| other | 02-moz.pdf | 18 | r4c2 | other | 35 | 3 |
| other | 02-moz.pdf | 18 | r4c3 | other | 10 | 3 |
| other | 02-moz.pdf | 21 | r1c2 | other | 57 | 3 |
| other | 02-moz.pdf | 21 | r2c2 | other | 25 | 2 |
| other | 02-moz.pdf | 21 | r3c2 | other | 1250000 | 3 |
| other | 02-moz.pdf | 21 | r4c2 | other | 300000 | 3 |
| other | 02-moz.pdf | 23 | r1c2 | other | 20000000 | 3 |
| other | 02-moz.pdf | 23 | r2c2 | other | 6000000 | 3 |
| other | 02-moz.pdf | 23 | r3c2 | other | 13000000 | 3 |
| other | 03-buffer.pptx | 5 | r6c1 | other | 1500000 | 3 |
| other | 03-buffer.pptx | 6 | r8c1 | other | 50 | 3 |
| other | 03-buffer.pptx | 7 | r2c1 | other | 2 | 3 |
| other | 03-buffer.pptx | 7 | r3c1 | other | 5 | 3 |
| other | 03-buffer.pptx | 9 | r2c1 | other | 200 | 2 |
| other | 03-buffer.pptx | 10 | r2c1 | other | 6 | 3 |
| other | 04-clevergig.docx | 6 | r5c1 | other | 30 | 3 |
| other | 04-clevergig.docx | 7 | r11c1 | other | 305 | 2 |
| other | 04-clevergig.docx | 7 | r16c1 | other | 485 | 2 |
| other | 04-clevergig.docx | 7 | r6c1 | other | 185 | 2 |
| other | 04-clevergig.docx | 9 | r1c1 | other | 50000 | 1 |
| other | 05-zero2hero.pdf | 22 | r2c1 | other | 250000 | 3 |
| other | 05-zero2hero.pdf | 22 | r3c3 | other | 40 | 3 |
| other | 05-zero2hero.pdf | 22 | r4c3 | other | 20 | 3 |
| other | 05-zero2hero.pdf | 22 | r5c3 | other | 25 | 3 |
| other | 05-zero2hero.pdf | 22 | r6c3 | other | 10 | 3 |
| other | 05-zero2hero.pdf | 22 | r7c3 | other | 5 | 3 |
| other | 08-genesisai-2021.pdf | 8 | r3c1 | other | 300 | 1 |
| other | 08-genesisai-2021.pdf | 12 | r3c1 | other | 30 | 3 |
| other | 08-genesisai-2021.pdf | 13 | r3c1 | other | 25 | 3 |
| other | 08-genesisai-2021.pdf | 14 | r4c2 | other | 30 | 3 |
| other | 09-genesisai-2024.pdf | 12 | r3c1 | other | 70 | 2 |
| other | 09-genesisai-2024.pdf | 13 | r3c1 | other | 30 | 3 |
| dropped: not_plan | 01-front-b.pptx | 15 | r3c1 | other | 3.1 | 1 |
| dropped: not_plan | 01-front-b.pptx | 15 | r3c2 | other | 10.0 | 1 |
| dropped: not_plan | 02-moz.pdf | 2 | r3c3 | other | 1100000.0 | 3 |
| dropped: not_plan | 03-buffer.pptx | 12 | r5c1 | users | 55000.0 | 3 |
| dropped: not_plan | 04-clevergig.docx | 2 | r9c1 | other | 1000000.0 | 3 |
| dropped: not_plan | 06-uber.pdf | 24 | r4c2 | market | 3500000000.0 | 3 |
| dropped: not_plan | 07-equals-seed.docx | 10 | r2c1 | other | 4000000.0 | 3 |
| dropped: not_plan | 08-genesisai-2021.pdf | 13 | r4c1 | cash | 2300000.0 | 2 |
| dropped: not_plan | 08-genesisai-2021.pdf | 13 | r4c1 | other | 2300000.0 | 1 |
| dropped: not_plan | 09-genesisai-2024.pdf | 5 | r5c1 | other | 5500000.0 | 3 |
| dropped: not_plan | 10-tea.pdf | 9 | r3c3 | other | 100000000.0 | 3 |
| dropped: not_plan | 10-tea.pdf | 12 | r2c1 | cash | 1000000.0 | 3 |
| dropped: not_plan | 10-tea.pdf | 12 | r3c1 | other | 10000000.0 | 3 |
| dropped: not_plan | 10-tea.pdf | 12 | r4c1 | cash | 1400000.0 | 3 |
| dropped: not_plan | 10-tea.pdf | 12 | r5c1 | other | 50000000.0 | 3 |
| period | 02-moz.pdf | 20 | r1c2 | revenue | 12000000 | 3 |
| period | 02-moz.pdf | 20 | r2c2 | revenue | 10800000 | 3 |
| period | 02-moz.pdf | 21 | r6c2 | net_profit | 1000000 | 3 |
| period | 04-clevergig.docx | 11 | r3c1 | revenue | 5000000 | 3 |
| period | 04-clevergig.docx | 11 | r3c1 | customers | 1500 | 3 |
| period | 04-clevergig.docx | 11 | r5c1 | people | 20 | 3 |
| period | 09-genesisai-2024.pdf | 4 | r4c1 | market | 210000000000 | 1 |
| period | 09-genesisai-2024.pdf | 5 | r3c1 | revenue | 8000 | 3 |
| period | 09-genesisai-2024.pdf | 5 | r4c1 | users | 2600 | 3 |
| period+other | 01-front-b.pptx | 12 | r7c3 | other | 18 | 3 |
| period+other | 01-front-b.pptx | 12 | r7c3 | other | 19 | 3 |
| period+other | 02-moz.pdf | 3 | r5c1 | other | 1100000 | 2 |
| period+other | 04-clevergig.docx | 7 | r11c1 | other | 305 | 1 |
| period+other | 04-clevergig.docx | 7 | r16c1 | other | 485 | 1 |
| period+other | 04-clevergig.docx | 7 | r6c1 | other | 185 | 1 |
| value | 01-front-b.pptx | 6 | r1c1 | customers | 2300.0 | 3 |
| value | 02-moz.pdf | 3 | r5c2 | users | 1200000.0 | 1 |
| value | 02-moz.pdf | 9 | r6c2 | market | 31000000000.0 | 1 |
| value | 02-moz.pdf | 31 | r1c1 | people | 40.0 | 3 |
| value | 02-moz.pdf | 35 | r1c2 | users | 300000.0 | 3 |
| value | 09-genesisai-2024.pdf | 4 | r3c1 | market | 2800000000000.0 | 2 |
| unit+period | 01-front-b.pptx | 12 | r8c3 | ltv_cac | 2.5 | 3 |
| unit+period | 01-front-b.pptx | 12 | r8c3 | ltv_cac | 2.6 | 3 |
| unit+period | 01-front-b.pptx | 12 | r8c3 | ltv_cac | 4.4 | 3 |
| value+other | 02-moz.pdf | 3 | r5c2 | other | 1200000.0 | 2 |
| value+other | 02-moz.pdf | 9 | r6c2 | other | 31000000000.0 | 1 |
| value+period | 02-moz.pdf | 3 | r3c1 | gross_margin | 83.0 | 3 |
| value+period | 09-genesisai-2024.pdf | 4 | r3c1 | market | 2800000000000.0 | 1 |
| unit | 06-uber.pdf | 20 | r3c6 | net_profit | 20000000 | 3 |
