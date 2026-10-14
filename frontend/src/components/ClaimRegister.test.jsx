import React, { act } from "react";
import { createRoot } from "react-dom/client";

import ClaimRegister from "./ClaimRegister";
import { REGISTER_COLUMNS, REGISTER_COLUMN_WIDTHS } from "@/lib/claimRegister";
import { CALCULATE_CLASS } from "@/lib/chatUpload";
import * as api from "@/lib/api";

jest.mock("@/lib/api", () => ({
  getClaimRegister: jest.fn(),
  updateClaimInputs: jest.fn(),
  answerTurnover: jest.fn(),
  answerDefinitionCheck: jest.fn(),
  saveAllGatesCall: jest.fn(),
  claimsCsvUrl: (id) => `http://api/api/audits/${id}/claims.csv`,
}));
jest.mock("sonner", () => ({ toast: { error: jest.fn(), success: jest.fn() } }));

globalThis.IS_REACT_ACT_ENVIRONMENT = true;

const ROW = {
  claim_id: "c01", claim_type: "revenue", claimed_value: 200000, claimed_high: null, unit: null, currency: "EUR", period: "Feb 2024",
  period_note: null, segment: "Whole company", segment_set_by: "python", metric: "ARR", metric_set_by: "python", direction: "higher",
  observed_value: 202125.48, observed_at: "2024-02", observed_source: { file: "revenue.csv", sheet: "CSV", rows: "rows 2–71", rule: "ARR" },
  gap: -2125.48, gap_normalised: -0.010627, gap_kind: "beat", gloss: "€2,125 better than claimed", evidence_label: "Verified",
  reason: "within ±5% of the claim", tolerance: "±5%", rank: 1, value_at_stake_arr: null, shortfall: null, overlaps_with: [],
  evidence_analysis: "Monthly MRR by Segment", evidence_source_key: "mrr_series.data.total",
  gate_sentence: null, gate_threshold: null, gate_budget_decision: null, gate_metric_name: null, gate_direction: null,
  key_gate: false, gate_needed: false, gate_date: null, gate_saved: false, deck_reading: "parser", page_ref: "slide 4",
};
const RESULTS = { reporting_currency: "EUR", mrr_series: { segments: ["Enterprise", "SMB"] } };

async function mount(rows) {
  api.getClaimRegister.mockResolvedValue({ claims: [], register: rows });
  const host = document.createElement("div");
  document.body.appendChild(host);
  const root = createRoot(host);
  await act(async () => { root.render(<ClaimRegister auditId="a1" results={RESULTS} />); });
  return { host, root };
}

// A gate's fields show only after "Set gate" is clicked on its row.
async function openGates(host) {
  for (const button of host.querySelectorAll('[data-testid="register-set-gate"]')) await act(async () => { button.click(); });
}

test("the section has its title, the download button and one row per claim with the spec's columns", async () => {
  const { host } = await mount([ROW, { ...ROW, claim_id: "c02", rank: 2 }]);
  expect(host.querySelector("h2").textContent).toBe("Claim register");
  const button = host.querySelector('[data-testid="claim-register-csv"]');
  expect(button.textContent).toBe("Download baseline (CSV)");
  expect(button.getAttribute("href")).toBe("http://api/api/audits/a1/claims.csv");
  expect([...host.querySelectorAll("thead th")].map((th) => th.textContent)).toEqual(REGISTER_COLUMNS);
  expect(host.querySelectorAll('[data-testid="claim-register-row"]').length).toBe(2);
  const row = host.querySelector('[data-testid="claim-register-row"]');
  expect(row.textContent).toContain("Revenue · 200,000 EUR");
  expect(row.textContent).toContain("Feb 2024");
  expect(row.textContent).toContain("slide 4");
  expect(row.textContent).toContain("Read by the parser");
  expect(row.querySelector('[data-testid="register-observed"]').textContent).toContain("202,125 EUR");
  expect(row.querySelector('[data-testid="register-gap"]').textContent).toBe("beat 2,125 EUR · 1.1%");
  expect(row.querySelector('[data-testid="register-gloss"]').textContent).toBe("€2,125 better than claimed");
  expect(row.querySelector('[data-testid="register-evidence"]').textContent).toBe("Verified");
  expect(row.textContent).toContain("within ±5% of the claim");
  expect(row.querySelector('[data-testid="register-value-at-stake"]').textContent).toBe("VaS not yet computed");
  expect(row.querySelector('[data-testid="register-overlaps"]').textContent).toBe("Overlaps with —");
  expect(row.querySelector('[data-testid="register-page"]').textContent).toBe("slide 4");
  expect(row.querySelector('[data-testid="register-period"]').textContent).toBe("Feb 2024");
  expect(row.textContent).not.toContain("Value at stake");
  expect(row.querySelector('[data-testid="register-evidence-source"]').textContent).toBe("Monthly MRR by Segment · mrr_series.data.total (2024-02)");
  expect(row.querySelector('[data-testid="register-gate-needed"]')).toBeNull();
  expect(row.querySelector('[data-testid="register-gate-sentence"]')).toBeNull();
});

