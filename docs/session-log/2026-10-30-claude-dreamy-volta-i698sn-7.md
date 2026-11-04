2026-10-30, claude/dreamy-volta-i698sn
Deleted: nothing; the prompt version label no longer takes part in the stored-reading key.
Decided: sheet_reading goes to the adapter with temperature 0 (call and retry); reading key uses a 16-hex hash of the prompt text sent, version label kept as display field; fixtures job builds its own empty store and fails on any cache hit.
Slow or unclear: the adapter withholds temperature from Sonnet/Opus (MODELS_ACCEPTING_TEMPERATURE), so on the allow-listed models temperature 0 does not reach the provider; the test asserts the gateway's outbound call.
Root cause and rule: a key built on a hand-bumped label let an edited prompt reuse an old reading; the key now derives from the text itself, so no manual step can be forgotten.
Process change to propose: moved to docs/pr6-cleanup.md or docs/pr6-cleanup-archive.md.
