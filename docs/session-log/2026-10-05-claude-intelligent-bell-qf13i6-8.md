2026-10-05, claude/intelligent-bell-qf13i6.
Deleted: text cell values from the column-mapping path (text columns now send a profile only), and CRM deal names as a place where substring replacement applies.
Optimized: the column-mapping path can no longer leak a name, so the only text the model sees is deck structure cells, which carry all the redaction rules; the known limit is stated once.
Slow/unclear: a column profile is neither a header nor a sample value, the two things rule 16 names; read here as a redacted sample, which carries less than one.
Process change: when a decision removes data from a path, re-read every rule that mentions that data and remove what no longer applies.
