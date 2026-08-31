# massif

Live closure and status map for the Mont Blanc massif.

Answers one question well: **what is currently shut, restricted, or officially
flagged as dangerous?** Commune arrêtés, lift and mountain-train status, hut
closures, glacier route closures after rockfall.

This is a directory of published notices. It is **not** a safety service. It
reports what sources have said; it does not tell anyone whether to go.

`CLAUDE.md` is the working spec: architecture, conventions, and the hard-won
rules that each cost a bug. `DEPLOY.md` covers hosting.

## Status

v1, in development. The pipeline runs end to end: four sources ingest, the API
serves, and the frontend renders the map, the feed and a page per feature. Not
deployed yet — `DEPLOY.md` is the runbook, and the ingest cron stays gated
behind `INGEST_ENABLED` until there is a database to write to.

## Stack

| Layer | Choice |
|---|---|
| Ingest + API | Python 3.12, FastAPI |
| Database | Postgres 16 + PostGIS |
| Frontend | Next.js (server-rendered) + MapLibre GL JS |
| Basemap | IGN Géoplateforme WMTS (free, key-less) |
| Scheduling | GitHub Actions cron |
| Hosting | Two Vercel projects, frontend and read API — see `DEPLOY.md` |

## Local setup

Requires Python 3.12+ and Postgres 14+ with PostGIS.

```bash
cp .env.example .env

# Postgres + PostGIS, either way:
docker compose up -d              # Docker, port 5433
./scripts/setup_db_native.sh      # or apt, port 5432 — edit .env to match

# install backend
cd backend
python3 -m venv .venv && source .venv/bin/activate
pip install -e ".[dev]"

# apply schema
python -m massif.scripts.migrate

# generate OSM feature candidates for the massif (needs network)
python -m massif.scripts.fetch_osm_candidates > seeds/osm_candidates.yaml

# load curated + candidate features
python -m massif.scripts.seed_features

# run the API
uvicorn massif.main:app --reload
```

The frontend server-renders against that API, so start the API first:

```bash
cd frontend
npm install
npm run dev                       # :3000, expects the API on :8000
```

## Architecture

Four ingest stages, each independently re-runnable. Never fuse them:

```
fetch → store document → extract statements → resolve to feature → recompute status
```

`documents` is immutable and never deleted. Extraction runs *from* stored
documents, so improving a parser means re-running it over history rather than
re-hammering someone's website.

## Data model

- `features` — the physical things (routes, huts, lifts, glaciers, couloirs)
- `sources` — who publishes (mairie, lift operator, OHM, Montagna Sicura)
- `documents` — raw fetched artifacts, immutable, hash-deduped
- `statements` — the normalised unit; closures *and* (later) conditions
- `feature_status` — materialised current state, what the map reads
- `feature_facts` — properties of a thing, not claims about it: hut capacity,
  whether there is water. Never enters the status pipeline
- `ingest_runs` — one row per source per run, so a source going quiet is visible
- `unresolved_mentions` — review queue for names that didn't match a feature

## Scraping conduct

Honour `robots.txt`. Identify with a real User-Agent and contact URL.
Rate-limit hard, back off on errors. Attribute every displayed statement and
link to the original. You are a guest on these servers.
