export default function NotFound() {
  return (
    <main className="subpage">
      <h1>Not tracked</h1>
      <p className="meta">
        No feature by that name. It may not be seeded yet — the massif is
        covered deliberately rather than exhaustively.
      </p>
      <p>
        <a className="back" href="/">
          <span aria-hidden="true">←</span>All statuses
        </a>
      </p>
    </main>
  );
}