test("the table has the six columns, each claim's second line spans the row, and the layout cannot scroll sideways at 1280 px", async () => {
  const { host } = await mount([ROW, { ...ROW, claim_id: "c02", rank: 2, evidence_label: "Unverified", gate_needed: true }]);
  expect(REGISTER_COLUMNS).toEqual(["#", "Claim", "Segment", "Observed", "Gap", "Evidence"]);
  expect(REGISTER_COLUMN_WIDTHS.reduce((a, b) => a + b, 0)).toBe(100);
  const table = host.querySelector('[data-testid="claim-register-table"]');
  const cols = [...table.querySelectorAll("col")].map((c) => c.style.width);
  expect(cols).toEqual(REGISTER_COLUMN_WIDTHS.map((w) => `${w}%`));
  // jsdom has no layout, so the guarantee is structural: a fixed table as wide as its box, no scroll container around it,
  // no minimum width anywhere inside, and the only no-wrap items are the label pill and the buttons.
  expect(table.className.split(" ")).toEqual(expect.arrayContaining(["table-fixed", "w-full"]));
  const section = host.querySelector('[data-testid="claim-register"]');
  expect(section.querySelectorAll('[class*="overflow-x"]').length).toBe(0);
  expect(section.querySelectorAll('[class*="min-w-"]').length).toBe(0);
  const nowrap = [...table.querySelectorAll('[class*="whitespace-nowrap"]')];
  expect(nowrap.length).toBeGreaterThan(0);
  expect(nowrap.every((el) => el.matches('[data-testid="register-evidence"], button'))).toBe(true);
  for (const body of host.querySelectorAll('[data-testid="claim-register-row"]')) {
    const [first, second] = body.querySelectorAll("tr");
    expect(first.querySelectorAll("td").length).toBe(REGISTER_COLUMNS.length);
    expect(second.querySelectorAll("td").length).toBe(1);
    expect(second.querySelector("td").getAttribute("colspan")).toBe(String(REGISTER_COLUMNS.length));
    expect(second.querySelector('[data-testid="register-page"]')).not.toBeNull();
  }
  // Save all gates and the download stay at the top
  expect(host.querySelector('[data-testid="register-gates-save-all"]')).not.toBeNull();
  expect(host.querySelector('[data-testid="claim-register-csv"]')).not.toBeNull();
});

test("a Verified row has no Set gate button; every other label has one, and a click opens the gate fields below the row", async () => {
  const labels = ["Verified", "Contradicted", "Unverified", "Unsupported"];
  const { host } = await mount(labels.map((evidence_label, i) => ({ ...ROW, claim_id: `c${i}`, rank: i + 1, evidence_label })));
  const rows = [...host.querySelectorAll('[data-testid="claim-register-row"]')];
  expect(rows.map((r) => r.querySelector('[data-testid="register-set-gate"]') !== null)).toEqual([false, true, true, true]);
  expect(rows[0].querySelector('[data-testid="register-gate-threshold"]')).toBeNull();
  expect(host.querySelector('[data-testid="register-gate-threshold"]')).toBeNull();           // closed until clicked
  expect(rows[1].querySelector('[data-testid="register-set-gate"]').textContent).toBe("Set gate");
  await act(async () => { rows[1].querySelector('[data-testid="register-set-gate"]').click(); });
  const [claimLine, detailLine] = rows[1].querySelectorAll("tr");
  expect(claimLine.querySelector('[data-testid="register-gate-threshold"]')).toBeNull();      // below the claim's line, not in it
  for (const id of ["register-gate-threshold", "register-gate-date", "register-gate-save", "register-key-gate"]) {
    expect(detailLine.querySelector(`[data-testid="${id}"]`)).not.toBeNull();
  }
  expect(host.querySelectorAll('[data-testid="register-gate-threshold"]').length).toBe(1);   // only the clicked row opened
  await act(async () => { rows[1].querySelector('[data-testid="register-set-gate"]').click(); });
  expect(host.querySelector('[data-testid="register-gate-threshold"]')).toBeNull();           // a second click closes it
});

