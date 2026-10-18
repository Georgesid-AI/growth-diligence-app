// The owner page (docs/specs/prompt-store.md section 3): the token is entered once and kept in memory only; prompts are listed by
// name, version and date and uploaded as new versions; tester links are issued (shown once), listed, revoked and re-issued. No audit
// data and no prompt text on the page beyond what the owner is typing in.
import React, { act } from "react";
import { createRoot } from "react-dom/client";

import OwnerPage from "./OwnerPage";
import * as api from "@/lib/api";

jest.mock("@/lib/api", () => ({
  ownerPrompts: jest.fn(), ownerUploadPrompt: jest.fn(), ownerTesters: jest.fn(),
  ownerIssueTester: jest.fn(), ownerRevokeTester: jest.fn(), ownerReissueTester: jest.fn(),
  ownerUsage: jest.fn(), ownerSetAllowance: jest.fn(), ownerAuditCosts: jest.fn(),
}));

globalThis.IS_REACT_ACT_ENVIRONMENT = true;

const q = (id) => document.body.querySelector(`[data-testid="${id}"]`);
const qa = (id) => [...document.body.querySelectorAll(`[data-testid="${id}"]`)];
const NAMES = ["growth_engine", "data_inventory", "data_integrity", "structure_reading"];
const LIST = { names: NAMES, missing: ["data_inventory", "data_integrity", "structure_reading"],
  prompts: [{ name: "growth_engine", version: "v2", uploaded_at: "2026-10-15T09:30:12+00:00", sha256: "a".repeat(64) },
            { name: "growth_engine", version: "v1", uploaded_at: "2026-10-14T08:00:00+00:00", sha256: "b".repeat(64) }] };
// the shape of GET /api/admin/testers (access-links.md section 2): no status field, it is read from the dates
const TESTERS = [{ id: "t1", label: "Tester One", created_at: "x", expires_at: "2999-11-14T09:30:00+00:00", revoked_at: null },
  { id: "t2", label: "Tester Two", created_at: "x", expires_at: "2999-11-14T09:30:00+00:00", revoked_at: "2026-10-15T10:00:00+00:00" },
  { id: "t3", label: "Tester Three", created_at: "x", expires_at: "2020-01-01T00:00:00+00:00", revoked_at: null }];

// the shape of GET /api/admin/usage (usage-and-allowance.md section 3)
const T = (files, calls, tokens, cost_usd) => ({ files, calls, tokens, cost_usd });
const USAGE = { month: "2026-10", totals: { this_month: T(3, 4, 1500, 1.75), all_time: T(5, 9, 4000, 5.75) },
  testers: [{ id: "t1", label: "Tester One", status: "active", allowance_usd: 10, this_month: T(2, 3, 1000, 1.25), all_time: T(4, 8, 3500, 5.25) },
            { id: "t2", label: "Tester Two", status: "revoked", allowance_usd: 25.5, this_month: T(1, 1, 500, 0.5), all_time: T(1, 1, 500, 0.5) }] };

// the shape of GET /api/admin/audit-costs (usage-and-allowance.md section 9): no audit id, company or file name
const COSTS = { audits: [
  { tester: "Tester One", created_at: "2026-10-18T14:32:00", calls: 3, tokens: 1500, cost_usd: 1.25 },
  { tester: null, created_at: "2026-01-05T09:07:00", calls: 0, tokens: 0, cost_usd: 0 }] };

function setValue(el, value) {
  const proto = { TEXTAREA: window.HTMLTextAreaElement, SELECT: window.HTMLSelectElement }[el.tagName] || window.HTMLInputElement;
  Object.getOwnPropertyDescriptor(proto.prototype, "value").set.call(el, value);
  el.dispatchEvent(new Event(el.tagName === "SELECT" ? "change" : "input", { bubbles: true }));
}

let host, root;
beforeEach(async () => {
  Object.values(api).filter((f) => typeof f === "function").forEach((f) => f.mockReset());
  api.ownerPrompts.mockResolvedValue(LIST);
  api.ownerTesters.mockResolvedValue(TESTERS);
  api.ownerUsage.mockResolvedValue(USAGE);
  api.ownerAuditCosts.mockResolvedValue(COSTS);
  window.localStorage.clear();
  host = document.createElement("div");
  document.body.appendChild(host);
  root = createRoot(host);
  await act(async () => { root.render(<OwnerPage />); });
});
afterEach(async () => { await act(async () => { root.unmount(); }); host.remove(); });

async function enter(token = "owner-secret") {
  await act(async () => { setValue(q("owner-token-input"), token); });
  await act(async () => { q("owner-enter").click(); });
}

test("only the token field shows until the owner token is accepted, and it is a password field", async () => {
  expect(q("owner-token-input").type).toBe("password");
  expect(q("owner-prompts")).toBeNull();
  expect(q("owner-testers")).toBeNull();
  expect(q("owner-enter").disabled).toBe(true);
});

