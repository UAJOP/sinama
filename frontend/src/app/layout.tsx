import type { Metadata } from "next";

import "./globals.css";


export const metadata: Metadata = {
  title: "SINAMA | Demo Agent Playground",
  description: "Turkish-first AI agent reliability lab",
};


export default function RootLayout({ children }: Readonly<{ children: React.ReactNode }>) {
  return (
    <html lang="tr">
      <body>{children}</body>
    </html>
  );
}
