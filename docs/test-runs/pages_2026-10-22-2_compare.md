# Compare: rules read (A) against the page read (B), recorded replies of pages_2026-10-22-2

scripts/compare_pipelines.py --recorded: B replays the model's recorded replies of each pass through the gateway and page_check; A is the rules read (claims.detect_candidates). Recall and precision against the answer file (tests/fixtures/decks/expected_claims.json). Dropped: claims page_check drops before any check (an axis tick, a line the rules read drops, a cell not on the page).

## Per deck and pass

| Deck | Pass | Pages | Sent | A rows | A recall | A precision | B rows | Matched | Unmatched | Dropped | B recall | B precision | Only A | Only B |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| 01-front-b.pptx | 1 | 23 | 9 | 46 | 94% | 33% | 6 | 5 | 1 | 0 | 28% | 67% | 40 | 0 |
| 01-front-b.pptx | 2 | 23 | 9 | 46 | 94% | 33% | 7 | 5 | 2 | 0 | 33% | 71% | 39 | 0 |
| 01-front-b.pptx | 3 | 23 | 9 | 46 | 94% | 33% | 11 | 5 | 6 | 0 | 50% | 82% | 36 | 0 |
| 02-moz.pdf | 1 | 36 | 15 | 43 | 96% | 49% | 28 | 25 | 3 | 0 | 86% | 64% | 17 | 2 |
| 02-moz.pdf | 2 | 36 | 15 | 43 | 96% | 49% | 24 | 21 | 3 | 0 | 86% | 75% | 20 | 1 |
| 02-moz.pdf | 3 | 36 | 15 | 43 | 96% | 49% | 28 | 25 | 3 | 0 | 86% | 64% | 17 | 2 |
| 03-buffer.pptx | 1 | 12 | 6 | 24 | 100% | 83% | 19 | 19 | 0 | 0 | 80% | 84% | 6 | 1 |
| 03-buffer.pptx | 2 | 12 | 6 | 24 | 100% | 83% | 20 | 20 | 0 | 0 | 85% | 85% | 5 | 1 |
| 03-buffer.pptx | 3 | 12 | 6 | 24 | 100% | 83% | 19 | 19 | 0 | 0 | 80% | 84% | 6 | 1 |
| 04-clevergig.docx | 1 | 13 | 5 | 21 | 93% | 62% | 19 | 18 | 1 | 0 | 93% | 68% | 5 | 4 |
| 04-clevergig.docx | 2 | 13 | 5 | 21 | 93% | 62% | 18 | 17 | 1 | 0 | 93% | 72% | 6 | 4 |
| 04-clevergig.docx | 3 | 13 | 5 | 21 | 93% | 62% | 18 | 17 | 1 | 0 | 93% | 72% | 6 | 4 |
| 05-zero2hero.pdf | 1 | 22 | 6 | 44 | 94% | 75% | 40 | 32 | 8 | 0 | 89% | 78% | 13 | 9 |
| 05-zero2hero.pdf | 2 | 22 | 6 | 44 | 94% | 75% | 41 | 32 | 9 | 0 | 91% | 78% | 12 | 9 |
| 05-zero2hero.pdf | 3 | 22 | 6 | 44 | 94% | 75% | 40 | 32 | 8 | 0 | 89% | 78% | 13 | 9 |
| 06-uber.pdf | 1 | 25 | 15 | 28 | 100% | 14% | 6 | 6 | 0 | 1 | 75% | 50% | 23 | 1 |
| 06-uber.pdf | 2 | 25 | 15 | 28 | 100% | 14% | 7 | 7 | 0 | 1 | 75% | 43% | 22 | 1 |
| 06-uber.pdf | 3 | 25 | 15 | 28 | 100% | 14% | 6 | 6 | 0 | 1 | 75% | 50% | 23 | 1 |
| 07-equals-seed.docx | 1 | 10 | 3 | 3 | 100% | 33% | 0 | 0 | 0 | 0 | 0% | - | 3 | 0 |
| 07-equals-seed.docx | 2 | 10 | 3 | 3 | 100% | 33% | 0 | 0 | 0 | 0 | 0% | - | 3 | 0 |
| 07-equals-seed.docx | 3 | 10 | 3 | 3 | 100% | 33% | 0 | 0 | 0 | 0 | 0% | - | 3 | 0 |
| 08-genesisai-2021.pdf | 1 | 14 | 4 | 0 | - | - | 1 | 0 | 1 | 0 | - | 0% | 0 | 1 |
| 08-genesisai-2021.pdf | 2 | 14 | 4 | 0 | - | - | 4 | 0 | 4 | 0 | - | 0% | 0 | 4 |
| 08-genesisai-2021.pdf | 3 | 14 | 4 | 0 | - | - | 2 | 0 | 2 | 0 | - | 0% | 0 | 2 |
| 09-genesisai-2024.pdf | 1 | 14 | 5 | 7 | 100% | 29% | 6 | 4 | 2 | 0 | 100% | 33% | 3 | 2 |
| 09-genesisai-2024.pdf | 2 | 14 | 5 | 7 | 100% | 29% | 6 | 4 | 2 | 0 | 100% | 33% | 3 | 2 |
| 09-genesisai-2024.pdf | 3 | 14 | 5 | 7 | 100% | 29% | 5 | 4 | 1 | 0 | 100% | 40% | 3 | 1 |
| 10-tea.pdf | 1 | 14 | 4 | 16 | 100% | 44% | 0 | 0 | 0 | 0 | 0% | - | 16 | 0 |
| 10-tea.pdf | 2 | 14 | 4 | 16 | 100% | 44% | 0 | 0 | 0 | 0 | 0% | - | 16 | 0 |
| 10-tea.pdf | 3 | 14 | 4 | 16 | 100% | 44% | 0 | 0 | 0 | 0 | 0% | - | 16 | 0 |
| all | 1 | | | 232 | | | 125 | 109 | 16 | 1 | 72% | | | |
| all | 2 | | | 232 | | | 127 | 106 | 21 | 1 | 74% | | | |
| all | 3 | | | 232 | | | 129 | 108 | 21 | 1 | 75% | | | |

