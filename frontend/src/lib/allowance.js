// The tester's monthly AI allowance (docs/specs/usage-and-allowance.md sections 5 and 9). A percentage only: no amount on a tester screen.
export const allowanceLine = ({ percent }) => `You have used ${percent}% of this month's AI allowance.`;

export const ALLOWANCE_REACHED = [
  "Monthly AI allowance reached.",
  "AI steps are paused: AI column suggestions, reading board decks, and writing narratives.",
  "Everything else still works: all metrics (revenue, NRR, churn, CAC payback, sales cycle, win rate), data checks, saved mappings, your review and exports. These are calculated in Python from your files.",
  "New files can still be mapped by the app's rules; you confirm any column it is unsure about yourself.",
  "To raise your allowance, contact the app owner.",
];

