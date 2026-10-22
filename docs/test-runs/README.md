# Consistency run reports

`scripts/consistency_run.py` writes each live run's report here (`consistency_<date>.md`, then `-2`, `-3`, ... for a
later run that day) and, with `--diagnostic`, its diagnostic beside it (`consistency_<date>_diagnostic.md`). Commit
both after the run, on the branch it measured, so its numbers (agreement, match rate, tokens and cost) stay with the
code. A `--fake` run writes to the system temp folder, never here.

The diagnostic holds the cell text sent to the model. `--diagnostic` runs on the 10 public test decks only
(`tests/fixtures/decks/decks/`, checked by file name and SHA-256) and refuses any other deck, so the files here hold
public test-deck text only, never a client's (CLAUDE.md rule 15).

`scripts/consistency_run.py --pages` (docs/design/ai-reads-rules-check.md section 7, PR B) writes its run output here as
`pages_<date>.md` (`-2`, `-3`, ... for a later run that day): agreement on (value cell, metric, period), claims, tokens and an
upper-bound cost per deck and pass, and whether it stopped at `--max-spend`. It holds no deck text. The model's replies are recorded
beside the hand-written ones, under `backend/tests/fixtures/page_replies/recorded/pages_<date>/pass-<n>/`; each file holds the
model's claims for one page and, to find the page again, its first line as sent, so the 10 public test decks only. Commit both after
the run. `--zip` bundles both under their repository paths.

`scripts/compare_pipelines.py --recorded pages_<date> --md docs/test-runs/pages_<date>_compare.md` replays a run's recorded replies
through the gateway and page_check, pass by pass, and writes the compare tables here: per deck and pass the rules read (A) and the
page read (B) with matched, unmatched and dropped claims and recall and precision against the answer file; the agreement across the
passes with the disagreeing claims by kind; every unmatched or dropped claim grouped by the check that failed, with page and cell
ids. Counts, cell ids, values, types and statuses; no deck text. The hand-written reading of a run (what failed and why, what to
change in the prompt or in page_check, what the next run should cost) goes beside it as `pages_<date>_analysis.md`.