## Agreement across passes

Claims (value cell, metric, period) found in every pass / found in any pass, from the recorded replies. Disagreeing claims by kind: metric (the cell is claimed in every pass, with another metric in some), period (cell and metric in every pass, another period in some), presence (the cell is claimed in some passes only). Pages differ: a pass read pages another did not.

| Deck | Agreed | Union | Agreement | Metric | Period | Presence | Pages differ |
|---|---:|---:|---:|---:|---:|---:|---|
| 01-front-b.pptx | 6 | 11 | 54.5% | 0 | 2 | 3 | no |
| 02-moz.pdf | 23 | 29 | 79.3% | 2 | 0 | 4 | yes |
| 03-buffer.pptx | 18 | 21 | 85.7% | 3 | 0 | 0 | no |
| 04-clevergig.docx | 16 | 20 | 80.0% | 4 | 0 | 0 | no |
| 05-zero2hero.pdf | 36 | 45 | 80.0% | 0 | 8 | 1 | no |
| 06-uber.pdf | 7 | 8 | 87.5% | 1 | 0 | 0 | no |
| 07-equals-seed.docx | 0 | 0 | 100.0% | 0 | 0 | 0 | no |
| 08-genesisai-2021.pdf | 1 | 4 | 25.0% | 0 | 0 | 3 | yes |
| 09-genesisai-2024.pdf | 5 | 6 | 83.3% | 0 | 0 | 1 | yes |
| 10-tea.pdf | 0 | 0 | 100.0% | 0 | 0 | 0 | no |
| all | | | 77.8% | | | | |

## Claims by cause

Over all passes. A cause names the checks that failed (value, unit, period), the metric other (never matched by design), no value (a milestone), or why the claim was dropped.

| Cause | Claims | Share |
|---|---:|---:|
| matched | 323 | 84% |
| other | 15 | 4% |
| period | 14 | 4% |
| unit | 10 | 3% |
| unit+period | 9 | 2% |
| value | 9 | 2% |
| dropped: not_plan | 3 | 1% |
| no value | 1 | 0% |

## Unmatched and dropped rows

One line per deck, page, cell, cause, metric and value; passes: in how many passes it appears.

| Cause | Deck | Page | Cell | Metric | Value | Passes |
|---|---|---:|---|---|---:|---:|
| other | 04-clevergig.docx | 6 | r5c1 | other | 30 | 3 |
| other | 08-genesisai-2021.pdf | 8 | r3c1 | other | 300 | 2 |
| other | 08-genesisai-2021.pdf | 12 | r3c1 | other | 30 | 1 |
| other | 08-genesisai-2021.pdf | 13 | r3c1 | other | 25 | 3 |
| other | 08-genesisai-2021.pdf | 14 | r4c2 | other | 30 | 1 |
| other | 09-genesisai-2024.pdf | 12 | r3c1 | other | 70 | 3 |
| other | 09-genesisai-2024.pdf | 13 | r3c1 | other | 30 | 2 |
| unit+period | 01-front-b.pptx | 12 | r8c3 | ltv_cac | 2.5 | 2 |
| unit+period | 01-front-b.pptx | 12 | r8c3 | ltv_cac | 2.6 | 1 |
| unit+period | 01-front-b.pptx | 12 | r8c3 | ltv_cac | 4.4 | 1 |
| unit+period | 05-zero2hero.pdf | 17 | r10c2 | revenue | 415107 | 1 |
| unit+period | 05-zero2hero.pdf | 17 | r15c2 | revenue | 278085 | 1 |
| unit+period | 05-zero2hero.pdf | 17 | r17c2 | revenue | 49284 | 2 |
| unit+period | 05-zero2hero.pdf | 17 | r9c2 | revenue | 550508 | 1 |
| period | 01-front-b.pptx | 12 | r7c3 | sales | 18 | 3 |
| period | 01-front-b.pptx | 12 | r7c3 | sales | 19 | 1 |
| period | 02-moz.pdf | 3 | r3c1 | gross_margin | 83 | 3 |
| period | 02-moz.pdf | 20 | r2c2 | revenue | 10800000 | 3 |
| period | 02-moz.pdf | 21 | r6c2 | net_profit | 1000000 | 3 |
| unit | 05-zero2hero.pdf | 17 | r10c2 | revenue | 415107 | 2 |
| unit | 05-zero2hero.pdf | 17 | r15c2 | revenue | 278085 | 2 |
| unit | 05-zero2hero.pdf | 17 | r16c2 | revenue | 181193 | 3 |
| unit | 05-zero2hero.pdf | 17 | r17c2 | revenue | 49284 | 1 |
| unit | 05-zero2hero.pdf | 17 | r9c2 | revenue | 550508 | 2 |
| value | 05-zero2hero.pdf | 11 | r14c3 | market | 570000000000.0 | 3 |
| value | 05-zero2hero.pdf | 11 | r15c4 | market | 374000000000.0 | 3 |
| value | 05-zero2hero.pdf | 11 | r5c4 | market | 52000000000.0 | 3 |
| dropped: not_plan | 06-uber.pdf | 24 | r4c2 | market | 3500000000.0 | 3 |
| no value | 05-zero2hero.pdf | 19 | r5c1 | ebitda | None | 1 |