test("a Verified row that already holds a saved gate still shows the gate as text, with no button", async () => {
  const sentence = "Before the plan, ARR must be at least €195,000 by 2024-06-30.";
  const { host } = await mount([{ ...ROW, gate_saved: true, gate_sentence: sentence }]);
  expect(host.querySelector('[data-testid="register-gate-sentence"]').textContent).toContain("must be at least €195,000");
  expect(host.querySelector('[data-testid="register-set-gate"]')).toBeNull();
});

test("overlaps show the other rows' ranks and a shortfall shows beside the value at stake", async () => {
  const { host } = await mount([{ ...ROW, overlaps_with: ["c02"], shortfall: 0.183 }, { ...ROW, claim_id: "c02", rank: 2, overlaps_with: ["c01"] }]);
  const rows = host.querySelectorAll('[data-testid="claim-register-row"]');
  expect(rows[0].querySelector('[data-testid="register-overlaps"]').textContent).toBe("Overlaps with #2");
  expect(rows[1].querySelector('[data-testid="register-overlaps"]').textContent).toBe("Overlaps with #1");
  expect(rows[0].querySelector('[data-testid="register-value-at-stake"]').textContent).toBe("VaS not yet computed · shortfall 18.3%");
});

test("the segment and metric are selects of the right options; the rest is text", async () => {
  const { host } = await mount([ROW]);
  const segment = host.querySelector('[data-testid="register-segment"]');
  expect([...segment.options].map((o) => o.value)).toEqual(["Whole company", "Enterprise", "SMB", "Not in the data"]);
  const metric = host.querySelector('[data-testid="register-metric"]');
  expect(metric.value).toBe("ARR");
  expect([...metric.options].map((o) => o.value)).toEqual(["Revenue", "ARR", "MRR", "New MRR", "ACV", "Transaction volume", "none"]);
  expect(host.querySelectorAll("select").length).toBe(2);
});

test("choosing a segment saves it and the rows follow the server's answer", async () => {
  const { host } = await mount([ROW]);
  api.updateClaimInputs.mockResolvedValue({ register: [{ ...ROW, segment: "Enterprise", segment_set_by: "analyst" }] });
  const segment = host.querySelector('[data-testid="register-segment"]');
  await act(async () => {
    const setter = Object.getOwnPropertyDescriptor(HTMLSelectElement.prototype, "value").set;
    setter.call(segment, "Enterprise");
    segment.dispatchEvent(new Event("change", { bubbles: true }));
  });
  expect(api.updateClaimInputs).toHaveBeenCalledWith("a1", "c01", { segment: "Enterprise" });
  expect(host.querySelector('[data-testid="register-segment"]').value).toBe("Enterprise");
  expect(host.textContent).toContain("set by you");
});

test("Gate needed until it is saved, then its sentence; a row with no figure shows only the claimed one", async () => {
  const saved = { ...ROW, claim_id: "c2", gate_saved: true, gate_threshold: 195000, gate_budget_decision: "the plan", gate_date: "2024-06-30",
    gate_sentence: "Before the plan, ARR must be at least €195,000 by 2024-06-30. Observed €202,125 (2024-02); claimed €200,000 (Feb 2024)." };
  const { host } = await mount([{ ...ROW, observed_value: null, evidence_label: "Unverified", gate_needed: true }, saved]);
  const rows = host.querySelectorAll('[data-testid="claim-register-row"]');
  expect(rows[0].querySelector('[data-testid="register-gate-needed"]').textContent).toBe("Gate needed");      // shown before the row is opened
  await openGates(host);
  expect(rows[0].querySelector('[data-testid="register-gate-context"]').textContent).toBe("Claimed 200,000 EUR (Feb 2024)");
  expect(rows[0].querySelectorAll('[data-testid="register-gate-needed"]').length).toBe(1);
  expect(rows[1].querySelector('[data-testid="register-gate-needed"]')).toBeNull();
  expect(rows[1].querySelector('[data-testid="register-gate-sentence"]').textContent).toBe(
    "Before the plan, ARR (see glossary) must be at least €195,000 by 2024-06-30. Observed €202,125 (2024-02); claimed €200,000 (Feb 2024).");
  expect(rows[1].querySelector('[data-testid="register-gate-saved"]').textContent).toBe("Gate saved");
  expect(rows[1].querySelector('[data-testid="register-value-at-stake"]').textContent).toMatch(/^VaS /);      // VaS keeps its glossary spelling
});

