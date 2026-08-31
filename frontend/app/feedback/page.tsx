import type { Metadata } from "next";

export const metadata: Metadata = {
  title: "Report a problem",
  description:
    "Report a wrong status, a missing hut or lift, or an attribution problem " +
    "in the Mont Blanc massif closure directory.",
};

const REPO = "https://github.com/Deltaspace2/massif";
const CONTACT = "steven@innes.io";

/** Build a prefilled "new issue" link.
 *
 * There is no `.github/ISSUE_TEMPLATE/` in this repo, which is the only
 * reason plain `?title=&body=` survives: with a template directory present
 * GitHub shows the chooser instead and silently drops both parameters. If
 * templates are ever added, these links have to become `?template=<file>` or
 * they will quietly stop prefilling — and nothing will look broken.
 *
 * No `labels=`: a reporter without write access cannot apply them, and the
 * request is rejected or the label dropped depending on the path.
 */
function issueUrl(title: string, body: string): string {
  const q = new URLSearchParams({ title, body });
  return `${REPO}/issues/new?${q.toString()}`;
}

/** `mailto:` cannot use URLSearchParams. It percent-encodes a space as `+`,
 * which is correct for a query string and wrong here — mail clients put a
 * literal "+" in the subject line. encodeURIComponent gives %20. */
function mailtoUrl(subject: string, body: string): string {
  return (
    `mailto:${CONTACT}` +
    `?subject=${encodeURIComponent(subject)}` +
    `&body=${encodeURIComponent(body)}`
  );
}

/** The prefill is the form. There is no server to validate a report, so the
 * only leverage over report quality is asking the right questions before
 * someone starts typing — and a checklist in the box gets filled in far more
 * often than the same checklist sitting above it on the page. */
type Report = {
  id: string;
  heading: string;
  lede: string;
  /** Issue title, or mail subject when `channel` is "email". */
  title: string;
  body: string;
  cta: string;
  /** Defaults to a public GitHub issue. */
  channel?: "issue" | "email";
};

const REPORTS: Report[] = [
  {
    id: "wrong",
    heading: "A status here is wrong",
    lede:
      "The most useful thing you can send. A green dot on something that is " +
      "shut is the failure this site exists to avoid.",
    title: "Wrong status: ",
    body: [
      "Page (paste the URL): ",
      "What this site says: ",
      "What is actually the case: ",
      "Where you saw that (operator's page, a sign at the lift, the guardian): ",
      "When: ",
      "",
      "Anything else:",
    ].join("\n"),
    cta: "Report a wrong status",
  },
  {
    id: "missing",
    heading: "Something is missing",
    lede:
      "The massif is covered deliberately rather than exhaustively, and the " +
      "Italian side is thinner than the French. A name and a link is enough.",
    title: "Missing feature: ",
    body: [
      "What is missing (hut, lift, railway, route): ",
      "Where it is, roughly: ",
      "Who publishes its status (a URL, if you know one): ",
      "",
      "Anything else:",
    ].join("\n"),
    cta: "Report something missing",
  },
  {
    id: "attribution",
    heading: "Attribution, licence or takedown",
    lede:
      "If you run one of the sources this site quotes and something here " +
      "misrepresents you, breaches your licence, or should not be reproduced " +
      "at all, this goes to the front of the queue. Email is faster than an " +
      "issue and does not make the problem public first.",
    title: "massif — attribution / licence",
    body: [
      "Which source or page: ",
      "What the problem is: ",
      "Your relationship to the source: ",
    ].join("\n"),
    cta: "Email about attribution",
    // The only card that does not open a public issue. Telling a rights
    // holder that email is faster and more private, and then handing them a
    // button that files their complaint publicly, would be the opposite of
    // what the paragraph above it promises.
    channel: "email" as const,
  },
  {
    id: "suggestion",
    heading: "A suggestion",
    lede:
      "Something confusing, something missing from a page, a wording that " +
      "reads as advice when it should not.",
    title: "Suggestion: ",
    body: ["What you were trying to do: ", "What got in the way: "].join("\n"),
    cta: "Send a suggestion",
  },
];

