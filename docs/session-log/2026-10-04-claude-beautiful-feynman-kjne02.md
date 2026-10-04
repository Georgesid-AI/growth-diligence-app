2026-10-04, claude/beautiful-feynman-kjne02.
Deleted: nothing in code; the drafted "words beside a figure" limit on borrowing was measured (recall 97% to 92%, precision +2 points) and not kept.
Optimized: recall 52% to 97% (89/92) by borrowing keyword and date from table header, text box, position and slide title; pdf columns kept apart; unpack cap; pass mark 95%, precision floor 30%.
Slow/unclear: precision is 34% (96/280): most false candidates are borrowed labels, date-only lines and chart axis numbers. Next improvement, not built: reduce false candidates, starting with date-only lines and chart axis numbers.
Process change: draft the answer file before running the parser on the decks, and measure recall against the spec rule before tuning it, so a rule change is a measured decision.
