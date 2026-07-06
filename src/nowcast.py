"""
Nowcasting: convert the live GOES X-ray flux (long channel, 0.1-0.8nm)
into the same A/B/C/M/X classification NOAA uses for flare events, and
compute a short-term rising/falling trend directly from the raw flux
time series -- this is "what is the Sun doing right now," as opposed to
the flare-probability model's "what might it do in the next 24h."

GOES classification thresholds (W/m^2), standard NOAA convention:
    A: < 1e-7        B: 1e-7 - 1e-6        C: 1e-6 - 1e-5
    M: 1e-5 - 1e-4    X: >= 1e-4
"""
from datetime import datetime, timedelta, timezone

THRESHOLDS = [
    ("X", 1e-4),
    ("M", 1e-5),
    ("C", 1e-6),
    ("B", 1e-7),
    ("A", 0.0),
]

LONG_CHANNEL = "0.1-0.8nm"


def flux_to_class(flux_w_m2):
    if flux_w_m2 is None or flux_w_m2 <= 0:
        return None
    for letter, threshold in THRESHOLDS:
        if flux_w_m2 >= threshold:
            magnitude = flux_w_m2 / threshold if threshold > 0 else flux_w_m2 / 1e-8
            return f"{letter}{magnitude:.1f}"
    return None


def _parse_time(tag):
    return datetime.fromisoformat(tag.replace("Z", "+00:00"))


def current_state(xray_records):
    """
    Returns current long-channel flux, its GOES-class equivalent, a
    short-term trend label, and a (time, flux) series for charting.
    Trend compares the latest reading to ~30 minutes prior -- long
    enough to smooth 1-minute noise, short enough to reflect an
    in-progress flare rise/decay rather than the whole 6h window.
    """
    long_records = [r for r in xray_records if r.get("energy") == LONG_CHANNEL and r.get("flux")]
    if not long_records:
        return {"available": False}

    long_records.sort(key=lambda r: r["time_tag"])
    latest = long_records[-1]
    latest_time = _parse_time(latest["time_tag"])

    reference_time = latest_time - timedelta(minutes=30)
    reference = min(long_records, key=lambda r: abs(_parse_time(r["time_tag"]) - reference_time))

    delta = latest["flux"] - reference["flux"]
    relative_change = delta / reference["flux"] if reference["flux"] else 0
    if relative_change > 0.15:
        trend = "rising"
    elif relative_change < -0.15:
        trend = "falling"
    else:
        trend = "steady"

    series = [{"time": r["time_tag"], "flux": r["flux"]} for r in long_records]

    return {
        "available": True,
        "flux_w_m2": latest["flux"],
        "goes_class": flux_to_class(latest["flux"]),
        "sample_time": latest["time_tag"],
        "trend": trend,
        "trend_change_pct": round(relative_change * 100, 1),
        "series": series,
    }


if __name__ == "__main__":
    import json
    with open(r"C:\Users\UJWAL M\OneDrive\Desktop\New folder\solar_flare_prediction\data\xray_flux.json") as f:
        records = json.load(f)
    state = current_state(records)
    print("class:", state["goes_class"], "trend:", state["trend"], state["trend_change_pct"], "%")
    print("series points:", len(state["series"]))
