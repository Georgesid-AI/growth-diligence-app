import { placeTip } from "./tipPlacement";

const win = { width: 1440, height: 800 };
const tip = { width: 288, height: 120 };
const anchor = (left, top, w = 50, h = 16) => ({ left, top, right: left + w, bottom: top + h });

describe("placeTip keeps a pop-up inside the window (George, 2026-10-27)", () => {
  test("under the anchor, from its left edge, when there is room", () => {
    expect(placeTip(anchor(100, 300), tip, win)).toMatchObject({ left: 100, top: 320, flipLeft: false, flipUp: false });
  });
  test("flips left near the right edge: the pop-up's right edge on the anchor's right edge", () => {
    const at = placeTip(anchor(1380, 300), tip, win);
    expect(at).toMatchObject({ left: 1430 - 288, flipLeft: true });
    expect(at.left + tip.width).toBeLessThanOrEqual(win.width);
  });
  test("flips up near the bottom edge", () => {
    expect(placeTip(anchor(500, 780), tip, win)).toMatchObject({ top: 780 - 4 - 120, flipUp: true });
  });
  test("never goes past any edge, even when it fits on neither side", () => {
    const at = placeTip(anchor(5, 5, 10, 10), { width: 400, height: 900 }, { width: 380, height: 700 });
    expect([at.left >= 8, at.top >= 8]).toEqual([true, true]);
    const far = placeTip(anchor(1430, 790), tip, win);
    expect([far.left + 288 <= 1432, far.top + 120 <= 792]).toEqual([true, true]);
  });
});
