"""A shared key must never be silently owned by whichever feature loaded first.

Found 10 Sep 2026, in production: the model read "Ouvert du 23 mai 2026 au 1er
novembre 2026" off the Refuge du Plan de l'Aiguille's own page and the
statement was filed on the Refuge de Plan Glacier — at score 100, the EXACT
path, immune to the fuzzy floor and the review candidates. `normalise` strips
"aiguille" and "glacier" as generic terrain nouns, both huts collapse to the
key "plan", and the index was first-writer-wins: one hut owned the key, the
other became unreachable, and nothing said so.

Measured across the live inventory, ELEVEN keys were shared by more than one
feature — gouter (the route vs the refuge) and bossons (a glacier vs a
chairlift) among them. Every one was this bug waiting for a sentence.

The fix is tiers, each refusing to answer on a shared key:

    exact  fold accents/case/punctuation, strip nothing.
           "refuge du gouter" is only the refuge.
    tight  strip building-type words and articles, KEEP terrain nouns.
           "plan aiguille" vs "plan glacier" stay apart.
    loose  the old `normalise`, for fuzzy's benefit.

Ambiguity at every tier goes to a person, because no string score can say
which building a sentence means.
"""

from __future__ import annotations

import uuid

from massif.ingest.resolve import FeatureResolver, normalise_exact, normalise_tight


class _Feature:
    def __init__(self, name, aliases=(), names=None):
        self.id = uuid.uuid4()
        self.name_default = name
        self.aliases = list(aliases)
        self.names = names or {}


class _Rows(list):
    def all(self):
        return list(self)


class _Session:
    def __init__(self, features):
        self.features = features

    def scalars(self, _query):
        return _Rows(self.features)


# The live collision cases, as fixtures.
PLAN_GLACIER = _Feature("Refuge de Plan Glacier")
PLAN_AIGUILLE = _Feature("Refuge du Plan de l'Aiguille", ["Plan de l'Aiguille"])
REFUGE_GOUTER = _Feature("Refuge du Goûter")
GOUTER_ROUTE = _Feature("Goûter Route", ["Goûter", "Voie du Goûter"])
REFUGE_MONTENVERS = _Feature("Refuge du Montenvers")
RAILWAY = _Feature("Chemin de fer du Montenvers", ["Montenvers"])
HOUCHES = _Feature("Les Houches", ["Bellevue"])
NID_ROAD = _Feature("Route du Nid d'Aigle", ["Bellevue"])


def _resolver(*features):
    return FeatureResolver(_Session(features))


def _got(resolver, mention):
    match, _ = resolver.resolve(mention)
    return match


# ---------------------------------------------------- the production bug


def test_the_plan_de_laiguille_sentence_files_on_the_right_hut():
    r = _resolver(PLAN_GLACIER, PLAN_AIGUILLE)
    assert _got(r, "Refuge du Plan de l'Aiguille").feature_id == str(PLAN_AIGUILLE.id)
    assert _got(r, "Refuge de Plan Glacier").feature_id == str(PLAN_GLACIER.id)


def test_load_order_changes_nothing():
    """First-writer-wins is exactly the bug; whoever loads first must not
    matter."""
    r = _resolver(PLAN_AIGUILLE, PLAN_GLACIER)
    assert _got(r, "Refuge de Plan Glacier").feature_id == str(PLAN_GLACIER.id)


# ------------------------------------------------ the tiers, one by one


def test_the_type_word_is_sometimes_the_whole_difference():
    """"Refuge du Goûter" vs the route's bare alias "Goûter": stripping
    "refuge" merges them, so the exact-form tier must answer first."""
    r = _resolver(REFUGE_GOUTER, GOUTER_ROUTE)
    assert _got(r, "Refuge du Goûter").feature_id == str(REFUGE_GOUTER.id)
    assert _got(r, "Goûter Route").feature_id == str(GOUTER_ROUTE.id)
    # The bare alias still answers: it is claimed by exactly one feature.
    assert _got(r, "Goûter").feature_id == str(GOUTER_ROUTE.id)


def test_the_tight_tier_reaches_a_variant_the_exact_form_misses():
    """What the middle tier is FOR — caught by mutation, not foresight: with
    the tight tier deleted, every other test still passed, because their
    mentions were all stored forms the exact tier answers. The tier earns its
    place on variants: "Le Plan de l'Aiguille" is no stored form, but its
    tight key "plan aiguille" is claimed by one feature alone, while its loose
    key "plan" is shared with Plan Glacier and would go to the queue."""
    r = _resolver(PLAN_GLACIER, PLAN_AIGUILLE)
    got = _got(r, "Le Plan de l'Aiguille")
    assert got is not None, "the variant fell past the tight tier"
    assert got.feature_id == str(PLAN_AIGUILLE.id)


def test_terrain_nouns_survive_the_tight_key():
    assert normalise_tight("Refuge du Plan de l'Aiguille") == "plan aiguille"
    assert normalise_tight("Refuge de Plan Glacier") == "plan glacier"
    assert normalise_tight("Goûter Route") == "gouter route"


def test_the_exact_key_strips_nothing_but_form():
    assert normalise_exact("Refuge du Goûter") == "refuge du gouter"
    assert normalise_exact("REFUGE  DU   GOUTER") == "refuge du gouter"


def test_the_refuge_and_the_railway_both_stay_reachable():
    r = _resolver(REFUGE_MONTENVERS, RAILWAY)
    assert _got(r, "Refuge du Montenvers").feature_id == str(REFUGE_MONTENVERS.id)
    # The bare name is the railway's own alias, claimed by it alone at the
    # exact tier.
    assert _got(r, "Montenvers").feature_id == str(RAILWAY.id)


# ------------------------------------------------------ genuine ambiguity


def test_an_identical_alias_on_two_features_goes_to_a_person():
    """Two features literally carry the alias "Bellevue". No tier can tell
    them apart, no score should pretend to, and auto-accepting whichever
    sorted first is the first-writer bug in fuzzy clothing."""
    r = _resolver(HOUCHES, NID_ROAD)
    match, candidates = r.resolve("Bellevue")
    assert match is None
    offered = {c.feature_id for c in candidates}
    assert {str(HOUCHES.id), str(NID_ROAD.id)} <= offered


def test_a_fuzzy_tie_between_different_features_is_not_auto_accepted():
    """The tie rule, behaviourally: a mention near both Bellevue owners must
    not be claimed by either."""
    r = _resolver(HOUCHES, NID_ROAD)
    match, candidates = r.resolve("Bellevue!")
    assert match is None
    assert len({c.feature_id for c in candidates}) >= 2


def test_one_feature_claiming_a_key_through_many_forms_is_not_ambiguous():
    """The route claims "gouter" through half a dozen aliases. Many forms, one
    feature — that is emphasis, not ambiguity."""
    r = _resolver(GOUTER_ROUTE)
    assert _got(r, "Voie du Goûter").feature_id == str(GOUTER_ROUTE.id)
