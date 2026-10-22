# Pages run 2026-10-22: analysis (PR B)

Reading of the live run recorded in `pages_2026-10-22.md` and under `backend/tests/fixtures/page_replies/recorded/pages_2026-10-22/`,
from the recorded replies replayed by `scripts/compare_pipelines.py --recorded pages_2026-10-22` (tables in `pages_2026-10-22_compare.md`).
No live call was made. Counts, cell ids and values; the few cell texts quoted are from the public test decks.

## 1. The eight batches not read

64 calls for 51 batches: 13 replies failed validation. 8 batches failed twice (not read); 3 replies were accepted on the reask
(moz pass 1 twice, buffer pass 1 once). The output tokens of each deck-pass, less about 107 tokens per recorded claim (the mean of
the 20 deck-passes read in full), say what the failed attempts produced:

| Deck, pass | Calls | Batches read | Output tokens | Of which the read claims | Left for the failed attempts | Kind |
|---|---:|---|---:|---:|---:|---|
| 05-zero2hero.pdf, 1 / 2 / 3 | 3 each | 1 of 2 | 9,048 / 9,057 / 8,953 | ~700 | ~8,300 each pass = 2 x 4,000 | cut at PAGE_MAX_TOKENS (4,000), twice |
| 01-front-b.pptx, 1 | 3 | 1 of 2 | 2,365 | ~1,300 | ~1,000 (1 attempt) | a normal-length reply the schema refused |
| 01-front-b.pptx, 2 | 4 | 1 of 2 | 3,359 | ~1,300 | ~2,000 (2 attempts) | same |
| 06-uber.pdf, 1 / 3 | 4 each | 2 of 3 | 1,997 / 1,810 | ~900 | ~1,000 (1 attempt each) | same |
| 06-uber.pdf, 2 | 5 | 2 of 3 | 3,083 | ~1,100 | ~2,000 (2 attempts) | same |

So the "eight schema failures" are two things. Three (zero2hero batch 1: pages 5, 11, 14, 17, 19, 263 lines, two 5-year tables) are
replies cut at the 4,000-token output limit: the cut JSON fails the schema with check=schema, and the reask is cut again at the same
place. Five (front-b batch 2 in passes 1 and 2, uber in every pass) are replies of about 1,000 tokens, 8 to 10 claims, that the
schema refused for a field value the log did not name: a period outside the closed forms, a cell id without its page, a unit_other
that is not an ISO code, or a value_high without a value. The reask returned the same shape and failed again. The gateway now logs
`fields=<name>` on such a line (closed schema names), so the next run tells.

Fixes in this PR: the adapter reports a reply stopped at max_tokens as "truncated" with the tokens it billed; the gateway bills it,
logs the closed reason and does not reask; the page step splits the batch and reads the halves (a single page still cut keeps the
status); PAGE_MAX_TOKENS is 8,000 (the 350 tokens per page of the design note were 90 to 150 tokens per claim on the run, and a
5-page batch of tables needs more than 4,000). The script's spend guard bills the cut call.

## 2. Did passes 2 and 3 hit the cache?

No. Each pass read each deck in its own audit (`pages-<deck>-pass<n>`) and the gateway's cache is keyed by audit, so no pass could be
served from it; every pass's row shows input tokens for every call (a cache hit logs 0 tokens), and of the 39 pages read in all three
passes 23 differ between passes and 16 are identical. The identical token counts of equals-seed (194 x 3), tea (500 x 3) and
genesisai-2021 (450 / 449 / 450) are the model repeating itself, not the cache. The agreement therefore measured the model.

Fixes in this PR: `read_pages` takes `use_cache`; the run passes `use_cache=False` from pass 2 on (as the structure run does) and the
report counts each pass's cache hits (expected 0), so a pass that measured the cache would show as such.

## 3. The match rate: 161 of 371 recorded claims (43%)

Replay of the recorded replies through page_check, over the three passes (the table's 160 of 356 is over the run's own claims; see 4):

| Cause | Claims | Share | What it is |
|---|---:|---:|---|
| matched | 161 | 43% | |
| other | 101 | 27% | every check passed; the metric is "other", which never matches by design |
| dropped: not_plan | 38 | 10% | funds raised, valuations, token supply, industry size, founder bios: dropped before any check, as the rules read drops them |
| period | 25 | 7% | the model's period is right but no period cell was cited, or the cited cell is not a date source of the value cell |
| period+other | 14 | 4% | |
| value | 13 | 4% | the figure is in a title line, or written as "1.2+MM", "$31+ Billion", "$2.8T" (see 6) |
| unit+period | 9 | 2% | one cell: LTV / CAC ratios with no "x" on the page and one date line for three figures |
| value+period | 4 | 1% | |
| value+other | 3 | 1% | |
| unit | 3 | 1% | a profit range with no currency mark on the page (the check is right) |

