import React, { act } from "react";
import { createRoot } from "react-dom/client";

import AuditHub from "./AuditHub";
import * as api from "@/lib/api";
import { CONSENT_EXPLAINER, CONSENT_LABEL } from "@/lib/auditForm";

jest.mock("@/lib/api", () => ({
  listAudits: jest.fn(),
  createAudit: jest.fn(),
  deleteAudit: jest.fn(),
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
