2026-10-02, fix/create-audit-dates (3).
Deleted: double count of ambiguous invoice-date rows in "no usable invoice date".
Optimized: ambiguous row ids travel in frame attrs from normalize to build_mrr_matrix; no new results keys.
Slow/unclear: "reach the gateway" vs. anomalies being outside every step slice; the gateway test is a guard and cannot fail before the change.
Process change: when asking for a boundary check, say whether a field should reach the model or must stay out.
