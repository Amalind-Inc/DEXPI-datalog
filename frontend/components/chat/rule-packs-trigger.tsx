"use client";

import { Layers } from "lucide-react";
import { useState } from "react";
import { RulePackPicker } from "@/components/chat/rule-pack-picker";

// Chat-scoped attach trigger (bead 2c5.4, MikeOSS composer reference): lives
// inside the composer's action row next to the + (P&ID attach) button, since
// the sidebar's Rule Packs item navigates to the standalone /rule-packs
// browse page. Opens the picker over a blurred backdrop; the full attach
// modal (detail pane + View Page/Cancel/Use + chips) is the rest of 2c5.4.
export function RulePacksTrigger() {
  const [open, setOpen] = useState(false);

  return (
    <>
      <button
        type="button"
        className="aui-composer-rule-packs text-muted-foreground hover:bg-muted-foreground/15 flex h-7 items-center gap-1.5 rounded-full px-2.5 text-xs font-medium"
        onClick={() => setOpen((value) => !value)}
      >
        <Layers size={14} aria-hidden="true" />
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