test("the key gate checkbox is off until the gate is saved, saves on a click and sends false to clear it", async () => {
  const open = { ...ROW, evidence_label: "Unverified" };
  const saved = { ...open, gate_saved: true, gate_threshold: 1, gate_budget_decision: "x", gate_date: "2024-06-30" };
  const { host } = await mount([open, saved]);
  await openGates(host);
  const boxes = host.querySelectorAll('[data-testid="register-key-gate"]');
  expect([boxes[0].disabled, boxes[1].disabled]).toEqual([true, false]);
  expect(host.textContent).toContain("Key gate");
  api.updateClaimInputs.mockResolvedValue({ register: [{ ...saved, key_gate: true }] });
  await act(async () => { boxes[1].click(); });
  expect(api.updateClaimInputs).toHaveBeenCalledWith("a1", "c01", { key_gate: true });
  api.updateClaimInputs.mockResolvedValue({ register: [saved] });
  await act(async () => { host.querySelector('[data-testid="register-key-gate"]').click(); });
  expect(api.updateClaimInputs).toHaveBeenLastCalledWith("a1", "c01", { key_gate: false });
});

test("a refused key gate shows the server's reason", async () => {
  const { toast } = require("sonner");
  const saved = { ...ROW, evidence_label: "Unverified", gate_saved: true, gate_threshold: 1, gate_budget_decision: "x", gate_date: "2024-06-30" };
  const { host } = await mount([saved]);
  await openGates(host);
  api.updateClaimInputs.mockRejectedValue({ response: { status: 400, data: { detail: "At most 5 key gates." } } });
  await act(async () => { host.querySelector('[data-testid="register-key-gate"]').click(); });
  expect(toast.error).toHaveBeenCalledWith(expect.stringContaining("At most 5 key gates."));
});

test("a row with no metric of the app asks for the metric (max 100 characters) and At least / At most", async () => {
  const none = { ...ROW, metric: null, reason: "no metric", observed_value: null, evidence_label: "Unsupported", evidence_analysis: null, gate_needed: true };
  const { host } = await mount([none, { ...ROW, evidence_label: "Unverified" }]);
  await openGates(host);
  const rows = host.querySelectorAll('[data-testid="claim-register-row"]');
  const name = rows[0].querySelector('[data-testid="register-gate-metric-name"]');
  expect(name.getAttribute("placeholder")).toBe("Metric (max 100 characters)");
  expect(name.maxLength).toBe(100);
  expect([...rows[0].querySelector('[data-testid="register-gate-direction"]').options].map((o) => o.textContent)).toEqual(["", "At least", "At most"]);
  expect(rows[1].querySelector('[data-testid="register-gate-metric-name"]')).toBeNull();
});

test("a qualified Users row asks for the metric and its direction too, as the server needs them to save its gate", async () => {
  const qualified = { ...ROW, claim_type: "users", metric: null, reason: "deck label 'registered institutions' is not paying customers; the analyst can edit the type to Customers to test it",
    observed_value: null, evidence_label: "Unsupported", evidence_analysis: null, gate_needed: true };
  const { host } = await mount([qualified]);
  await openGates(host);
  const row = host.querySelector('[data-testid="claim-register-row"]');
  expect(row.querySelector('[data-testid="register-gate-metric-name"]')).not.toBeNull();
  expect(row.querySelector('[data-testid="register-gate-direction"]')).not.toBeNull();
});

test("no claim yet gives a line that says so", async () => {
  const { host } = await mount([]);
  expect(host.querySelector('[data-testid="claim-register-empty"]')).not.toBeNull();
  expect(host.querySelector("table")).toBeNull();
});

async function pick(row, code) {
  const select = row.querySelector('[data-testid="register-turnover-reason"]');
  await act(async () => {
    Object.getOwnPropertyDescriptor(HTMLSelectElement.prototype, "value").set.call(select, code);
    select.dispatchEvent(new Event("change", { bubbles: true }));
  });
}

const TURNOVER = { ...ROW, claim_id: "t1", metric: null, observed_value: null, evidence_label: "Unverified", evidence_analysis: null,
  reason: "turnover or volume: confirm Revenue or Volume", turnover_state: "ask",
  turnover_note: "Revenue or volume? Confirm below", turnover_set_by: "python", turnover_reason: null };

test("a deck revenue below the turnover pre-selects Volume, shows the deck figure and still needs the analyst's answer", async () => {
  const note = "Deck revenue for the same period: 150,000 GBP (page 19); implied take rate 27%, derived, not verified";
  const { host } = await mount([{ ...TURNOVER, turnover_suggested: "volume", deck_revenue_note: note }, TURNOVER]);
  const rows = host.querySelectorAll('[data-testid="claim-register-row"]');
  expect(rows[0].querySelector('[data-testid="register-deck-revenue"]').textContent).toBe(note);
  expect(rows[0].querySelector('[data-testid="register-turnover-volume"]').getAttribute("aria-pressed")).toBe("true");
  expect(rows[0].querySelector('[data-testid="register-turnover-revenue"]').getAttribute("aria-pressed")).toBeNull();
  expect(rows[0].querySelector('[data-testid="register-turnover-volume"]').disabled).toBe(true);       // a reason is still required
  expect(rows[0].querySelector('[data-testid="register-turnover-note"]').textContent).toBe("Revenue or volume? Confirm below");
  expect(rows[1].querySelector('[data-testid="register-deck-revenue"]')).toBeNull();
  expect(rows[1].querySelector('[data-testid="register-turnover-volume"]').getAttribute("aria-pressed")).toBeNull();
});

