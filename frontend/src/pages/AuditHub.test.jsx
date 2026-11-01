import React, { act } from "react";
import { createRoot } from "react-dom/client";

import AuditHub from "./AuditHub";
import * as api from "@/lib/api";
import { NEW_AUDIT_TITLE, NEW_AUDIT_PARAGRAPHS, formatCreated } from "@/lib/auditForm";
import { S18_MISMATCH } from "@/lib/chatUpload";

jest.mock("@/lib/api", () => ({
  listAudits: jest.fn(),
  createAudit: jest.fn(),
  deleteAudit: jest.fn(),
  getDatasets: jest.fn(), getReview: jest.fn(), getDecks: jest.fn(), runStage: jest.fn(), uploadChatFile: jest.fn(), uploadDeck: jest.fn(),
}));
jest.mock("sonner", () => ({ toast: { error: jest.fn(), success: jest.fn() } }));
const mockNavigate = jest.fn();
jest.mock("react-router-dom", () => ({ useNavigate: () => mockNavigate }), { virtual: true });
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

describe("new-audit dates and fields", () => {
  let cleanup;
  beforeEach(async () => { cleanup = await openDialog(); });
  afterEach(async () => { await cleanup(); });

  test("there is no engagement reference field", () => {
    expect(q("audit-engagement-input")).toBeNull();
    expect(q("audit-dialog").textContent).not.toMatch(/engagement reference/i);
  });

  test("the dialog asks for the project or company name only: the set-up fields are at the top of the mapping page", () => {
    for (const gone of ["reporting-currency-select", "audit-target-arr-input", "audit-target-date-input", "audit-asof-month-input",
      "audit-fiscal-year-end-select"]) expect(q(gone)).toBeNull();
    expect(q("audit-dialog-body").querySelectorAll("input").length).toBe(1);   // the name alone: no client name, no consent tick
    expect(q("audit-dialog").textContent).not.toMatch(/Reporting currency|Target ARR|Target date|As-of month|Fiscal year-end/);
  });

  test("a new audit is created with the defaults for the set-up fields, to be set on the next page", async () => {
    api.createAudit.mockResolvedValue({ id: "new1" });
    const set = async (id, value) => act(async () => {
      Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, "value").set.call(q(id), value);
      q(id).dispatchEvent(new Event("input", { bubbles: true }));
    });
    await set("audit-company-input", "TestCo");
    await act(async () => { q("submit-audit-button").click(); });
    expect(api.createAudit).toHaveBeenCalledWith({
      company_name: "TestCo", reporting_currency: "EUR", target_arr: 0, target_date: null, as_of_month: null,
      fiscal_year_end: 12, structure_reading_consent: true,
    });
    expect(mockNavigate).toHaveBeenCalledWith("/audit/new1/mapping");
  });
});

describe("the text above the name field and the consent default", () => {
  let cleanup;
  beforeEach(async () => { jest.clearAllMocks(); cleanup = await openDialog(); });
  afterEach(async () => { await cleanup(); });

  test("the title and the four paragraphs are the spec's words and stand above the name field", () => {
    expect(q("audit-dialog").textContent).toContain(NEW_AUDIT_TITLE);
    const intro = q("audit-dialog-intro");
    expect([...intro.querySelectorAll("p")].map((p) => p.textContent)).toEqual(NEW_AUDIT_PARAGRAPHS);
    expect(intro.compareDocumentPosition(q("audit-company-input")) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();
  });

  test("there is no client name field and no consent tick or explainer in the dialog", () => {
    for (const gone of ["audit-client-input", "audit-consent", "audit-consent-checkbox", "audit-consent-toggle", "audit-consent-explainer"]) {
      expect(q(gone)).toBeNull();
    }
    expect(q("audit-dialog").querySelector('[role="checkbox"]')).toBeNull();
    expect(q("audit-dialog").textContent).not.toMatch(/client name|What is sent/i);
  });

  test("a blank name is refused before anything is sent", async () => {
    await act(async () => { q("submit-audit-button").click(); });
    expect(api.createAudit).not.toHaveBeenCalled();
  });
});


describe("delete audit", () => {
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
      "Deleting this audit with its files, mappings and results cannot be undone. Type Acme SaaS Inc. to confirm.");
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

  test("the hub has no usage section: a tester's usage is not shown here, and nothing asks for the totals", async () => {
    expect(q("usage-totals")).toBeNull();
    expect(document.body.textContent).not.toContain("Your usage");
    expect(api.getUsageTotals).toBeUndefined();
  });
});

