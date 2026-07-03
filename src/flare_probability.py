"""
Flare-probability model for a single active region.

Combines three independent signals into one picture, rather than a
black-box single number:

1. McIntosh + Mount Wilson base rate: a heuristic table keyed by the
   region's McIntosh classification (Zurich class, penumbra, compactness
   -- the `spot_class` field, e.g. "Eki") and Mount Wilson magnetic class
   (`mag_class`, e.g. "BGD"). This mirrors the *shape* of the statistical
   tables NOAA forecasters have historically used (bigger/more complex
   spot groups with delta-class fields flare far more often), but the
   exact percentages here are a defensible approximation, not a
   peer-reviewed lookup table -- treat it as a cross-check, not ground
   truth.

2. NOAA's own operational probability: `solar_regions.json` already
   ships NOAA's issued c/m/x_flare_probability for the region (their
   official forecaster-reviewed number). We surface this directly
   alongside our own estimate so the two can be compared.

3. Poisson hot-region boost: NOAA's SRS-derived event counts
   (c_xray_events, m_xray_events, x_xray_events) are the region's flare
   count in the past 24h. We treat that as a Poisson rate and compute
   P(>=1 event in the next 24h) from it, which reacts faster than the
   McIntosh table to a region that just became newly active.
"""
import math

# Zurich class -> base daily probability (%) of at least one flare of
# each class, roughly increasing with spot-group size/complexity.
# X (no spots) < A < B < C < H < D < E < F.
ZURICH_BASE = {
    "X": {"C": 1, "M": 0, "X": 0},
    "A": {"C": 5, "M": 1, "X": 0},
    "B": {"C": 15, "M": 2, "X": 0},
    "H": {"C": 15, "M": 3, "X": 0},
    "C": {"C": 30, "M": 5, "X": 1},
    "D": {"C": 55, "M": 15, "X": 3},
    "E": {"C": 70, "M": 25, "X": 7},
    "F": {"C": 75, "M": 30, "X": 10},
}

# Mount Wilson magnetic class -> multiplier applied to the Zurich base.
MAG_MULTIPLIER = {
    "ALPHA": 0.6,
    "A": 0.6,
    "BETA": 1.0,
    "B": 1.0,
    "BG": 1.6,
    "BETA-GAMMA": 1.6,
    "GAMMA": 1.7,
    "G": 1.7,
    "BGD": 2.4,
    "BETA-GAMMA-DELTA": 2.4,
    "GD": 2.2,
    "DELTA": 2.5,
    "D": 2.5,
}


def _zurich_letter(spot_class):
    if not spot_class:
        return "X"
    letter = spot_class[0].upper()
    return letter if letter in ZURICH_BASE else "X"


def _mag_multiplier(mag_class):
    if not mag_class:
        return 1.0
    return MAG_MULTIPLIER.get(mag_class.upper(), 1.0)


def mcintosh_base_probability(spot_class, mag_class):
    """Returns {'C': pct, 'M': pct, 'X': pct} capped at 99%."""
    base = ZURICH_BASE[_zurich_letter(spot_class)]
    mult = _mag_multiplier(mag_class)
    return {k: round(min(99, v * mult), 1) for k, v in base.items()}


def poisson_hot_region_boost(events_last_24h):
    """
    P(>=1 event in next 24h) assuming a stationary Poisson process with
    rate lambda = events observed in the last 24h. Simple but directionally
    useful: a region that produced 3 C-flares today is treated as more
    likely to produce another one tomorrow than a quiet region, before the
    McIntosh class has even been re-classified.
    """
    lam = max(0, events_last_24h)
    return round((1 - math.exp(-lam)) * 100, 1)


def blended_probability(region):
    """
    region: one record from NOAA's solar_regions.json
    Returns a structured comparison of the three signals plus a final
    blended estimate (simple average of McIntosh-table and Poisson-boost,
    displayed next to NOAA's own official number for reference).
    """
    spot_class = region.get("spot_class")
    mag_class = region.get("mag_class")

    mcintosh = mcintosh_base_probability(spot_class, mag_class)
    poisson = {
        "C": poisson_hot_region_boost(region.get("c_xray_events") or 0),
        "M": poisson_hot_region_boost(region.get("m_xray_events") or 0),
        "X": poisson_hot_region_boost(region.get("x_xray_events") or 0),
    }
    noaa_official = {
        "C": region.get("c_flare_probability"),
        "M": region.get("m_flare_probability"),
        "X": region.get("x_flare_probability"),
    }

    blended = {}
    for cls in ("C", "M", "X"):
        vals = [v for v in (mcintosh[cls], poisson[cls]) if v is not None]
        blended[cls] = round(sum(vals) / len(vals), 1) if vals else None

    return {
        "region": region.get("region"),
        "location": region.get("location"),
        "spot_class": spot_class,
        "mag_class": mag_class,
        "mcintosh_table_pct": mcintosh,
        "poisson_hot_region_pct": poisson,
        "noaa_official_pct": noaa_official,
        "blended_estimate_pct": blended,
    }


def rank_regions(regions, top_n=5):
    """Rank regions by blended X-class probability, descending."""
    scored = [blended_probability(r) for r in regions]
    scored.sort(key=lambda r: (r["blended_estimate_pct"]["X"] or 0,
                                r["blended_estimate_pct"]["M"] or 0), reverse=True)
    return scored[:top_n]


if __name__ == "__main__":
    sample = {
        "region": 4479, "location": "N16W66", "spot_class": "Eki", "mag_class": "BGD",
        "c_xray_events": 2, "m_xray_events": 0, "x_xray_events": 0,
        "c_flare_probability": 85, "m_flare_probability": 35, "x_flare_probability": 10,
    }
    import json
    print(json.dumps(blended_probability(sample), indent=2))