test("a turnover claim reads Turnover, never Revenue, in the Claim cell until the analyst confirms it (section 11 point 8)", async () => {
  const { host } = await mount([TURNOVER, { ...TURNOVER, claim_id: "t2", turnover_state: "volume", turnover_note: "Transaction volume",
    turnover_set_by: "analyst" }, ROW]);
  const cells = [...host.querySelectorAll('[data-testid="register-claim"]')].map((td) => td.textContent);
  expect(cells).toEqual(["Turnover · 200,000 EUR", "Revenue · 200,000 EUR", "Revenue · 200,000 EUR"]);
});

test("a turnover row shows its label, the question and one click Revenue or Volume with a reason code", async () => {
  const { host } = await mount([TURNOVER, ROW]);
  const rows = host.querySelectorAll('[data-testid="claim-register-row"]');
  expect(rows[0].querySelector('[data-testid="register-turnover-note"]').textContent).toBe("Revenue or volume? Confirm below");
  expect(rows[0].textContent).toContain("Revenue or transaction volume?");
  expect(rows[1].querySelector('[data-testid="register-turnover"]')).toBeNull();
  api.answerTurnover.mockResolvedValue({ register: [{ ...TURNOVER, turnover_state: "volume", turnover_note: "Transaction volume", turnover_set_by: "analyst" }] });
  await act(async () => { rows[0].querySelector('[data-testid="register-turnover-volume"]').click(); });
  expect(api.answerTurnover).not.toHaveBeenCalled();           // no reason chosen yet: nothing is sent
  await pick(rows[0], "deck_says_processed_volume");
  await act(async () => { rows[0].querySelector('[data-testid="register-turnover-volume"]').click(); });
  expect(api.answerTurnover).toHaveBeenCalledWith("a1", "t1", { as: "volume", reason: "deck_says_processed_volume" });
  expect(host.querySelector('[data-testid="register-turnover-note"]').textContent).toContain("Transaction volume");
});

test("a confirmed row can be switched back, and the implied take rate shows both sources as derived", async () => {
  const volume = { ...TURNOVER, turnover_state: "volume", turnover_note: "Transaction volume", turnover_set_by: "analyst",
    implied_take_rate: 0.1, implied_take_rate_source: "revenue: revenue.csv · CSV · rows 2–71; volume: deck.pptx · slide 3" };
  const { host } = await mount([volume]);
  expect(host.querySelector('[data-testid="register-take-rate"]').textContent).toContain("Implied take rate 10.00% (derived, not verified)");
  expect(host.querySelector('[data-testid="register-take-rate-source"]').textContent).toContain("deck.pptx");
  api.answerTurnover.mockResolvedValue({ register: [{ ...volume, turnover_state: "revenue" }] });
  await act(async () => { host.querySelector('[data-testid="register-turnover-revenue"]').click(); });
  expect(api.answerTurnover).not.toHaveBeenCalled();           // the reason is empty again for the new answer
  await pick(host, "file_confirms");
  await act(async () => { host.querySelector('[data-testid="register-turnover-revenue"]').click(); });
  expect(api.answerTurnover).toHaveBeenLastCalledWith("a1", "t1", { as: "revenue", reason: "file_confirms" });
});

test("there is no default reason: the buttons are disabled until one is chosen and for a contradicting pair", async () => {
  const { host } = await mount([TURNOVER]);
  const reason = host.querySelector('[data-testid="register-turnover-reason"]');
  const btn = (v) => host.querySelector(`[data-testid="register-turnover-${v}"]`);
  expect(reason.value).toBe("");
  expect([btn("revenue").disabled, btn("volume").disabled]).toEqual([true, true]);
  await pick(host, "deck_says_gross_revenue");
  expect([btn("revenue").disabled, btn("volume").disabled]).toEqual([false, true]);
  await pick(host, "deck_says_processed_volume");
  expect([btn("revenue").disabled, btn("volume").disabled]).toEqual([true, false]);
  await pick(host, "file_confirms");
  expect([btn("revenue").disabled, btn("volume").disabled]).toEqual([false, false]);      // no note step: a reason is enough
});

