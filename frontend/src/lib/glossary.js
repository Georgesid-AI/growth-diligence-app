// The abbreviations whose first use in a text block points to the glossary: "VaS (see glossary)", later uses plain
// (George, 2026-10-09). Mirrors GLOSSED and see_glossary in backend/app/formatting.py.
export const GLOSSED = ["VaS", "ARR", "MRR", "NRR", "CAC"];
export const SEE_GLOSSARY = "(see glossary)";

/** One text block (a help text, a note, a sentence the server writes) with each abbreviation of GLOSSED followed by
 *  "(see glossary)" at its first use; later uses stay plain. A term inside a compound ("NRR-compounded") is not a use.
 *  Idempotent. Not for labels, headings, column headers or figures. */
export function seeGlossary(text) {
  if (typeof text !== "string") return text;
  return GLOSSED.reduce((out, term) => out.replace(new RegExp(`(?<![\\w-])${term}(?![\\w-])( \\(see glossary\\))?`),
    (m, already) => (already ? m : `${m} ${SEE_GLOSSARY}`)), text);
}

/** Terms used in the narrative, dashboard and exports. Mirrors GLOSSARY in
 *  backend/app/formatting.py - keep the two in step. */
export const GLOSSARY = {
  ACV: "average contract value",
  "Landed ACV": "first-month ARR of a customer who has just landed, with no expansion applied",
  ARR: "annual recurring revenue",
  MRR: "monthly recurring revenue",
  NRR: "net revenue retention",
  CAC: "customer acquisition cost",
  VaS: "value at stake: the amount of ARR or cash that depends on this claim being true. ARR and cash are stated separately and never added together. Where several claims drive the same ARR or cash, the register shows the overlap, and the memo gives either a de-duplicated total or the largest single exposure and says which. Until the ARR bridge exists, ARR VaS is not computed and claims are ranked by the size of the gap to the data.",
};
