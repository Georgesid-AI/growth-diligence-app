/**
 * Where a pop-up goes so that it stays inside the window (George, 2026-10-27): under its anchor and starting at the anchor's left edge; near the right
 * edge it flips left (its right edge on the anchor's right edge), near the bottom edge it flips up (above the anchor). Never past the window on any
 * side. All numbers are viewport pixels, as getBoundingClientRect gives them.
 */
export const TIP_MARGIN = 8;
export const TIP_GAP = 4;

export function placeTip(anchor, tip, win, { margin = TIP_MARGIN, gap = TIP_GAP } = {}) {
  const flipLeft = anchor.left + tip.width > win.width - margin;
  const flipUp = anchor.bottom + gap + tip.height > win.height - margin;
  const wantLeft = flipLeft ? anchor.right - tip.width : anchor.left;
  const wantTop = flipUp ? anchor.top - gap - tip.height : anchor.bottom + gap;
  return {
    left: Math.max(margin, Math.min(wantLeft, win.width - margin - tip.width)),
    top: Math.max(margin, Math.min(wantTop, win.height - margin - tip.height)),
    flipLeft,
    flipUp,
  };
}