test("the dropdown offers exactly three reasons, and 'Revenue file confirms' is hidden when no revenue-file period exists to compare", async () => {
  const { host } = await mount([TURNOVER, { ...TURNOVER, claim_id: "t2", file_note: "Revenue file does not cover this period" }]);
  const options = (row) => [...row.querySelectorAll('[data-testid="register-turnover-reason"] option')].map((o) => o.textContent);
  const rows = host.querySelectorAll('[data-testid="claim-register-row"]');
  expect(options(rows[0])).toEqual(["Reason…", "Deck says gross revenue", "Deck says processed volume", "Revenue file confirms"]);
  expect(options(rows[1])).toEqual(["Reason…", "Deck says gross revenue", "Deck says processed volume"]);
  expect(host.textContent).not.toContain("Other");
  expect(host.querySelector('[data-testid="register-turnover-reason-note"]')).toBeNull();
});

test("a stored 'Revenue file confirms' on a row with no revenue-file period shows no reason and keeps the buttons off", async () => {
  const { host } = await mount([{ ...TURNOVER, turnover_reason: "file_confirms", file_note: "Revenue file does not cover this period" }]);
  expect(host.querySelector('[data-testid="register-turnover-reason"]').value).toBe("");
  expect(host.querySelector('[data-testid="register-turnover-revenue"]').disabled).toBe(true);
});

test("the reason, Revenue and Volume sit on one line in that order; the answered button is blue and both buttons keep one size", async () => {
  const { host } = await mount([{ ...TURNOVER, turnover_state: "volume", turnover_note: "Transaction volume", turnover_set_by: "analyst",
    turnover_reason: "deck_says_processed_volume" }]);
  const reason = host.querySelector('[data-testid="register-turnover-reason"]');
  const revenue = host.querySelector('[data-testid="register-turnover-revenue"]');
  const volume = host.querySelector('[data-testid="register-turnover-volume"]');
  const line = reason.parentElement;
  expect([...line.children].map((n) => n.tagName)).toEqual(["SELECT", "BUTTON", "BUTTON"]);
  expect([...line.children].map((n) => n.getAttribute("data-testid"))).toEqual(
    ["register-turnover-reason", "register-turnover-revenue", "register-turnover-volume"]);
  expect(line.className).toContain("flex-nowrap");
  expect(line.className).not.toContain("flex-wrap");
  expect(volume.className).toContain(CALCULATE_CLASS);                 // active: the Map / Compute style
  expect(revenue.className).toContain(CALCULATE_CLASS);                // inactive: the same style, paler
  expect(volume.className.split(" ")).not.toContain("opacity-50");
  expect(revenue.className.split(" ")).toContain("opacity-50");
  expect(revenue.className.match(/\bh-\d+\b/)[0]).toBe(volume.className.match(/\bh-\d+\b/)[0]);
});

test("the dropdown decides which button is active: gross revenue, processed volume, any other reason", async () => {
  const { host } = await mount([{ ...TURNOVER, turnover_reason: "deck_says_gross_revenue" }]);
  const b = (v) => host.querySelector(`[data-testid="register-turnover-${v}"]`);
  const select = host.querySelector('[data-testid="register-turnover-reason"]');
  const pale = (v) => b(v).className.split(" ").includes("opacity-50");
  expect([pale("revenue"), pale("volume")]).toEqual([false, true]);
  const choose = async (value) => { await act(async () => {
    Object.getOwnPropertyDescriptor(HTMLSelectElement.prototype, "value").set.call(select, value);
    select.dispatchEvent(new Event("change", { bubbles: true })); }); };
  await choose("deck_says_processed_volume");
  expect([pale("revenue"), pale("volume")]).toEqual([true, false]);
  await choose("file_confirms");
  expect([pale("revenue"), pale("volume")]).toEqual([true, true]);
});

test("a row with no rate names the pair and links to the FX settings", async () => {
  const needs = { ...ROW, metric: "Revenue", observed_value: null, evidence_label: "Unverified", evidence_analysis: null,
    reason: "FX rate needed: GBP→EUR" };
  const { host } = await mount([needs, ROW]);
  const rows = host.querySelectorAll('[data-testid="claim-register-row"]');
  expect(rows[0].querySelector('[data-testid="register-evidence-reason"]').textContent).toBe("FX rate needed: GBP→EUR");
  expect(rows[0].querySelector('[data-testid="register-fx-link"]').getAttribute("href")).toBe("/audit/a1/mapping#fx-settings");
  expect(rows[1].querySelector('[data-testid="register-fx-link"]')).toBeNull();
});

