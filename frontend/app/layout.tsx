import type { Metadata } from "next";
import { Fraunces } from "next/font/google";
import { TooltipProvider } from "@/components/ui/tooltip";
import "./globals.css";

const fraunces = Fraunces({
  subsets: ["latin"],
  variable: "--calm-display-font",
  display: "swap",
});

export const metadata: Metadata = {
  title: "P&ID QA Assistant",
  description: "assistant-ui powered P&ID QA chat and graph workspace",
};

export default function RootLayout({
  children,
}: Readonly<{
  children: React.ReactNode;
}>) {
  return (
    <html lang="en" className={fraunces.variable}>
      <body>
        <TooltipProvider>{children}</TooltipProvider>
      </body>
    </html>
  );
}
