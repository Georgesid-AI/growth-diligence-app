// docs/specs/claim-groups.md: the screen reads the server's roles, groups and questions; it relates, sums and chooses nothing.
import {
  KEPT_NOTE, countsOf, countsText, detailsLabel, figureText, groupQuestions, partsLabel, partsOf, questionTitle, visibleRows,
} from "./claimGroups";

const total = { claim_id: "a1", group_id: "g1", group_role: "total", rank: 1 };
const q1 = { claim_id: "q1", group_id: "g1", group_role: "part", rank: 2 };
const q2 = { claim_id: "q2", group_id: "g1", group_role: "part", rank: 3 };
const same = { claim_id: "a2", group_id: null, group_role: null, rank: 4 };
const alone = { claim_id: "x1", group_id: null, group_role: null, rank: 5 };
const rows = [total, q1, q2, same, alone];

test("a part is shown under its total, every other row is an item, a repeat of a figure included", () => {
  expect(visibleRows(rows).map((r) => r.claim_id)).toEqual(["a1", "a2", "x1"]);
  expect(visibleRows(undefined)).toEqual([]);
});

test("the parts of a total are its parts, in the server's order; a row that is no total has none", () => {
  expect(partsOf(total, rows).map((r) => r.claim_id)).toEqual(["q1", "q2"]);
  expect(partsOf(alone, rows)).toEqual([]);
  expect(partsOf(q1, rows)).toEqual([]);
});

test("the parts of another set and a figure stated again are shown under Details too, also for a row that is no total", () => {
  const h1 = { claim_id: "h1", group_id: "g1", group_role: "also", rank: 6 };
  const again = { claim_id: "a9", group_id: "g1", group_role: "repeat", rank: 7 };
  const lead = { claim_id: "b1", group_id: "s1", group_role: null, rank: 8 };
  const repeat = { claim_id: "b2", group_id: "s1", group_role: "repeat", rank: 9 };
  const all = [...rows, h1, again, lead, repeat];
  expect(visibleRows(all).map((r) => r.claim_id)).toEqual(["a1", "a2", "x1", "b1"]);
  expect(partsOf(total, all).map((r) => r.claim_id)).toEqual(["q1", "q2", "h1", "a9"]);
  expect(partsOf(lead, all).map((r) => r.claim_id)).toEqual(["b2"]);
  expect(countsOf(all)).toEqual({ items: 4, claims: 9, groups: 1 });
});

test("the collapsed line of Details counts the parts, the other set, the repeats and the contradicted ones", () => {
  const parts = [{ group_role: "part", evidence_label: "Verified" }, { group_role: "part", evidence_label: "Contradicted" },
    { group_role: "also", evidence_label: "Verified" }, { group_role: "repeat", evidence_label: "Verified" }];
  expect(detailsLabel(parts)).toBe("Details · 2 parts · 1 in another set · 1 repeat · 1 contradicted");
  expect(detailsLabel([{ group_role: "repeat" }, { group_role: "repeat" }])).toBe("Details · 2 repeats");
  expect(detailsLabel([{ group_role: "part", evidence_label: "Verified" }])).toBe("Details · 1 part");
});

test("displayed items are counted apart from the claims underneath, and only when something is grouped", () => {
  expect(countsOf(rows)).toEqual({ items: 3, claims: 5, groups: 1 });
  expect(countsText(countsOf(rows))).toBe("3 items shown for 5 claims; 1 annual total stands for its parts.");
  expect(countsText(countsOf([alone]))).toBeNull();
  expect(countsText({ items: 1, claims: 9, groups: 2 })).toBe("1 item shown for 9 claims; 2 annual totals stand for their parts.");
  expect(partsLabel(1)).toBe("1 part");
  expect(partsLabel(4)).toBe("4 parts");
});

test("an open question and a conflict that stays after a choice are one card each, by question id", () => {
  const open = { id: "r1", kind: "total", state: "open", candidates: [] };
  const chosen = { id: "r2", kind: "total", state: "chosen", candidates: [] };
  expect(groupQuestions({ reviews: [open], conflicts: [open, chosen] }).map((q) => q.id)).toEqual(["r1", "r2"]);
  expect(groupQuestions(null)).toEqual([]);
});

test("a candidate figure reads in its own currency and a question names its metric and period", () => {
  expect(figureText({ value: 1250000, currency: "EUR" })).toContain("1,250,000");
  expect(figureText({ value: 120, currency: null, unit: "customers" })).toBe("120 customers");
  expect(questionTitle({ kind: "total", metric: "Revenue", period: "FY2024" })).toBe("Which annual figure should the audit use? Revenue, FY2024");
  expect(KEPT_NOTE).toContain("stay as claims");
});
