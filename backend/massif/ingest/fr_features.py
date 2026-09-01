"""Recognising Mont Blanc massif features in French prose.

Shared by every French source. Saint-Gervais and the OHM name the same routes,
and two divergent copies of these patterns is a bug waiting to happen — the
resolver bug that filed lift statuses against a glacier came from exactly this
kind of near-duplicate matching logic.

Matched against accent-stripped lowercase text. Order matters: specific before
general, because "voie normale du mont-blanc" also contains "voie normale".
"""

from __future__ import annotations

import re

from massif.ingest.fr_dates import strip_accents


def norm(text: str) -> str:
    return re.sub(r"\s+", " ", strip_accents(text).lower()).strip()


FEATURE_PATTERNS: list[tuple[re.Pattern, str]] = [
    # Mont Blanc normal routes
    (re.compile(r"voie normale du mont[- ]blanc"), "gouter-route"),
    (re.compile(r"(voie|arete|itineraire) du gouter"), "gouter-route"),
    (re.compile(r"aiguille du gouter"), "gouter-route"),
    (re.compile(r"voie royale"), "gouter-route"),
    (re.compile(r"voie normale"), "gouter-route"),
    (re.compile(r"(traversee des )?(trois|3) monts"), "trois-monts"),
    (re.compile(r"voie italienne|aiguilles grises|gonella"), "aiguilles-grises"),
    # named hazard sections and classics
    # "Grand Couloir" is not unique: the OHM writes about the "Grand Couloir
    # Ouest du Buet", a different mountain entirely, and an unqualified match
    # filed it against the Grand Couloir du Goûter — wrong-feature attribution
    # on the most safety-critical name in the database. Only the bare form,
    # or one explicitly tied to the Goûter, counts.
    (re.compile(r"grand couloir(?!\s+(?:ouest|est|nord|sud|central|du buet))"), "grand-couloir"),
    (re.compile(r"cosmiques"), "cosmiques-arete"),
    (re.compile(r"midi[- ]plan"), "arete-midi-plan"),
    (re.compile(r"vallee blanche"), "vallee-blanche"),
    (re.compile(r"dent du geant|dente del gigante"), "dent-du-geant"),
    (re.compile(r"arete du diable"), "arete-du-diable"),
    (re.compile(r"eperon frendo|frendo"), "frendo-spur"),
    # huts
    (re.compile(r"tete rousse"), "refuge-tete-rousse"),
    (re.compile(r"grands mulets"), "refuge-des-grands-mulets"),
    (re.compile(r"cosmiques.{0,12}refuge|refuge des cosmiques"), "refuge-des-cosmiques"),
    (re.compile(r"refuge du requin"), "refuge-du-requin"),
    (re.compile(r"refuge d'?argentiere"), "refuge-dargentiere"),
    (re.compile(r"albert 1er|albert premier"), "refuge-albert-1er"),
    (re.compile(r"rifugio torino|refuge torino"), "refuge-torino"),
    (re.compile(r"abri vallot|refuge vallot"), "abri-vallot"),
    # glaciers and access
    (re.compile(r"mer de glace"), "mer-de-glace"),
    (re.compile(r"glacier des bossons"), "glacier-des-bossons"),
    (re.compile(r"tramway du mont[- ]blanc|nid d'aigle"), "tramway-du-mont-blanc"),
    (re.compile(r"montenvers"), "montenvers-railway"),
]

# "Goûter" alone means either the refuge or the route. It is never matched
# bare: a wrong guess closes the wrong thing on the busiest route in the Alps.
# Context within this many characters decides, and both senses can apply.
GOUTER = re.compile(r"gouter")
GOUTER_WINDOW = 45
REFUGE_SENSE = re.compile(r"refuge|cabane|dortoir|nuit|reservation|gardien")
ROUTE_SENSE = re.compile(r"voie|arete|itineraire|acces|couloir|ascension|course")


# Peaks outside the Mont Blanc massif that share vocabulary with it. A
# sentence about one of these is not about our features.
ELSEWHERE = re.compile(r"\bbuet\b|aiguilles rouges|belledonne|vanoise|ecrins")


def features_mentioned(text: str) -> list[str]:
    """Every feature this text names. Order-stable, deduped, never guessed."""
    flat = norm(text)
    if ELSEWHERE.search(flat):
        return []
    found: list[str] = []

    for pattern, slug in FEATURE_PATTERNS:
        if pattern.search(flat) and slug not in found:
            found.append(slug)

    for match in GOUTER.finditer(flat):
        start = max(0, match.start() - GOUTER_WINDOW)
        window = flat[start : match.end() + GOUTER_WINDOW]
        if REFUGE_SENSE.search(window) and "refuge-du-gouter" not in found:
            found.append("refuge-du-gouter")
        if ROUTE_SENSE.search(window) and "gouter-route" not in found:
            found.append("gouter-route")

    return found
