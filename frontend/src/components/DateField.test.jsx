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
  expect(q("d").value).toBe("30 Jun 2026");
  await act(async () => { root.unmount(); });
  host.remove();
  await mount("0001-01-01");
  expect([q("d").value, q("d").placeholder]).toEqual(["", "Pick"]);
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
  expect(q("d").value).toBe("15 Jul 2025");
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
  expect(q("d").value).toBe("");
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

const typeAndLeave = async (text) => {
  await act(async () => { q("d").focus(); });
  await type(q("d"), text);
  await act(async () => { q("d").blur(); });
};

test("a date can be typed as 2026-06-30 or as 30.06.2026; both give the same ISO value", async () => {
  await mount("");
  await typeAndLeave("2026-06-30");
  expect(changes).toEqual(["2026-06-30"]);
  expect(q("d").value).toBe("30 Jun 2026");
  await typeAndLeave("01.07.2027");
  expect(changes).toEqual(["2026-06-30", "2027-07-01"]);
  await typeAndLeave("1.2.2028");
  expect(changes.at(-1)).toBe("2028-02-01");
  expect(q("d-error")).toBeNull();
});

test("a typed date that is not one of the two forms, not real or outside 2000 to 2100 is refused and the value stays", async () => {
  await mount("2026-06-30");
  for (const bad of ["06/07/2026", "2026-02-30", "31.04.2026", "30.06.1999", "2101-01-01", "tomorrow", "30 Jun 2026"]) {
    await typeAndLeave(bad);
    expect(q("d-error").textContent).toBe("Type the date as 2026-06-30 or 30.06.2026");
    expect(q("d").value).toBe("30 Jun 2026");
  }
  expect(changes).toEqual([]);
  await typeAndLeave("2026-07-01");
  expect(q("d-error")).toBeNull();
  expect(changes).toEqual(["2026-07-01"]);
});

test("Enter commits a typed date and closes the calendar; emptying the box clears the value", async () => {
  await mount("2026-06-30");
  await open();
  await act(async () => { q("d").focus(); });
  await type(q("d"), "15.08.2026");
  await act(async () => { q("d").dispatchEvent(new KeyboardEvent("keydown", { key: "Enter", bubbles: true })); });
  expect(changes).toEqual(["2026-08-15"]);
  expect(q("d-calendar")).toBeNull();
  await typeAndLeave("");
  expect(changes).toEqual(["2026-08-15", ""]);
});

describe("the calendar opens on one side and stays there", () => {
  const rectAt = (bottom) => {
    const spy = jest.spyOn(HTMLElement.prototype, "getBoundingClientRect").mockReturnValue(
      { top: bottom - 36, bottom, left: 0, right: 200, width: 200, height: 36, x: 0, y: bottom - 36, toJSON() {} });
    return spy;
  };
  afterEach(() => jest.restoreAllMocks());

  test("room below: it opens below, and a different position afterwards does not move it", async () => {
    window.innerHeight = 900;
    const spy = rectAt(200);
    await mount("2026-06-30");
    await open();
    expect(q("d-calendar").getAttribute("data-side")).toBe("bottom");
    spy.mockReturnValue({ top: 800, bottom: 836, left: 0, right: 200, width: 200, height: 36, x: 0, y: 800, toJSON() {} });
    await act(async () => { window.dispatchEvent(new Event("scroll")); window.dispatchEvent(new Event("resize")); });
    await act(async () => { q("d-month-next").click(); });          // a month with another number of weeks
    expect(q("d-calendar").getAttribute("data-side")).toBe("bottom");
  });

  test("no room below: it opens above and stays above", async () => {
    window.innerHeight = 900;
    const spy = rectAt(800);
    await mount("2026-06-30");
    await open();
    expect(q("d-calendar").getAttribute("data-side")).toBe("top");
    spy.mockReturnValue({ top: 100, bottom: 136, left: 0, right: 200, width: 200, height: 36, x: 0, y: 100, toJSON() {} });
    await act(async () => { window.dispatchEvent(new Event("scroll")); });
    expect(q("d-calendar").getAttribute("data-side")).toBe("top");
  });

  test("every month shows six week rows, so the calendar's height never changes", async () => {
    await mount("2026-02-10");                                       // February 2026 spans four weeks
    await open();
    const rows = () => q("d-calendar").querySelectorAll("tbody tr").length;
    expect(rows()).toBe(6);
    await act(async () => { q("d-month-next").click(); });
    expect(rows()).toBe(6);
  });
});
