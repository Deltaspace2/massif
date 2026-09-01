import StatusLedger from "@/components/StatusLedger";

export const revalidate = 60;

// No metadata here: the root title and description live in layout.tsx and are
// the ones this site is found by. The three focused views below override them,
// because three pages sharing one description is three near-duplicates in an
// index — worse than not having them.

export default function Home() {
  return <StatusLedger focus="all" />;
}
