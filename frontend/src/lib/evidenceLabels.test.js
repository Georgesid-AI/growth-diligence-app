// docs/design/simplified-flow.md, "Evidence labels": one definition per label, from one shared string, in the note's words.
import fs from "fs";
import path from "path";
import labels from "./evidence_labels.json";
import { LABEL_DEFINITIONS, LABEL_ORDER, labelDefinition } from "./claimRegister";

const read = (rel) => fs.readFileSync(path.join(__dirname, "../../..", rel), "utf8").replace(/\s+/g, " ");
const capital = (s) => s[0].toUpperCase() + s.slice(1);

test("the five labels, in the note's order, each with the definition the note gives", () => {
  expect(LABEL_ORDER).toEqual(["Verified", "Unverified", "Unsupported", "Contradicted", "Inconclusive"]);
  expect([...LABEL_ORDER].sort()).toEqual([...labels.statuses].sort());
  const note = read("docs/design/simplified-flow.md");
  LABEL_ORDER.forEach((label) => {
    expect(note).toContain(`**${label}** — ${LABEL_DEFINITIONS[label].replace(/\.$/, "")}`);
  });
});

test("evidence-labels.md section 2 says the same, word for word", () => {
  const spec = read("docs/specs/evidence-labels.md");
  LABEL_ORDER.forEach((label) => expect(spec).toContain(`| ${label} | ${capital(LABEL_DEFINITIONS[label].replace(/\.$/, ""))}`));
});

test("the hover is the label and its definition; a Definition check is no label and has none", () => {
  expect(labelDefinition("Unverified")).toBe(`Unverified: ${LABEL_DEFINITIONS.Unverified}`);
  expect(labelDefinition("Definition check")).toBeUndefined();
  expect(labelDefinition(null)).toBeUndefined();
});
