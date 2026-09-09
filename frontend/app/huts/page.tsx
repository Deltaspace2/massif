import type { Metadata } from "next";
import StatusLedger from "@/components/StatusLedger";

export const revalidate = 60;

export const metadata: Metadata = {
  // Self-referential, and safe on a page rather than on the layout: layout
  // metadata is inherited verbatim by every route below it, so a canonical
  // there would name the front page as the original for the whole site.
  alternates: { canonical: "/huts" },
  title: "Huts & refuges",
  description:
    "Every hut, refuge and bivouac tracked in the Mont Blanc massif, highest " +
    "first: capacity, warden and water from the directories, plus anything " +
    "published about them. These describe the building, not today.",
};

export default function Huts() {
  return <StatusLedger focus="huts" />;
}
