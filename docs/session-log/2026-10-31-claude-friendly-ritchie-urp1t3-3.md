2026-10-31, claude/friendly-ritchie-urp1t3
Deleted: the DECK_FIXTURE-only branch and its separate "DECK_READING_PROMPT is not set" path for the job's decision (kept in read_decks for direct calls).
Decided: one deck_due() (DECK_FIXTURE=1 and the deck prompt set), the workflow's own converter condition, used by the preflight and by read_all; tokens in/out taken from the counting adapter wrapper, no gateway change.
Slow or unclear: the backend suite takes about 3.5 minutes and is moved to the background by the tool timeout; waited for it in the foreground.
Root cause: the job had two different conditions for "the deck is due", so a deck path change without the prompt read nothing yet reported no skip; one function now decides, and a test covers each missing half.
Process change to propose: when a workflow step and a script share a condition, name it once in the script and cite the workflow line in its docstring.
