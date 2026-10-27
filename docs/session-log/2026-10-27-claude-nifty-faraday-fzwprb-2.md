2026-10-27 · claude/nifty-faraday-fzwprb (is_quote drop, segment and share_of display)
Deleted: nothing; the drop reuses the existing drop path (checker.drop_reason, the Diagnostics line, the dropped count).
Decided: a quoted figure is a drop kind checked first, so the existing counts and Diagnostics apply; the panel count is read from the stored Diagnostics lines, no new stored field; the row carries page_segment and page_share_of so they never collide with the register's segment; no contract bump, the deck list's closed claim fields are unchanged.
Slow or unclear: "Why column" has no heading of that name; I read it as the reasons under Extraction confidence, and the label as the "Label from" line of the claim cell.
Root cause and rule: a field carried with no behaviour (is_quote) waits for a design line; the design section now states what each of the four fields does.
Process change to propose: a design section that adds a model field lists its behaviour in the same edit, even when it is "none".
