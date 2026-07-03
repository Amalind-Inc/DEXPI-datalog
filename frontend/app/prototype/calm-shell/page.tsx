"use client";

// PROTOTYPE — throwaway. Answered: "what should the calm review shell look
// like?" (bead pydexpi-datalog-1-2ki.3). Direction B ("hero-first, minimal
// chrome" with a split-pane P&ID panel) was approved by the user; the losing
// A/C variants and the comparison switcher have been deleted. This route
// stays as a living reference for the real shell implementation slice
// (2ki.10) — see NOTES.md for the verdict and captured design tokens.
import { Fraunces } from "next/font/google";
import { VariantB } from "./variant-b";

const fraunces = Fraunces({
  subsets: ["latin"],
  variable: "--calm-display-font",
  display: "swap",
});

export default function CalmShellPrototypePage() {
  return (
    <div
      className={`${fraunces.variable} min-h-screen bg-[var(--calm-paper)] text-[var(--calm-ink)]`}
      style={
        {
          "--calm-paper": "#fbfaf8",
          "--calm-ink": "#1c1815",
          "--calm-ink-muted": "#6b6259",
          "--calm-accent": "#b9542e",
          "--calm-accent-soft": "#f4e3d8",
          "--calm-line": "#e8e3dc",
        } as React.CSSProperties
      }
    >
      <VariantB />
    </div>
  );
}
