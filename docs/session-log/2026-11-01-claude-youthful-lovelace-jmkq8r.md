2026-11-01, branch claude/youthful-lovelace-jmkq8r (PR 4d).
Deleted: nothing; the shape-based learning of row labels was narrowed, not removed elsewhere.
Decided: label column and header rows of a metric-by-period sheet (a row with 3+ period headers) are never learned as company names, only coded when the map holds the name; counted apart as row_labels; ledgers unchanged.
Slow or unclear: whether a customer-by-month table with unknown names should still learn its label column (now it does not unless the name is known from another file or sheet).
Root cause: _company_cell learned any text below any company-name header cell (a "Customers"/"Clients" cell anywhere above it in the column), with no regard for where the cell sat; rule: names are learned from customer columns, never from label columns of period sheets.
Process change: add a masking test with a synthetic row-label set whenever a learning rule is added or widened.
