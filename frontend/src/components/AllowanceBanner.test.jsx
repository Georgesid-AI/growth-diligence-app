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
  api.getAllowance.mockResolvedValue({ state: "ok", percent: 79, used_usd: 7.9, allowance_usd: 10 });
  await mount();
  expect(host.textContent).toBe("");
});

test("from 80% one line with the exact words, rounded-down percent, USD with two decimals and a whole allowance", async () => {
  api.getAllowance.mockResolvedValue({ state: "warn", percent: 83, used_usd: 8.3, allowance_usd: 10 });
  await mount();
  expect(q("allowance-warn").textContent).toBe("You have used 83% of this month's AI allowance (USD 8.30 of USD 10).");
  expect(allowanceLine({ percent: 90, used_usd: 11.25, allowance_usd: 12.5 })).toBe("You have used 90% of this month's AI allowance (USD 11.25 of USD 12.50).");
  expect(q("allowance-reached")).toBeNull();
});

test("at 100% the full message replaces the line, word for word", async () => {
  api.getAllowance.mockResolvedValue({ state: "blocked", percent: 100, used_usd: 10, allowance_usd: 10 });
  await mount();
  expect(q("allowance-warn")).toBeNull();
  const paragraphs = [...q("allowance-reached").querySelectorAll("p")].map((p) => p.textContent);
  expect(paragraphs).toEqual(ALLOWANCE_REACHED);
  expect(paragraphs).toEqual([
    "You’ve reached your monthly AI allowance.",
    "AI features are paused for now, including column suggestions, reading board decks, and writing narratives.",
    "Everything else still works at no extra cost: all metrics (revenue, NRR, churn, CAC payback, sales cycle, and win rate), data checks, saved mappings, review, and exports.",
    "You can still upload new files. The app will match columns using its built-in rules and ask you to confirm any uncertain matches.",
    "Need a higher allowance? Contact the app owner.",
  ]);
});

test("a failed read (the owner token's 404, access off) shows nothing, and the state is read again after an upload", async () => {
  api.getAllowance.mockRejectedValueOnce(new Error("404"));
  await mount();
  expect(host.textContent).toBe("");
  api.getAllowance.mockResolvedValue({ state: "warn", percent: 80, used_usd: 8, allowance_usd: 10 });
  await act(async () => { window.dispatchEvent(new Event(BLOCKERS_CHANGED)); });
  expect(q("allowance-warn")).not.toBeNull();
});
