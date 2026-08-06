import type { Metadata } from "next";

import { RunsDashboard } from "./runs-dashboard";

export const metadata: Metadata = {
  title: "Test Runs | SINAMA",
  description: "Run and inspect deterministic SINAMA scenario packs.",
};

export default function RunsPage() {
  return <RunsDashboard />;
}
