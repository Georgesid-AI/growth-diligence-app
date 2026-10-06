# Consistency run 2026-10-06: diagnostic

Public test decks only: --diagnostic refuses any other deck. This file holds the text of cells as sent to the model; the report beside it holds none. A pass gives the model's metric, period, unit and actual_or_forecast as written, then the verifier's result: verified, the reason, or dropped (not_a_metric). Not read: the structure was not read in that pass.

## Unverified items

Every unverified item, as listed in the report.

| Deck | Page | Type | Item | Cell | Cell text | Python's values | Reason | Pass 1 | Pass 2 | Pass 3 |
|---|---:|---|---|---|---|---|---|---|---|---|
| 01-front-b.pptx | 12 | kpi_panel | i6 | r3c3#1 | 18% 18% 19% | 18 | period not rebuilt | costs 2017-Q1 % unknown: period not rebuilt | costs 2017-Q1 % actual: period not rebuilt | costs 2017-Q1 % unknown: period not rebuilt |
| 01-front-b.pptx | 12 | kpi_panel | i7 | r3c3#2 | 18% 18% 19% | 18 | period not rebuilt | costs 2017-Q2 % unknown: period not rebuilt | costs 2017-Q2 % actual: period not rebuilt | costs 2017-Q2 % unknown: period not rebuilt |
| 01-front-b.pptx | 12 | kpi_panel | i8 | r3c3#3 | 18% 18% 19% | 19 | period not rebuilt | costs 2017-Q3 % unknown: period not rebuilt | costs 2017-Q3 % actual: period not rebuilt | costs 2017-Q3 % unknown: period not rebuilt |
| 01-front-b.pptx | 12 | kpi_panel | i9 | r4c3#1 | 2.5 2.6 4.4 | 2.5 | other (type Other) | other 2017-Q1 x unknown: other (type Other) | other 2017-Q1 x actual: other (type Other) | other 2017-Q1 x unknown: other (type Other) |
| 01-front-b.pptx | 12 | kpi_panel | i10 | r4c3#2 | 2.5 2.6 4.4 | 2.6 | other (type Other) | other 2017-Q2 x unknown: other (type Other) | other 2017-Q2 x actual: other (type Other) | other 2017-Q2 x unknown: other (type Other) |
| 01-front-b.pptx | 12 | kpi_panel | i11 | r4c3#3 | 2.5 2.6 4.4 | 4.4 | other (type Other) | other 2017-Q3 x unknown: other (type Other) | other 2017-Q3 x actual: other (type Other) | other 2017-Q3 x unknown: other (type Other) |
| 01-front-b.pptx | 15 | kpi_panel | i3 | r5c2#1 | $7m left | 7000000 | other (type Other) | other null USD actual: other (type Other) | other null USD actual: other (type Other) | other null USD actual: other (type Other) |
| 01-front-b.pptx | 15 | kpi_panel | i4 | r5c3#1 | 18 months | 18 | other (type Other) | other null months actual: other (type Other) | other null months forecast: other (type Other) | other null months forecast: other (type Other) |
| 01-front-b.pptx | 15 | kpi_panel | i5 | r6c5#1 | Profitable in 10 months | 10 | other (type Other) | other null months forecast: other (type Other) | other null months forecast: other (type Other) | other null months forecast: other (type Other) |
| 02-moz.pdf | 2 | roadmap | i2 | r4c4#1 | Prices rise to $99 / $499 / | 99 | other (type Other) | other null USD actual: other (type Other) | other null USD actual: other (type Other) | other null USD actual: other (type Other) |
| 02-moz.pdf | 2 | roadmap | i3 | r4c4#2 | Prices rise to $99 / $499 / | 499 | other (type Other) | other null USD actual: other (type Other) | other null USD actual: other (type Other) | other null USD actual: other (type Other) |
| 02-moz.pdf | 2 | roadmap | i4 | r5c4#1 | $1999 per month. | 1999 | other (type Other) | other null USD actual: other (type Other) | other null USD actual: other (type Other) | other null USD actual: other (type Other) |
| 02-moz.pdf | 2 | roadmap | i6 | r11c3#1 | “PRO” for $39/month | 39 | other (type Other) | other null USD actual: other (type Other) | other null USD actual: other (type Other) | other null USD actual: other (type Other) |
| 02-moz.pdf | 20 | kpi_panel | i5 | r4c2#1 | ~100 | 100 | other (type Other) | other null count actual: other (type Other) | other null count actual: other (type Other) | customers null count actual: verified |
| 02-moz.pdf | 20 | kpi_panel | i6 | r5c2#1 | ~$900 | 900 | other (type Other) | other null USD actual: other (type Other) | other null USD actual: other (type Other) | other null USD actual: other (type Other) |
| 02-moz.pdf | 21 | kpi_panel | i1 | r1c2#1 | ~57% | 57 | other (type Other) | other null % unknown: other (type Other) | other null % unknown: other (type Other) | other null % actual: other (type Other) |
| 02-moz.pdf | 32 | kpi_panel | i1 | r2c1#1 | ($25/month for lighter use) | 25 | other (type Other) | other null USD unknown: other (type Other) | other null USD unknown: other (type Other) | other null USD unknown: other (type Other) |
| 02-moz.pdf | 20 | kpi_panel | i7 | r6c2#1 | ~9 Months | 9 | other (type Other) | retention null months actual: verified | other null months actual: other (type Other) | other null months actual: other (type Other) |
| 03-buffer.pptx | 6 | roadmap | i3 | r7c1#1 | Integrated in 50 apps | 50 | other (type Other) | other null count unknown: other (type Other) | product null count unknown: verified | product null count unknown: verified |
| 04-clevergig.docx | 7 | kpi_panel | i1 | r1c1#1 | Up to 200 shifts p.m. | 200 | other (type Other) | other null count forecast: other (type Other) | sales null count forecast: verified | sales null count forecast: verified |
| 04-clevergig.docx | 7 | kpi_panel | i3 | r3c1#1 | Up to 400 shifts p.m. | 400 | other (type Other) | other null count forecast: other (type Other) | sales null count forecast: verified | sales null count forecast: verified |
| 04-clevergig.docx | 7 | kpi_panel | i5 | r5c1#1 | Up to 800 shifts p.m. | 800 | other (type Other) | other null count forecast: other (type Other) | sales null count forecast: verified | sales null count forecast: verified |
| 04-clevergig.docx | 7 | kpi_panel | i7 | r7c1#1 | 800 shifts p.m. | 800 | other (type Other) | other null count forecast: other (type Other) | sales null count forecast: verified | sales null count forecast: verified |
| 08-genesisai-2021.pdf | 13 | kpi_panel | i1 | r1c1#1 | Over 25 partnerships! | 25 | other (type Other) | other null count actual: other (type Other) | other null count actual: other (type Other) | other null count actual: other (type Other) |