test("a token the server refuses shows a message and opens nothing", async () => {
  api.ownerPrompts.mockRejectedValue({ response: { status: 401, data: { detail: "x" } } });
  await enter("wrong");
  expect(q("owner-error").textContent).toBe("The owner token was not accepted.");
  expect(q("owner-prompts")).toBeNull();
});

test("the accepted token is kept in memory only: not in storage, not in the page, and the field is gone", async () => {
  await enter("owner-secret");
  expect(api.ownerPrompts).toHaveBeenCalledWith("owner-secret");
  expect(q("owner-token-input")).toBeNull();
  expect(document.body.innerHTML).not.toContain("owner-secret");
  expect(JSON.stringify({ ...window.localStorage })).not.toContain("owner-secret");
  expect(JSON.stringify({ ...window.sessionStorage })).not.toContain("owner-secret");
  expect(window.location.href).not.toContain("owner-secret");
});

test("prompts are listed by name, version and date, newest first as the server sends them, with a note for the names that hold none", async () => {
  await enter();
  const rows = qa("owner-prompt-row").map((r) => r.textContent);
  expect(rows).toHaveLength(2);
  expect(rows[0]).toContain("growth_engine");
  expect(rows[0]).toContain("v2");
  expect(rows[0]).toContain("2026-10-15 09:30 UTC");
  expect(rows[1]).toContain("v1");
  expect(q("owner-prompts-missing").textContent).toContain("data_inventory, data_integrity, structure_reading");
  expect(host.textContent).not.toContain("a".repeat(64));      // a short hash only
});

test("pasted text is uploaded under the chosen name, the text is cleared afterwards and the list is read again", async () => {
  await enter();
  api.ownerUploadPrompt.mockResolvedValue({ name: "data_integrity", version: "v1" });
  await act(async () => { setValue(q("owner-prompt-name"), "data_integrity"); });
  expect(q("owner-prompt-upload").disabled).toBe(true);
  await act(async () => { setValue(q("owner-prompt-text"), "pasted prompt text"); });
  await act(async () => { q("owner-prompt-upload").click(); });
  expect(api.ownerUploadPrompt).toHaveBeenCalledWith("owner-secret", "data_integrity", "pasted prompt text");
  expect(api.ownerPrompts).toHaveBeenCalledTimes(2);
  expect(q("owner-prompt-text").value).toBe("");
});

test("a file is read in the browser and uploaded as text", async () => {
  await enter();
  api.ownerUploadPrompt.mockResolvedValue({});
  const file = new File(["text from a file"], "growth_engine.md", { type: "text/markdown" });
  const input = q("owner-prompt-file");
  Object.defineProperty(input, "files", { value: [file], configurable: true });
  await act(async () => { input.dispatchEvent(new Event("change", { bubbles: true })); });
  await act(async () => { await new Promise((r) => setTimeout(r, 30)); });
  expect(q("owner-prompt-text").value).toBe("text from a file");
  await act(async () => { q("owner-prompt-upload").click(); });
  expect(api.ownerUploadPrompt).toHaveBeenCalledWith("owner-secret", "growth_engine", "text from a file");
});

test("a refused upload shows the server's reason and keeps the text for another try", async () => {
  await enter();
  api.ownerUploadPrompt.mockRejectedValue({ response: { status: 422, statusText: "", data: { detail: "the prompt text is empty" } } });
  await act(async () => { setValue(q("owner-prompt-text"), "x"); });
  await act(async () => { q("owner-prompt-upload").click(); });
  expect(q("owner-error").textContent).toContain("the prompt text is empty");
  expect(q("owner-prompt-text").value).toBe("x");
});

test("there is no way to delete or read back a prompt on the page", async () => {
  await enter();
  const labels = [...document.body.querySelectorAll("button")].map((b) => b.textContent.toLowerCase());
  expect(labels.some((l) => l.includes("delete") || l.includes("remove") || l.includes("view") || l.includes("show text"))).toBe(false);
});

test("the tester list shows name and a status read from the dates, and Revoke is off for a revoked tester", async () => {
  await enter();
  expect(qa("owner-tester-row").map((r) => r.querySelector('[data-testid="owner-tester-status"]').textContent)).toEqual(["active", "revoked", "expired"]);
  expect(qa("owner-tester-revoke").map((b) => b.disabled)).toEqual([false, true, false]);
});

test("an issued link is shown once with its warning, built on this page's address whatever address the server printed, and gone once dismissed", async () => {
  await enter();
  api.ownerIssueTester.mockResolvedValue({ id: "t9", label: "New Tester", link: "https://backend.example/t/abc123" });
  await act(async () => { setValue(q("owner-tester-name"), "New Tester"); });
  await act(async () => { q("owner-tester-issue").click(); });
  expect(api.ownerIssueTester).toHaveBeenCalledWith("owner-secret", "New Tester");
  expect(q("owner-link").value).toBe(`${window.location.origin}/t/abc123`);
  expect(q("owner-link-once").textContent).toContain("Shown once");
  expect(api.ownerTesters).toHaveBeenCalledTimes(2);
  await act(async () => { q("owner-link-dismiss").click(); });
  expect(q("owner-link-once")).toBeNull();
  expect(document.body.innerHTML).not.toContain("abc123");
});