118 of the 172 unmatched rows (69%) are figures the model labelled "other". The answer file lists some of them under a metric
(moz p21: trials converting to paid = sales, churn = retention; buffer p7: 2% conversion = sales; clevergig p6: 30% of leads via
referrals = sales; front-b p12: spend as % of revenue = sales), and most as not a plan claim (use-of-funds splits, market shares,
commission rates, integrations, updates). Rows per cause with deck, page, cell, metric and value: `pages_2026-10-22_compare.md`.

## 4. The per-pass lines against the report table

The recorded files hold 371 claims; the table counts 356. They disagree in both directions in 9 of 30 deck-passes:

| Deck | Table (passes 1 / 2 / 3) | Recorded files |
|---|---|---|
| 01-front-b.pptx | 7 / 6 / 19 | 11 / 11 / 19 |
| 02-moz.pdf | 35 / 33 / 40 | 35 / 34 / 38 |
| 03-buffer.pptx | 21 / 21 / 20 | 22 / 22 / 21 |
| 04-clevergig.docx | 14 / 21 / 18 | 18 / 21 / 18 |

The script writes a pass's recorded files and the table row from the same list of claims, so one run cannot produce both: the files
under `pages_2026-10-22/` and the committed table come from two runs of that day. The run name is chosen from the report file alone,
so a run that stopped or crashed before writing its report (or a run in another checkout, or a zip unpacked over the folder) leaves a
recorded folder the next run of the day writes into, page by page: the folder ends up a union of two runs. The per-pass lines George
saw on screen belong to whichever run printed them. Which run's figures are right cannot be told from the files; the compare tables
use the recorded files, since they hold the claims.

Fixes in this PR: the run name skips a name whose recorded folder exists; the report is rewritten after every pass beside the recorded
files, so both always come from one run; each row counts the claims recorded (equal to its claims); tokens, cost, truncated batches
and cache hits come from the gateway's call log of the pass, which bills every attempt, the cut and split ones included.

## 5. Prompt changes for George to upload (page_claims v2)

The prompt is not in the repository (rule 26); each change names the rows it fixes.

1. Which figures to report: the company's own plan figures only. Do not report funds raised, valuations, use-of-funds splits, token
   supply or allocation, industry or market size, cited research, or figures in a founder's biography. Fixes the 38 dropped rows
   (zero2hero p22 r2c1-r7c3, tea p9 r3c3 and p12 r2c1-r5c1, moz p2 r3c3 and p23 r1c2-r3c2, equals-seed p10 r2c1, genesisai p5 r5c1
   and p13 r4c1, clevergig p2 r9c1, front-b p15 r3c1-r3c2, uber p24 r4c2, buffer p12 r5c1) and about 60 of the 101 "other" rows;
   fewer claims also mean fewer output tokens and fewer chances to disagree between passes.
2. The metric list with one line per metric saying what counts: conversion of trials or free users to paid = sales; churn and
   net retention = retention; visits, members, subscribers of a free product = users; marketing spend as a share of revenue = sales;
   gross margin in any wording = gross_margin; a price plan is not a metric (do not report). Fixes the metric disagreements between
   passes (19 claims: moz p21 r1c2, r2c2; buffer p7 r2c1, r3c1; clevergig p6 r5c1, p7 r6c1, r11c1, r16c1; genesisai-2021 p12 r3c1,
   p13 r3c1, p14 r4c2; genesisai-2024 p12 r3c1, p13 r3c1) and turns the "other" rows that the answer file types into matches.
3. The period cell: when the period is written in the value line itself, cite the value cell as period_cell (clevergig p11 r3c1 and
   r5c1, genesisai-2024 p5 r3c1, moz p3 r5c1: 14 rows); when it is written in the label line next to the figure, cite the label line
   (moz p20 r1c2, p21 r6c2: 6 rows); for a bar, cite its axis year label (genesisai-2024 p4 r4c1); never cite "per month" or
   "p.m." as a period (clevergig p7 pass 3: 3 rows); a line of several dates beside a line of several figures: the nth date for the
   nth figure, cited as the same cell (front-b p12 r7c3 and r8c3: 18 rows, see 6).
4. The period forms, with examples, and what to write otherwise: YYYY, YYYY-Qn, YYYY-Hn, YYYY-MM, FY2025, FY2025/26; "by end of
   2024" is 2024 (the run wrote 2024-12 in pass 1 and 2024 in passes 2 and 3: 4 of the 6 clevergig period disagreements); "in 10
   months", "2 years", a day of the month, a range of years: null. The five normal-length replies the schema refused (front-b batch
   2: pages 14, 15, 16, 18; uber batches 1 and 2) most likely carried such a period; the `fields=` log line of the next run confirms.
