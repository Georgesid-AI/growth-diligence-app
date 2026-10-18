2026-10-18, claude/charming-dijkstra-w5fw70 (PR #128 decision: the 100% allowance message and the helper wording no longer mention cost)
Deleted: "at no extra cost", "Costs one AI request", "costs another AI request" and "for free" from every tester string.
Decided: the five-line message is George's text word for word in `lib/allowance.js` and the spec; "Uses one AI request" replaces the helper wording because the brief says no other tester text may mention cost.
Slow or unclear: nothing; code comments that say "cost" are not tester screens and stay.
Root cause and rule: the earlier brief allowed "Costs one AI request" and an approved message with "no extra cost", so the hidden-cost rule had two exceptions in wording. Rule: tester strings never name cost; `AllowanceBanner.test.jsx` checks the banner text for it.
Process change to propose: when a figure is hidden from an audience, the brief lists the words as well as the numbers.
