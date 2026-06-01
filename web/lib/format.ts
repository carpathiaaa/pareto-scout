// Small presentational helpers shared by the cards. Pure functions, no UI.

import type { Status } from "./types";

// Map a 0-100 score to a spine/gauge color: amber for strong, fading to rose for weak.
export function scoreColor(score: number | null): string {
  if (score === null) return "var(--paper-faint)";
  if (score >= 80) return "var(--signal)";
  if (score >= 55) return "var(--signal-deep)";
  if (score >= 30) return "var(--tier-3)";
  return "var(--rose)";
}

// Map a reachability tier (1 best .. 4 weakest) to its color token.
export function tierColor(tier: number | null): string {
  switch (tier) {
    case 1: return "var(--tier-1)";
    case 2: return "var(--tier-2)";
    case 3: return "var(--tier-3)";
    default: return "var(--tier-4)";
  }
}

export function tierLabel(tier: number | null): string {
  switch (tier) {
    case 1: return "Tier 1 · email";
    case 2: return "Tier 2 · platform";
    case 3: return "Tier 3 · profile";
    default: return "Tier 4 · weak";
  }
}

export function statusClass(status: Status): string {
  return status === "new" ? "status-new" : status === "archived" ? "status-archived" : "";
}
