// Analyst note box: help text, character counter from the API's note_max, hard stop at the limit; no summary line says "tokenised".
import React, { act } from "react";
import { createRoot } from "react-dom/client";

import { AnalystNote } from "./Verdict";
import { NOTE_HELP } from "@/lib/verdict";
import { deckReadLine, deckSummaryLine } from "@/lib/deckClaims";

jest.mock("@/lib/api", () => ({ putIcInputs: jest.fn(() => Promise.resolve({})) }));
jest.mock("sonner", () => ({ toast: { error: jest.fn(), success: jest.fn() } }));
globalThis.IS_REACT_ACT_ENVIRONMENT = true;

const HELP = "Your own words, added as the last line of the verdict in the downloaded report and marked as yours. Never sent to any AI. Use it for what the files cannot show: a call booked, a figure management confirmed, a file promised.";

async function mount(props) {
  const host = document.createElement("div"); document.body.appendChild(host);
  const root = createRoot(host);
  await act(async () => { root.render(<AnalystNote auditId="a1" {...props} />); });
  return { host, done: async () => { await act(async () => root.unmount()); host.remove(); } };
}
const type = async (ta, value) => {
  const set = Object.getOwnPropertyDescriptor(HTMLTextAreaElement.prototype, "value").set;
  await act(async () => { set.call(ta, value); ta.dispatchEvent(new Event("input", { bubbles: true })); });
};

test("the help text renders word for word", async () => {
  const { host, done } = await mount({ note: null, noteMax: 1000 });
  try {
    expect(NOTE_HELP).toBe(HELP);
    expect(host.querySelector('[data-testid="analyst-note-help"]').textContent).toBe(HELP);
  } finally { await done(); }
});

test("the counter shows the length and the API's note_max, red at the limit, and the field takes no more", async () => {
  const { host, done } = await mount({ note: null, noteMax: 12 });
  try {
    const ta = host.querySelector('[data-testid="analyst-note-text"]');
    const count = () => host.querySelector('[data-testid="analyst-note-count"]');
    expect(count().textContent).toBe("0/12");
    expect(count().className).not.toMatch(/red/);
    await type(ta, "hello");
    expect(count().textContent).toBe("5/12");
    expect(ta.getAttribute("maxlength")).toBe("12");
    await type(ta, "x".repeat(12));
    expect(count().textContent).toBe("12/12");
    expect(count().className).toMatch(/red/);
    expect(ta.maxLength).toBe(12);   // the browser refuses a 13th typed character
  } finally { await done(); }
});

test("no summary line says tokenised", () => {
  const deck = { pages: 24, figure_pages: 9, ai_status: "read", read: 7, rejected: 2, personal_removed: 3, names_replaced: 5 };
  for (const line of [deckReadLine(deck), deckSummaryLine(deck), "Sent to the AI: 2 lines. Personal items removed: 0. Company names coded: 2. Columns withheld: 0."]) {
    expect(line).not.toMatch(/tokenised/i);
    expect(line).toMatch(/company names coded/i);
  }
});
