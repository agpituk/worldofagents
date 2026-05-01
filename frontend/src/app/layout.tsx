import type { Metadata } from "next";
import Link from "next/link";
import "./globals.css";

export const metadata: Metadata = {
  title: "World of Agents",
  description:
    "A persistent MMO where LLM-driven heroes live a life on the prompts you wrote.",
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="en">
      <body className="min-h-screen">
        <header className="border-b border-border bg-bg-card/60 backdrop-blur">
          <div className="mx-auto max-w-6xl px-6 py-4 flex items-center justify-between">
            <Link href="/" className="text-2xl font-display text-amber">
              World of Agents
            </Link>
            <nav className="text-sm text-fg-muted flex gap-5">
              <Link href="/">World</Link>
              <a href="https://github.com/agpituk" target="_blank" rel="noreferrer">GitHub</a>
            </nav>
          </div>
        </header>
        <main className="mx-auto max-w-6xl px-6 py-8">{children}</main>
        <footer className="mx-auto max-w-6xl px-6 py-8 text-xs text-fg-muted">
          v0.4 · spectator UI
        </footer>
      </body>
    </html>
  );
}
