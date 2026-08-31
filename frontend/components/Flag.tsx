/** Which side of the massif a thing is on.
 *
 *  A regional-indicator pair, not an image: it inherits font size and colour,
 *  costs no request, and on a platform that will not draw flags (Windows will
 *  not) it degrades to the letters "FR" — which is the country code, so the
 *  failure mode is still the right answer.
 *
 *  role="img" + aria-label because the emoji alone is announced inconsistently
 *  and sometimes not at all. An unknown code renders as itself rather than
 *  vanishing: a country we have not mapped is not a country we do not know.
 *
 *  Lives here rather than in a route file so both the front page and the
 *  feature pages can use it without importing one route into another.
 */
const COUNTRIES: Record<string, { flag: string; name: string }> = {
  FR: { flag: "🇫🇷", name: "France" },
  IT: { flag: "🇮🇹", name: "Italy" },
  CH: { flag: "🇨🇭", name: "Switzerland" },
};

export default function Flag({ code }: { code: string | null }) {
  if (!code) return null;
  const country = COUNTRIES[code.toUpperCase()];
  if (!country) return <span className="flag flag--code">{code}</span>;
  return (
    <span className="flag" role="img" aria-label={country.name}>
      {country.flag}
    </span>
  );
}
