# Consistency run 2026-10-07: diagnostic

Public test decks only: --diagnostic refuses any other deck. This file holds the text of cells as sent to the model; the report beside it holds none. A pass gives the model's metric, period, unit and actual_or_forecast as written, then the verifier's result: verified, the reason, or dropped (not_a_metric). Not read: the structure was not read in that pass.

## Unverified items

Every unverified item, as listed in the report.

| Deck | Page | Type | Item | Cell | Cell text | Python's values | Reason | Pass 1 | Pass 2 | Pass 3 |
|---|---:|---|---|---|---|---|---|---|---|---|
| 01-front-b.pptx | 12 | kpi_panel | i6 | r3c3#1 | 18% 18% 19% | 18 | period not rebuilt | costs 2017-Q1 % unknown: period not rebuilt | costs 2017-Q1 % unknown: period not rebuilt | costs 2017-Q1 % unknown: period not rebuilt |
| 01-front-b.pptx | 12 | kpi_panel | i7 | r3c3#2 | 18% 18% 19% | 18 | period not rebuilt | costs 2017-Q2 % unknown: period not rebuilt | costs 2017-Q2 % unknown: period not rebuilt | costs 2017-Q2 % unknown: period not rebuilt |
| 01-front-b.pptx | 12 | kpi_panel | i8 | r3c3#3 | 18% 18% 19% | 19 | period not rebuilt | costs 2017-Q3 % unknown: period not rebuilt | costs 2017-Q3 % unknown: period not rebuilt | costs 2017-Q3 % unknown: period not rebuilt |
| 01-front-b.pptx | 12 | kpi_panel | i9 | r4c3#1 | 2.5 2.6 4.4 | 2.5 | period not rebuilt | ltv_cac 2017-Q1 x unknown: period not rebuilt | ltv_cac 2017-Q1 x unknown: period not rebuilt | ltv_cac 2017-Q1 x unknown: period not rebuilt |
| 01-front-b.pptx | 12 | kpi_panel | i10 | r4c3#2 | 2.5 2.6 4.4 | 2.6 | period not rebuilt | ltv_cac 2017-Q2 x unknown: period not rebuilt | ltv_cac 2017-Q2 x unknown: period not rebuilt | ltv_cac 2017-Q2 x unknown: period not rebuilt |
| 01-front-b.pptx | 12 | kpi_panel | i11 | r4c3#3 | 2.5 2.6 4.4 | 4.4 | period not rebuilt | ltv_cac 2017-Q3 x unknown: period not rebuilt | ltv_cac 2017-Q3 x unknown: period not rebuilt | ltv_cac 2017-Q3 x unknown: period not rebuilt |
| 02-moz.pdf | 2 | roadmap | i2 | r1c4#1 | Moz’scollection of tools becomes a singular, campaign-based web app. Prices rise to $99 / $499 / $1999 per month. | 99 | other (type Other) | other null USD actual: other (type Other) | other null USD actual: other (type Other) | other null USD actual: other (type Other) |
| 02-moz.pdf | 2 | roadmap | i3 | r1c4#2 | Moz’scollection of tools becomes a singular, campaign-based web app. Prices rise to $99 / $499 / $1999 per month. | 499 | other (type Other) | other null USD actual: other (type Other) | other null USD actual: other (type Other) | other null USD actual: other (type Other) |
| 02-moz.pdf | 2 | roadmap | i4 | r1c4#3 | Moz’scollection of tools becomes a singular, campaign-based web app. Prices rise to $99 / $499 / $1999 per month. | 1999 | other (type Other) | other null USD actual: other (type Other) | other null USD actual: other (type Other) | other null USD actual: other (type Other) |
| 02-moz.pdf | 2 | roadmap | i6 | r4c3#1 | SEOmoz launches its first subscription software product, “PRO” for $39/month | 39 | other (type Other) | other null USD actual: other (type Other) | other null USD actual: other (type Other) | other null USD actual: other (type Other) |
| 02-moz.pdf | 21 | kpi_panel | i3 | r3c2#1 | ~1.25 million | 1250000 | other (type Other) | other null count unknown: other (type Other) | other null count unknown: other (type Other) | other null count unknown: other (type Other) |
| 02-moz.pdf | 21 | kpi_panel | i4 | r4c2#1 | ~300K | 300000 | other (type Other) | other null count unknown: other (type Other) | other null count unknown: other (type Other) | other null count unknown: other (type Other) |
| 02-moz.pdf | 32 | kpi_panel | i1 | r2c1#1 | ($25/month for lighter use) | 25 | other (type Other) | other null USD unknown: other (type Other) | other null USD unknown: other (type Other) | other null USD unknown: other (type Other) |
| 05-zero2hero.pdf | 17 | kpi_panel | i1 | r1c1#1 | Telegram(30K) | 30000 or -30000 | other (type Other) | other null count unknown: other (type Other) | other null count unknown: other (type Other) | other null count unknown: other (type Other) |
| 05-zero2hero.pdf | 17 | kpi_panel | i2 | r2c1#1 | Discord(150) | 150 or -150 | other (type Other) | other null count unknown: other (type Other) | other null count unknown: other (type Other) | other null count unknown: other (type Other) |
| 05-zero2hero.pdf | 17 | kpi_panel | i3 | r3c1#1 | Twitter(6.5K) | 6500 or -6500 | other (type Other) | other null count unknown: other (type Other) | other null count unknown: other (type Other) | other null count unknown: other (type Other) |
| 05-zero2hero.pdf | 17 | kpi_panel | i4 | r4c1#1 | Instagram(85K) | 85000 or -85000 | other (type Other) | other null count unknown: other (type Other) | other null count unknown: other (type Other) | other null count unknown: other (type Other) |
| 05-zero2hero.pdf | 17 | kpi_panel | i5 | r6c1#1 | MeetUp((3K) | 3000 or -3000 | other (type Other) | other null count unknown: other (type Other) | other null count unknown: other (type Other) | other null count unknown: other (type Other) |
| 05-zero2hero.pdf | 17 | kpi_panel | i6 | r7c1#1 | LinkedIn(10K) | 10000 or -10000 | other (type Other) | other null count unknown: other (type Other) | other null count unknown: other (type Other) | other null count unknown: other (type Other) |

