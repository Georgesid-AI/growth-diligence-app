2026-10-02, fix/create-audit-dates.
Deleted: inline date check in AuditHub, type="month" inputs (both moved to one ISO helper and type="date").
Optimized: one date rule in lib/auditForm.js; backend refuses non-ISO as_of_month instead of pandas guessing day/month order.
Slow/unclear: npm registry blocked, so jest/jsdom could not be installed; the input-type bug could only be proven in Chromium, not in a unit test.
Process change: allow registry.npmjs.org in the cloud environment so frontend tests run in sessions.
