export default function NotFound() {
  return (
    <main className="subpage">
      <h1>Not tracked</h1>
      <p className="meta">
        No feature by that name. It may not be seeded yet — the massif is
        covered deliberately rather than exhaustively.{" "}
        {/* Someone who reached a 404 looking for a real hut is the best
            possible source for "this is missing", and they are never closer to
            saying so than right now. */}
        <a href="/feedback">Tell us what you were looking for.</a>
      </p>
      <p>
        <a className="back" href="/">
          <span aria-hidden="true">←</span>All statuses
        </a>
      </p>
    </main>
  );
}