test("revoke and re-issue call the server for that tester; a re-issue shows the new link once", async () => {
  await enter();
  api.ownerRevokeTester.mockResolvedValue({});
  await act(async () => { qa("owner-tester-revoke")[0].click(); });
  expect(api.ownerRevokeTester).toHaveBeenCalledWith("owner-secret", "t1");
  api.ownerReissueTester.mockResolvedValue({ id: "t2", link: "https://backend.example/t/fresh" });
  await act(async () => { qa("owner-tester-reissue")[1].click(); });
  expect(api.ownerReissueTester).toHaveBeenCalledWith("owner-secret", "t2");
  expect(q("owner-link").value).toBe(`${window.location.origin}/t/fresh`);
  expect(q("owner-link-once").textContent).toContain("Tester Two");
});

test("the page shows no audit data: it imports only the owner calls and renders no company or file word", async () => {
  await enter();
  const source = require("fs").readFileSync(require("path").join(__dirname, "OwnerPage.jsx"), "utf8");
  const imported = /import \{([^}]*)\} from "@\/lib\/api"/.exec(source)[1].split(",").map((x) => x.trim()).filter(Boolean);
  expect(imported.length).toBeGreaterThan(0);
  expect(imported.every((name) => name.startsWith("owner"))).toBe(true);
  expect(host.textContent.toLowerCase()).not.toMatch(/company|revenue|deck|claim/);
});

test("the Usage section lists totals and one row per tester label, this month and all time, in USD", async () => {
  await enter();
  const cellsOf = (tr) => [...tr.querySelectorAll("td")].map((td) => td.textContent);
  expect(cellsOf(q("owner-usage-totals")).slice(0, 9)).toEqual(["All testers", "3", "4", "1,500", "USD 1.75", "5", "9", "4,000", "USD 5.75"]);
  expect(qa("owner-usage-row").map((tr) => cellsOf(tr).slice(0, 9))).toEqual([
    ["Tester One", "2", "3", "1,000", "USD 1.25", "4", "8", "3,500", "USD 5.25"],
    ["Tester Two", "1", "1", "500", "USD 0.50", "1", "1", "500", "USD 0.50"]]);
  expect(q("owner-usage").textContent).not.toMatch(/\.xlsx|\.pptx/);
  expect(qa("owner-allowance-input").map((i) => i.value)).toEqual(["10", "25.5"]);
});

test("an allowance is saved per link, only when it is a valid changed USD amount, and the usage is read again", async () => {
  api.ownerSetAllowance.mockResolvedValue({ ok: true });
  await enter();
  const [save] = qa("owner-allowance-save");
  expect(save.disabled).toBe(true);
  await act(async () => { setValue(qa("owner-allowance-input")[0], "1001"); });
  expect(qa("owner-allowance-save")[0].disabled).toBe(true);
  await act(async () => { setValue(qa("owner-allowance-input")[0], "15.5"); });
  expect(qa("owner-allowance-save")[0].disabled).toBe(false);
  await act(async () => { qa("owner-allowance-save")[0].click(); });
  expect(api.ownerSetAllowance).toHaveBeenCalledWith("owner-secret", "t1", 15.5);
  expect(api.ownerUsage).toHaveBeenCalledTimes(2);
});

test("Cost per audit lists tester label, creation time, AI calls, tokens and USD, and never an audit, company or file name", async () => {
  await enter();
  expect(api.ownerAuditCosts).toHaveBeenCalledWith("owner-secret");
  const rows = qa("owner-audit-cost-row").map((tr) => [...tr.children].map((c) => c.textContent));
  expect(rows).toEqual([
    ["Tester One", "18 Oct 2026, 14:32", "3", "1,500", "USD 1.25"],
    ["no tester", "5 Jan 2026, 09:07", "0", "0", "USD 0.00"],
  ]);
  expect([...q("owner-audit-costs-table").querySelectorAll("th")].map((th) => th.textContent)).toEqual(["Tester", "Audit created", "AI calls", "Tokens", "Cost"]);
  expect(q("owner-audit-costs").textContent).not.toMatch(/\.xlsx|\.pptx|\.csv|company/i);
});

test("a failed read of the cost list leaves the rest of the owner page working", async () => {
  api.ownerAuditCosts.mockRejectedValue(new Error("500"));
  await enter();
  expect(q("owner-audit-costs")).toBeNull();
  expect(q("owner-usage")).not.toBeNull();
});
