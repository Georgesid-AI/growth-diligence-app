# Reading consistency: a second read of the same input

Status: built 2026-11-04 (brief of George, items 5 to 8; commit 2 of the reconciliation and reading-consistency PR). Architecture change (CLAUDE.md rule 32):
approved by George on #237 (2026-11-04), with the per-audit token cap raised from 400,000 to 600,000.

## What changes

A model reading is not repeatable, so what a read gives is checked against a second read of the same input.

**Spreadsheets.** `sheet_reading` runs twice on the same masked payload, the same prompt text and the same model (`gateway.read_structure(second_read=True)`).
The first read is the stored reading, as before. The second is stored beside it in `reading_second_reads` (insert-only, one per reading; model JSON output
with the series, tokens and cost; no cell text). `app/consistency.py` compares the two file maps:

* a row both reads give with the same role, metric, series (actual and plan), segment flag, parent row, unit, currency and basis is stored as it is (unit, currency and basis added 2026-11-05, George: they are read into the figures, so a difference is one; each candidate button names the differing value);
* a row that differs, or that only one read gives, stays stored with the first read's values and is marked "Reading uncertain – confirm" on the file's tab,
  with both candidates;
* a sheet-level field that differs (granularity, header row, last actual column) or a sheet only one read gives is marked the same way on the Detected
  layout block;
* the analyst picks one candidate (`POST /audits/{id}/readings/{file_hash}/uncertain`, `{key, pick: first|second}`): an override record (item
  `uncertain:...`), like a Change. Nothing is picked automatically. Picking the first reading records the decision and changes nothing; picking
  the second reading of a sheet only the first read gave removes the sheet from the effective map (review of commit 2, 2026-11-05).
* while a sheet-level item waits (the sheet itself, or granularity, header row or last actual column), every row of that sheet is held out of the
  calculations with the rows the reads disagree on (`consistency.held_rows`): the rows' series and the as-of month are read under that layout, so
  they are in doubt with it. A difference in the last actual column flags no row of its own, so without this rule its rows would compute under a
  disputed boundary (review of commit 2, 2026-11-05).

**Deck pages.** Each page is read twice (`pages.read_pages(seconds=...)`, `PAGE_SECOND_READ=0` switches it off). The second reply is stored in
`llm_structures` under a key of its own with type `page_claims_second`; the first reply names it (`second_key`) so a check again of the stored reply
(`renormalise_audit`) compares the two as before. `pages.merge_reads` accepts a figure both reads give with the same page, metric, period and value. Any
other figure is stored with the review flag `reading uncertain` and a correction that waits (`field` "reading", one button per reading): it is listed in
the review tab and on the deck's tab in the reading screen, and used by no reconciliation, rating or verdict until the analyst chooses (the existing
`answer_correction` route; Undo brings the card back). A chosen reading stands through a Re-read of the deck, a Run audit and a new upload of the
file: `apply_reply` lists no new row for a cell whose reading the analyst chose on that reply, whichever reading they took (review of commit 2,
2026-11-05: before, choosing the second reading and re-reading the deck brought the uncertain card back beside the chosen figure).

**Ratings.** `role_metrics.awaiting_confirmation` {count, rows, figures} counts every uncertain sheet row and deck figure (George, 2026-11-04: no fixed role
list). Both are held out of the calculations until the analyst chooses (`role_engine.confirmed_rows`); a metric that needs only held rows reads "awaits
confirmation" (`mark_awaiting`). The first read's values stay stored. When the count is not zero each rating line says "N figures await confirmation" (`verdict.ratings`) and the memo's
Summary says it once.

**Cost.** The second read reuses what is stored: a file or page whose second read is stored makes no call; a file read before this change makes the one
new call. A failed second read stores nothing, leaves the first reading standing and flags nothing (the file's tab says "second read not completed").
Both reads log their tokens per call (`llm_calls.read_no` 1 and 2, with the file hash or the deck id).

## What does not change

What reaches the model: the same payload twice. What is stored: model JSON output only (rule 17); the second read adds `reading_second_reads` and
`llm_structures` records of type `page_claims_second`, deleted with the audit (rule 22: `purge_audit`, `purge_file`, `delete_structures`).

## Second pass (brief of George, 2026-11-05)

**Compare rules.** A difference in the segment flag alone is no disagreement (the flag is no longer compared). A deck figure the two page reads agree on
in metric and value, one with a period and one without, is accepted with the period; a figure of the metric `other` is never raised. An override already on
a row (an analyst's Change) settles the fields it sets: the item keeps the fields it left open, or goes when it left none. Rows of one sheet with identical
candidate pairs (position and cells aside) are one item with one pick that applies to all of them (`rows`, "rows 6–9"); the key is the first row's. The
mapping flag skips the role `other`.

**Held rows.** While a row an OPEX-split estimate is built from (OPEX, S&M, R&D, G&A) is held out, the S&M, R&D and G&A estimates and a "No estimate" line read
"awaits confirmation"; the trend rows gain `reason`; the templated lines (`report_text`) read a role whose rows are all held as "awaiting". Contract 22.

**The All section.** Four categories, each with a one-line explanation: Matches source, Doesn't match source, Uncertain (the list: file or page, row or
figure, what differs, first and second reading, Use first / Use second) and Needs attention (renamed from Needs review). The per-file tab keeps its cards in
the same words; the Detected layout block is unchanged. Above Run audit a line counts the readings that await confirmation and links to the list; Run audit
stays enabled; the reading step says "M uncertain readings". M counts the lines of the list (a group of rows is one).

**Tokens.** The tester ledger keeps `read1_tokens` and `read2_tokens` beside `tokens`; a token cap's "ai call refused" line ends with `first=` and `second=`
(the allowance's line still names no amount). A review that stopped on the reviewer's token cap or the tester's allowance is stored with `stopped`; the
register then says `review.stopped` ({reviewed, total}) and marks every Matches-source row `unreviewed`.

