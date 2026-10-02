# CLAUDE.md — working rules

## Architecture
1. Architecture is frozen. Never change it. Only execution steps may change.
2. Do not challenge the frozen architecture when questioning requirements. Only
   execution steps are open.
3. Do not confuse rigor with dumb. Evidence tiers, citations and source references
   are the core of the audit method. Challenge how they are built, never whether
   they exist.
9. If a fix needs an architecture change, stop and report it as an
   "Architecture note". Do not change it.

## Before and during coding
4. Before coding, in max 5 lines: (a) challenge the requirement: is it needed, who
   needs it, what is a simpler version; (b) list what can be deleted first.
5. Only then optimize what remains. Automate last, and only if it repeats.
6. Keep changes small. No new features unless asked.

## Finishing a task
7. A task is finished when the change is committed and pushed. Then create
   docs/session-log/YYYY-MM-DD-<branch>.md with max 5 lines: date, what was
   deleted, what was optimized, what was slow or unclear, one process change to
   propose. If that file already exists, add a number to the name
   (YYYY-MM-DD-<branch>-2.md, ...). Then commit and push the log. Pushing the log
   itself does not count as a finished task. Never log the log.
8. Never write client names or data into the log.
