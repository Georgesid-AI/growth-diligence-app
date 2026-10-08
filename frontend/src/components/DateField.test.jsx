import React, { act } from "react";
import { createRoot } from "react-dom/client";

import DateField from "./DateField";

globalThis.IS_REACT_ACT_ENVIRONMENT = true;

const q = (id) => document.body.querySelector(`[data-testid="${id}"]`);
const type = async (el, value) => act(async () => {
  Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, "value").set.call(el, value);
  el.dispatchEvent(new Event("input", { bubbles: true }));
});

let host, root, changes;
async function mount(value = "") {
  changes = [];
  host = document.createElement("div");
  document.body.appendChild(host);
  root = createRoot(host);
  const Harness = () => {
    const [v, setV] = React.useState(value);
    return <DateField testId="d" value={v} onChange={(x) => { changes.push(x); setV(x); }} placeholder="Pick" />;
  };
  await act(async () => { root.render(<Harness />); });
}
const open = async () => act(async () => { q("d").click(); });
afterEach(async () => { await act(async () => { root.unmount(); }); host.remove(); document.body.innerHTML = ""; });

test("it shows the date as 30 Jun 2026, or the placeholder; a value outside the range shows no year at all", async () => {
  await mount("2026-06-30");
  expect(q("d").textContent).toBe("30 Jun 2026");
  await act(async () => { root.unmount(); });
  host.remove();
  await mount("0001-01-01");
  expect(q("d").textContent).toBe("Pick");
  expect(document.body.textContent).not.toContain("0001");
});

test("month and year arrows move the calendar, and a day picks an ISO date", async () => {
  await mount("2026-06-30");
  await open();
  expect(q("d-month").textContent).toBe("June");
  expect(q("d-year").value).toBe("2026");
  await act(async () => { q("d-month-next").click(); });
  expect(q("d-month").textContent).toBe("July");
  await act(async () => { q("d-year-prev").click(); });
  expect(q("d-year").value).toBe("2025");
  await act(async () => { q("d-day-15").click(); });
  expect(changes).toEqual(["2025-07-15"]);
  expect(q("d").textContent).toBe("15 Jul 2025");
  expect(q("d-calendar")).toBeNull();
});

test("the month arrow crosses the year, and both stop at 2000 and 2100", async () => {
  await mount("2026-01-10");
  await open();
  await act(async () => { q("d-month-prev").click(); });
  expect([q("d-month").textContent, q("d-year").value]).toEqual(["December", "2025"]);
  await type(q("d-year"), "2000");
  await act(async () => { q("d-year").dispatchEvent(new KeyboardEvent("keydown", { key: "Enter", bubbles: true })); });
  await act(async () => { q("d-month-prev").click(); });          // December -> November 2000
  expect(q("d-year").value).toBe("2000");
  for (let i = 0; i < 11; i++) await act(async () => { q("d-month-prev").click(); });
  expect([q("d-month").textContent, q("d-year").value]).toEqual(["January", "2000"]);
  expect(q("d-month-prev").disabled).toBe(true);
  expect(q("d-year-prev").disabled).toBe(true);
  await type(q("d-year"), "2100");
  await act(async () => { q("d-year").dispatchEvent(new FocusEvent("focusout", { bubbles: true })); });
  expect(q("d-year").value).toBe("2100");
  for (let i = 0; i < 11; i++) await act(async () => { q("d-month-next").click(); });
  expect(q("d-month-next").disabled).toBe(true);
  expect(q("d-year-next").disabled).toBe(true);
});

test("a typed year inside the range moves the calendar; a year outside is rejected and the calendar stays", async () => {
  await mount("2026-06-30");
  await open();
  await type(q("d-year"), "2031");
  await act(async () => { q("d-year").dispatchEvent(new KeyboardEvent("keydown", { key: "Enter", bubbles: true })); });
  expect(q("d-year").value).toBe("2031");
  expect(q("d-year-error")).toBeNull();
  for (const bad of ["1999", "2101", "0001", "27", "0000"]) {
    await type(q("d-year"), bad);
    await act(async () => { q("d-year").dispatchEvent(new FocusEvent("focusout", { bubbles: true })); });
    expect(q("d-year-error").textContent).toBe("Year must be between 2000 and 2100");
    expect(q("d-year").value).toBe("2031");                       // back to the year the calendar shows
    expect(document.body.textContent).not.toMatch(/\b0001\b/);
  }
  await type(q("d-year"), "20a6");                                // only digits are typed
  expect(q("d-year").value).toBe("206");
  expect(changes).toEqual([]);
});

test("Clear empties an optional field", async () => {
  await mount("2026-06-30");
  await open();
  await act(async () => { q("d-clear").click(); });
  expect(changes).toEqual([""]);
  expect(q("d").textContent).toBe("Pick");
});

test("the message line keeps its height, so the grid does not move when the message goes away", async () => {
  await mount("2026-06-30");
  await open();
  const line = () => q("d-calendar").querySelector("p");
  const before = line().className;
  await type(q("d-year"), "1999");
  await act(async () => { q("d-year").dispatchEvent(new FocusEvent("focusout", { bubbles: true })); });
  expect(q("d-year-error")).not.toBeNull();
  expect(line().className).toBe(before);
  await act(async () => { q("d-day-9").click(); });                   // the first click after a rejected year picks the day
  expect(changes).toEqual(["2026-06-09"]);
});