## Disagreeing items

Every item whose labels differ between passes, as the model wrote them.

| Deck | Page | Type | Item | Cell | Cell text | Python's values | Reason | Pass 1 | Pass 2 | Pass 3 |
|---|---:|---|---|---|---|---|---|---|---|---|
| 01-front-b.pptx | 12 | kpi_panel | i1 | r1c4#1 | 2 weeks ago | 2 |  | people null null actual: verified | not_a_metric null null unknown: dropped (not_a_metric) | not_a_metric null null unknown: dropped (not_a_metric) |
| 01-front-b.pptx | 12 | kpi_panel | i2 | r1c6#1 | 10 months ago | 10 |  | people null months actual: verified | not_a_metric null null unknown: dropped (not_a_metric) | not_a_metric null null unknown: dropped (not_a_metric) |
| 01-front-b.pptx | 12 | kpi_panel | i3 | r1c7#1 | joined 6 months ago | 6 |  | people null months actual: verified | not_a_metric null null unknown: dropped (not_a_metric) | not_a_metric null null unknown: dropped (not_a_metric) |
| 01-front-b.pptx | 12 | kpi_panel | i4 | r1c8#1 | 2 months ago | 2 |  | people null months actual: verified | not_a_metric null null unknown: dropped (not_a_metric) | not_a_metric null null unknown: dropped (not_a_metric) |
| 01-front-b.pptx | 12 | kpi_panel | i5 | r1c9#1 | 10 months ago | 10 |  | people null months actual: verified | not_a_metric null null unknown: dropped (not_a_metric) | not_a_metric null null unknown: dropped (not_a_metric) |
| 01-front-b.pptx | 12 | kpi_panel | i6 | r3c3#1 | 18% 18% 19% | 18 |  | costs 2017-Q1 % unknown: period not rebuilt | costs 2017-Q1 % actual: period not rebuilt | costs 2017-Q1 % unknown: period not rebuilt |
| 01-front-b.pptx | 12 | kpi_panel | i7 | r3c3#2 | 18% 18% 19% | 18 |  | costs 2017-Q2 % unknown: period not rebuilt | costs 2017-Q2 % actual: period not rebuilt | costs 2017-Q2 % unknown: period not rebuilt |
| 01-front-b.pptx | 12 | kpi_panel | i8 | r3c3#3 | 18% 18% 19% | 19 |  | costs 2017-Q3 % unknown: period not rebuilt | costs 2017-Q3 % actual: period not rebuilt | costs 2017-Q3 % unknown: period not rebuilt |
| 01-front-b.pptx | 12 | kpi_panel | i9 | r4c3#1 | 2.5 2.6 4.4 | 2.5 |  | other 2017-Q1 x unknown: other (type Other) | other 2017-Q1 x actual: other (type Other) | other 2017-Q1 x unknown: other (type Other) |
| 01-front-b.pptx | 12 | kpi_panel | i10 | r4c3#2 | 2.5 2.6 4.4 | 2.6 |  | other 2017-Q2 x unknown: other (type Other) | other 2017-Q2 x actual: other (type Other) | other 2017-Q2 x unknown: other (type Other) |
| 01-front-b.pptx | 12 | kpi_panel | i11 | r4c3#3 | 2.5 2.6 4.4 | 4.4 |  | other 2017-Q3 x unknown: other (type Other) | other 2017-Q3 x actual: other (type Other) | other 2017-Q3 x unknown: other (type Other) |
| 01-front-b.pptx | 15 | kpi_panel | i4 | r5c3#1 | 18 months | 18 |  | other null months actual: other (type Other) | other null months forecast: other (type Other) | other null months forecast: other (type Other) |
| 02-moz.pdf | 20 | kpi_panel | i5 | r4c2#1 | ~100 | 100 |  | other null count actual: other (type Other) | other null count actual: other (type Other) | customers null count actual: verified |
| 02-moz.pdf | 20 | kpi_panel | i7 | r6c2#1 | ~9 Months | 9 |  | retention null months actual: verified | other null months actual: other (type Other) | other null months actual: other (type Other) |
| 02-moz.pdf | 21 | kpi_panel | i1 | r1c2#1 | ~57% | 57 |  | other null % unknown: other (type Other) | other null % unknown: other (type Other) | other null % actual: other (type Other) |
| 02-moz.pdf | 21 | kpi_panel | i2 | r2c2#1 | ~25% | 25 |  | retention null % unknown: verified | retention null % unknown: verified | retention null % actual: verified |
| 02-moz.pdf | 21 | kpi_panel | i3 | r3c2#1 | ~1.25 million | 1250000 |  | users null count unknown: verified | users null count unknown: verified | users null count actual: verified |
| 02-moz.pdf | 21 | kpi_panel | i4 | r4c2#1 | ~300K | 300000 |  | customers null count unknown: verified | customers null count unknown: verified | users null count actual: verified |
| 02-moz.pdf | 21 | kpi_panel | i5 | r5c2#1 | ~82% | 82 |  | gross_margin null % unknown: verified | gross_margin null % unknown: verified | gross_margin null % actual: verified |
| 02-moz.pdf | 21 | kpi_panel | i7 | r7c2#1 | ~$650K / Month | 650000 |  | costs null USD unknown: verified | costs null USD unknown: verified | costs null USD actual: verified |
| 02-moz.pdf | 21 | kpi_panel | i8 | r8c2#1 | ~$180K / Month | 180000 |  | costs null USD unknown: verified | costs null USD unknown: verified | costs null USD actual: verified |
| 02-moz.pdf | 23 | kpi_panel | i1 | r1c2#1 | $20-$25 Million | 20 |  | not_a_metric null USD forecast: dropped (not_a_metric) | not_a_metric null USD unknown: dropped (not_a_metric) | not_a_metric null USD forecast: dropped (not_a_metric) |
| 02-moz.pdf | 23 | kpi_panel | i2 | r1c2#2 | $20-$25 Million | 25 |  | not_a_metric null USD forecast: dropped (not_a_metric) | not_a_metric null USD unknown: dropped (not_a_metric) | not_a_metric null USD forecast: dropped (not_a_metric) |
| 02-moz.pdf | 23 | kpi_panel | i3 | r2c2#1 | $6-7 Million | 6 |  | not_a_metric null USD forecast: dropped (not_a_metric) | not_a_metric null USD unknown: dropped (not_a_metric) | not_a_metric null USD forecast: dropped (not_a_metric) |
| 02-moz.pdf | 23 | kpi_panel | i4 | r2c2#2 | $6-7 Million | 7 |  | not_a_metric null USD forecast: dropped (not_a_metric) | not_a_metric null USD unknown: dropped (not_a_metric) | not_a_metric null USD forecast: dropped (not_a_metric) |
| 02-moz.pdf | 23 | kpi_panel | i5 | r3c2#1 | $13-19 Million | 13 |  | not_a_metric null USD forecast: dropped (not_a_metric) | not_a_metric null USD unknown: dropped (not_a_metric) | not_a_metric null USD forecast: dropped (not_a_metric) |
| 02-moz.pdf | 23 | kpi_panel | i6 | r3c2#2 | $13-19 Million | 19 |  | not_a_metric null USD forecast: dropped (not_a_metric) | not_a_metric null USD unknown: dropped (not_a_metric) | not_a_metric null USD forecast: dropped (not_a_metric) |
| 02-moz.pdf | 23 | kpi_panel | i7 | r4c2#1 | 2 Investors (Michelle +1) | 2 |  | not_a_metric null count forecast: dropped (not_a_metric) | not_a_metric null count unknown: dropped (not_a_metric) | not_a_metric null count forecast: dropped (not_a_metric) |
| 02-moz.pdf | 23 | kpi_panel | i8 | r4c2#2 | 2 Investors (Michelle +1) | 1 |  | not_a_metric null count forecast: dropped (not_a_metric) | not_a_metric null count unknown: dropped (not_a_metric) | not_a_metric null count forecast: dropped (not_a_metric) |
| 02-moz.pdf | 23 | kpi_panel | i9 | r5c2#1 | 2 Insiders (Rand +1) | 2 |  | not_a_metric null count forecast: dropped (not_a_metric) | not_a_metric null count unknown: dropped (not_a_metric) | not_a_metric null count forecast: dropped (not_a_metric) |
| 02-moz.pdf | 23 | kpi_panel | i10 | r5c2#2 | 2 Insiders (Rand +1) | 1 |  | not_a_metric null count forecast: dropped (not_a_metric) | not_a_metric null count unknown: dropped (not_a_metric) | not_a_metric null count forecast: dropped (not_a_metric) |
| 02-moz.pdf | 23 | kpi_panel | i11 | r6c2#1 | 1 Independent (TBD) | 1 |  | not_a_metric null count forecast: dropped (not_a_metric) | not_a_metric null count unknown: dropped (not_a_metric) | not_a_metric null count forecast: dropped (not_a_metric) |
| 03-buffer.pptx | 6 | roadmap | i3 | r7c1#1 | Integrated in 50 apps | 50 |  | other null count unknown: other (type Other) | product null count unknown: verified | product null count unknown: verified |
| 04-clevergig.docx | 7 | kpi_panel | i1 | r1c1#1 | Up to 200 shifts p.m. | 200 |  | other null count forecast: other (type Other) | sales null count forecast: verified | sales null count forecast: verified |
| 04-clevergig.docx | 7 | kpi_panel | i3 | r3c1#1 | Up to 400 shifts p.m. | 400 |  | other null count forecast: other (type Other) | sales null count forecast: verified | sales null count forecast: verified |
| 04-clevergig.docx | 7 | kpi_panel | i5 | r5c1#1 | Up to 800 shifts p.m. | 800 |  | other null count forecast: other (type Other) | sales null count forecast: verified | sales null count forecast: verified |
| 04-clevergig.docx | 7 | kpi_panel | i7 | r7c1#1 | 800 shifts p.m. | 800 |  | other null count forecast: other (type Other) | sales null count forecast: verified | sales null count forecast: verified |
| 05-zero2hero.pdf | 11 | kpi_panel | i2 | r8c1#1 | ($570 B) | -570000000000 |  | not_a_metric null USD unknown: dropped (not_a_metric) | not_a_metric 2028 USD forecast: dropped (not_a_metric) | not_a_metric null USD unknown: dropped (not_a_metric) |
| 05-zero2hero.pdf | 11 | kpi_panel | i3 | r9c2#1 | ($374B) | -374000000000 |  | not_a_metric null USD unknown: dropped (not_a_metric) | not_a_metric 2028 USD forecast: dropped (not_a_metric) | not_a_metric null USD unknown: dropped (not_a_metric) |
| 05-zero2hero.pdf | 17 | kpi_panel | i1 | r1c1#1 | Telegram(30K) | 30000 or -30000 |  | users null count unknown: verified | users null count unknown: verified | users null count actual: verified |
| 05-zero2hero.pdf | 17 | kpi_panel | i2 | r2c1#1 | Discord(150) | 150 or -150 |  | users null count unknown: verified | users null count unknown: verified | users null count actual: verified |
| 05-zero2hero.pdf | 17 | kpi_panel | i3 | r3c1#1 | Twitter(6.5K) | 6500 or -6500 |  | users null count unknown: verified | users null count unknown: verified | users null count actual: verified |
| 05-zero2hero.pdf | 17 | kpi_panel | i4 | r4c1#1 | Instagram(85K) | 85000 or -85000 |  | users null count unknown: verified | users null count unknown: verified | users null count actual: verified |
| 05-zero2hero.pdf | 17 | kpi_panel | i5 | r6c1#1 | MeetUp((3K) | 3000 or -3000 |  | users null count unknown: verified | users null count unknown: verified | users null count actual: verified |
| 05-zero2hero.pdf | 17 | kpi_panel | i6 | r7c1#1 | LinkedIn(10K) | 10000 or -10000 |  | users null count unknown: verified | users null count unknown: verified | users null count actual: verified |
| 09-genesisai-2024.pdf | 5 | kpi_panel | i2 | r2c1#1 | 2,600+ users | 2600 |  | users null count unknown: verified | users null count actual: verified | users null count unknown: verified |
| 09-genesisai-2024.pdf | 5 | kpi_panel | i3 | r3c1#1 | Raised ~$5.5M | 5500000 |  | not_a_metric null USD unknown: dropped (not_a_metric) | not_a_metric null USD actual: dropped (not_a_metric) | not_a_metric null USD actual: dropped (not_a_metric) |
| 10-tea.pdf | 9 | kpi_panel | i1 | r3c2#1 | 100 million total supply. | 100000000 |  | not_a_metric null null unknown: dropped (not_a_metric) | not_a_metric null null unknown: dropped (not_a_metric) | not_a_metric null count unknown: dropped (not_a_metric) |
