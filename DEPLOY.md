# Deploying massif

Three hosts, one repo, €0/month:

```
Vercel project "massif"     ← frontend/   Next.js, server-rendered
Vercel project "massif-api" ← backend/    FastAPI as a serverless function
Supabase                                  Postgres 17 + PostGIS
GitHub Actions                            ingest, hourly cron
```

The hosting is free; the domain is not, and it is the only recurring bill.

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
| Vercel function | `aws-N-<region>.pooler.supabase.com` | **6543** | transaction | Serverless. Many short-lived, frequently frozen clients. |
| Actions: `migrate`, `run_ingest` | `aws-N-<region>.pooler.supabase.com` | **5432** | session | Wants one stable session; multi-statement migrations in a transaction. |
| Anything on Actions | `db.<ref>.supabase.co` | — | direct | **Never.** Actions runners are IPv4-only; this host is IPv6-only. It will hang, not refuse. |

**The pooler hostname is not stable.** It was `aws-0-eu-west-3` when this was
written and a project created 6 Sep 2026 got `aws-1-eu-west-3`. Read it off the
Connect dialog rather than typing it from here; the shard number is not
something to guess at.

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

Both sides must agree. Measured 6 Sep 2026: `133 | 99 | 133 | 860 | 12`.
The last column is the one people forget, and it is the one that matters —
see below. The figures move every session; compare the two databases rather
than trusting a number written here.

### schema_migrations must arrive with everything else

Every ingest run starts with `python -m massif.scripts.migrate`. If the
schema restored but the nine `schema_migrations` rows did not, the next ingest
re-applies every migration against a database that already has them — which is
hard-won rule 11, the bug that has already shipped twice here. It will not
warn you. If the two databases disagree on that count, fix it before going
further:

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

**API, optional** — `ADMIN_TOKEN` mounts the review page at `/admin/review`.

Set it ONLY on the API project. The frontend exists to be crawled and must
carry no login. With the variable unset the admin routes are not registered at
all — absent rather than open, so a missing secret cannot become a public write
endpoint.

HTTP Basic, any username, the token as the password. Accept and reject are
POST-only and check `Origin`, so nothing that follows a link — a crawler, a
link preview, a browser prefetch — can clear the queue.

**Frontend** — root directory `frontend/`.

- Env var `MASSIF_API` = the API project's production URL, no trailing slash.
  That is `https://api.montblancmassif.org` — see the domain section below.

Deploy the API first; the frontend build wants it.

### The domain

`montblancmassif.org`, registered at Namecheap on 7 Sep 2026. It is attached
to both projects and both are live on it:

| Project | Host |
|---|---|
| Frontend | `montblancmassif.org` (apex) |
| API | `api.montblancmassif.org` |

The frontend needs no env var to know this: `frontend/lib/site.ts` defaults
`SITE_URL` to the apex, and `metadataBase`, `sitemap.ts` and `robots.ts` all
read it from there. `NEXT_PUBLIC_SITE_URL` overrides it and exists so a
preview deploy can point at itself; leave it unset in production, and unset on
previews too unless you have a reason — a preview that falls back to the
production origin emits canonicals naming production, which is the right
answer for a duplicate.

**Bot Protection is on the frontend project and not the API one**, set to
Challenge, which passes verified crawlers — so Googlebot is fine and the SEO
channel is intact. It does not pass curl. Every scripted request to
`montblancmassif.org` answers **429** with `x-vercel-mitigated: challenge`,
which is indistinguishable from an outage if you do not know it is there, and
was read as one for half an hour the day it appeared. **Verify the frontend in
a browser.** curl is still the tool for `api.montblancmassif.org`.

Two records at the apex fail silently rather than loudly, so any DNS move —
the registrar transfer in the task queue, or Cloudflare Email Routing — is not
done when the site loads:

- the **Google Search Console TXT**, verified 10 Sep 2026. Google re-checks
  it; lose it and the property un-verifies and the ranking data stops, with
  nothing anywhere saying why.
- the **`contact@` MX records**, once that mailbox exists. A bounce there is
  the address a sysadmin uses when they want us to stop fetching.

Which nameservers the zone is on today is **not recorded and worth checking
before assuming** — Namecheap BasicDNS is where it started, and the Vercel
wiring may have moved it.