test("a market-size row: the value, the converted value, FY2028 from the deck, and no rate date on the row", async () => {
  const market = { ...ROW, claim_id: "m01", claim_type: "market", currency: "USD", claimed_value: 2.5e9, period: "FY2028",
    claimed_converted: 2.25e9, fx_rate: 0.9, fx_date: "2026-06-30" };
  const undated = { ...market, claim_id: "m02", claimed_value: 1e9, claimed_converted: 9e8, period: null, period_note: "no period stated" };
  const { host } = await mount([market, undated]);
  const [a, b] = host.querySelectorAll('[data-testid="claim-register-row"]');
  const cells = (tr) => ["register-claim", "register-period"].map((id) => tr.querySelector(`[data-testid="${id}"]`));
  expect([cells(a)[0].textContent, cells(a)[1].textContent]).toEqual(["Market size · 2,500,000,000 USD (2,250,000,000 EUR)", "FY2028"]);
  expect([cells(b)[0].textContent, cells(b)[1].textContent]).toEqual(["Market size · 1,000,000,000 USD (900,000,000 EUR)", "no date"]);
  expect(a.textContent).not.toMatch(/30 Jun 2026|Jun 2026|0\.9\b/);
  expect(a.querySelector('[data-testid="register-claim"]').getAttribute("title")).toBe("Rate used: 1 USD = 0.9 EUR on 30 Jun 2026");
});

test("a row with no saved rate says which rate is missing, and FX settings in it is the link", async () => {
  const brl = { ...ROW, currency: "BRL", claimed_value: 150000, claimed_converted: null, fx_rate: null, fx_date: null,
    evidence_label: "Unverified", reason: "FX rate needed: BRL→EUR", observed_value: null, evidence_analysis: null };
  const { host } = await mount([brl]);
  const cell = host.querySelector('[data-testid="register-claim"]');
  expect(cell.textContent).toBe("Revenue · 150,000 BRL (BRL→EUR rate missing – enter it in FX settings at the top of the page)");
  const link = cell.querySelector("a");
  expect([link.textContent, link.getAttribute("href")]).toEqual(["FX settings", "/audit/a1/mapping#fx-settings"]);
});

// --- gate prefill: marked until saved, one Save all --------------------------------------------------------------------------
const GATE_ROW = (id, extra = {}) => ({ ...ROW, claim_id: id, observed_value: null, evidence_label: "Unverified", gate_needed: true, ...extra });
const FILL = { gate_threshold: 200000, gate_date: "2025-03-31", key_gate: true };

async function mountGates(rows, prefill, budgets = []) {
  api.getClaimRegister.mockResolvedValue({ claims: [], register: rows, gate_prefill: prefill, budget_decisions: budgets });
  const host = document.createElement("div");
  document.body.appendChild(host);
  await act(async () => { createRoot(host).render(<ClaimRegister auditId="a1" results={RESULTS} />); });
  await openGates(host);
  return host;
}

async function choose(el, value) {
  const proto = el.tagName === "SELECT" ? HTMLSelectElement.prototype : HTMLInputElement.prototype;
  await act(async () => {
    Object.getOwnPropertyDescriptor(proto, "value").set.call(el, value);
    el.dispatchEvent(new Event(el.tagName === "SELECT" ? "change" : "input", { bubbles: true }));
  });
}

test("a gate starts with the prefill, each prefilled field marked, and the budget decision blank", async () => {
  const host = await mountGates([GATE_ROW("c01")], { c01: FILL });
  const row = host.querySelector('[data-testid="claim-register-row"]');
  expect(row.querySelector('[data-testid="register-gate-threshold"]').value).toBe("200000");
  expect(row.querySelector('[data-testid="register-gate-date"]').value).toBe("31 Mar 2025");
  expect(row.querySelector('[data-testid="register-key-gate"]').checked).toBe(true);
  for (const f of ["threshold", "date", "key"]) expect(row.querySelector(`[data-testid="register-gate-prefilled-${f}"]`).textContent).toBe("prefilled – confirm");
  expect(row.querySelector('[data-testid="register-gate-budget"]').value).toBe("");
});

test("editing a prefilled field removes its mark", async () => {
  const host = await mountGates([GATE_ROW("c01")], { c01: FILL });
  await choose(host.querySelector('[data-testid="register-gate-threshold"]'), "150000");
  expect(host.querySelector('[data-testid="register-gate-prefilled-threshold"]')).toBeNull();
  expect(host.querySelector('[data-testid="register-gate-prefilled-date"]')).not.toBeNull();
});

