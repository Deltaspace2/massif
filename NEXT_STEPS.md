# Next steps

## Immediate — verify the scaffold runs

Nothing here has been executed against a live database yet. Before writing any
more code:

```bash
docker compose up -d
cd backend
python3 -m venv .venv && source .venv/bin/activate
pip install -e ".[dev]"
python -m massif.scripts.migrate      # should print: applying 0001_init ... ok
pytest -q
```

Then generate and load features (needs network for Overpass):

```bash
python -m massif.scripts.fetch_osm_candidates > seeds/osm_candidates.yaml
python -m massif.scripts.seed_features
uvicorn massif.main:app --reload      # http://localhost:8000/health
```

Expect the OSM match rate to be partial — routes and couloirs have no OSM
equivalent, which is exactly why they are curated by hand.

## Then — first scraper end to end

Compagnie du Mont-Blanc lift status. Chosen deliberately as the opener:
structured, changes several times a day, and visible on the map the moment it
lands. Order of work:

1. Open the lift status page with devtools and find the JSON endpoint the
   frontend calls. Scrape the rendered HTML only if there genuinely isn't one.
2. Write `massif/ingest/sources/compagnie_du_mont_blanc.py` subclassing
   `Scraper`, implementing `collect()`.
3. Set `active: true` on the source in `seeds/sources.yaml` and re-seed.
4. Run it. Check `python -m massif.scripts.review_queue` — unmatched lift names
   go straight into `features_curated.yaml` as aliases.
5. Add `massif/scripts/run_ingest.py` to dispatch all due sources, then enable
   the cron in `.github/workflows/ingest.yml`.

## Then — the map

Next.js in `frontend/`, MapLibre GL JS, IGN Géoplateforme WMTS basemap
(free, key-less). Three surfaces:

- `/` — the massif map, features coloured by status
- `/feed` — what changed, reverse-chronological
- `/[type]/[slug]` — server-rendered per-feature page with full statement
  history and source links. This is the SEO surface and where the traffic
  actually arrives.

Every status shows "last confirmed N days ago". Stale is displayed, never
hidden.

## Deferred deliberately

Conditions aggregation (v2) and the hazard model (v3). Both are already
accommodated by the schema — `statement_type` carries `condition` and
`hazard_observation`, and `statements.payload` takes their structured data
without a migration. Don't start them until v1 has been live and maintained
through a full season.

## Open questions

- **Name.** `massif` is a placeholder in the package and docker-compose. Change
  it before you push anywhere public, or accept it forever.
- **Domain and contact URL.** `USER_AGENT` in `.env.example` must carry a real
  contact address before this touches anyone's server.
- **Arrêté discovery.** Both mairie sites need recon: are notices listed at a
  stable URL, or published to a portal? This determines whether that source is
  a morning's work or a week's.
