# Deploying massif

Three hosts, one repo, €0/month:

```
Vercel project "massif"     ← frontend/   Next.js, server-rendered
Vercel project "massif-api" ← backend/    FastAPI as a serverless function
Supabase                                  Postgres 15 + PostGIS
GitHub Actions                            ingest, hourly cron
```

The frontend server-renders every page against `MASSIF_API`, so the read API
has to be reachable from Vercel's build and runtime — that is why there is a
second project rather than a `render.com` free instance, whose ~50s cold start
would land on exactly the SEO pages this site exists for.

Nothing here is automated on purpose. It is done once, and a script that runs
once is a script nobody has ever debugged.

## The port table

Supabase gives you three connection strings and they are not
interchangeable. Getting this wrong produces slowness or IPv6 timeouts, not
error messages.

| Use | Host | Port | Mode | Why |
|---|---|---|---|---|
| Vercel function | `aws-0-<region>.pooler.supabase.com` | **6543** | transaction | Serverless. Many short-lived, frequently frozen clients. |
| Actions: `migrate`, `run_ingest` | `aws-0-<region>.pooler.supabase.com` | **5432** | session | Wants one stable session; multi-statement migrations in a transaction. |
| Anything on Actions | `db.<ref>.supabase.co` | — | direct | **Never.** Actions runners are IPv4-only; this host is IPv6-only. It will hang, not refuse. |

Append `?sslmode=require` to both. psycopg defaults to `prefer`, which will
silently fall back to plaintext across the public internet rather than fail.

Do **not** paste `&pgbouncer=true` onto the session-mode (`:5432`) URL. It is a
Prisma idiom, and here it flips `Settings.pooled` to true and hands the ingest
job `NullPool` — a new TCP connection per checkout. Slow, not broken, and
invisible.

## 1. Supabase

New project, region `eu-west-3` (Paris — the sources are all French/Italian).
Save the database password; it appears once.

Then SQL Editor:

```sql
create extension if not exists postgis;
create extension if not exists pg_trgm;
```

`pg_trgm` is not optional — `FeatureResolver` fuzzy-matches against it, and
without it ingest resolves nothing and quietly fills `unresolved_mentions`.

### Check *which schema* postgis landed in, before restoring anything

This is the cheap gate in front of the expensive failure below.

```sql
select extname, extnamespace::regnamespace as schema from pg_extension where extname in ('postgis','pg_trgm');
```

The laptop has both in `public`. Supabase has historically installed postgis
into an `extensions` schema instead, and which one a new project gives you is
not worth guessing from here — read it.

- **Both say `public`** → nothing to do, go to §2.
- **postgis says `extensions`** → the dump will not restore. Fix it now, in a
  project with no data in it yet:

  ```sql
  drop extension postgis cascade;
  create extension postgis with schema public;
  ```

  `cascade` is safe *only* because the project is empty; it drops every
  dependent object. Never run it on a database that has `features` in it.

## 2. Load the data

**Dump the laptop; do not re-seed.** Two reasons, both of which produce a
working-looking deployment that is wrong:

- `backend/seeds/osm_candidates.yaml` is gitignored, so `seed_features` in
  Actions creates 75 features with **no geometry** and an empty map.
- `documents` is immutable by design and extraction re-runs *from* it.
  Re-seeding throws away the history that makes `reextract` mean anything.

```bash
pg_dump "postgresql://massif:massif@localhost:5432/massif" --no-owner --no-privileges --exclude-table=spatial_ref_sys -Fc -f /tmp/massif.dump
```

Note the scheme. `pg_dump` and `psql` speak `postgresql://`; the
`postgresql+psycopg://` form in `.env` and in the Actions secret is
SQLAlchemy's, and libpq rejects it. The two differ by more than taste and the
error is not obvious.

`spatial_ref_sys` is PostGIS's own table and is already populated on Supabase;
restoring over it fails on permissions, which is correct and unhelpful.

```bash
pg_restore --no-owner --no-privileges -d "postgresql://postgres.<ref>:<password>@aws-0-eu-west-3.pooler.supabase.com:5432/postgres?sslmode=require" /tmp/massif.dump
```

No `--disable-triggers`: it only applies to `--data-only` restores and it
wants superuser, which the Supabase `postgres` role is not. A full-schema
restore loads the data before it adds the constraints anyway.

Expect errors about `postgis` and `pg_trgm` already existing. That is fine —
those two lines are `IF NOT EXISTS` and become no-ops.

**That no-op is also the trap.** The dump was taken from a database with
postgis in `public`, so it declares the column as
`geom public.geometry(Geometry,4326)` and then empties `search_path`. If
postgis is in `extensions` on the target, `CREATE EXTENSION IF NOT EXISTS
postgis WITH SCHEMA public` does *not* move it — it does nothing, succeeds,
and then `features` fails to create with `type "public.geometry" does not
exist`. §1 is what prevents this.

**Do not read the exit code as the result** — verify by counting rows:

```bash
psql "postgresql://postgres.<ref>:<password>@aws-0-eu-west-3.pooler.supabase.com:5432/postgres?sslmode=require" -c "select (select count(*) from features) features, (select count(*) from features where geom is not null) with_geom, (select count(*) from documents) documents, (select count(*) from statements) statements, (select count(*) from schema_migrations) migrations;"
```

