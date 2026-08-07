import type { Metadata } from "next";

import { AppHeader } from "@/components/app-header";

import "./globals.css";

export const metadata: Metadata = {
  metadataBase: new URL("https://sinama.kaanbalci.com"),
  title: "SINAMA — AI Agent Reliability Lab",
  description: "Turkish-first AI agent reliability lab",
  icons: {
    icon: "/favicon.ico",
    apple: "/apple-touch-icon.png",
  },
  openGraph: {
    title: "SINAMA — AI Agent Reliability Lab",
    description: "Turkish-first AI agent reliability lab",
    images: ["/media/sinama-social-cover.png"],
  },
  twitter: {
    card: "summary_large_image",
    title: "SINAMA — AI Agent Reliability Lab",
    description: "Turkish-first AI agent reliability lab",
    images: ["/media/sinama-social-cover.png"],
  },
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
