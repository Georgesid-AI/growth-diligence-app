2026-10-31, claude/sleepy-thompson-mj7ztr
Deleted: the fixture script's direct gateway call and its token column (it now goes through the sheet reader).
Decided: a reading stores its prompt text as sent (`prompt_text`) and a re-read uses it with the record's version and model, no store lookup; a failed re-read keeps the first reading as read and notes "re-read not completed: <reason>"; the job reads through read_file, so the one-call cap is the failing re-read; the job's preflight draws the deck fixture and a workflow step installs LibreOffice.
Slow or unclear: the full backend suite takes about 170 s and moves to the background past the 2-minute foreground limit. The stored `prompt_text` is a storage change for George's approval under rule 32.
Root cause: the re-read depended on state outside its record (the live prompt store), and the workflow assumed a converter the runner image does not carry. Rule: a derived call takes all its inputs from the record it derives from; a job that needs a tool checks it first.
Process change: have every workflow step that needs a system tool include a presence-check test, as the converter check now does.
