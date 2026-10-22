# Pages run 2026-10-22-2: analysis (PR B, run 2)

Reading of the second live run (prompt page_claims v2), recorded in `pages_2026-10-22-2.md` and under
`backend/tests/fixtures/page_replies/recorded/pages_2026-10-22-2/`, from the recorded replies replayed by
`scripts/compare_pipelines.py --recorded pages_2026-10-22-2` (tables in `pages_2026-10-22-2_compare.md`). No live call was made.
Counts, cell ids and values; the few cell texts quoted are from the public test decks. The replay reproduces the run's own figures
(323 matched, 58 unmatched, 3 dropped of 384 claims; 79.7% agreement over the decks every pass read in full).

## 1. Run 2 next to run 1

Per deck, both runs replayed through one page_check: the code of this branch before this PR's changes 5 and 6 (PR #162's reader
fixes included), so the two columns are measured by the same check. The compare table committed with PR #161 counted run 1 with
the page_check of that day (49 / 54 / 58 matched per pass); with PR #162 it is 53 / 60 / 64. Three figures per cell are the
three passes; "r1 / r2" is run 1 then run 2. Recall and precision are against the answer file (company claims).

| Deck | Sent | Batches read r1 / r2 | Matched r1 / r2 | Unmatched r1 / r2 | Dropped r1 / r2 | B recall r1 / r2 | B precision r1 / r2 | Agreement r1 / r2 |
|---|---:|---|---|---|---|---|---|---|
| 01-front-b.pptx | 9 | 1 / 1 / 2 of 2 / 1 / 1 / 1 of 2 | 3 / 3 / 9 / 5 / 5 / 5 | 8 / 8 / 8 / 1 / 2 / 6 | 0 / 0 / 2 / 0 / 0 / 0 | 50% / 50% / 67% / 28% / 33% / 50% | 82% / 82% / 71% / 67% / 71% / 82% | 57.9% / 54.5% (not complete) |
| 02-moz.pdf | 15 | 3 / 3 / 3 of 3 / 3 / 3 / 3 of 3 | 16 / 17 / 19 / 25 / 21 / 25 | 18 / 16 / 18 / 3 / 3 / 3 | 1 / 1 / 1 / 0 / 0 / 0 | 86% / 86% / 86% / 86% / 86% / 86% | 53% / 55% / 49% / 64% / 75% / 64% | 69.8% / 79.3% |
| 03-buffer.pptx | 6 | 2 / 2 / 2 of 2 / 2 / 2 / 2 of 2 | 15 / 15 / 15 / 19 / 20 / 19 | 6 / 6 / 5 / 0 / 0 / 0 | 1 / 1 / 1 / 0 / 0 / 0 | 85% / 85% / 85% / 80% / 85% / 80% | 81% / 81% / 85% / 84% / 85% / 84% | 87.0% / 85.7% |
| 04-clevergig.docx | 5 | 1 / 1 / 1 of 1 / 1 / 1 / 1 of 1 | 10 / 12 / 10 / 18 / 17 / 17 | 7 / 8 / 7 / 1 / 1 / 1 | 1 / 1 / 1 / 0 / 0 / 0 | 86% / 100% / 86% / 93% / 93% / 93% | 71% / 70% / 71% / 68% / 72% / 72% | 50.0% / 80.0% |
| 05-zero2hero.pdf | 6 | 1 / 1 / 1 of 2 / 2 / 2 / 2 of 2 | 0 / 0 / 0 / 32 / 32 / 32 | 6 / 6 / 6 / 8 / 9 / 8 | 0 / 0 / 0 / 0 / 0 / 0 | 0% / 0% / 0% / 89% / 91% / 89% | 0% / 0% / 0% / 78% / 78% / 78% | 100.0% (1 of 2 batches) / 80.0% |
| 06-uber.pdf | 15 | 2 / 2 / 2 of 3 / 3 / 3 / 3 of 3 | 6 / 8 / 6 / 6 / 7 / 6 | 1 / 1 / 1 / 0 / 0 / 0 | 1 / 1 / 1 / 1 / 1 / 1 | 75% / 75% / 75% / 75% / 75% / 75% | 43% / 33% / 43% / 50% / 43% / 50% | 88.9% / 87.5% |
| 07-equals-seed.docx | 3 | 1 / 1 / 1 of 1 / 1 / 1 / 1 of 1 | 1 / 1 / 1 / 0 / 0 / 0 | 0 / 0 / 0 / 0 / 0 / 0 | 1 / 1 / 1 / 0 / 0 / 0 | 100% / 100% / 100% / 0% / 0% / 0% | 100% / 100% / 100% / - / - / - | 100.0% / 100.0% |
| 08-genesisai-2021.pdf | 4 | 1 / 1 / 1 of 1 / 1 / 1 / 1 of 1 | 1 / 0 / 1 / 0 / 0 / 0 | 3 / 4 / 3 / 1 / 4 / 2 | 1 / 1 / 1 / 0 / 0 / 0 | - / - / - / - / - / - | 0% / 0% / 0% / 0% / 0% / 0% | 42.9% / 25.0% |
| 09-genesisai-2024.pdf | 5 | 1 / 1 / 1 of 1 / 1 / 1 / 1 of 1 | 1 / 4 / 3 / 4 / 4 / 4 | 5 / 2 / 3 / 2 / 2 / 1 | 1 / 1 / 1 / 0 / 0 / 0 | 100% / 100% / 100% / 100% / 100% / 100% | 33% / 33% / 33% / 33% / 33% / 40% | 40.0% / 83.3% |
| 10-tea.pdf | 4 | 1 / 1 / 1 of 1 / 1 / 1 / 1 of 1 | 0 / 0 / 0 / 0 / 0 / 0 | 0 / 0 / 0 / 0 / 0 / 0 | 5 / 5 / 5 / 0 / 0 / 0 | 0% / 0% / 0% / 0% / 0% / 0% | - / - / - / - / - / - | 100.0% / 100.0% |
| all, pass 1 | | 43 / 48 of 51 | 53 / 109 | 54 / 16 | 12 / 1 | 51% / 72% | | |
| all, pass 2 | | | 60 / 106 | 51 / 21 | 12 / 1 | 52% / 74% | | |
| all, pass 3 | | | 64 / 108 | 51 / 21 | 14 / 1 | 53% / 75% | | |
| all | | | | | | | | 68.0% / 77.8% (all decks); 70.9% / 79.7% (complete decks) |

