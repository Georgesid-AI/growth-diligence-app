2026-10-23, claude/dazzling-ramanujan-rgbzeu
Deleted: the 100,000 limit and the old refusal wording ("the prompt text is over N characters").
Decided: store limit 10,000 (George) with the message "Prompt is n characters; the limit is 10,000."; no pydantic max_length on the API model, so the store is the one validator and the message is the same everywhere; the page refuses over the limit before sending and never cuts; list_versions counts the stored text and returns `chars` only (data-boundary test extended); old versions over 10,000 stay loadable.
Slow or unclear: the task premise (truncation at about 4,000) did not match the code (no such limit; store limit was 100,000), so I stopped and asked; George chose option 1.
Root cause and rule: a premise that contradicted the code was caught by reading the code before editing; rules 12 and 13 (stop and ask when spec and code disagree) did their job.
Process change to propose: a task that quotes a current limit names the file or line it comes from, so the check takes one grep.