5. Units: a ratio written without "x" (LTV / CAC) is unit x; a figure with no currency mark on the page (uber p20 r3c6
   "20-30M+ per year profit") takes the currency only when the page states it, else null.

## 6. page_check changes to propose (the model was right, the check wrong)

Not built here (rule 11: beyond the task); each with the rows that show it. Rows count over the three passes.

1. A figure in a title line: `items.list_items` skips title cells, so the value check finds no item. front-b p6 r1c1 (2300
   companies, 3 rows), moz p31 r1c1 (40 Mozzers, 3), moz p35 r1c2 (300K marketers, 3), moz p3 r3c1 (83% margins, 3): 12 rows.
2. A "+" between the number and its scale: "1.2+MM", "$31+ Billion" read as 1.2 and 31 by `verify.figures` (the rules reader
   `claims.find_numbers` reads 1,200,000). moz p3 r5c2 (3 rows), moz p9 r6c2 (2): 5 rows.
3. The trillion scale: "$2.8T" reads as 2.8 in `verify.figures` (`claims._SCALE` knows T). genesisai-2024 p4 r3c1: 3 rows.
4. No period cell cited, but the value cell's own text, or an adjacent date label, rebuilds the model's period: pass with that cell
   (the design's own list of sources; a difference counts as a correction). clevergig p11 r3c1 (6 rows), r5c1 (3), genesisai-2024
   p5 r3c1 (3), moz p20 r1c2 (3), moz p3 r5c1 (2): 17 rows. Prompt change 3 fixes the same rows from the other side; one of the two
   is enough.
5. A date line of N dates beside a value line of N figures: the nth date is the nth figure's period. front-b p12 r6c3 "Q1 17 Q2 17
   Q3 17" over r7c3 and r8c3: 18 rows (r8c3 also needs 6).
6. A ratio metric (ltv_cac) claimed as unit x when the figure carries no unit of its own passes the unit check. front-b p12 r8c3:
   9 rows.
7. A neighbouring line that holds its own figure is not a date source for a value cell: genesisai-2024 p5 r4c1 "2,600+ users" fails
   a null period because r3c1 "$8,000 revenue in 2022" is read as a date label next to it. 3 rows.

The unit check on uber p20 r3c6 (no currency mark) and the null-period check on genesisai-2024 p4 r4c1 (the bar's year label stands
below it) are right as they are.

## 7. A second live run: cost and what to expect

Cost of the first run at list price: 221,394 input and 80,669 output tokens, $1.25 (the real bill is lower: about 130,000 of the
input tokens were the cached prompt, read at a tenth of list). Of that, about $0.44 was spent on failed attempts: the six cut
replies (24,000 output tokens, $0.24, plus their input) and the ten normal-length attempts that failed the schema or were reasked.

With the fixes of this PR and no prompt change, the ten decks, three passes, 5 pages per call: about 55 to 60 calls, 220,000 input
and 70,000 to 80,000 output tokens, $1.10 to $1.30 upper bound at list (zero2hero batch 1 read once per pass at up to 8,000 output
tokens, or split once more if still cut), well under `--max-spend 4`. With prompt changes 1 and 2 the claims fall by about a third
(no funds, no use of funds, no "other" figures), so about $0.90 to $1.10.

Agreement, if the fixes hold: the eight presence disagreements of front-b and the one of uber come from batches read in one pass only
and disappear when every batch is read, which gives 102 agreed of 141 (72%) on the run's own replies. The 19 metric and 10 period
disagreements are the prompt's (changes 2 to 4); if they go, agreement is about 93%, and the 95% target needs the metric mapping to
be closed enough that the same figure gets the same word in every pass. Expect 85 to 90% on the second run, 95% only if changes 1
to 4 land together.

Match rate, if the fixes hold: today 161 of 371 (43%). Prompt changes 1 and 2 remove the 38 dropped and most of the 118 "other"
rows from the denominator and turn about 20 of them into matches: about 75 to 80% of the claims returned. The seven page_check
changes of section 6 add about 55 matched rows: about 90%.

## 8. Decisions for George

1. May a claim whose metric is "other" be "Matched to page" when its figure, unit and period pass? 101 rows in this run. Today it is
   never matched by design (decision 3a). Recommend no: keep "other" unmatched and stop the model reporting such figures (prompt
   change 1), since most are not plan claims.
2. Which of the seven page_check changes (section 6) to build; recommend 1, 2, 3 and 7 (reader fixes, no new source of a period) now
   and 4, 5, 6 only if prompt change 3 does not take.
3. PAGE_MAX_TOKENS 8,000: raises the upper bound a call can cost from $0.04 to $0.08 of output; the guard still stops at --max-spend.
