"use client";

// PROTOTYPE — throwaway. Answers: "what should the calm review shell look
// like?" (bead pydexpi-datalog-1-2ki.3). Three structurally different
// directions, switchable via ?variant=. Sub-shape B (new page) per
// skill://prototype: this is a new top-level surface, not an adjustment to
// the existing chat app at app/page.tsx.
//
// Design tokens under exploration here (white ground, one accent, serif
// display face, shadow elevation) are captured in NOTES.md once a direction
// is chosen — see that file for the running verdict.
import { Fraunces } from "next/font/google";
import { Suspense } from "react";
import { useSearchParams } from "next/navigation";
import { PrototypeSwitcher } from "@/components/prototype/prototype-switcher";
import { VariantA } from "./variant-a";
import { VariantB } from "./variant-b";
import { VariantC } from "./variant-c";

const fraunces = Fraunces({
  subsets: ["latin"],
  variable: "--calm-display-font",
  display: "swap",
});

const variants = [
  { key: "A", name: "Rail + timeline" },
  { key: "B", name: "Hero-first, minimal chrome" },
  { key: "C", name: "Split workspace" },
];

function CalmShellPrototype() {
  const searchParams = useSearchParams();
  const variant = searchParams.get("variant") ?? "A";

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
      {variant === "A" && <VariantA />}
      {variant === "B" && <VariantB />}
      {variant === "C" && <VariantC />}
      <PrototypeSwitcher variants={variants} current={variant} />
    </div>
  );
}

export default function CalmShellPrototypePage() {
  return (
    <Suspense fallback={null}>
      <CalmShellPrototype />
    </Suspense>
  );
}