Run 1's batches read are the run's own (the replay reads every recorded page). The run 1 "sent" column is the same as run 2's.

What changed between the runs, and why:

1. **Prompt v2** (changes 1 to 4 of the run 1 analysis) took the non-plan figures out of the replies: dropped claims 38 to 3, claims
   with the metric "other" 118 to 15, while the matched claims went from 53 / 60 / 64 to 109 / 106 / 108 per pass and B recall
   against the answer file from 51 to 53% to 72 to 75%. Claims per pass rose (107 to 115, then 125 to 129) because the batches
   that failed in run 1 were read.
2. **PR #161's fixes**: zero2hero batch 1 is no longer cut at the output limit (PAGE_MAX_TOKENS 8,000; 0 truncated batches),
   so its two five-year tables are read in every pass (32 matched per pass, 0 before); uber's three batches are read in every
   pass; every pass bypassed the cache (0 hits). front-b batch 2 is still not read (section 3): 48 of 51 batches read, 43 before.
3. **Agreement** 68.0% to 77.8% over all decks (70.9% to 79.7% over the complete decks). The disagreeing claims fell from 48 to
   32 (metric 19 to 10, period 10 to 10, presence 19 to 12) on a union of 150, then 144. The period disagreements are new in kind:
   run 1's were period forms (2024-12 against 2024), run 2's are a bar chart's year cells (section 2c).
4. **Cost**: 64 calls and $1.25 to 55 calls and $0.93 (upper bound at list price); output tokens 80,669 to 50,287, since fewer
   figures are reported and no reply is cut.
5. Not changed: the rules read (A: 232 rows, 96% recall, unchanged code); front-b's recall (50% to 67% in run 1 with batch 2 read
   once, 28% to 50% in run 2 with batch 2 never read).

## 2. Diagnosis

### 2a. genesisai-2021: agreement 25%

