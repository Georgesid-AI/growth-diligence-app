2026-10-30, claude/dreamy-volta-i698sn
Deleted: nothing.
Decided: 4xx provider message goes on the "structure not read" line (capped 300, quoted spans/figures blanked, dropped if it holds a token, key or 20 characters of anything sent); sheet_reading schema keeps the first 16 nullable fields as unions and makes the rest optional, because the provider caps union parameters at 16 and optional at 24.
Slow or unclear: whether the 400 is the union limit is unconfirmed until the CI run; the log line will now say.
Root cause and rule: the generator made all 35 nullable fields unions and nothing checked the provider's numeric limits; the schema test now asserts both limits and every unsupported construct.
Process change to propose: run the reading-fixtures job on a schema change in this repository's PRs before merge, not only on the reading path.
