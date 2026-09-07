"""Hand-sourced hut altitudes, and the rules that decide which ones may be written.

WHY THIS EXISTS. `features.alt_max` is not decoration: it is the physical half
of every two-screen match in this codebase — `hut_facts`, the camptocamp
importer, `tmb_refuges` — and a hut without one is matched on its name alone,
which rule 8 in CLAUDE.md exists because we already got wrong. Nine active huts
had no altitude anywhere: not in `features`, not in `feature_facts`, and not in
OSM, which carries no `ele` for any of the nine. There is nothing left in the
database to fill them from, so the number has to come from outside, by hand.

By hand is the dangerous part, so the file is gated rather than trusted:

* **Two independent sources, or nothing.** One published figure is a claim; two
  that agree is a measurement. Two hosts, not two pages — a directory and the
  four sites that republish it are one source in four coats.
* **The written value must BE one of the published values.** No averaging, no
  rounding to a nicer number. An altitude nobody published is one nobody can
  check.
* **The sources we ingest cannot vouch for themselves.** `tmb-refuges` refuses
  a hut whose altitude we do not hold; taking the altitude from that same
  portal and then letting it clear the portal's own screen is a circle with a
  number in it. Those hosts are refused outright here.
* **A wide disagreement holds the row instead of picking a winner.** Beyond the
  tolerance the matching screens use, two figures are not one hut measured
  twice, and choosing between them is the invention this module is here to
  prevent.

A row that fails an evidence rule is HELD, not dropped — it stays in the file
with its one source and prints on every run, so the gap keeps asking to be
filled. A row that breaks a *rule* raises, because that is a mistake in the
file rather than a shortage of evidence.

Pure. The writing lives in `scripts/import_hut_altitudes.py`.
"""

from __future__ import annotations

from dataclasses import dataclass
from urllib.parse import urlparse

from massif.ingest.hut_facts import ALTITUDE_TOLERANCE_M

# Two sources are "the same figure" within this. Surveys of the same building
# differ by a metre or two; they do not differ by fifty.
AGREEMENT_M = 10

# Below this many agreeing hosts, the row is held.
MIN_AGREEING_HOSTS = 2

# Hosts whose altitude cannot validate a match we make against that same host.
# Both are the Tour du Mont-Blanc portal that `tmb_refuges` reads: `refuge-du
# -fioux`, `refuge-le-peuty` and `rifugio-bertone` were each refused by its
# name/altitude screen for want of an altitude on our side, so a figure taken
# from there would be marking its own homework.
CIRCULAR_HOSTS = {
    "montourdumontblanc.com": "the TMB portal tmb-refuges reads",
    "autourdumontblanc.com": "the TMB portal tmb-refuges reads",
    "monrefugepaysdumontblanc.com": "the same TMB portal under a third domain",
}


@dataclass(frozen=True)
class Reading:
    """One published altitude, and where it was read."""

    url: str
    value: int
    retrieved: str

    @property
    def host(self) -> str:
        host = urlparse(self.url).hostname or ""
        host = host.removeprefix("www.")
        # en.refugedumontenvers.com and refugedumontenvers.com are one source.
        # Two labels is not a registrable-domain parser and does not pretend to
        # be one; it is enough to stop a language subdomain counting twice.
        return ".".join(host.split(".")[-2:])


@dataclass(frozen=True)
class Row:
    slug: str
    alt_max: int | None
    readings: tuple[Reading, ...]
    held: str | None
    note: str | None


def read_row(raw: dict) -> Row:
    """One YAML mapping to a Row. Raises on anything structurally wrong."""
    slug = raw.get("slug")
    if not slug:
        raise ValueError(f"row has no slug: {raw!r}")
    readings = tuple(
        Reading(url=source["url"], value=int(source["value"]), retrieved=str(source["retrieved"]))
        for source in raw.get("sources") or []
    )
    if not readings:
        raise ValueError(f"{slug}: no sources — an altitude with no provenance is a rumour")
    for reading in readings:
        if reading.host in CIRCULAR_HOSTS:
            raise ValueError(
                f"{slug}: {reading.host} is {CIRCULAR_HOSTS[reading.host]}, so its "
                "altitude cannot be what clears its own match"
            )
    alt_max = raw.get("alt_max")
    return Row(
        slug=slug,
        alt_max=None if alt_max is None else int(alt_max),
        readings=readings,
        held=raw.get("held"),
        note=raw.get("note"),
    )


def hold_reason(row: Row) -> str | None:
    """Why this row may not be written, or None if it may.

    Reads the evidence rather than the author's summary of it: `held:` explains
    a shortfall to a human, and is required where one exists, but it is the
    readings that decide.
    """
    if row.alt_max is None:
        return row.held or "no altitude chosen"

    if all(reading.value != row.alt_max for reading in row.readings):
        raise ValueError(
            f"{row.slug}: {row.alt_max} m is not a figure any source published "
            f"({sorted({r.value for r in row.readings})}) — we do not average altitudes"
        )

    agreeing = {r.host for r in row.readings if abs(r.value - row.alt_max) <= AGREEMENT_M}
    if len(agreeing) < MIN_AGREEING_HOSTS:
        return (
            f"only {len(agreeing)} host publishes {row.alt_max} m "
            f"({', '.join(sorted(agreeing))}) — one source is not a measurement"
        )

    widest = max(abs(r.value - row.alt_max) for r in row.readings)
    if widest > ALTITUDE_TOLERANCE_M:
        far = [
            f"{r.value} m ({r.host})"
            for r in row.readings
            if abs(r.value - row.alt_max) > ALTITUDE_TOLERANCE_M
        ]
        return (
            f"a published figure is {widest} m from {row.alt_max} m — further than the "
            f"{ALTITUDE_TOLERANCE_M} m the matching screens allow, so this may be two "
            f"buildings: {', '.join(far)}"
        )
    return None


def provenance(row: Row) -> str:
    """The reader-facing sentence for a hut whose altitude came from here.

    The huts this fills were created by `import_osm_huts`, whose note tells the
    reader that position AND altitude come from OpenStreetMap. Once an altitude
    arrives from somewhere else that note is false on a public page, so the
    writer appends this rather than leaving the old sentence to speak for a
    number it did not supply.

    Only the hosts that published THIS figure are named. The first draft named
    every host in the row, which put "1877 m as published by ... refuges.info"
    on the Flégère page when refuges.info is the one source saying 1807 —
    crediting a number to somebody who did not print it, on the page, in the
    sentence written to be honest about where the number came from.
    """
    hosts = sorted(
        {r.host for r in row.readings if abs(r.value - (row.alt_max or 0)) <= AGREEMENT_M}
    )
    return f"Altitude {row.alt_max} m as published by {' and '.join(hosts)}."
