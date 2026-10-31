Date and branch: 2026-10-31, claude/friendly-ritchie-urp1t3
Deleted: nothing.
Decided: one test in test_gateway_data_boundary.py uploads a sheet through the real flow and asserts the stored reading's prompt_text is in no response (register, audit, export JSON and CSV, cell window, Change) and no log line, as a string and as a key. It undoes the module-wide reader-off patch of tests/conftest.py inside the test, so the other tests in the file are unchanged. Nothing needed stripping: the export builds its fields by name.
Slow or unclear: the conftest switch that turns the sheet reader off cost one failed run before the test queued a reading.
Root cause and rule: the prompt text sits on the stored reading record, so only the explicit field lists in reading_export and register keep it off the wire; the new test fails when either gains the field (checked with three deliberate violations).
Process change to propose: a shared fixture that runs the sheet-reader flow, so boundary tests need not undo conftest patches.
