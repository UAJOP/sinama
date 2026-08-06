import type { Metadata } from "next";

import { AppHeader } from "@/components/app-header";

import "./globals.css";

export const metadata: Metadata = {
  title: "SINAMA | Agent Reliability Lab",
  description: "Turkish-first AI agent reliability lab",
};

export default function RootLayout({ children }: Readonly<{ children: React.ReactNode }>) {
  return (
    <html lang="tr">
      <body>
        <AppHeader />
        {children}
      </body>
    </html>
  );
}
