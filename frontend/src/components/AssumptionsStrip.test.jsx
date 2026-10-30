import React, { act } from "react";
import { createRoot } from "react-dom/client";

import AssumptionsStrip from "./AssumptionsStrip";

/**
 * The as-of month on the assumptions strip (docs/design/read-check-review.md section 6, PR 2): the month, a typed month marked "set by analyst",
 * "not determined" when no file gave a confirmed month, and under the line the evidence in the reader's words. Run with --no-cache (rule 25).
 */
globalThis.IS_REACT_ACT_ENVIRONMENT = true;

const q = (id) => document.body.querySelector(`[data-testid="${id}"]`);
let host, root;
const show = async (audit, results = null) => {
  host = document.createElement("div");
  document.body.appendChild(host);
  root = createRoot(host);
  await act(async () => { root.render(<AssumptionsStrip audit={audit} results={results} onChange={() => {}} />); });
};
afterEach(async () => { await act(async () => { root.unmount(); }); host.remove(); });

const AUDIT = { reporting_currency: "EUR", target_arr: 0, fiscal_year_end: 12, datasets: {} };

describe("the as-of month on the assumptions strip", () => {
  test("a month the reader confirmed shows with its evidence line", async () => {
    await show({ ...AUDIT, as_of_month: "2025-06-30", as_of_by: "detected", as_of_file: "monthly.xlsx",
      as_of_evidence: "Customers row stops at G (confirmed on sheet Report, column G)" });
    expect(q("assumption-as-of").textContent).toBe("As-of month June 2025");
    expect(q("assumption-as-of-evidence").textContent).toBe("Detected from monthly.xlsx: Customers row stops at G (confirmed on sheet Report, column G)");
  });

  test("a typed month reads 'set by analyst' and the evidence line keeps the files' proposal beside it", async () => {
    await show({ ...AUDIT, as_of_month: "2025-03-31", as_of_by: "analyst",
      as_of_proposal: { month: "2025-06-30", file: "monthly.xlsx", evidence: "Customers row stops at G" } });
    expect(q("assumption-as-of").textContent).toBe("As-of month March 2025 (set by analyst)");
    expect(q("assumption-as-of-evidence").textContent).toBe("Set by analyst. The files proposed Jun 2025: Customers row stops at G.");
  });

  test("with no confirmed month the strip says 'not determined' and shows no evidence line", async () => {
    await show({ ...AUDIT, as_of_month: null, as_of_by: "detected" });
    expect(q("assumption-as-of").textContent).toBe("As-of month not determined");
    expect(q("assumption-as-of-evidence")).toBeNull();
  });
});
