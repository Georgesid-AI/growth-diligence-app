// The tester's monthly AI allowance (docs/specs/usage-and-allowance.md sections 5 and 9). A percentage only: no amount on a tester screen.
export const allowanceLine = ({ percent }) => `You have used ${percent}% of this month's AI allowance.`;

export const ALLOWANCE_REACHED = [
  "You’ve reached your monthly AI allowance.",
  "AI features are paused for now, including column suggestions, reading board decks, and writing narratives.",
  "Everything else still works at no extra cost: all metrics (revenue, NRR, churn, CAC payback, sales cycle, and win rate), data checks, saved mappings, review, and exports.",
  "You can still upload new files. The app will match columns using its built-in rules and ask you to confirm any uncertain matches.",
  "Need a higher allowance? Contact the app owner.",
];

