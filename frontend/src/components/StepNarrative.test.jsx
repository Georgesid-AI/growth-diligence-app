import React, { act } from "react";
import { createRoot } from "react-dom/client";

import StepNarrative from "./StepNarrative";
import { NarrativeControl } from "./NarrativeControl";
import * as api from "@/lib/api";

jest.mock("@/lib/api", () => ({
  readNarrative: jest.fn(), generateNarrative: jest.fn(),
  NARRATIVE_TIMEOUT_MS: 150000, NARRATIVE_EXPECTED_SECONDS: 33,
}));

globalThis.IS_REACT_ACT_ENVIRONMENT = true;

const NARRATIVE = {
  headline: "Material concerns: the revenue file and the P&L differ by 10% over the window.",
  what_this_means: "The revenue file is above the P&L.",
  table_rows: [{ label: "Revenue file against P&L", value: "10%", source_key: "S1", decision_informed: "Whether revenue can be relied on" }],
  worth_flagging: ["3 revenue lines have no customer ID."],
  next_actions: ["Ask management to reconcile the files.", "Ask for the CRM export."],
  source_keys: ["S1"], verdict: "Material concerns",
};

let host;
let root;
beforeEach(() => { host = document.createElement("div"); document.body.appendChild(host); root = createRoot(host); jest.resetAllMocks(); });
afterEach(() => { act(() => root.unmount()); host.remove(); jest.restoreAllMocks(); });

const mount = async (props) => {
  await act(async () => { root.render(<StepNarrative auditId="a1" ready onChanged={jest.fn()} {...props} />); });
};
const q = (id) => host.querySelector(`[data-testid="${id}"]`);

test.each(["data_inventory", "data_integrity"])("%s has one Write narrative button with the growth-engine helper text and cost note", async (step) => {
  api.readNarrative.mockResolvedValue({ narrative_status: "not_generated" });
  await mount({ step });
  const button = q(`narrative-generate-${step}`);
  expect(button.textContent).toBe("Write narrative");
  expect(host.querySelectorAll("button")).toHaveLength(1);
  const helper = q(`narrative-helper-${step}`).textContent;
  expect(helper).toContain("Writes a short summary of the numbers below, in plain English.");
  expect(helper).toContain("Costs one AI request");
  // The same words as the growth-engine control.
  const growth = document.createElement("div");
  const r2 = createRoot(growth);
  act(() => r2.render(<NarrativeControl status="not_generated" busy={false} onGenerate={() => {}} />));
  expect(growth.querySelector('[data-testid="narrative-helper"]').textContent).toBe(helper);
  act(() => r2.unmount());
});

test("opening reads a saved narrative and never generates one", async () => {
  api.readNarrative.mockResolvedValue({ narrative_status: "not_generated" });
  await mount({ step: "data_integrity" });
  expect(api.readNarrative).toHaveBeenCalledWith("a1", "data_integrity");
  expect(api.generateNarrative).not.toHaveBeenCalled();
});

test("the button writes this step's narrative and shows the verdict, the decision informed column and a ranked list", async () => {
  api.readNarrative.mockResolvedValue({ narrative_status: "not_generated" });
  api.generateNarrative.mockResolvedValue({ narrative_status: "ok", narrative: NARRATIVE, row_labels: {}, generated_at: "2026-10-11T10:00:00Z" });
  const onChanged = jest.fn();
  await mount({ step: "data_integrity", onChanged });
  await act(async () => { q("narrative-generate-data_integrity").click(); });
  expect(api.generateNarrative).toHaveBeenCalledWith("a1", "data_integrity");
  expect(q("narrative-verdict-data_integrity").textContent).toContain("Material concerns");
  expect(host.textContent).toContain("Decision informed");
  expect(q("narrative-row-decision").textContent).toBe("Whether revenue can be relied on");
  expect(host.textContent).toContain("1.Ask management to reconcile the files.");
  expect(host.textContent).toContain("2.Ask for the CRM export.");
  expect(onChanged).toHaveBeenCalled();
});

test("the inventory's next actions read as the ranked data request list", async () => {
  api.readNarrative.mockResolvedValue({ narrative_status: "ok", narrative: { ...NARRATIVE, verdict: null }, row_labels: {} });
  await mount({ step: "data_inventory" });
  expect(host.textContent).toContain("Data request list (ranked)");
  expect(q("narrative-verdict-data_inventory")).toBeNull();
});

test("when the gateway fails the step says so and the page is not blocked (rule 20)", async () => {
  api.readNarrative.mockResolvedValue({ narrative_status: "not_generated" });
  api.generateNarrative.mockRejectedValue(new Error("provider down"));
  jest.spyOn(console, "error").mockImplementation(() => {});
  await mount({ step: "data_inventory" });
  await act(async () => { q("narrative-generate-data_inventory").click(); });
  expect(q("narrative-unavailable-data_inventory").textContent).toContain("Narrative could not be generated.");
  expect(q("narrative-generate-data_inventory")).not.toBeNull();
});

test("nothing is read before the results are loaded", async () => {
  await mount({ step: "data_inventory", ready: false });
  expect(api.readNarrative).not.toHaveBeenCalled();
});
