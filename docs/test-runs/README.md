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
