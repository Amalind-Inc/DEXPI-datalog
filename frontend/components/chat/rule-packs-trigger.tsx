"use client";

import { Layers } from "lucide-react";
import { useState } from "react";
import { RulePackPicker } from "@/components/chat/rule-pack-picker";

// Chat-scoped attach trigger (ADR 0006): the sidebar's Rule Packs item now
// navigates to the standalone /rule-packs browse page, so loading a pack
// onto the active chat needs its own entry point next to the composer.
// This stays the existing flyout for now; bead 2c5.4 replaces it with the
// full attach modal (search list + detail pane + View Page/Cancel/Use).
export function RulePacksTrigger() {
  const [open, setOpen] = useState(false);

  return (
    <>
      <button
        type="button"
        className="calm-chat-bar-btn"
        onClick={() => setOpen((value) => !value)}
      >
        <Layers size={15} aria-hidden="true" />
        <span>Rule Packs</span>
      </button>

      {open && (
        <div className="calm-flyout-backdrop" aria-hidden="true" onClick={() => setOpen(false)} />
      )}

      {open && (
        <div className="calm-flyout calm-flyout--wide" role="dialog" aria-label="Rule Packs">
          <RulePackPicker onRunPosted={() => setOpen(false)} />
        </div>
      )}
    </>
  );
}
