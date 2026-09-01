/** The map key, shared by the overview pane and the full-screen map so the two
 *  cannot drift apart — and so a correction lands in both.
 *
 *  It used to read: green ● open, amber ▲ restricted, red ■ closed, grey ○
 *  unknown. Three things were wrong with that, and the first was serious.
 *
 *  A hut is drawn as a GREEN HOUSE whatever its status — that is IGN's own
 *  refuge symbol, redrawn so ours sits exactly on theirs. The key said green
 *  means open, so it taught the reader that every one of those houses was
 *  open. Sixty-three of the seventy-four are unknown. A key that turns
 *  "nobody has said anything" into a green light is the exact failure this
 *  site exists to avoid, and it was doing it in the one place a reader looks
 *  to find out what the colours mean.
 *
 *  Second, the shapes were invented: the map draws circles for everything, and
 *  never a triangle or a square. Third, the status pip on a hut's corner — the
 *  thing that actually carries status — was not in the key at all.
 */
export default function MapKey({ className }: { className?: string }) {
  return (
    <div className={className}>
      <span>
        <i className="mapkey__house" aria-hidden="true">
          <svg viewBox="0 0 16 16" width="13" height="13">
            <path
              d="M8 1.7 14.6 7.3V14.4H1.4V7.3Z"
              fill="#246138"
              stroke="#ffffff"
              strokeWidth="1.1"
              strokeLinejoin="round"
            />
          </svg>
        </i>
        a hut
      </span>
      <span>
        <i style={{ color: "var(--open)" }}>●</i>open
      </span>
      <span>
        {/* Hollow, in the OPEN colour: the door is unlocked and nobody is
            running the hut. A second hue here would read as a caution, and
            this is not one. */}
        <i style={{ color: "var(--open)" }}>◍</i>open · unstaffed
      </span>
      <span>
        <i style={{ color: "var(--restricted-glass)" }}>●</i>restricted
      </span>
      <span>
        <i style={{ color: "var(--closed)" }}>●</i>closed
      </span>
      <span>
        <i style={{ color: "var(--unknown)" }}>○</i>nothing published
      </span>
      <span className="mapkey__note">
        The house means hut, not open — a hut&rsquo;s status is the dot on its
        corner, and most have none.
      </span>
    </div>
  );
}
