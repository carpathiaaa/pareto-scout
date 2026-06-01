import type { Metadata } from "next";
import "./globals.css";

export const metadata: Metadata = {
  title: "Pareto Scout — Review Desk",
  description: "Scored, drafted outreach candidates awaiting review.",
};

export default function RootLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  return (
    // suppressHydrationWarning: browser extensions (ad-blockers, window-resizers)
    // inject attributes like `speedupyoutubeads` / `resize` onto <html> before React
    // hydrates, which trips a benign hydration mismatch. This flag suppresses the
    // diff for THIS element's attributes only — it does not mask real mismatches in
    // the component tree below.
    <html lang="en" suppressHydrationWarning>
      <head>
        {/* Distinctive type: Fraunces (display serif) + IBM Plex Sans/Mono. Loaded
            via Google Fonts link rather than next/font to keep the build dependency
            footprint minimal for the POC. */}
        <link rel="preconnect" href="https://fonts.googleapis.com" />
        <link rel="preconnect" href="https://fonts.gstatic.com" crossOrigin="" />
        <link
          href="https://fonts.googleapis.com/css2?family=Fraunces:opsz,wght@9..144,500;9..144,600&family=IBM+Plex+Mono:wght@400;600&family=IBM+Plex+Sans:wght@400;500&display=swap"
          rel="stylesheet"
        />
      </head>
      <body>{children}</body>
    </html>
  );
}
