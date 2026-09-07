import type { Metadata } from "next";

export const metadata: Metadata = {
  title: "About",
  description:
    "What this site is, where every status comes from, how it is collected, " +
    "and how to ask for it to stop. A directory of published notices for the " +
    "Mont Blanc massif — not a safety service.",
};

const REPO = "https://github.com/Deltaspace2/massif";
const CONTACT = "steven@innes.io";

/** The sources, as `seeds/sources.yaml` has them.
 *
 *  Written out rather than fetched. The API returns statements, not a source
 *  register, and adding an endpoint so this page could render a list that
 *  changes twice a year would be machinery for its own sake. The cost is that
 *  it can drift — so it says when it was last checked, which is the honest
 *  way to publish a hand-maintained list.
 */
const SOURCES: {
  name: string;
  href: string;
  what: string;
  licence?: { name: string; href: string };
}[] = [
  {
    name: "Mairie de Saint-Gervais",
    href: "https://www.saintgervais.com/",
    what: "Arrêtés — legally binding closure decrees, which is why they outrank everything else here. The Goûter route regulation comes from here.",
  },
  {
    name: "Compagnie du Mont-Blanc",
    href: "https://www.montblancnaturalresort.com/",
    what: "Live lift status and the seasonal calendar for the Chamonix valley lifts and mountain railways.",
  },
  {
    name: "FFCAM",
    href: "https://www.ffcam.fr/",
    what: "Warden seasons for the federation's own refuges — Goûter, Tête Rousse, Argentière, Couvercle and the rest.",
  },
  {
    name: "hut-reservation.org",
    href: "https://www.hut-reservation.org/",
    what: "The Swiss Alpine Club booking platform, for the Trient and Orny huts.",
  },
  {
    name: "Tour du Mont-Blanc",
    href: "https://www.montourdumontblanc.com/",
    what: "Hut availability on both sides of the border — the only source here that carries French, Italian and Swiss refuges in one place.",
  },
  {
    name: "Tramway du Mont-Blanc",
    href: "https://www.tramwaydumontblanc.fr/",
    what: "The operator's own timetable for the tramway.",
  },
  {
    name: "Refuges.info",
    href: "https://www.refuges.info/",
    what: "A volunteer-maintained directory: hut capacities, wardening, water, and the state of a few huts nobody else reports on.",
    licence: {
      name: "CC BY-SA 2.0",
      href: "https://creativecommons.org/licenses/by-sa/2.0/",
    },
  },
  {
    name: "Camptocamp",
    href: "https://www.camptocamp.org/",
    what: "Hut descriptions, and dated condition reports written by people who were actually on the route.",
    licence: {
      name: "CC BY-SA",
      href: "https://creativecommons.org/licenses/by-sa/3.0/",
    },
  },
];

export default function About() {
  return (
    <main className="subpage">
      <a className="back" href="/">
        ← All statuses
      </a>
      <h1>About</h1>

      <p className="meta">
        This site answers one question: what is currently shut, restricted or
        officially flagged as dangerous in the Mont Blanc massif.
      </p>

      <p className="disclaimer">
        It is a <b>directory of published notices, not a safety service.</b> It
        reports what lift operators, mairies, hut federations and booking
        systems have actually said, links every claim back to whoever said it,
        and never makes a claim of its own. It does not know whether a route is
        safe, and it will not tell you whether to go. A status here can be out
        of date — every row shows when it was published and when we last
        confirmed it, and where we have nothing it says so rather than staying
        quiet.
      </p>

      {/* The primary reader of this page is not a climber. It is a sysadmin
          who found our User-Agent in their access log and followed the URL in
          it, and the first thing they need is to know who we are and how to
          make us stop. That is why this section is above the rest and not in a
          footer. */}
      <h2>If you are here from your server logs</h2>

      <p className="disclaimer">
        You have seen a request from{" "}
        <code>massif/0.1 (+{REPO}; {CONTACT})</code> and want to know what it
        is. It is this site, collecting whatever you publish about lifts, huts
        and mountain routes so that people can find it in one place, with a
        link back to you.
      </p>

      <ul className="about-list">
        <li>
          <b>robots.txt is honoured</b>, and a <i>robots.txt we cannot read is
          treated as a refusal</i> rather than as permission. Two hosts refuse
          us and are not fetched at all.
        </li>
        <li>
          <b>At least two seconds between requests</b> to the same host, always,
          regardless of how many pages we want.
        </li>
        <li>
          <b>Most sources are read once a week</b>, a few daily, and only the
          live lift feed more often than that. Nothing is crawled broadly: we
          fetch a known list of pages, not your whole site.
        </li>
        <li>
          <b>We keep a copy and re-read that, not you.</b> Every page fetched is
          stored, and when the parser improves it is re-run over the stored
          copies. Improving how we read your site costs you no traffic at all.
        </li>
        <li>
          <b>Everything is attributed and linked back</b> to the page it came
          from, on every row that uses it.
        </li>
      </ul>

      <p className="disclaimer">
        <b>If you would rather we did not,</b> email{" "}
        <a href={`mailto:${CONTACT}?subject=massif%20%E2%80%94%20please%20stop%20fetching`}>
          {CONTACT}
        </a>{" "}
        and we will stop, or add a <code>Disallow</code> for us in your
        robots.txt and we will stop by ourselves on the next run. You do not
        need to justify it and we will not ask you to.
      </p>

      <h2>Where the information comes from</h2>

      <p className="meta">
        Checked 7 September 2026. Sources are weighted: a mairie&rsquo;s decree
        outranks an operator&rsquo;s page, which outranks a booking calendar,
        which outranks a community report. Where two disagree, the more
        authoritative one is shown and the other is still listed on the
        feature&rsquo;s own page.
      </p>

      <ul className="about-list">
        {SOURCES.map((s) => (
          <li key={s.name}>
            <a href={s.href} rel="nofollow noopener">
              {s.name}
            </a>{" "}
            — {s.what}
            {s.licence && (
              <>
                {" "}
                Used under{" "}
                <a href={s.licence.href} rel="license noopener">
                  {s.licence.name}
                </a>
                , which is a condition rather than a courtesy: every row links
                back to the individual entry its author wrote.
              </>
            )}
          </li>
        ))}
      </ul>

      <h2>Two dates, not one</h2>

      <p className="disclaimer">
        Every status carries when the <b>source published it</b> and when{" "}
        <b>we last checked it still stood</b>. They are different facts and
        conflating them hides the one that matters: a decree from three months
        ago that we confirmed an hour ago is current, and a lift status from
        this morning that we have not re-read since is not. Rows aged past what
        their kind of notice holds for are marked <b>OLD</b>; rows we are
        overdue to re-read are marked <b>OVERDUE</b>.
      </p>

      <h2>Something wrong?</h2>

      <p className="disclaimer">
        A wrong status is worth telling us about, and so is a hut or lift we
        are missing, or an attribution we have got wrong.{" "}
        <a href="/feedback">Report it here</a> — it takes a couple of clicks and
        goes to a public issue tracker, or to email if you would rather.
      </p>

      <h2>Who runs it</h2>

      <p className="disclaimer">
        One person, as a personal project, with no commercial interest in any
        lift, hut or guiding company. The code is public at{" "}
        <a href={REPO} rel="noopener">
          github.com/Deltaspace2/massif
        </a>{" "}
        — including every source it reads and the rules it applies to them, so
        anything on this page can be checked rather than taken on trust.
      </p>
    </main>
  );
}