export default function Feedback() {
  return (
    <main className="subpage">
      <a className="back" href="/">
        <span aria-hidden="true">←</span>All statuses
      </a>

      <h1>Report a problem</h1>
      <p className="meta">
        Corrections, missing features, and anything that reads as advice when it
        should not.
      </p>

      {/* First, above every "tell us" on the page. A closure directory's
          report channel will eventually receive "someone is stuck at the
          Goûter", and the only responsible thing this page can do about that
          is say — before it invites any kind of message — that nobody is
          reading it. Placing this under the report options would be worse
          than omitting it, because it would look like it had been considered
          and ranked below them. */}
      <aside className="report-alert" role="note">
        <b>This is not an emergency channel.</b>
        <p>
          Nothing here is monitored. Reports are read when there is time to read
          them, which may be days. If someone is in danger, call{" "}
          <b>112</b> — it works anywhere in France and Italy, from any phone,
          including one with no signal from your own network. In France,{" "}
          <b>114</b> takes SMS if you cannot make a voice call.
        </p>
      </aside>

      <p className="report-intro">
        massif is a directory of published notices, not a safety service. It
        reports what sources have said, and sources go stale, contradict each
        other and occasionally publish a reopening as a closure. If what you see
        here disagrees with what you saw on the mountain, trust the mountain —
        and then tell us, so the next person reads the right thing.
      </p>

      <div className="grid report-grid">
        {REPORTS.map((r) => (
          <section key={r.id} className="card report-opt">
            <h3>{r.heading}</h3>
            <p>{r.lede}</p>
            <p className="report-actions">
              {r.channel === "email" ? (
                <a className="btn-report" href={mailtoUrl(r.title, r.body)}>
                  {r.cta}
                </a>
              ) : (
                <a
                  className="btn-report"
                  href={issueUrl(r.title, r.body)}
                  target="_blank"
                  rel="noopener noreferrer"
                >
                  {r.cta} <span aria-hidden="true">↗</span>
                </a>
              )}
            </p>
          </section>
        ))}
      </div>

      <h2 className="report-h2">If you would rather not use GitHub</h2>
      <p className="report-intro">
        A GitHub issue is public, keeps its history and is the only channel with
        a record. But it needs an account, and plenty of people who know exactly
        which lift is shut do not have one. Email works just as well:
      </p>
      <p>
        <a className="btn-report" href={`mailto:${CONTACT}?subject=massif`}>
          {CONTACT}
        </a>
      </p>

      <h2 className="report-h2">What makes a report usable</h2>
      <ul className="report-list">
        <li>
          <b>The page you were on.</b> Pasting the URL removes all guessing
          about which of several similarly-named things you mean — there is
          more than one Mer de Glace.
        </li>
        <li>
          <b>What you saw, and where.</b> An operator&apos;s own page, a sign at
          the valley station, or the guardian on the phone all carry more weight
          than this site does, and knowing which one it was decides how it gets
          handled.
        </li>
        <li>
          <b>When.</b> Almost everything here is only true for a window. A
          report without a date cannot be told apart from one about last
          season, and gets treated as unknown rather than acted on.
        </li>
      </ul>

      <h2 className="report-h2">What this cannot do</h2>
      <p className="disclaimer">
        It cannot tell you whether to go — no correction here will ever amount
        to clearance, and a status that reads &ldquo;open&rdquo; is a report
        about a notice, not permission. It is not a rota: this is one person,
        answering when they can. And it is not a way to reach a hut guardian, a
        lift operator or the mairie — for anything that needs a person on the
        ground, look for their own details on the page for that feature,
        alongside the notice they published — though not every feature has
        them, and some carry no contact details at all.
      </p>
    </main>
  );
}