describe("the audit list when it cannot be read", () => {
  const fail = (status) => Object.assign(new Error("failed"), { response: { status, statusText: "", data: "<html>Bad gateway</html>" } });
  let host, root;
  const mountHub = async () => {
    host = document.createElement("div");
    document.body.appendChild(host);
    root = createRoot(host);
    await act(async () => { root.render(<AuditHub />); });
    await act(async () => { await Promise.resolve(); });
  };
  beforeEach(() => { api.listAudits.mockReset(); });
  afterEach(async () => { await act(async () => { root.unmount(); }); host.remove(); });

  test("a rejected listAudits (502) shows the message and a Retry, and no spinner", async () => {
    api.listAudits.mockRejectedValue(fail(502));
    await mountHub();
    expect(q("audits-load-error").textContent).toContain("Server is restarting – try again in a few seconds");
    expect(q("audits-load-retry").textContent).toBe("Retry");
    expect(document.body.querySelector(".animate-spin")).toBeNull();
  });

  test("Retry reads again and shows the list when the second read works", async () => {
    api.listAudits.mockRejectedValueOnce(fail(502)).mockResolvedValueOnce([
      { id: "a1", company_name: "Acme", status: "draft", reporting_currency: "EUR", target_arr: 0 }]);
    await mountHub();
    await act(async () => { q("audits-load-retry").click(); });
    await act(async () => { await Promise.resolve(); });
    expect(q("audits-load-error")).toBeNull();
    expect(q("audit-row-a1")).not.toBeNull();
    expect(api.listAudits).toHaveBeenCalledTimes(2);
  });

  test("under React.StrictMode the list and the error still land (alive ref is re-armed on the second mount)", async () => {
    api.listAudits.mockRejectedValue(fail(502));
    host = document.createElement("div");
    document.body.appendChild(host);
    root = createRoot(host);
    await act(async () => { root.render(<React.StrictMode><AuditHub /></React.StrictMode>); });
    await act(async () => { await Promise.resolve(); });
    expect(q("audits-load-error")).not.toBeNull();
  });
});

