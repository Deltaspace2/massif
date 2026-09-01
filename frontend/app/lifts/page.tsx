import type { Metadata } from "next";
import StatusLedger from "@/components/StatusLedger";

export const revalidate = 60;

export const metadata: Metadata = {
  title: "Lifts & railways",
  description:
    "Every tracked lift, cable car and mountain railway in the Mont Blanc " +
    "massif, with what its operator last published and when we last checked. " +
    "Coloured by season, not by the clock.",
};

export default function Lifts() {
  return <StatusLedger focus="lifts" />;
}
