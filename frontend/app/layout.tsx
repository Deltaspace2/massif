import type { Metadata } from "next";
import localFont from "next/font/local";
import "./globals.css";

// The woff2 files live in the repo rather than being fetched from Google at
// build time. next/font/google would self-host them in the output either way,
// but it needs egress *during the build* — and this project is meant to build
// in a CI runner and in an unattended container, neither of which is
// guaranteed to reach fonts.gstatic.com. Latin subset only; 84 KB in total.
const archivo = localFont({
  src: [{ path: "./fonts/archivo-200_700.woff2", weight: "200 700", style: "normal" }],
  variable: "--font-archivo",
  display: "swap",
});

const plexMono = localFont({
  src: [
    { path: "./fonts/plexmono-400.woff2", weight: "400", style: "normal" },
    { path: "./fonts/plexmono-500.woff2", weight: "500", style: "normal" },
    { path: "./fonts/plexmono-600.woff2", weight: "600", style: "normal" },
  ],
  variable: "--font-plex-mono",
  display: "swap",
});

export const metadata: Metadata = {
  title: {
    default: "Mont Blanc massif — what's open, what's shut",
    template: "%s — massif",
  },
  description:
    "Live closure and status directory for the Mont Blanc massif: lifts, " +
    "mountain railways, huts and routes, with the source for every claim.",
};

export default function RootLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  return (
    <html lang="en" className={`${archivo.variable} ${plexMono.variable}`}>
      <body>
        {/* The masthead is a solid bar rather than white text floating on the
            photo. See the note in globals.css — over this image the floating
            version measures 1.9:1, and no scrim opacity rescues it. */}
        <header className="masthead">
          <a href="/" className="masthead__mark">
            MASSIF
          </a>
          <nav className="masthead__nav">
            <a href="/#map">MAP</a>
            <a href="/feed">FEED</a>
          </nav>
        </header>
        {children}
      </body>
    </html>
  );
}
