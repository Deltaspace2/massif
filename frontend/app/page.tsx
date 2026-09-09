import type { Metadata } from "next";
import StatusLedger from "@/components/StatusLedger";

export const revalidate = 60;

// No title or description here: the root ones live in layout.tsx and are the
// ones this site is found by. The three focused views below override them,
// because three pages sharing one description is three near-duplicates in an
// index — worse than not having them.
//
// The canonical is the exception, and has to be stated here rather than
// inherited: layout metadata is copied to every route below it verbatim, so a
// canonical set there would tell Google that all 140 urls on this site are
// copies of the front page. Naming only `alternates` leaves everything else
// inherited.
export const metadata: Metadata = {
  alternates: { canonical: "/" },
};

export default function Home() {
  return <StatusLedger focus="all" />;
}