test("the budget dropdown lists the decisions already used and Other, which opens a text field", async () => {
  const host = await mountGates([GATE_ROW("c01")], { c01: FILL }, ["Series B"]);
  const pick = host.querySelector('[data-testid="register-gate-budget-pick"]');
  expect([...pick.options].map((o) => o.textContent)).toEqual(["Budget decision…", "Series B", "Other"]);
  expect(host.querySelector('[data-testid="register-gate-budget"]')).toBeNull();
  await choose(pick, "Other");
  expect(host.querySelector('[data-testid="register-gate-budget"]')).not.toBeNull();
});

test("Save all gates sends every gate with a budget decision, prefilled or edited, and leaves the unfilled ones", async () => {
  const host = await mountGates([GATE_ROW("c01"), GATE_ROW("c02"), GATE_ROW("c03")],
    { c01: FILL, c02: { ...FILL, key_gate: false }, c03: FILL }, ["Series B"]);
  const picks = host.querySelectorAll('[data-testid="register-gate-budget-pick"]');
  await choose(picks[0], "Series B");
  await choose(picks[1], "Series B");
  await choose(host.querySelectorAll('[data-testid="register-gate-threshold"]')[1], "150000");
  api.saveAllGatesCall.mockResolvedValue({ register: [] });
  await act(async () => { host.querySelector('[data-testid="register-gates-save-all"]').click(); });
  expect(api.saveAllGatesCall).toHaveBeenCalledTimes(1);
  expect(api.saveAllGatesCall).toHaveBeenCalledWith("a1", [
    { claim_id: "c01", gate_threshold: 200000, gate_budget_decision: "Series B", gate_date: "2025-03-31", key_gate: true },
    { claim_id: "c02", gate_threshold: 150000, gate_budget_decision: "Series B", gate_date: "2025-03-31" },
  ]);
});

// claim-matching.md section 4.1: a gap beyond 50% of the claim asks "Same metric and period?" on the row.
const CHECK = { ...ROW, claim_id: "k1", claim_type: "customers", claimed_value: 1, currency: null, unit: "customers", metric: "Customer count",
  observed_value: 26, gap: -25, gap_normalised: -25, gloss: "25 customers more (beat)", evidence_label: null, definition_check: "ask",
  definition_question: "Observed 26, claimed 1. Same metric and period?", reason: "definition check: the gap is beyond 50% of the claim" };

test("a row with an open Definition check has no Set gate button; once answered it has one like any row that is not Verified", async () => {
  const { host } = await mount([CHECK, { ...CHECK, claim_id: "k2", rank: 2, definition_check: "no", evidence_label: "Unverified" }]);
  const rows = [...host.querySelectorAll('[data-testid="claim-register-row"]')];
  expect(rows.map((r) => r.querySelector('[data-testid="register-set-gate"]') !== null)).toEqual([false, true]);
});

test("a row in Definition check reads so in the Evidence cell and asks its question with Yes and No on one line", async () => {
  const { host } = await mount([CHECK, ROW]);
  const rows = host.querySelectorAll('[data-testid="claim-register-row"]');
  expect(rows[0].querySelector('[data-testid="register-evidence"]').textContent).toBe("Definition check");
  const line = rows[0].querySelector('[data-testid="register-detail"] [data-testid="definition-check"]');
  expect(line.className).toContain("flex-nowrap");
  expect(line.querySelector('[data-testid="definition-question"]').textContent).toBe("Observed 26, claimed 1. Same metric and period?");
  expect([...line.querySelectorAll("button")].map((b) => b.textContent)).toEqual(["Yes", "No"]);
  expect(line.querySelector('[data-testid="definition-yes"]').getAttribute("aria-pressed")).toBeNull();
  expect(rows[1].querySelector('[data-testid="definition-check"]')).toBeNull();
  expect(host.querySelectorAll("thead th").length).toBe(6);
  api.answerDefinitionCheck.mockResolvedValue({ register: [{ ...CHECK, definition_check: "yes", evidence_label: "Verified",
    reason: "beat: observed beats the claim by 25 customers more (beat)" }, ROW] });
  await act(async () => { line.querySelector('[data-testid="definition-yes"]').click(); });
  expect(api.answerDefinitionCheck).toHaveBeenCalledWith("a1", "k1", "yes");
  const after = host.querySelector('[data-testid="claim-register-row"]');
  expect(after.querySelector('[data-testid="register-evidence"]').textContent).toBe("Verified");
  expect(after.querySelector('[data-testid="definition-yes"]').getAttribute("aria-pressed")).toBe("true");
  expect(after.querySelector('[data-testid="definition-no"]').getAttribute("aria-pressed")).toBe("false");
  expect(after.querySelector('[data-testid="definition-check"]').textContent).toContain("set by you");
});
