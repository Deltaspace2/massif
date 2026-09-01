from enum import StrEnum


class FeatureType(StrEnum):
    ROUTE = "route"
    HUT = "hut"
    LIFT = "lift"
    LIFT_STATION = "lift_station"
    GLACIER = "glacier"
    COULOIR = "couloir"
    ACCESS_ROAD = "access_road"
    TRAIL = "trail"
    ZONE = "zone"
    PEAK = "peak"


class SourceType(StrEnum):
    OFFICIAL = "official"
    OPERATOR = "operator"
    INSTITUTIONAL = "institutional"
    COMMUNITY = "community"


class StatementType(StrEnum):
    CLOSURE = "closure"
    RESTRICTION = "restriction"
    OPENING = "opening"
    OPERATIONAL_STATUS = "operational_status"
    # v2
    CONDITION = "condition"
    HAZARD_OBSERVATION = "hazard_observation"


class StatusValue(StrEnum):
    OPEN = "open"
    # Open, and nobody is running it: the door is unlocked, there is no warden,
    # and a walker carries their own food and bedding. A VARIANT OF OPEN and
    # never a warning — a third of the huts here are in this state and the one
    # thing this site must not do is make an open hut look shut.
    UNSTAFFED = "unstaffed"
    CLOSED = "closed"
    RESTRICTED = "restricted"
    UNKNOWN = "unknown"


class ExtractionMethod(StrEnum):
    MANUAL = "manual"
    RULE = "rule"
    LLM = "llm"
