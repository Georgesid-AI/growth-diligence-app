import React, { act } from "react";
import { createRoot } from "react-dom/client";

import ClaimRegister from "./ClaimRegister";
import { REGISTER_COLUMNS } from "@/lib/claimRegister";
import * as api from "@/lib/api";

jest.mock("@/lib/api", () => ({
  getClaimRegister: jest.fn(),
  updateClaimInputs: jest.fn(),
  answerTurnover: jest.fn(),
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
  expect(row.querySelector('[data-testid="register-value-at-stake"]').textContent).toBe("not yet computed");
  expect(row.querySelector('[data-testid="register-overlaps"]').textContent).toBe("—");
  expect(row.querySelector('[data-testid="register-evidence-source"]').textContent).toBe("Monthly MRR by Segment · mrr_series.data.total (2024-02)");
  expect(row.querySelector('[data-testid="register-gate-date"]').placeholder).toBe("Gate date", "the gate date starts empty");
  expect(row.querySelector('[data-testid="register-gate-needed"]')).toBeNull();
  expect(row.querySelector('[data-testid="register-gate-context"]').textContent).toBe("Claimed 200,000 EUR (Feb 2024) · Observed 202,125 EUR (2024-02)");
  expect(row.querySelector('[data-testid="register-gate-threshold"]').value).toBe("");
  expect(row.querySelector('[data-testid="register-gate-sentence"]')).toBeNull();
});

test("overlaps show the other rows' ranks and a shortfall shows beside the value at stake", async () => {
  const { host } = await mount([{ ...ROW, overlaps_with: ["c02"], shortfall: 0.183 }, { ...ROW, claim_id: "c02", rank: 2, overlaps_with: ["c01"] }]);
  const rows = host.querySelectorAll('[data-testid="claim-register-row"]');
  expect(rows[0].querySelector('[data-testid="register-overlaps"]').textContent).toBe("#2");
  expect(rows[1].querySelector('[data-testid="register-overlaps"]').textContent).toBe("#1");
  expect(rows[0].querySelector('[data-testid="register-value-at-stake"]').textContent).toBe("not yet computed · shortfall 18.3%");
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

test("every row has a gate: Gate needed until it is saved, then its sentence; a row with no figure shows only the claimed one", async () => {
  const saved = { ...ROW, claim_id: "c2", gate_saved: true, gate_threshold: 195000, gate_budget_decision: "the plan", gate_date: "2024-06-30",
    gate_sentence: "Before the plan, ARR must be at least €195,000 by 2024-06-30. Observed €202,125 (2024-02); claimed €200,000 (Feb 2024)." };
  const { host } = await mount([{ ...ROW, observed_value: null, evidence_label: "Unverified", gate_needed: true }, saved]);
  const rows = host.querySelectorAll('[data-testid="claim-register-row"]');
  expect(rows[0].querySelector('[data-testid="register-gate-context"]').textContent).toBe("Claimed 200,000 EUR (Feb 2024)");
  expect(rows[0].querySelector('[data-testid="register-gate-needed"]').textContent).toBe("Gate needed");
  expect(rows[1].querySelector('[data-testid="register-gate-needed"]')).toBeNull();
  expect(rows[1].querySelector('[data-testid="register-gate-sentence"]').textContent).toBe(
    "Before the plan, ARR (see glossary) must be at least €195,000 by 2024-06-30. Observed €202,125 (2024-02); claimed €200,000 (Feb 2024).");
  expect(rows[1].querySelector('[data-testid="register-gate-saved"]').textContent).toBe("Gate saved");
  const vas = [...host.querySelectorAll("thead th")].find((th) => th.textContent === "VaS");
  expect(vas.className).toContain("normal-case");          // the header row is in capitals; VaS keeps its case
});

test("the key gate checkbox is off until the gate is saved, saves on a click and sends false to clear it", async () => {
  const saved = { ...ROW, gate_saved: true, gate_threshold: 1, gate_budget_decision: "x", gate_date: "2024-06-30" };
  const { host } = await mount([ROW, saved]);
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
  const saved = { ...ROW, gate_saved: true, gate_threshold: 1, gate_budget_decision: "x", gate_date: "2024-06-30" };
  const { host } = await mount([saved]);
  api.updateClaimInputs.mockRejectedValue({ response: { status: 400, data: { detail: "At most 5 key gates." } } });
  await act(async () => { host.querySelector('[data-testid="register-key-gate"]').click(); });
  expect(toast.error).toHaveBeenCalledWith(expect.stringContaining("At most 5 key gates."));
});

test("a row with no metric of the app asks for the metric (max 100 characters) and At least / At most", async () => {
  const none = { ...ROW, metric: null, reason: "no metric", observed_value: null, evidence_label: "Unsupported", evidence_analysis: null, gate_needed: true };
  const { host } = await mount([none, ROW]);
  const rows = host.querySelectorAll('[data-testid="claim-register-row"]');
  const name = rows[0].querySelector('[data-testid="register-gate-metric-name"]');
  expect(name.getAttribute("placeholder")).toBe("Metric (max 100 characters)");
  expect(name.maxLength).toBe(100);
  expect([...rows[0].querySelector('[data-testid="register-gate-direction"]').options].map((o) => o.textContent)).toEqual(["", "At least", "At most"]);
  expect(rows[1].querySelector('[data-testid="register-gate-metric-name"]')).toBeNull();
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
  const { host } = await mount([TURNOVER, { ...TURNOVER, claim_id: "t2", file_note: "No revenue-file period to compare" }]);
  const options = (row) => [...row.querySelectorAll('[data-testid="register-turnover-reason"] option')].map((o) => o.textContent);
  const rows = host.querySelectorAll('[data-testid="claim-register-row"]');
  expect(options(rows[0])).toEqual(["Reason…", "Deck says gross revenue", "Deck says processed volume", "Revenue file confirms"]);
  expect(options(rows[1])).toEqual(["Reason…", "Deck says gross revenue", "Deck says processed volume"]);
  expect(host.textContent).not.toContain("Other");
  expect(host.querySelector('[data-testid="register-turnover-reason-note"]')).toBeNull();
});

test("a stored 'Revenue file confirms' on a row with no revenue-file period shows no reason and keeps the buttons off", async () => {
  const { host } = await mount([{ ...TURNOVER, turnover_reason: "file_confirms", file_note: "No revenue-file period to compare" }]);
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
  expect(volume.className).toContain("bg-sky-600");
  expect(revenue.className).not.toContain("bg-sky-600");
  expect(revenue.className.match(/\bh-\d+\b/)[0]).toBe(volume.className.match(/\bh-\d+\b/)[0]);
});

test("a row with no rate names the pair and links to the FX settings", async () => {
  const needs = { ...ROW, metric: "Revenue", observed_value: null, evidence_label: "Unverified", evidence_analysis: null,
    reason: "FX rate needed: GBP→EUR" };
  const { host } = await mount([needs, ROW]);
  const rows = host.querySelectorAll('[data-testid="claim-register-row"]');
  expect(rows[0].querySelector('[data-testid="register-evidence-reason"]').textContent).toBe("· FX rate needed: GBP→EUR");
  expect(rows[0].querySelector('[data-testid="register-fx-link"]').getAttribute("href")).toBe("/audit/a1/mapping#fx-settings");
  expect(rows[1].querySelector('[data-testid="register-fx-link"]')).toBeNull();
});

test("a market-size row: the value, the converted value, FY2028 from the deck, and no rate date on the row", async () => {
  const market = { ...ROW, claim_id: "m01", claim_type: "market", currency: "USD", claimed_value: 2.5e9, period: "FY2028",
    claimed_converted: 2.25e9, fx_rate: 0.9, fx_date: "2026-06-30" };
  const undated = { ...market, claim_id: "m02", claimed_value: 1e9, claimed_converted: 9e8, period: null, period_note: "no period stated" };
  const { host } = await mount([market, undated]);
  const [a, b] = host.querySelectorAll('[data-testid="claim-register-row"]');
  const cells = (tr) => [...tr.querySelectorAll("td")].slice(1, 3).map((td) => td.textContent);
  expect(cells(a)).toEqual(["Market size · 2,500,000,000 USD (2,250,000,000 EUR)", "FY2028"]);
  expect(cells(b)).toEqual(["Market size · 1,000,000,000 USD (900,000,000 EUR)", "no date"]);
  expect(a.textContent).not.toMatch(/30 Jun 2026|Jun 2026|0\.9\b/);
  expect(a.querySelector('[data-testid="register-claim"] span').getAttribute("title")).toBe("Rate used: 1 USD = 0.9 EUR on 30 Jun 2026");
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