## Disagreeing items

Every item whose labels differ between passes, as the model wrote them.

| Deck | Page | Type | Item | Cell | Cell text | Python's values | Reason | Pass 1 | Pass 2 | Pass 3 |
|---|---:|---|---|---|---|---|---|---|---|---|
| 01-front-b.pptx | 15 | kpi_panel | i4 | r5c3#1 | 18 months | 18 |  | runway null months forecast: verified | runway null months unknown: verified | runway null months unknown: verified |
| 02-moz.pdf | 23 | kpi_panel | i3 | r2c2#1 | $6-7 Million | 6 |  | use_of_funds null USD forecast: verified | not_a_metric null USD unknown: dropped (not_a_metric) | not_a_metric null USD unknown: dropped (not_a_metric) |
| 02-moz.pdf | 23 | kpi_panel | i4 | r2c2#2 | $6-7 Million | 7 |  | use_of_funds null USD forecast: verified | not_a_metric null USD unknown: dropped (not_a_metric) | not_a_metric null USD unknown: dropped (not_a_metric) |
| 02-moz.pdf | 23 | kpi_panel | i5 | r3c2#1 | $13-19 Million | 13 |  | use_of_funds null USD forecast: verified | not_a_metric null USD unknown: dropped (not_a_metric) | not_a_metric null USD unknown: dropped (not_a_metric) |
| 02-moz.pdf | 23 | kpi_panel | i6 | r3c2#2 | $13-19 Million | 19 |  | use_of_funds null USD forecast: verified | not_a_metric null USD unknown: dropped (not_a_metric) | not_a_metric null USD unknown: dropped (not_a_metric) |
| 02-moz.pdf | 23 | kpi_panel | i7 | r4c2#1 | 2 Investors (Michelle +1) | 2 |  | not_a_metric null null unknown: dropped (not_a_metric) | not_a_metric null count unknown: dropped (not_a_metric) | not_a_metric null count unknown: dropped (not_a_metric) |
| 02-moz.pdf | 23 | kpi_panel | i8 | r4c2#2 | 2 Investors (Michelle +1) | 1 |  | not_a_metric null null unknown: dropped (not_a_metric) | not_a_metric null count unknown: dropped (not_a_metric) | not_a_metric null count unknown: dropped (not_a_metric) |
| 02-moz.pdf | 23 | kpi_panel | i9 | r5c2#1 | 2 Insiders (Rand +1) | 2 |  | not_a_metric null null unknown: dropped (not_a_metric) | not_a_metric null count unknown: dropped (not_a_metric) | not_a_metric null count unknown: dropped (not_a_metric) |
| 02-moz.pdf | 23 | kpi_panel | i10 | r5c2#2 | 2 Insiders (Rand +1) | 1 |  | not_a_metric null null unknown: dropped (not_a_metric) | not_a_metric null count unknown: dropped (not_a_metric) | not_a_metric null count unknown: dropped (not_a_metric) |
| 02-moz.pdf | 23 | kpi_panel | i11 | r6c2#1 | 1 Independent (TBD) | 1 |  | not_a_metric null null unknown: dropped (not_a_metric) | not_a_metric null count unknown: dropped (not_a_metric) | not_a_metric null count unknown: dropped (not_a_metric) |
| 04-clevergig.docx | 7 | kpi_panel | i2 | r2c1#1 | Approx. 950 hours | 950 |  | product null null unknown: verified | product null count unknown: verified | product null count unknown: verified |
| 04-clevergig.docx | 7 | kpi_panel | i4 | r4c1#1 | Approx. 2.500 hours | 2500 or 2.5 |  | product null null unknown: verified | product null count unknown: verified | product null count unknown: verified |
| 04-clevergig.docx | 7 | kpi_panel | i6 | r6c1#1 | Approx. 6.250 hours | 6250 or 6.25 |  | product null null unknown: verified | product null count unknown: verified | product null count unknown: verified |
| 05-zero2hero.pdf | 22 | hiring_table | i1 | r2c1#1 | •1 environment artist and game developer •1 Fullstackdeveloper •1 blockchain developer | 1 |  | people null count unknown: verified | people null count unknown: verified | people null count forecast: verified |
| 05-zero2hero.pdf | 22 | hiring_table | i2 | r2c1#2 | •1 environment artist and game developer •1 Fullstackdeveloper •1 blockchain developer | 1 |  | people null count unknown: verified | people null count unknown: verified | people null count forecast: verified |
| 05-zero2hero.pdf | 22 | hiring_table | i3 | r2c1#3 | •1 environment artist and game developer •1 Fullstackdeveloper •1 blockchain developer | 1 |  | people null count unknown: verified | people null count unknown: verified | people null count forecast: verified |

