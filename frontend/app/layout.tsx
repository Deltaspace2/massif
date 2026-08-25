import type { Metadata } from "next";
import "./globals.css";

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
    <html lang="en">
      <body>
        <div className="wrap">
          <header className="site">
            <h1>
              <a href="/" style={{ textDecoration: "none" }}>
                Mont Blanc massif — what&rsquo;s open, what&rsquo;s shut
              </a>
            </h1>
            <p>Published notices, with a source for every line. Not a safety service.</p>
          </header>
          {children}
        </div>
      </body>
    </html>
  );
}