The deck has no plan claim: the answer file lists none as a company claim and the rules read finds 0 rows. The union is 4 claims,
all with the metric "other" (never matched by design): p13r3c1 ("Over 25 partnerships", count 25) in all three passes, p8r3c1
(300%, "quality of AI products") in passes 2 and 3, p12r3c1 (30% of marketplace transactions) and p14r4c2 (30% commission) in pass
2 only. 1 agreed of 4 = 25%. In run 1 the same four cells were claimed in every pass (plus p13r4c1, funds raised, dropped; and
p8r3c1 as product against other): 3 of 7 = 42.9%, the disagreements being metric words. Prompt v2 removed the funds row and made
the model unsure whether to report these figures at all: pass 2 reported all four, passes 1 and 3 one or two. So the 25% measures
the model's consistency on figures the prompt tells it not to report, on a deck with nothing to find; none of the four could ever
reach the register as matched. Fix on the prompt side (change A below); on the measure side, see section 7.

### 2b. The remaining unmatched rows by cause

58 rows over three passes as run; 49 after this PR's page_check changes 5 and 6 (section 4). Rows per cause, with the cells:

| Cause | Rows | Cells | Reading |
|---|---:|---|---|
| unit (10) and unit+period (5) | 15 | zero2hero p17 r9c2, r10c2, r15c2, r16c2, r17c2 (the five bars 550,508 / 415,107 / 278,085 / 181,193 / 49,284, claimed GBP) | The only currency mark on the page is the axis title r2c1 "Turnover(£/year)", not adjacent to any bar; the adjacency rule refuses. The five are the deck's revenue series (five company claims). In pass 2 the model cited r19c2 "2020" for every bar, so four of the five fail the period too; in passes 1 and 3 each bar's own year label is cited and passes. Decision 1 (section 8). |
| other | 15 | clevergig p6 r5c1 (30% of leads via referrals, 3 rows); genesisai-2021 p8 r3c1 (2), p12 r3c1 (1), p13 r3c1 (3), p14 r4c2 (1); genesisai-2024 p12 r3c1 (3), p13 r3c1 (2) | Every check passes; "other" never matches. The answer file types clevergig p6 r5c1 as sales (a company claim); the rest are not plan claims (product performance, commission rates, partnerships). Prompt changes A and B. |
| period | 14 (5 after this PR) | front-b p12 r7c3 (18% / 18% / 19% under "Q1 17 Q2 17 Q3 17": 5 rows, fixed by change 5); moz p3 r3c1 ("maintain margins of 83%+", period 2011 citing the title sentence, 3); moz p20 r2c2 ("~$10.8 million", period 2011-06 citing "Current Revenue Run Rate (June)", 3); moz p21 r6c2 ("~$1 million", period 2011 citing "Estimated Net Profit in 2011", 3) | moz p3: a sentence is no source (#154), right. moz p20: the cited label holds a month and no year, right to refuse (the answer file gives no date). moz p21: the label next to the figure holds the year and nothing else dated, but four other words, so it is not a date label by the roadmap rule; the answer file says 2011. Decision 2. |
| unit+period, ltv_cac | 4 (0 after this PR) | front-b p12 r8c3 (2.5 / 2.6 / 4.4 under the same date line, unit x) | No "x" on the page and the date line two rows up: changes 5 and 6. |
| value | 9 | zero2hero p11 r5c4 "($52 B)", r14c3 "($570 B)", r15c4 "($374B)" (market, 3 passes) | The bracket reads as a negative (-52,000,000,000) and the model says 52,000,000,000. Not plan claims (market sizes for 2028 in the answer file): prompt change A removes them; a reader fix is not worth its code (decision 3). |
| dropped: not_plan | 3 | uber p24 r4c2 "Growing to a $3.5B industry by 2010" | The industry word drops it, as the rules read does; right. |
| no value | 1 | zero2hero p19 r5c1 "Positive EBITDA", ebitda, 2024-Q2 (pass 2 only) | A milestone, never matched by design, dated from its source (the answer file lists it as a company claim). Its presence in one pass only is prompt change F. |

### 2c. The remaining disagreements by kind

32 disagreeing claims on a union of 144 over all decks (27 of 133 over the complete decks). By kind, with every cell:

- **Presence (12)**: moz p16 r2c1 (market 5%, passes 1 and 3), moz p18 r4c1 / r4c2 / r4c3 (users 55% / 35% / 10%, passes 1 and
  3): a share split prompt v2 left optional (not in the answer file); genesisai-2021 p8 r3c1, p12 r3c1, p14 r4c2 (section 2a);
  genesisai-2024 p13 r3c1 (other, passes 1 and 2); zero2hero p19 r5c1 (the EBITDA milestone, pass 2); front-b p12 r8c3 (the three
  LTV / CAC figures, passes 2 and 3: pass 1 did not report the line; front-b is not among the complete decks). Of the 12, 9 are
  figures with the metric "other" or no plan claim at all: prompt change A removes them from the union.
- **Metric (10)**: buffer p5 r5c1 (40%: growth in pass 3, user_growth in 1 and 2; the answer file says user_growth); buffer p7
  r4c1 (1,000,000: users in pass 2, another word in 1 and 3); clevergig p2 r7c1 and p6 r3c1 (15%: growth in pass 1, revenue_growth
  in 2 and 3; the answer file says revenue growth); moz p35 r3c2 (2x: growth in pass 2, revenue_growth in 1 and 3); uber p25 r6c2
  (5: people in pass 2, another word in 1 and 3). Eight of the ten are the one word "growth" against "revenue_growth" or
  "user_growth": prompt change B.
- **Period (10)**: zero2hero p17 r9c2, r10c2, r15c2, r17c2 (8 triples: pass 2 cites r19c2 "2020" for every bar, passes 1 and 3
  cite each bar's own year label); front-b p12 r7c3 (2 triples: pass 3 reports all three figures of the line with their three
  quarters, passes 1 and 2 report one figure with 2017-Q1). The zero2hero eight are the model wrong in one pass and page_check
  right in every pass: the four wrong citations are unmatched. Prompt changes C and E.

Over the complete decks, agreement is 79.7% on every claim, 81.7% (103 of 126) with the metric "other" left out and 87.2% (95 of
109) over the claims page_check matched (the rows that reach the register without a click). zero2hero is 80.0% on every claim
and 100% (32 of 32) on matched claims: the check caught the pass that disagreed.

## 3. front-b batch 2 (pages 14, 15, 16, 18): what the schema refused

Facts from the run: 3 calls per pass for 2 batches; batch 1 (pages 6, 12, 13 and two more) read in every pass with 6 / 7 / 11
claims; batch 2 (pages 14, 15, 16, 18: 22 + 17 + 20 + 12 lines) refused twice in every pass with `fields=claims check=schema`.
Output tokens 2,837 / 2,839 / 3,444 per pass; batch 1's claims at about 107 tokens each take 640 / 750 / 1,180, which leaves
about 2,200 / 2,100 / 2,260 for the two refused attempts: about 1,100 tokens, 8 to 10 claims, each time. The same reply, three
passes, six attempts; a reask carries no hint of what was wrong, so it repeats.

What `fields=claims` means. The provider enforces the JSON schema (structured output), so a reply cannot fail on an enum, a type or
a missing key. Pydantic checks four things beyond the JSON schema: the period form, the cell-id form, finite numbers (each on its
own field: a failure names it, `fields=period`) and three rules on the claim as a whole, whose error location is the claim's index
with no field name: unit_other must be an ISO currency code outside the listed 20 when unit is "other", unit_other must be null
otherwise, value_high needs a value. `fields=claims` is the last named location, so the refusal was one of these three, in every
pass.

Which one, from the page text. Page 18 line r3c1 reads "2.5 hours" with r4c1 "per user per day" under it. "hours" is not a unit
of the list (%, x, count, days, months, years, currencies), so the model writes unit "other" with unit_other "hours" (or unit null
with unit_other "hours"): both are refused by the whole-claim rules, and the page is the same on every attempt. Page 14's r7c1
"5.0" (a Glassdoor rating; unit_other "rating" or "stars") and r8c6 "17 Ratings" would fail the same way. Nothing on the four
pages suggests a value_high without a value, and a period such as "in 10 months" (page 15 r7c5) would have named `fields=period`.
The answer file itself lists the page 18 figure with unit "hours". Most likely, then: unit_other "hours" on p18r3c1 (code
`unit_other_not_iso`), with the ratings as a second candidate; the next run's record file names the claim index, the field and the
code, so this is the last time it is inferred. The six lost readings cost about $0.07 per pass and the deck six of its eighteen
answer-file claims (page 14 attrition 0, page 15 cash $7m, runway 18 months, profitable in 10 months, 5% growth assumption, page
16 the 2018 target): front-b's recall of 28 to 50% is this one batch. Fix on the prompt side (change D); the schema rule is right
as it is (a word in unit_other would be deck text in the store).

What this PR adds (task 3): a rejected reply's validation errors are read back to closed codes (`gateway.SCHEMA_CODES`: period_form,
cell_id_form, not_finite, unit_other_not_iso, unit_other_without_other, value_high_without_value, literal, missing, extra, type,
json, other) with the claim's index and the schema field, on the "structure not read" line as `errors=claims[3].unit_other:
unit_other_not_iso`, in llm_calls as `schema_errors`, in the deck's page_reads entry (check, fields, schema_errors) and, for a
pages run, in a record file `<deck>_p14-p18.failed.json` beside the recorded replies. Never the value, pydantic's message or the
reply. The compare script lists the record files under "Batches not read".

## 4. page_check changes 4, 5, 6 of the run 1 analysis

- **4** (no period cell cited, the value cell's own text or an adjacent date label rebuilds the period): **not built**. 0 claims of
  run 2 carry a period without a period cell (17 rows in run 1); prompt change 3 took. Nothing left for it to fix.
- **5** (a date line of N dates beside a line of N figures: the nth date is the nth figure's period): **built**. The nearest line
  above the value cell in its own text box and column that is a date line of as many dates as the cell holds figures, with only
  lines of as many figures between them, dates the figure at position n with the nth date; among equal figures the position
  whose date is the model's period is taken; the model's period, when it is another, is replaced and counted as a correction; a
  null period under such a line is not matched. Fixes front-b p12 r7c3 (5 rows) and the period half of r8c3 (4 rows).
- **6** (a ratio metric claimed as unit x with a bare figure passes the unit check): **built** for `RATIO_METRICS = {ltv_cac}`
  when the figure states no unit of its own. Fixes front-b p12 r8c3 (4 rows).

Replay of run 2 with 5 and 6: matched 323 to 332, unmatched 58 to 49; front-b matched 5 / 5 / 5 to 6 / 7 / 11 (every front-b
claim matched). Recall against the answer file is unchanged (a value found counts whether matched or not).

## 5. Script hardening (task 4)

- A run takes a lock document in its scratch database (`run_lock`), heartbeats it after every deck and pass and releases it at the
  end; a second run on the same database stops before any call while the heartbeat is younger than 30 minutes, and the start-up
  drop of old scratch databases leaves one a run holds and stops. A stale lock is a crashed run's and is taken over.
- Every line a run prints and the gateway's "structure read" and "structure not read" lines go to `<CONSISTENCY_RUN_LOG_DIR or
  ~/.growth-diligence/run-logs>/<run name>.log`, refused inside the repository; `--fake` writes under the temp folder. The last
  run's checks were inferred from token counts because the lines were on screen only.

## 6. Prompt changes for George to upload (page_claims v3)

The prompt is not in the repository (rule 26); each change names the rows it fixes.

- **A. Nothing with the metric "other".** A figure that is none of the listed metrics is not reported: no market or industry size,
  share split, commission rate, product performance, partnership or community count. Fixes the 15 "other" rows (clevergig p6
  r5c1 aside, which B types), the 9 value rows of zero2hero p11, and 9 of the 12 presence disagreements (moz p16 r2c1, p18
  r4c1-r4c3, genesisai-2021 p8 r3c1, p12 r3c1, p14 r4c2, genesisai-2024 p13 r3c1): genesisai-2021 would then have a union of 0
  and agreement 100%, as equals-seed and tea do.
- **B. Growth words.** Growth of revenue, MRR, ARR or bookings is revenue_growth; growth of users, customers or members is
  user_growth; "growth" alone only when the page does not say what grows. A share of leads or trials that convert is sales.
  Fixes 8 of the 10 metric disagreements (buffer p5 r5c1, clevergig p2 r7c1 and p6 r3c1, moz p35 r3c2) and the clevergig p6 r5c1
  "other" rows. buffer p7 r4c1 (1,000,000 users, a forecast assumption) and uber p25 r6c2 (5 people) need the list line for users
  against customers and for people.
- **C. Bars.** For a bar's data label, cite the year label of that bar as period_cell, never one year cell for every bar. Fixes
  the 8 period disagreements of zero2hero p17 and the 4 period failures of its pass 2.
- **D. Units outside the list.** When a figure's unit is none of the listed ones (hours, ratings, stars, sessions, visits), do not
  report the figure (A covers most) or, for a listed metric, write unit null and unit_other null; unit_other takes an ISO
  currency code only and is otherwise null. Fixes front-b batch 2 (section 3: 6 refused attempts, 6 answer-file claims never read).
- **E. One claim per figure in a line of several.** A line of N figures under a line of N dates gives N claims, the nth with the
  nth date and the date line as period_cell. Fixes the 2 period disagreements of front-b p12 r7c3 and the presence of r8c3
  (passes 1 and 2 reported one figure of three, pass 1 none of the ratios).
- **F. Milestones.** A dated line without a figure ("Positive EBITDA" over "Q2 2024") is reported in every pass as a claim with
  value null and the date line as period_cell. Fixes zero2hero p19 r5c1 (pass 2 only). Alternative: never report one; the answer
  file lists it, so the recommendation is to report it.

## 7. Go / no-go for PR C (the switch to the AI pipeline)

**No-go on run 2.** The numbers:

| Measure | Run 2 | Bar |
|---|---:|---|
| Batches read in every pass | 48 of 51 (front-b batch 2 lost three times) | 51 of 51 |
| Agreement, every claim, complete decks | 79.7% | 95% (design note section 6) |
| Agreement, "other" left out | 81.7% | |
| Agreement, matched claims only | 87.2% (95 of 109) | |
| Match rate (matched of claims) | 84% (323 of 384); 86% with changes 5 and 6 | |
| B recall against the answer file | 72 / 74 / 75% per pass; A (the rules read) 96% | PR B's own bar: 95% |
| B precision on the decks with claims | 64 to 85% (A: 14 to 83%) | |

The strongest reason is the recall: PR C deletes the rules read, and the page read finds three quarters of the company claims the
rules read finds today (front-b's lost batch, zero2hero's unit refusals and the moz periods are most of the gap). The second is
the lost batch itself: a refused batch loses whole pages, not a claim.

What run 3 (prompt v3, this PR's gateway and page_check) must show for a go: every batch read in every pass (a record file is a
no-go on its own); B recall against the answer file at least 90% and within five points of A's; agreement on matched claims at
least 95%; agreement on every claim at least 90%, reported beside it; an unmatched rate under 10% (each unmatched claim is a
click). From the run 2 rows, prompt changes A to F and page_check changes 5 and 6 take the union of the complete decks to about
110 claims with 3 to 5 disagreements left (the two cells of B's second sentence, the moz p21 period), so 95% on matched claims
is in reach; recall stays at about 85% until front-b batch 2 reads and the zero2hero unit question (decision 1) is settled, so
the recall gate is the one most likely to hold run 3 back.

On the bar: 95% agreement on (value cell, metric, period) over every claim measures the model twice for things the analyst never
sees. It counts claims page_check refuses (zero2hero p17 pass 2: eight disagreements, every one caught and unmatched) and claims
with the metric "other" that never match (genesisai-2021: three of its four). The measure that matters for the switch is what
enters the register without a click: agreement on matched claims, with recall against the answer file beside it (the switch
must not lose claims the rules find) and the unmatched rate (the clicks it adds). Recommendation: keep 95%, on matched claims;
add the recall and batches-read gates above; report every-claim agreement as a second line, not a gate. Decision 4.

## 8. Decisions for George

1. **page_check change 8**: a chart's axis title ("Turnover(£/year)") as the unit source for the bars of that chart, as the
   structure read's table corner is for a scale. 15 rows (zero2hero p17), the deck's whole revenue series; without it the five
   revenue claims never match. Recommend build: narrow (a unit mark in the axis title of the bars' own chart, nothing else).
2. **page_check change 9**: a label line directly next to the value cell that holds exactly one date ("Estimated Net Profit in
   2011") is a period source. 3 rows (moz p21 r6c2). Recommend build, narrow (one date, adjacent, no figure in the label).
3. **"($52 B)"**: a bracket holding a currency sign read as a parenthesis, not a negative. 9 rows, all market sizes the answer
   file lists as not plan claims. Recommend no: prompt change A removes them.
4. **The PR C bar** (section 7): 95% on matched claims with recall and batches-read gates, or 95% on every claim as the design
   note says. Recommend the first.
5. Prompt v3 (section 6) to upload to the store before run 3 (rule 26).
