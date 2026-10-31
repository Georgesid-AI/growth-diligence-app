2026-10-31, branch claude/awesome-newton-l3l4zq.
Deleted: the narrow-screen CSS and its test, the deck "Show all" link and anchor line, the year, date, page-number, phone and background-page floors on page sending.
Decided: no-unit page figures compare exactly as counts; the suffix, sign and bracket reading lives in deck_figures, not in the shared parser; a heading-sourced period is dropped in figure_of, the heading goes to Label; a rate row with no label cell takes its label from the sheet's label column; tabs sit under the heading with the strip shown in All only.
Slow or unclear: no table-shape test exists in the repo to delete; the skip rule needed rule 16 reworded in CLAUDE.md.
Root cause and prevention: the rate row lost its label because the reader may cite no label cell and the lines builder trusted that cell; the new test builds the case on the yearly P&L fixture.
Process change to propose: name the test to delete by file and test name in the task, so it can be found without a search.