The laptop, at the time of writing, says `75 | 40 | 26 | 301 | 9`. The last
column is the one people forget.

### schema_migrations must arrive with everything else

Every ingest run starts with `python -m massif.scripts.migrate`. If the
schema restored but the nine `schema_migrations` rows did not, the next ingest
re-applies `0001`–`0009` against a database that already has them — which is
hard-won rule 11, the bug that has already shipped twice here. It will not
warn you. If `migrations` is not 9 above, fix it before going further:

```bash
psql "$SUPABASE_SESSION_URL" -c "select version from schema_migrations order by 1;"
```

## 3. The two Vercel projects

Both import the same GitHub repo. The only meaningful setting is the root
directory.

**API** — root directory `backend/`.

- Vercel detects `api/index.py` and `vercel.json` and needs no framework preset.
- Env var, all environments: `DATABASE_URL` = the **`:6543` transaction** URL.
- Env var: `USER_AGENT` — see §5.

A missing `DATABASE_URL` here **deploys green and serves errors**: `Settings`
and `create_engine` both run at import, and `database_url` has a
`localhost:5433` default, so the function boots perfectly and every request
fails against a database that isn't there. Set it before the first deploy.

`vercel.json` pins `maxDuration: 15`. If the account's plan won't allow it the
*deploy* fails loudly — cheap to find out, so don't pre-emptively lower it.

**Frontend** — root directory `frontend/`.

- Env var `MASSIF_API` = the API project's production URL, no trailing slash.

Deploy the API first; the frontend build wants it.

### The dependency list is maintained by hand

`backend/requirements.txt` is the read API's subset — `pyproject.toml` remains
the source of truth for local dev, CI and ingest. It deliberately omits
`httpx`, `selectolax`, `rapidfuzz`, `pyyaml` and `anthropic`, which makes it
structurally impossible to fetch someone's website from a page request.

The cost is that **an import added to `massif.main` that is not listed there
dies at cold start with `ModuleNotFoundError`**. `massif/ingest/__init__.py` is
empty, which is the only reason `main.py`'s `massif.ingest.fr_dates` import
does not drag the scrapers in. Keep it empty.

To re-check the subset after touching imports:

```bash
cd backend && python3.12 -m venv /tmp/coldstart && /tmp/coldstart/bin/pip install -q -r requirements.txt && /tmp/coldstart/bin/python -c "import sys; sys.path.insert(0,'.'); import api.index as m; print('ok', len(m.app.routes))"
```

## 4. Ingest on GitHub Actions

`.github/workflows/ingest.yml` is already correct and needs no commit to turn
on — the switch is a repository variable so that the reason it was off stays
written down.

```bash
gh secret set DATABASE_URL --body 'postgresql+psycopg://postgres.<ref>:<password>@aws-0-eu-west-3.pooler.supabase.com:5432/postgres?sslmode=require'
```

Note `postgresql+psycopg://` — SQLAlchemy needs the driver in the scheme, and
this is the **session-mode `:5432`** URL, not the one Vercel gets.

```bash
gh variable set INGEST_ENABLED --body 'true'
```

`gh auth status` reported the token invalid as of the last session; run
`gh auth login` first, or set all three in Settings → Secrets and variables →
Actions.

## 5. USER_AGENT

```bash
gh variable set USER_AGENT --body 'massif/0.1 (+https://<project>.vercel.app/about; steven.innes8@gmail.com)'
```

The workflow hard-fails without it, by design: this project does not touch
anyone's server without identifying itself and giving them a way to complain.
Set the same string on the Vercel API project. The URL has to resolve to a
real page before the first ingest run — it is the contact address, not a
label.

## 6. Verify, in this order

```bash
curl -s https://<api-project>.vercel.app/health
```

This is a real smoke test, not a liveness ping — `/health` runs two queries,
so a wrong `DATABASE_URL` gives a 500 here rather than a cheerful 200. Expect
`features: 75` and a non-null `last_successful_ingest`.

```bash
curl -s https://<api-project>.vercel.app/features | head -c 400
```

Then the ingest, by hand, before trusting the cron. `workflow_dispatch`
bypasses `INGEST_ENABLED` precisely so it can be tested first:

```bash
gh workflow run ingest && sleep 20 && gh run list --workflow=ingest --limit 1
```

A failure at the "Check the configuration" step means a missing secret, not a
regression — that is the step doing its job. Finally, load the frontend and
confirm the map has pins on it: 40 features have geometry, and an empty map is
the signature of a re-seed rather than a restore.

## What is deliberately not here

- **No custom domain.** Ships on `*.vercel.app`. That URL goes in
  `USER_AGENT`, which makes it semi-permanent — moving it later means the
  contact address in every request log we've ever sent is dead.
- **No migrations from Vercel.** `migrate.py` finds `db/migrations` via
  `parents[3]` and the function bundle is `backend/` only. Migrations belong
  to Actions, which checks out the whole repo. Do not "fix" this.
- **No `MASSIF_API` in CI.** The frontend build is supposed to survive an
  unreachable backend — that is what exercises the shipped failure copy.
