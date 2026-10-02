2026-10-02, fix/create-audit-dates (2).
Deleted: whole-column pd.to_datetime guess in normalize; two target-date test cases that already passed before the fix.
Optimized: one parse_date_column for every mapped date field; target_date and as_of_month share the ISO round-trip rule.
Slow/unclear: no notes list in results, so the "order set from data" note went into anomalies; ambiguous invoice rows also count in "no usable invoice date".
Process change: add a fixed "Notes" results key for non-blocking data assumptions instead of reusing anomalies.
