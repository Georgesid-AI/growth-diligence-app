// docs/design/simplified-flow.md, Verdict detail: the gate starts as the app's proposal and the analyst edits it here only.
import React, { act } from "react";
import { createRoot } from "react-dom/client";

import GateEditor from "./GateEditor";

jest.mock("sonner", () => ({ toast: { error: jest.fn(), success: jest.fn() } }));
const { toast } = require("sonner");
globalThis.IS_REACT_ACT_ENVIRONMENT = true;

const ROW = {
  claim_id: "c05", claim_type: "revenue", claimed_value: 240000, claimed_high: null, unit: null, currency: "EUR", period: "FY2023", period_note: null,
  metric: "ARR", reason: "outside ±5%: a miss", observed_value: 198143, observed_at: "2023-12", evidence_label: "Contradicted",
  gate_sentence: "ARR must be at least €240,000 by 2023-12-31.", gate_status: "proposed", gate_saved: false, gate_threshold: 240000,
  gate_date: "2023-12-31", gate_budget_decision: null, gate_metric_name: null, gate_direction: null,
};
const mount = async (row, onSave = jest.fn(() => Promise.resolve())) => {
  const host = document.createElement("div");
  document.body.appendChild(host);
  await act(async () => { createRoot(host).render(<GateEditor row={row} ccy="EUR" onSave={onSave} />); });
  return { host, onSave };
};
const q = (host, id) => host.querySelector(`[data-testid="${id}"]`);
const type = async (el, value) => {
  await act(async () => {
    Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, "value").set.call(el, value);
    el.dispatchEvent(new Event("input", { bubbles: true }));
  });
};

test("the fields start with the proposal, the claimed and observed figures sit above them and the budget decision is optional and blank", async () => {
  const { host } = await mount(ROW);
  expect(q(host, "gate-threshold").value).toBe("240000");
  expect(q(host, "gate-date").value).toBe("31 Dec 2023");
  expect(q(host, "gate-budget").value).toBe("");
  expect(q(host, "gate-budget").getAttribute("placeholder")).toContain("optional");
  expect(q(host, "gate-context").textContent).toBe("Claimed 240,000 EUR (FY2023) · Observed 198,143 EUR (2023-12)");
  expect(q(host, "gate-metric-name")).toBeNull();
  expect(q(host, "gate-reset")).toBeNull();
});

test("Save with nothing changed sends nothing: the gate stays the proposal", async () => {
  const { host, onSave } = await mount(ROW);
  await act(async () => { q(host, "gate-save").click(); });
  expect(onSave).not.toHaveBeenCalled();
});

test("changing the threshold stores the whole gate (threshold and date), so the server counts it as the analyst's", async () => {
  const { host, onSave } = await mount(ROW);
  await type(q(host, "gate-threshold"), "195000");
  await act(async () => { q(host, "gate-save").click(); });
  expect(onSave).toHaveBeenCalledWith(ROW, { gate_threshold: 195000, gate_date: "2023-12-31" });
});

test("a budget decision typed alone is stored with the proposal's threshold and date", async () => {
  const { host, onSave } = await mount(ROW);
  await type(q(host, "gate-budget"), "the Series B hiring plan");
  await act(async () => { q(host, "gate-save").click(); });
  expect(onSave).toHaveBeenCalledWith(ROW, { gate_threshold: 240000, gate_date: "2023-12-31", gate_budget_decision: "the Series B hiring plan" });
});

test("a threshold that is not a number is refused on screen and nothing is sent", async () => {
  const { host, onSave } = await mount(ROW);
  await type(q(host, "gate-threshold"), "lots");
  await act(async () => { q(host, "gate-save").click(); });
  expect(toast.error).toHaveBeenCalledWith("The threshold must be a number");
  expect(onSave).not.toHaveBeenCalled();
});

test("a row with no metric of the app asks for the metric name and At least / At most, and stores them with the gate", async () => {
  const none = { ...ROW, metric: null, reason: "no metric", gate_metric_name: "Market, 2024", gate_direction: "at least" };
  const { host, onSave } = await mount(none);
  expect(q(host, "gate-metric-name").value).toBe("Market, 2024");
  expect(q(host, "gate-metric-name").maxLength).toBe(100);
  expect([...q(host, "gate-direction").options].map((o) => o.textContent)).toEqual(["", "At least", "At most"]);
  await type(q(host, "gate-threshold"), "7");
  await act(async () => { q(host, "gate-save").click(); });
  expect(onSave).toHaveBeenCalledWith(none, { gate_threshold: 7, gate_date: "2023-12-31", gate_metric_name: "Market, 2024", gate_direction: "at least" });
});

test("a gate the analyst set sends only what changed, and Back to proposed clears the edit", async () => {
  const saved = { ...ROW, gate_saved: true, gate_status: "set by the analyst", gate_threshold: 195000, gate_date: "2024-06-30", gate_budget_decision: "the plan" };
  const { host, onSave } = await mount(saved);
  await type(q(host, "gate-threshold"), "180000");
  await act(async () => { q(host, "gate-save").click(); });
  expect(onSave).toHaveBeenLastCalledWith(saved, { gate_threshold: 180000 });
  await act(async () => { q(host, "gate-reset").click(); });
  expect(onSave).toHaveBeenLastCalledWith(saved, { gate_threshold: null, gate_date: null, gate_budget_decision: null });
});
