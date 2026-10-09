/** Terms used in the narrative, dashboard and exports. Mirrors GLOSSARY in
 *  backend/app/formatting.py - keep the two in step. */
export const GLOSSARY = {
  ACV: "average contract value",
  "Landed ACV": "first-month ARR of a customer who has just landed, with no expansion applied",
  ARR: "annual recurring revenue",
  MRR: "monthly recurring revenue",
  NRR: "net revenue retention",
  CAC: "customer acquisition cost",
  "Value at stake": "The amount of ARR or cash that depends on this claim being true. ARR and cash are stated separately and never added together. Where several claims drive the same ARR or cash, the register shows the overlap, and the memo gives either a de-duplicated total or the largest single exposure and says which. Until the ARR bridge exists, ARR value at stake is not computed and claims are ranked by the size of the gap to the data.",
};
