import type { Metadata } from "next";
import Script from "next/script";
import type { ReactNode } from "react";
import { AppShell } from "@/components/chat/app-shell";
import {
  DEFAULT_WIDTH,
  MAX_WIDTH,
  MIN_WIDTH,
  WIDTH_STORAGE_KEY,
} from "@/components/chat/app-sidebar-constants";

export const metadata: Metadata = {
  title: "PortLog",
  description: "Harborfield's evidence-grounded engineering chat application.",
};

// Sets the sidebar's persisted width as a CSS var before the browser's first
// paint (a plain synchronous <script>, not next/script, so it runs in
// document order during HTML parsing) -- otherwise the SSR default (220px)
// paints first and visibly snaps to the stored width once React hydrates.
const setSidebarWidthVarScript = `(function(){try{var raw=window.localStorage.getItem(${JSON.stringify(
  WIDTH_STORAGE_KEY,
)});var n=raw?parseFloat(raw):NaN;var w=isFinite(n)?Math.min(${MAX_WIDTH},Math.max(${MIN_WIDTH},n)):${DEFAULT_WIDTH};document.documentElement.style.setProperty("--app-sidebar-width", w+"px");}catch(e){}})();`;

export default function ShellLayout({ children }: { children: ReactNode }) {
  return (
    <>
      <Script id="portlog-sidebar-width" strategy="beforeInteractive">
        {setSidebarWidthVarScript}
      </Script>
      <AppShell>{children}</AppShell>
    </>
  );
}