describe("the audit tile (docs/specs/chat-upload.md section 24)", () => {
  let root, host;
  const AUDITS = [
    { id: "a1", company_name: "Acme", status: "draft", reporting_currency: "EUR", target_arr: 2500000, target_date: "2027-06-30", created_at: "2026-10-18T14:32:00" },
    { id: "a2", company_name: "Beta", status: "draft", reporting_currency: "EUR", target_arr: 0, target_date: null, created_at: "2026-01-05T09:07:00" },
    { id: "a3", company_name: "Gamma", status: "draft", reporting_currency: "EUR", target_arr: null, created_at: null },
  ];
  beforeEach(async () => {
    mockNavigate.mockClear();
    api.listAudits.mockResolvedValue(AUDITS);
    host = document.createElement("div");
    document.body.appendChild(host);
    root = createRoot(host);
    await act(async () => { root.render(<AuditHub />); });
    await act(async () => { await Promise.resolve(); });
  });
  afterEach(async () => { await act(async () => { root.unmount(); }); host.remove(); });
  const tile = (id) => q(`audit-row-${id}`);
  const field = (id, key) => tile(id).querySelector(`[data-testid="${key}"]`).textContent;

  test("it shows Created with date and time, and no Target ARR or Target date", () => {
    expect(field("a1", "audit-created")).toBe("18 Oct 2026, 14:32");
    expect([...tile("a1").querySelectorAll("dt")].map((d) => d.textContent)).toEqual(["Created"]);
    expect(tile("a1").textContent).not.toMatch(/Target|n\.a\.(?!$)/);
    expect(tile("a1").querySelector('[data-testid="audit-target-arr"]')).toBeNull();
    expect(tile("a1").querySelector('[data-testid="audit-target-date"]')).toBeNull();
    expect(field("a2", "audit-created")).toBe("5 Jan 2026, 09:07");
    expect(field("a3", "audit-created")).toBe("n.a.");
  });

  test("the intro text is the agreed sentence", () => {
    expect(host.querySelector("h1").nextElementSibling.textContent.trim()).toBe(
      "Every number comes from your files. Each metric is calculated in Python from the rows you upload, never estimated, and shows the file, sheet and rows it came from.");
  });

  test("a time with an offset is shown in the viewer's local time", () => {
    const d = new Date("2026-10-18T23:30:00+00:00");
    const two = (n) => String(n).padStart(2, "0");
    expect(formatCreated("2026-10-18T23:30:00+00:00")).toBe(`${d.getDate()} Oct 2026, ${two(d.getHours())}:${two(d.getMinutes())}`);
    expect(formatCreated("not a date")).toBe("n.a.");
  });

  test("Open lands on Upload & Mapping", async () => {
    await act(async () => { q("open-dashboard-a1").click(); });
    expect(mockNavigate.mock.calls).toEqual([["/audit/a1/mapping"]]);
  });

  describe("Run audit on a tile runs the audit (George, 2026-10-27)", () => {
    const VIEW = { status: "ok", dtype: "revenue", file: "revenue.csv", pending: 0, missing_required: [] };
    const press = async (id) => { await act(async () => { q(id).click(); }); await act(async () => { await Promise.resolve(); }); await act(async () => { await Promise.resolve(); }); };
    beforeEach(() => {
      api.getDatasets.mockResolvedValue([VIEW]);
      api.getReview.mockResolvedValue({ computed: false });
      api.getDecks.mockResolvedValue({ decks: [], candidates: [] });
      api.runStage.mockImplementation(async (id, key) => ({ stage: key, status: "done" }));
    });
    afterEach(() => { jest.resetAllMocks(); });

    test("an audit that can run is run from the stage it stands at and ends on the Audit page, never on Upload & Mapping", async () => {
      await press("run-audit-a1");
      expect(api.runStage.mock.calls).toEqual([["a1", "engine"], ["a1", "claims"]]);
      expect(mockNavigate.mock.calls.map((c) => c[0])).toEqual(["/audit/a1/dashboard"]);
    });
    test("with no file the audit does not run: Upload & Mapping opens with one line saying what is missing", async () => {
      api.getDatasets.mockResolvedValue([]);
      await press("run-audit-a1");
      expect(api.runStage).not.toHaveBeenCalled();
      expect(mockNavigate).toHaveBeenCalledWith("/audit/a1/mapping", { state: { missing: "The audit cannot run yet. Missing: a file." } });
    });
    test("with Target ARR and Target date not set it still runs: they are parked and never block", async () => {
      await press("run-audit-a2");
      expect(api.runStage).toHaveBeenCalled();
      expect(mockNavigate.mock.calls.map((c) => c[0])).toEqual(["/audit/a2/dashboard"]);
    });
    test("a stage that fails opens Upload & Mapping with its message, where Retry stage is", async () => {
      api.runStage.mockImplementation(async (id, key) => (key === "engine" ? { stage: key, status: "failed", message: "The calculations could not be completed." } : { stage: key, status: "done" }));
      await press("run-audit-a1");
      expect(mockNavigate).toHaveBeenCalledWith("/audit/a1/mapping", { state: { missing: "The calculations could not be completed." } });
    });
    test("while an audit runs no second run starts", async () => {
      let release;
      api.runStage.mockImplementation((id, key) => new Promise((resolve) => { release = () => resolve({ stage: key, status: "done" }); }));
      await act(async () => { q("run-audit-a1").click(); });
      await act(async () => { await Promise.resolve(); });
      expect(q("run-audit-a1").disabled).toBe(true);
      expect(q("run-audit-a2").disabled).toBe(true);
      await act(async () => { release(); });
      await act(async () => { release(); });
      await act(async () => { await Promise.resolve(); });
    });
  });
});
