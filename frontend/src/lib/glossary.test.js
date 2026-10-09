import { GLOSSARY, GLOSSED, seeGlossary } from "./glossary";
import { REVENUE_REQUIRED_NOTE } from "./chatUpload";
import { SETUP_HELP } from "./auditForm";
import { REGISTER_COLUMNS } from "./claimRegister";

// George, 2026-10-09: "Value at stake" reads VaS; the first use of VaS, ARR, MRR, NRR or CAC in a text block reads
// "VaS (see glossary)", later uses plain.
describe("abbreviations point to the glossary at their first use in a text block", () => {
  test("the first use of each term gets the pointer, later uses stay plain", () => {
    expect(seeGlossary("ARR rose 10%; ARR is now 1,000,000 EUR and NRR 105%, NRR flat"))
      .toBe("ARR (see glossary) rose 10%; ARR is now 1,000,000 EUR and NRR (see glossary) 105%, NRR flat");
    expect(seeGlossary("VaS of the claim; CAC payback; New MRR")).toBe("VaS (see glossary) of the claim; CAC (see glossary) payback; New MRR (see glossary)");
  });

  test("each text block starts again, a compound is not a use, the pointer is never doubled", () => {
    expect(["ARR up", "ARR down"].map(seeGlossary)).toEqual(["ARR (see glossary) up", "ARR (see glossary) down"]);
    expect(seeGlossary("NRR-compounded base at NRR")).toBe("NRR-compounded base at NRR (see glossary)");
    expect(seeGlossary("ARRAY, barr, arr")).toBe("ARRAY, barr, arr");
    const once = seeGlossary("ARR and MRR");
    expect(seeGlossary(once)).toBe(once);
    expect(seeGlossary(null)).toBeNull();
  });

  test("the glossary defines every term the pointer names, VaS included", () => {
    expect(GLOSSED.filter((t) => !GLOSSARY[t])).toEqual([]);
    expect(GLOSSARY.VaS).toMatch(/^value at stake: /);
    expect(GLOSSARY["Value at stake"]).toBeUndefined();
  });

  test("Value at stake reads VaS on screen: the register column and the help text", () => {
    expect(REGISTER_COLUMNS).toContain("VaS");
    expect(REGISTER_COLUMNS).not.toContain("Value at stake");
    expect(SETUP_HELP.target_arr).toBe("The plan figure the audit tests. Every claim's VaS (see glossary) is measured against it.");
    expect(SETUP_HELP.target_date).toBe("When the plan says Target ARR (see glossary) is reached. Sets the forecast horizon.");
    expect(REVENUE_REQUIRED_NOTE).toBe("The revenue file is the only required file. Every metric in the audit – ARR (see glossary), "
      + "NRR (see glossary), churn, CAC (see glossary) payback – is computed from it; without it nothing can be calculated or verified.");
  });
});
