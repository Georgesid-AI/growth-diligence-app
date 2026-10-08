import React, { act } from "react";
import { createRoot } from "react-dom/client";

import AuditHub from "./AuditHub";
import * as api from "@/lib/api";
import { CONSENT_EXPLAINER, CONSENT_LABEL } from "@/lib/auditForm";
import { S18_MISMATCH, S19_USAGE_TOTALS, S19_USAGE_EXPLAINER } from "@/lib/chatUpload";

jest.mock("@/lib/api", () => ({
  listAudits: jest.fn(),
  createAudit: jest.fn(),
  deleteAudit: jest.fn(),
  getUsageTotals: jest.fn(),
}));
jest.mock("sonner", () => ({ toast: { error: jest.fn(), success: jest.fn() } }));
jest.mock("react-router-dom", () => ({ useNavigate: () => jest.fn() }), { virtual: true });
jest.mock("@/components/Layout", () => ({ Layout: ({ children }) => <div>{children}</div> }));

globalThis.IS_REACT_ACT_ENVIRONMENT = true;

const q = (id) => document.body.querySelector(`[data-testid="${id}"]`);

async function openDialog() {
  api.listAudits.mockResolvedValue([]);
  const host = document.createElement("div");
  document.body.appendChild(host);
  const root = createRoot(host);
  await act(async () => { root.render(<AuditHub />); });
  await act(async () => { q("create-audit-button").click(); });
  return () => act(async () => { root.unmount(); host.remove(); });
}

