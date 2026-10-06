# Consistency run reports

`scripts/consistency_run.py` writes each live run's report here (`consistency_<date>.md`, then `-2`, `-3`, ... for a
later run that day) and, with `--diagnostic`, its diagnostic beside it (`consistency_<date>_diagnostic.md`). Commit
both after the run, on the branch it measured, so its numbers (agreement, match rate, tokens and cost) stay with the
code. A `--fake` run writes to the system temp folder, never here.

The diagnostic holds the cell text sent to the model. `--diagnostic` runs on the 10 public test decks only
(`tests/fixtures/decks/decks/`, checked by file name and SHA-256) and refuses any other deck, so the files here hold
public test-deck text only, never a client's (CLAUDE.md rule 15).
