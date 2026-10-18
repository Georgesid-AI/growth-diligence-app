import React, { act } from "react";
import { createRoot } from "react-dom/client";

import AllowanceBanner from "./AllowanceBanner";
import { BLOCKERS_CHANGED } from "./BlockerBanner";
import * as api from "@/lib/api";
import { ALLOWANCE_REACHED, allowanceLine } from "@/lib/allowance";

jest.mock("@/lib/api", () => ({ getAllowance: jest.fn(), getBlockers: jest.fn() }));
jest.mock("react-router-dom", () => ({ Link: ({ to, children }) => <a href={to}>{children}</a> }), { virtual: true });
globalThis.IS_REACT_ACT_ENVIRONMENT = true;

let root, host;
const q = (id) => document.body.querySelector(`[data-testid="${id}"]`);
async function mount() {
  host = document.createElement("div");
  document.body.appendChild(host);
  root = createRoot(host);
  await act(async () => { root.render(<AllowanceBanner />); });
}
afterEach(async () => { await act(async () => { root.unmount(); }); host.remove(); jest.clearAllMocks(); });

test("below 80% nothing is shown", async () => {
  api.getAllowance.mockResolvedValue({ state: "ok", percent: 79 });
  await mount();
  expect(host.textContent).toBe("");
});

test("from 80% one line with the exact words and the rounded-down percent, no amount", async () => {
  api.getAllowance.mockResolvedValue({ state: "warn", percent: 83 });
  await mount();
  expect(q("allowance-warn").textContent).toBe("You have used 83% of this month's AI allowance.");
  expect(allowanceLine({ percent: 90 })).toBe("You have used 90% of this month's AI allowance.");
  expect(host.textContent).not.toMatch(/USD|\$|\d\.\d\d/);
  expect(q("allowance-reached")).toBeNull();
});

test("at 100% the full message replaces the line, word for word", async () => {
  api.getAllowance.mockResolvedValue({ state: "blocked", percent: 100 });
  await mount();
  expect(q("allowance-warn")).toBeNull();
  const paragraphs = [...q("allowance-reached").querySelectorAll("p")].map((p) => p.textContent);
  expect(paragraphs).toEqual(ALLOWANCE_REACHED);
  expect(host.textContent).not.toMatch(/USD|\$/);
  expect(paragraphs).toEqual([
    "Monthly AI allowance reached.",
    "AI steps are paused: AI column suggestions, reading board decks, and writing narratives.",
    "Everything else still works: all metrics (revenue, NRR, churn, CAC payback, sales cycle, win rate), data checks, saved mappings, your review and exports. These are calculated in Python from your files.",
    "New files can still be mapped by the app's rules; you confirm any column it is unsure about yourself.",
    "To raise your allowance, contact the app owner.",
  ]);
  expect(host.textContent).not.toMatch(/cost/i);
});

test("a failed read (the owner token's 404, access off) shows nothing, and the state is read again after an upload", async () => {
  api.getAllowance.mockRejectedValueOnce(new Error("404"));
  await mount();
  expect(host.textContent).toBe("");
  api.getAllowance.mockResolvedValue({ state: "warn", percent: 80 });
  await act(async () => { window.dispatchEvent(new Event(BLOCKERS_CHANGED)); });
  expect(q("allowance-warn")).not.toBeNull();
});
