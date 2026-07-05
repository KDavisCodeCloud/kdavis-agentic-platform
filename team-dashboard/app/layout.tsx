import type { Metadata } from "next";
import "./globals.css";

export const metadata: Metadata = {
  title: "THD Stack — Team Dashboard",
  description: "Team task management for THD Agentic Systems",
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="en">
      <body>{children}</body>
    </html>
  );
}
