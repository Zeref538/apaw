"""Dam registry: names as PAGASA writes them, plus coordinates.

Coordinates come from PAGASA's own placemark file,
https://pubfiles.pagasa.dost.gov.ph/hmd/Previous_Dam_Status/LocationsFinal.kml
— note that Magat's placemark is mislabelled `<name>Layers</name>` there; its
description HTML identifies it as MAGAT.
"""

# PAGASA has changed its own labels over the years — the Wayback history has
# both "Magat" and "Magat Dam" for the same reservoir. Everything is
# canonicalised on the way in so one dam stays one dam.
ALIASES = {
    "magat dam": "Magat",
    "magat": "Magat",
    "angat dam": "Angat",
    "ipo dam": "Ipo",
    "la mesa dam": "La Mesa",
    "ambuklao dam": "Ambuklao",
    "binga dam": "Binga",
    "san roque dam": "San Roque",
    "pantabangan dam": "Pantabangan",
    "caliraya dam": "Caliraya",
}


def canonical(name: str) -> str:
    cleaned = " ".join(str(name).split())
    return ALIASES.get(cleaned.lower(), cleaned)


# Keys are canonical names and are the join key into dam_levels.csv.
DAMS = {
    "Angat":       {"lat": 14.91139, "lon": 121.16500, "basin": "Angat"},
    "Ipo":         {"lat": 14.87500, "lon": 121.06222, "basin": "Angat"},
    "La Mesa":     {"lat": 14.71372, "lon": 121.07316, "basin": "Angat"},
    "Ambuklao":    {"lat": 16.46111, "lon": 120.74389, "basin": "Agno"},
    "Binga":       {"lat": 16.39611, "lon": 120.72667, "basin": "Agno"},
    "San Roque":   {"lat": 16.14600, "lon": 120.68400, "basin": "Agno"},
    "Pantabangan": {"lat": 15.81833, "lon": 121.10944, "basin": "Pampanga"},
    "Magat":       {"lat": 16.83333, "lon": 121.45056, "basin": "Cagayan"},
    "Caliraya":    {"lat": 14.28830, "lon": 121.50140, "basin": "Pasig-Laguna"},
}

# Dams PAGASA publishes no rule curve or NHWL for; excluded from spill risk.
NO_RULE_CURVE = {"Ipo", "La Mesa", "Caliraya"}
NO_NHWL = {"Caliraya"}
