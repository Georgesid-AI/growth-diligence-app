import React, { act } from "react";
import { createRoot } from "react-dom/client";

import AuditSetup from "./AuditSetup";
import * as api from "@/lib/api";
import { CONSENT_LABEL, VERIFIED_LINE } from "@/lib/auditForm";

jest.mock("@/lib/api", () => ({ getAudit: jest.fn(), putIcInputs: jest.fn(), updateAudit: jest.fn() }));
jest.mock("sonner", () => ({ toast: { error: jest.fn(), success: jest.fn() } }));

globalThis.IS_REACT_ACT_ENVIRONMENT = true;
const q = (id) => document.body.querySelector(`[data-testid="${id}"]`);
const AUDIT = { id: "a1", company_name: "TestCo", reporting_currency: "EUR", target_arr: 0, fiscal_year_end: 12, structure_reading_consent: true };
let root, host;

async function mount(audit) {
  const setAudit = jest.fn();
  host = document.createElement("div");
  document.body.appendChild(host);
  root = createRoot(host);
  await act(async () => { root.render(<AuditSetup audit={audit} setAudit={setAudit} asOf="" setAsOf={jest.fn()} />); });
  return setAudit;
}
beforeEach(() => {
  jest.resetAllMocks();
  api.updateAudit.mockResolvedValue({});
  api.getAudit.mockResolvedValue(AUDIT);
});
afterEach(async () => { await act(async () => { root.unmount(); }); host.remove(); });

// docs/specs/chat-upload.md section 23
test("the consent tick sits in the set-up section with the spec's label and the verification line under it", async () => {
  await mount(AUDIT);
  const setup = q("audit-setup");
  expect(setup.contains(q("setup-consent-checkbox"))).toBe(true);
  expect(q("setup-consent-label").textContent).toBe(CONSENT_LABEL);
  expect(q("setup-verified-line").textContent).toBe(VERIFIED_LINE);
  expect(q("setup-consent-checkbox").checked).toBe(true);
});

test("the tick shows the audit's state: unticked, and an audit with no consent field, read as off", async () => {
  await mount({ ...AUDIT, structure_reading_consent: false });
  expect(q("setup-consent-checkbox").checked).toBe(false);
  await act(async () => { root.unmount(); }); host.remove();
  const { structure_reading_consent: _gone, ...old } = AUDIT;
  await mount(old);
  expect(q("setup-consent-checkbox").checked).toBe(false);
});

test("ticking and unticking save the consent like the other set-up fields", async () => {
  await mount({ ...AUDIT, structure_reading_consent: false });
  await act(async () => { q("setup-consent-checkbox").click(); });
  expect(api.updateAudit).toHaveBeenLastCalledWith("a1", { structure_reading_consent: true });
  await act(async () => { root.unmount(); }); host.remove();
  await mount(AUDIT);
  await act(async () => { q("setup-consent-checkbox").click(); });
  expect(api.updateAudit).toHaveBeenLastCalledWith("a1", { structure_reading_consent: false });
});
