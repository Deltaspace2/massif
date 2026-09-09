import type { Metadata } from "next";
import StatusLedgerRuled from "@/components/StatusLedgerRuled";

export const revalidate = 60;

/** The previous front page, design 9c ("Ruled Ledger"), kept reachable.
 *
 *  `/` now renders 11a ("Photo Headers"). This route exists so the two can be
 *  compared in a browser rather than in a diff, while the choice between them
 *  is still open.
 *
 *  NOINDEX, and that is not optional. This renders the same statuses as `/`,
 *  and SEO is this project's distribution channel — two indexable pages with
 *  the same content is a request to have one of them treated as a duplicate,
 *  and there is no guarantee Google keeps the one we want. The canonical
 *  points home for the same reason.
 */
export const metadata: Metadata = {
  title: "Ruled ledger (previous design)",
  robots: { index: false, follow: false },
  alternates: { canonical: "/" },
};

export default function ClassicPage() {
  return <StatusLedgerRuled focus="all" />;
}
