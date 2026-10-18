// The tester's monthly AI allowance (docs/specs/usage-and-allowance.md section 5). Amounts are USD only.
const usd = (n) => Number(n).toFixed(2);
const whole = (n) => (Number.isInteger(Number(n)) ? String(Number(n)) : usd(n));

export const allowanceLine = ({ percent, used_usd, allowance_usd }) =>
  `You have used ${percent}% of this month's AI allowance (USD ${usd(used_usd)} of USD ${whole(allowance_usd)}).`;

export const ALLOWANCE_REACHED = [
  "You’ve reached your monthly AI allowance.",
  "AI features are paused for now, including column suggestions, reading board decks, and writing narratives.",
  "Everything else still works at no extra cost: all metrics (revenue, NRR, churn, CAC payback, sales cycle, and win rate), data checks, saved mappings, review, and exports.",
  "You can still upload new files. The app will match columns using its built-in rules and ask you to confirm any uncertain matches.",
  "Need a higher allowance? Contact the app owner.",
];

export const usdText = (n) => `USD ${usd(n)}`;
