"use client";

// PROTOTYPE-ONLY. Floating variant switcher for UI prototypes, gated off in
// production builds. See skill://prototype (UI branch).
import { useRouter, useSearchParams } from "next/navigation";
import { useEffect } from "react";

type Variant = { key: string; name: string };

export function PrototypeSwitcher({
  variants,
  current,
  paramName = "variant",
}: {
  variants: Variant[];
  current: string;
  paramName?: string;
}) {
  const router = useRouter();
  const searchParams = useSearchParams();

  if (process.env.NODE_ENV === "production") return null;

  const index = Math.max(
    0,
    variants.findIndex((variant) => variant.key === current),
  );

  function go(nextIndex: number) {
    const wrapped = (nextIndex + variants.length) % variants.length;
    const params = new URLSearchParams(searchParams.toString());
    params.set(paramName, variants[wrapped].key);
    router.replace(`?${params.toString()}`);
  }

  useEffect(() => {
    function onKeyDown(event: KeyboardEvent) {
      const target = event.target as HTMLElement | null;
      const isTyping =
        target?.tagName === "INPUT" ||
        target?.tagName === "TEXTAREA" ||
        target?.isContentEditable;
      if (isTyping) return;
      if (event.key === "ArrowLeft") go(index - 1);
      if (event.key === "ArrowRight") go(index + 1);
    }
    window.addEventListener("keydown", onKeyDown);
    return () => window.removeEventListener("keydown", onKeyDown);
  });

  const active = variants[index];

  return (
    <div className="fixed bottom-5 left-1/2 z-[9999] flex -translate-x-1/2 items-center gap-3 rounded-full border border-black/10 bg-black px-2 py-1.5 text-white shadow-[0_8px_30px_rgba(0,0,0,0.35)]">
      <button
        type="button"
        aria-label="Previous variant"
        onClick={() => go(index - 1)}
        className="flex h-7 w-7 items-center justify-center rounded-full text-white/70 hover:bg-white/10 hover:text-white"
      >
        ←
      </button>
      <span className="min-w-[9rem] px-1 text-center text-xs font-medium tracking-wide">
        {active.key} — {active.name}
      </span>
      <button
        type="button"
        aria-label="Next variant"
        onClick={() => go(index + 1)}
        className="flex h-7 w-7 items-center justify-center rounded-full text-white/70 hover:bg-white/10 hover:text-white"
      >
        →
      </button>
    </div>
  );
}
