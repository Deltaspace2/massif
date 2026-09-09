import type { Metadata } from "next";
import StatusLedger from "@/components/StatusLedger";

export const revalidate = 60;

export const metadata: Metadata = {
  // Self-referential, and safe on a page rather than on the layout: layout
  // metadata is inherited verbatim by every route below it, so a canonical
  // there would name the front page as the original for the whole site.
  alternates: { canonical: "/routes" },
  title: "Routes, couloirs & access",
  description:
    "Routes, couloirs, glaciers and the access roads that reach them in the " +
    "Mont Blanc massif — what has been published about each, and when. " +
    "Absence is our coverage, not a report that a route is fine.",
};

export default function Routes() {
  return <StatusLedger focus="routes" />;
}