describe("new-audit dialog on a short window", () => {
  let cleanup;
  beforeEach(async () => {
    window.innerHeight = 700; // jsdom has no layout: the cap is asserted on the classes that apply it
    cleanup = await openDialog();
  });
  afterEach(async () => { await cleanup(); });

  test("dialog is capped at the window height and does not overflow itself", () => {
    const cls = q("audit-dialog").className;
    expect(cls).toMatch(/max-h-\[100dvh\]|max-h-\[calc\(100dvh/);
    expect(cls).toMatch(/\bflex\b/);
    expect(cls).toMatch(/flex-col/);
    expect(cls).toMatch(/overflow-hidden/);
  });

  test("the form body scrolls inside the dialog", () => {
    const body = q("audit-dialog-body");
    expect(body.className).toMatch(/overflow-y-auto/);
    expect(body.className).toMatch(/min-h-0/);
    expect(body.contains(q("audit-company-input"))).toBe(true);
  });

  test("Create button is in a footer outside the scrolling body, so it stays visible", () => {
    const body = q("audit-dialog-body");
    const create = q("submit-audit-button");
    expect(create).not.toBeNull();
    expect(body.contains(create)).toBe(false);
    expect(q("audit-dialog").contains(create)).toBe(true);
    expect(q("audit-dialog-footer").className).toMatch(/shrink-0/);
  });
});

describe("AI-assisted reading explainer", () => {
  let cleanup;
  beforeEach(async () => { cleanup = await openDialog(); });
  afterEach(async () => { await cleanup(); });

  test("tick line is always shown; explainer is collapsed by default", () => {
    expect(q("audit-consent").textContent).toContain(CONSENT_LABEL);
    expect(q("audit-consent-checkbox")).not.toBeNull();
    expect(document.body.textContent).not.toContain(CONSENT_EXPLAINER);
    expect(q("audit-consent-toggle").textContent).toBe("What is sent");
    expect(q("audit-consent-toggle").getAttribute("aria-expanded")).toBe("false");
  });

  test("clicking 'What is sent' expands the unchanged text inline, and again collapses it", async () => {
    await act(async () => { q("audit-consent-toggle").click(); });
    expect(q("audit-consent-explainer").textContent).toBe(CONSENT_EXPLAINER);
    expect(q("audit-consent").contains(q("audit-consent-explainer"))).toBe(true);
    expect(q("audit-consent-toggle").getAttribute("aria-expanded")).toBe("true");
    await act(async () => { q("audit-consent-toggle").click(); });
    expect(document.body.textContent).not.toContain(CONSENT_EXPLAINER);
  });
});


describe("delete audit and the usage totals", () => {
  const AUDITS = [{ id: "a1", company_name: "Acme SaaS Inc.", status: "draft", reporting_currency: "EUR", target_arr: 1000000 }];
  let host, root;
  beforeEach(async () => {
    jest.clearAllMocks();
    api.listAudits.mockResolvedValue(AUDITS);
    api.deleteAudit.mockResolvedValue({});
    host = document.createElement("div");
    document.body.appendChild(host);
    root = createRoot(host);
    await act(async () => { root.render(<AuditHub />); });
  });
  afterEach(async () => { await act(async () => { root.unmount(); }); host.remove(); });
  const type = async (el, value) => act(async () => {
    Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, "value").set.call(el, value);
    el.dispatchEvent(new Event("input", { bubbles: true }));
  });

  test("the dialog is titled with the company, names it in bold in the body, and Delete waits for an exact, case-sensitive match", async () => {
    await act(async () => { q("delete-audit-a1").click(); });
    expect(q("delete-dialog-title").textContent).toBe("Delete Acme SaaS Inc.?");
    expect(q("delete-dialog-text").textContent).toBe(
      "Type Acme SaaS Inc. to delete this audit with its files, mappings and results. This cannot be undone.");
    expect(q("delete-dialog-name").tagName).toBe("STRONG");
    expect(q("delete-dialog-name").textContent).toBe("Acme SaaS Inc.");
    const button = q("confirm-delete-a1");
    expect(button.disabled).toBe(true);
    expect(q("delete-mismatch")).toBeNull();
    jest.useFakeTimers();
    try {
      for (const wrong of ["Acme SaaS", "acme saas inc.", "ACME SAAS INC."]) {
        await type(q("delete-name-a1"), wrong);
        expect(button.disabled).toBe(true);
        expect(q("delete-mismatch")).toBeNull();                    // not while typing
        await act(async () => { jest.advanceTimersByTime(900); });
        expect(q("delete-mismatch")).toBeNull();
        await act(async () => { jest.advanceTimersByTime(200); });  // about a second without typing
        expect(q("delete-mismatch").textContent).toBe(S18_MISMATCH);
        await type(q("delete-name-a1"), wrong + "x");               // typing again hides it
        expect(q("delete-mismatch")).toBeNull();
      }
      await type(q("delete-name-a1"), "Acme");                      // blur shows it at once
      await act(async () => { q("delete-name-a1").dispatchEvent(new FocusEvent("focusout", { bubbles: true })); });
      expect(q("delete-mismatch").textContent).toBe(S18_MISMATCH);
      expect(S18_MISMATCH).toBe("Name does not match");
      await type(q("delete-name-a1"), "  Acme SaaS Inc.  ");        // surrounding spaces are trimmed
      expect(button.disabled).toBe(false);
      await act(async () => { jest.advanceTimersByTime(1200); });
      expect(q("delete-mismatch")).toBeNull();
    } finally {
      jest.useRealTimers();
    }
  });

  test("Delete sends the name in the call, never in a URL, and nothing is sent before it matches", async () => {
    await act(async () => { q("delete-audit-a1").click(); });
    await type(q("delete-name-a1"), "wrong");
    await act(async () => { q("confirm-delete-a1").click(); });
    expect(api.deleteAudit).not.toHaveBeenCalled();
    await type(q("delete-name-a1"), " Acme SaaS Inc. ");
    await act(async () => { q("confirm-delete-a1").click(); });
    expect(api.deleteAudit).toHaveBeenCalledWith("a1", "Acme SaaS Inc.");
  });

  test("the usage totals are folded, asked for only when opened, and list the notes", async () => {
    api.getUsageTotals.mockResolvedValue({
      files: { uploaded: { revenue: 2 }, rejected: { pptx: 1 } }, columns: { rules: 9, saved: 1, ai: 2, confirmed: 3, corrected: 1, reasons: { other: 1 } },
      steps: { compute: { runs: 4, failures: { KeyError: 1 } }, mapping_ai: { read: 2 } }, evidence_labels: { Verified: 3 }, metrics_missing: 2,
      analyst_changes: 5, median_days_to_export: 1.5, tokens_and_cost_by_step: { structures: { input_tokens: 10, output_tokens: 5, cost_usd: 0.014 } },
      other_notes: [{ note: "Adj is not it", at: "t" }],
    });
    const details = q("usage-totals");
    expect(details.querySelector("summary").textContent).toBe("Usage totals (all audits)");
    expect(S19_USAGE_TOTALS).toBe("Usage totals (all audits)");
    expect(q("usage-explainer").textContent).toBe(S19_USAGE_EXPLAINER);
    expect(S19_USAGE_EXPLAINER).toBe("Totals across all audits on this server since counting began. Counts and costs only — no file names, figures or company names. Kept to improve the app.");
    expect(details.open).toBe(false);
    expect(api.getUsageTotals).not.toHaveBeenCalled();
    await act(async () => { details.open = true; details.dispatchEvent(new Event("toggle", { bubbles: true })); });
    await act(async () => { await Promise.resolve(); });
    expect(api.getUsageTotals).toHaveBeenCalledTimes(1);
    expect(q("usage-notes").textContent).toContain("Adj is not it");
    expect(details.textContent).toContain("revenue 2");
    expect(details.textContent).toContain("pptx 1");
    expect(details.textContent).toContain("Verified 3 · Unverified 0 · Unsupported 0 · Contradicted 0 · Metrics missing 2");
    expect(details.textContent).toContain("15 tokens · $0.01");
    expect(details.textContent).not.toContain("0.014");
    expect(details.textContent).not.toContain("Acme");
  });
});
