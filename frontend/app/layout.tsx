import type { Metadata } from "next";
import { Fraunces } from "next/font/google";
import { AccountPanel } from "@/components/auth/account-panel";
import { TooltipProvider } from "@/components/ui/tooltip";
import { isHostedProfile } from "@/lib/deployment";
import "./globals.css";

const fraunces = Fraunces({
  subsets: ["latin"],
  variable: "--calm-display-font",
  display: "swap",
  preload: false,
});

export const metadata: Metadata = {
  title: {
    default: "Amalind",
    template: "%s · Amalind",
  },
  description: "Neurosymbolic engineering intelligence grounded in inspectable evidence.",
};

export default function RootLayout({
  children,
}: Readonly<{
  children: React.ReactNode;
}>) {
  return (
    <html lang="en" className={fraunces.variable}>
      <body>
        <TooltipProvider>
          {/* Server-resolved: the client bundle is never told the profile, and
              in the local profile this renders nothing at all. */}
          <AccountPanel hosted={isHostedProfile()} />
          {children}
        </TooltipProvider>
      </body>
    </html>
  );
}