## Roadmap lines

Every text line of the roadmaps read in every pass (the lines the report counts): Python's date, the date it gives the line by its place (none: the line keeps the date the model pairs it with); then per pass the date the model paired it with (id, cell, text) and the category; no pair: the model left the line out. Same: the milestone the analyst sees is the same in every pass (paired or not, the date Python keeps, the category).

| Deck | Page | Line | Cell | Line text | Python's date | Same | Pass 1 | Pass 2 | Pass 3 |
|---|---:|---|---|---|---|---|---|---|---|
| 02-moz.pdf | 2 | t1 | r1c1 | Rand starts working w/ Gillian building websites for small, local businesses | 1997 | yes | d1 r2c1 1997: other | d1 r2c1 1997: other | d1 r2c1 1997: other |
| 02-moz.pdf | 2 | t2 | r1c2 | Deeply in debt, and failing to get traffic to clients’ sites, Rand starts the SEOmoz Blog as part of learning the SEO process. | 2004 | no | d2 r2c2 2004: launch | d2 r2c2 2004: other | d2 r2c2 2004: launch |
| 02-moz.pdf | 2 | t3 | r1c3 | SEOmoz takes an investment of $1.1M from Ignition Partners & Curious Office | 2007-11 | yes | d3 r2c3 Nov. 2007: funding | d3 r2c3 Nov. 2007: funding | d3 r2c3 Nov. 2007: funding |
| 02-moz.pdf | 2 | t4 | r1c4 | Moz’scollection of tools becomes a singular, campaign-based web app. Prices rise to $99 / $499 / $1999 per month. | 2010-09 | no | d4 r2c4 Sept. 2010: launch | d4 r2c4 Sept. 2010: feature | d4 r2c4 Sept. 2010: feature |
| 02-moz.pdf | 2 | t5 | r4c1 | Gillian (Rand’s Mom) founds the company that will become SEOmoz | 1981 | yes | d5 r3c1 1981: other | d5 r3c1 1981: other | d5 r3c1 1981: other |
| 02-moz.pdf | 2 | t6 | r4c2 | Rand drops out of UW, 2 classes from graduation to work full time w/ Gillian | 2001 | yes | d6 r3c2 2001: other | d6 r3c2 2001: other | d6 r3c2 2001: other |
| 02-moz.pdf | 2 | t7 | r4c3 | SEOmoz launches its first subscription software product, “PRO” for $39/month | 2007-02 | yes | d7 r3c3 Feb. 2007: launch | d7 r3c3 Feb. 2007: launch | d7 r3c3 Feb. 2007: launch |
| 02-moz.pdf | 2 | t8 | r4c4 | Linkscape, SEOmoz’sweb index and link graph, launches. By December, mozis profitable. | 2008-10 | yes | d8 r3c4 Oct. 2008: launch | d8 r3c4 Oct. 2008: launch | d8 r3c4 Oct. 2008: launch |
| 02-moz.pdf | 2 | t9 | r4c5 | SEOmozis moving from just “SEO” to social media, content marketing, analytics, local and video. To this end, we’ve acquired “Moz.com.” | 2011-07 | yes | d9 r3c5 July 2011: expansion | d9 r3c5 July 2011: expansion | d9 r3c5 July 2011: expansion |
| 03-buffer.pptx | 6 | t1 | r1c1 | Launched web app | 2011-01 | yes | d1 r2c1 January 2011: launch | d1 r2c1 January 2011: launch | d1 r2c1 January 2011: launch |
| 03-buffer.pptx | 6 | t2 | r3c1 | 55,000 users ($150K revenue) | 2011-10 | yes | d2 r4c1 October 2011: other | d2 r4c1 October 2011: other | d2 r4c1 October 2011: other |
| 03-buffer.pptx | 6 | t3 | r5c1 | Launch the API | 2011-10 | yes | d3 r6c1 October 2011: launch | d3 r6c1 October 2011: launch | d3 r6c1 October 2011: launch |
| 03-buffer.pptx | 6 | t4 | r7c1 | Integrated in 50 apps | 2011-12 | yes | d4 r8c1 December 2011: partnership | d4 r8c1 December 2011: partnership | d4 r8c1 December 2011: partnership |
| 03-buffer.pptx | 6 | t5 | r9c1 | 100,000 users ($288K revenue) | 2012-01 | yes | d5 r10c1 January 2012: other | d5 r10c1 January 2012: other | d5 r10c1 January 2012: other |
| 03-buffer.pptx | 6 | t6 | r11c1 | 1 million users ($3.6M revenue) | 2013-01 | yes | d6 r12c1 January 2013: other | d6 r12c1 January 2013: other | d6 r12c1 January 2013: other |
| 10-tea.pdf | 11 | t1 | r1c2 | Second milestone ongoing in 2021 | 2021-Q2 | no | no pair | no pair | d1 r1c1 2021: other |
| 10-tea.pdf | 11 | t2 | r1c3 | Preview 1 version launch | 2021-Q3 | yes | d2 r1c4 2021: launch | d2 r1c4 2021: launch | d2 r1c4 2021: launch |
| 10-tea.pdf | 11 | t3 | r2c1 | Q2 | 2021 | yes | no pair | no pair | no pair |
| 10-tea.pdf | 11 | t4 | r2c2 | Gluon wallet | 2021-Q2 | no | d1 r1c1 2021: launch | d1 r1c1 2021: feature | d1 r1c1 2021: launch |
| 10-tea.pdf | 11 | t5 | r2c3 | Begin Go2Market strategy starting with miners' economy | 2021-Q3 | yes | d2 r1c4 2021: expansion | d2 r1c4 2021: expansion | d2 r1c4 2021: expansion |
| 10-tea.pdf | 11 | t6 | r2c4 | Q3 | 2021 | yes | no pair | no pair | no pair |
| 10-tea.pdf | 11 | t7 | r3c2 | Web3 Foundation Open Grant | 2021-Q2 | yes | d1 r1c1 2021: funding | d1 r1c1 2021: funding | d1 r1c1 2021: funding |
| 10-tea.pdf | 11 | t8 | r3c3 | Testnet starts | 2021-Q3 | yes | d2 r1c4 2021: launch | d2 r1c4 2021: launch | d2 r1c4 2021: launch |
| 10-tea.pdf | 11 | t9 | r4c2 | Migrating TEA runtime to Amazon Nitro | 2021-Q2 | yes | d1 r1c1 2021: feature | d1 r1c1 2021: feature | d1 r1c1 2021: feature |
| 10-tea.pdf | 11 | t10 | r5c2 | Seed round secured including investment from Hashkey | 2021-Q2 | yes | d1 r1c1 2021: funding | d1 r1c1 2021: funding | d1 r1c1 2021: funding |
| 10-tea.pdf | 11 | t11 | r6c2 | Public mining in preview mode | 2021-Q4 | yes | d3 r6c1 2021: launch | d3 r6c1 2021: launch | d3 r6c1 2021: launch |
| 10-tea.pdf | 11 | t12 | r6c3 | Testnet mining up to epoch 9 | 2022-Q1 | yes | d4 r6c4 2022: feature | d4 r6c4 2022: feature | d4 r6c4 2022: feature |
| 10-tea.pdf | 11 | t13 | r7c1 | Q4 | 2021 | yes | no pair | no pair | no pair |
| 10-tea.pdf | 11 | t14 | r7c2 | Rich dApps running on network | 2021-Q4 | yes | d3 r6c1 2021: feature | d3 r6c1 2021: feature | d3 r6c1 2021: feature |
| 10-tea.pdf | 11 | t15 | r7c3 | TEA Party dApp released | 2022-Q1 | yes | d4 r6c4 2022: launch | d4 r6c4 2022: launch | d4 r6c4 2022: launch |
| 10-tea.pdf | 11 | t16 | r7c4 | Q1 | 2022 | yes | no pair | no pair | no pair |
| 10-tea.pdf | 11 | t17 | r8c2 | Majority of business logic migrated from layer-1 to layer-2 | 2022-Q2 | yes | d5 r8c1 2022: feature | d5 r8c1 2022: feature | d5 r8c1 2022: feature |
| 10-tea.pdf | 11 | t18 | r8c3 | Layer-1 EVM smart contract compatibility | 2022-Q3 | yes | d6 r8c4 2022: feature | d6 r8c4 2022: feature | d6 r8c4 2022: feature |
| 10-tea.pdf | 11 | t19 | r9c1 | Q2 | 2022 | yes | no pair | no pair | no pair |
| 10-tea.pdf | 11 | t20 | r9c2 | TEA framework dev guide released | 2022-Q2 | yes | d5 r8c1 2022: feature | d5 r8c1 2022: feature | d5 r8c1 2022: feature |
| 10-tea.pdf | 11 | t21 | r9c4 | Q3 | 2022 | yes | no pair | no pair | no pair |
| 10-tea.pdf | 11 | t22 | r10c2 | Post-seed round secured | 2022-Q2 | yes | d5 r8c1 2022: funding | d5 r8c1 2022: funding | d5 r8c1 2022: funding |
| 10-tea.pdf | 11 | t23 | r11c2 | Last testing epochs before mainnet | 2022-Q4 | yes | d7 r11c1 2022: other | d7 r11c1 2022: other | d7 r11c1 2022: other |
| 10-tea.pdf | 11 | t24 | r11c3 | Mainnet starts | 2023-H1 | yes | d8 r11c4 2023: launch | d8 r11c4 2023: launch | d8 r11c4 2023: launch |
| 10-tea.pdf | 11 | t25 | r12c1 | Q4 | 2022 | yes | no pair | no pair | no pair |
| 10-tea.pdf | 11 | t26 | r12c2 | Migrate to AWS Nitro for all nodes | 2022-Q4 | yes | d7 r11c1 2022: feature | d7 r11c1 2022: feature | d7 r11c1 2022: feature |
| 10-tea.pdf | 11 | t27 | r12c4 | Q1-Q2 | 2023 | yes | no pair | no pair | no pair |