### The dependency list is maintained by hand

`backend/requirements.txt` is the read API's subset — `pyproject.toml` remains
the source of truth for local dev, CI and ingest. It omits `httpx`,
`rapidfuzz`, `pyyaml` and `anthropic`.

**`httpx` is the one that carries the promise.** Without an HTTP client it is
structurally impossible to fetch someone's website from a page request. The
others are left out for bundle size, which is a judgement rather than a
guarantee, and lumping all of them into one sentence — as this section used to
— made adding a parser look like the same retreat as adding a fetcher.
`selectolax` IS included: the review panel parses the stored page it shows a
reviewer, and it reaches it through `massif/ingest/prose.py`, which imports
selectolax and the standard library and nothing else.

The cost is that **an import added to `massif.main` that is not listed there
dies at cold start with `ModuleNotFoundError`** — a green deploy that 500s on
every request. This had already happened by 7 Sep 2026 and nobody noticed:
`admin.py` grew an import of `massif.ingest.llm`, which reaches
`massif.ingest.base`, which imports httpx. Vercel installs more than this file
asks for, so the function booted anyway and the guarantee was fiction rather
than a build error.

`tests/test_cold_start.py` enforces it in the suite now, by blocking the
package with an import hook and starting the app. The manual check below still
works and is a better mirror of Vercel, but it went three weeks without being
run, which is the argument for having both.

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
gh variable set USER_AGENT --body 'massif/0.1 (+https://montblancmassif.org/about; steven@innes.io)'
```

The workflow hard-fails without it, by design: this project does not touch
anyone's server without identifying itself and giving them a way to complain.
Set the same string on the Vercel API project.

The URL half was the repo for as long as the site had no `/about` to point
at: a contact address has to resolve to a real page *before* the first request
goes out, and advertising one that 404s is the one thing a sysadmin reading
their logs cannot forgive. `/about` is up on the domain now, so the URL points
at the site.

The email half is **mid-change**. `steven@innes.io` above is the string
`frontend/app/about/page.tsx` publishes verbatim, which is what a sysadmin
grepping their logs will try to match, so it is what the variable should say
today — but it is a personal address, and so is the `steven.innes8@gmail.com`
this line carried before. `contact@montblancmassif.org` is the decided
destination; the mailbox has to exist first, and the task queue has the order.

**Nothing enforces the match between the page and the variable**, in either
direction, and the deployed value is the one in the logs of every server we
have ever fetched. `gh variable list` settles what is actually being sent —
check it before changing anything, and change the page and the variable
together.

The `example.org` placeholder that ships in `.env.example` is not a
placeholder in the harmless sense: it is a fake contact on every request. The
local `.env` carries a real one for the same reason.

## 6. Verify, in this order

```bash
curl -s https://api.montblancmassif.org/health
```

This is a real smoke test, not a liveness ping — `/health` runs two queries,
so a wrong `DATABASE_URL` gives a 500 here rather than a cheerful 200. Expect
`features: 75` and a non-null `last_successful_ingest`.

```bash
curl -s https://api.montblancmassif.org/features | head -c 400
```

Then the ingest, by hand, before trusting the cron. `workflow_dispatch`
bypasses `INGEST_ENABLED` precisely so it can be tested first:

```bash
gh workflow run ingest && sleep 20 && gh run list --workflow=ingest --limit 1
```

A failure at the "Check the configuration" step means a missing secret, not a
regression — that is the step doing its job. Finally, load
`https://montblancmassif.org` **in a browser** — Bot Protection 429s
everything else — and confirm the map has pins on it: 40 features have
geometry, and an empty map is the signature of a re-seed rather than a
restore.

## What is deliberately not here

- **No CDN in front of Vercel.** Should the DNS ever sit at Cloudflare, every
  record pointing at Vercel stays grey-cloud ("DNS only"). Proxying a second
  CDN on top of Vercel's buys nothing here and causes caching oddities and
  certificate-issuance trouble.
- **No migrations from Vercel.** `migrate.py` finds `db/migrations` via
  `parents[3]` and the function bundle is `backend/` only. Migrations belong
  to Actions, which checks out the whole repo. Do not "fix" this.
- **No `MASSIF_API` in CI.** The frontend build is supposed to survive an
  unreachable backend — that is what exercises the shipped failure copy.
