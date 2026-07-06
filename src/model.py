"""
Orchestrator: pulls live NOAA data, runs the flare-probability model on
every active region, runs the drag-based CME arrival model on every
recent M/X flare event, and assembles one structured prediction report.
"""
from datetime import datetime, timezone, timedelta

import fetch_data
import flare_probability
import drag_based_model as dbm
import pradan_client

# Empirical CME-speed-from-flare-class estimator.
# Real-time coronagraph (LASCO/DONKI) CME speeds were not reachable from
# this environment, so initial CME speed is estimated from the flare's
# GOES class using published CDAW-catalog statistics (Yashiro et al. 2004;
# Bein et al. 2012): X-class flares average ~1500 km/s associated CMEs,
# M-class ~700-900 km/s, C-class rarely produce a fast, geoeffective CME.
# This is clearly an estimate, not a measurement -- surfaced as such in
# the report.
def estimate_cme_speed_kms(flare_class_str):
    if not flare_class_str:
        return None
    letter = flare_class_str[0].upper()
    try:
        magnitude = float(flare_class_str[1:])
    except (ValueError, IndexError):
        magnitude = 1.0

    if letter == "X":
        return 900 + 130 * magnitude       # X1 ~1030, X5 ~1550, X10 ~2200
    if letter == "M":
        return 500 + 40 * magnitude        # M1 ~540, M5 ~700, M9 ~860
    if letter == "C":
        return 350 + 5 * magnitude         # rarely geoeffective
    return None


def _age_hours(time_tag, now):
    """
    Hours between a NOAA time_tag (naive UTC string, no offset) and now.
    NOAA's real-time solar wind feed is nominally updated every minute but
    can silently stall for hours (spacecraft/ground-station gaps) while
    still returning HTTP 200 -- a stale-but-"live" response looks
    identical to fresh data unless the payload's own last timestamp is
    checked against wall-clock time.
    """
    if not time_tag:
        return None
    try:
        t = datetime.fromisoformat(time_tag).replace(tzinfo=timezone.utc)
    except ValueError:
        return None
    return (now - t).total_seconds() / 3600.0


def latest_active(records, speed_field, extra_fields=()):
    """Most recent record with a non-null speed field and active=True."""
    candidates = [r for r in records if r.get("active") and r.get(speed_field) is not None]
    if not candidates:
        return None
    return max(candidates, key=lambda r: r["time_tag"])


# GOES and SoLEXS are on different satellites with independent clocks and
# onboard time handling; a few minutes of slack avoids penalizing a real
# match over clock/detector-response timing differences rather than an
# actual absence of correlated activity.
CROSS_VALIDATION_TOLERANCE_MINUTES = 5


def _flares_confirmed_by_solexs(flares_on_date, solexs_result):
    """
    Tag each GOES flare with isro_confirmed: True if any SoLEXS
    enhancement window overlaps its begin/end time (with tolerance).
    Returns (tagged_flares, summary_stats).
    """
    if not solexs_result.get("available"):
        return [], {"available": False, "reason": solexs_result.get("reason")}

    tolerance = timedelta(minutes=CROSS_VALIDATION_TOLERANCE_MINUTES)
    enhancement_windows = []
    for e in solexs_result["enhancements"]:
        start = datetime.fromisoformat(e["start"]) - tolerance
        end = datetime.fromisoformat(e["end"]) + tolerance
        enhancement_windows.append((start, end, e["peak_counts_per_sec"]))

    tagged = []
    confirmed_count = 0
    for f in flares_on_date:
        try:
            f_begin = datetime.fromisoformat(f["begin_time"].replace("Z", "+00:00"))
            f_end = datetime.fromisoformat(f["end_time"].replace("Z", "+00:00"))
        except (KeyError, ValueError):
            continue

        match = next((w for w in enhancement_windows if f_begin <= w[1] and w[0] <= f_end), None)
        confirmed = match is not None
        if confirmed:
            confirmed_count += 1
        tagged.append({
            "begin_time": f["begin_time"],
            "max_time": f["max_time"],
            "end_time": f["end_time"],
            "max_class": f["max_class"],
            "isro_confirmed": confirmed,
            "solexs_peak_counts_per_sec": match[2] if match else None,
        })

    return tagged, {
        "available": True,
        "date": solexs_result["date"],
        "data_age_days": solexs_result.get("data_age_days"),
        "instrument": solexs_result["instrument"],
        "satellite": solexs_result["satellite"],
        "source": solexs_result["source"],
        "baseline_counts_per_sec": solexs_result["baseline_counts_per_sec"],
        "total_enhancements_detected": len(solexs_result["enhancements"]),
        "goes_flares_on_date": len(tagged),
        "goes_flares_confirmed": confirmed_count,
    }


def build_report():
    data, sources = fetch_data.load_all()

    plasma = latest_active(data["solar_wind_plasma"], "proton_speed")
    mag = latest_active(data["solar_wind_mag"], "bt")
    ambient_speed = plasma["proton_speed"] if plasma else 400.0  # quiet-sun fallback
    bz = mag["bz_gsm"] if mag else None

    kp_records = data["planetary_kp"]
    latest_kp = kp_records[-1] if kp_records else None

    regions = data["solar_regions"]
    latest_date = max(r["observed_date"] for r in regions) if regions else None
    todays_regions = [r for r in regions if r["observed_date"] == latest_date]
    top_regions = flare_probability.rank_regions(todays_regions, top_n=5)

    flares = data["xray_flares"]
    mx_flares = [f for f in flares if f.get("max_class", "").startswith(("M", "X"))]

    def _flare_magnitude(f):
        cls = f.get("max_class", "")
        try:
            return float(cls[1:])
        except (ValueError, IndexError):
            return 0.0

    # Recency alone can silently drop the flare that actually matters: an
    # X-class (or big M-class) event from days ago is still the dominant
    # geoeffective driver while its CME is in transit, even if a dozen
    # smaller M1-class flares have happened more recently. So: always keep
    # every X-class and M5+ flare in the window, then top up with the most
    # recent remaining flares up to 5 total.
    significant = [f for f in mx_flares
                   if f["max_class"].startswith("X") or _flare_magnitude(f) >= 5]
    significant.sort(key=lambda f: f["max_time"], reverse=True)

    remaining = [f for f in mx_flares if f not in significant]
    remaining.sort(key=lambda f: f["max_time"], reverse=True)

    recent_mx = significant + remaining
    recent_mx = recent_mx[:max(5, len(significant))]
    recent_mx.sort(key=lambda f: f["max_time"], reverse=True)

    cme_predictions = []
    for flare in recent_mx:
        v0 = estimate_cme_speed_kms(flare["max_class"])
        arrival = dbm.predict_arrival(v0, ambient_speed)
        storm = dbm.estimate_geomagnetic_response(arrival.get("arrival_speed_kms"), bz)
        cme_predictions.append({
            "flare_class": flare["max_class"],
            "flare_peak_time": flare["max_time"],
            "estimated_cme_speed_kms": v0,
            "arrival": arrival,
            "geomagnetic_outlook": storm,
        })

    solexs_result = pradan_client.fetch_solexs_enhancements()
    aditya_l1_flares, aditya_l1_summary = [], {"available": False, "reason": "not attempted"}
    if solexs_result.get("available"):
        flares_on_date = [f for f in flares if f.get("begin_time", "").startswith(solexs_result["date"])]
        aditya_l1_flares, aditya_l1_summary = _flares_confirmed_by_solexs(flares_on_date, solexs_result)
    else:
        aditya_l1_summary = {"available": False, "reason": solexs_result.get("reason")}

    now = datetime.now(timezone.utc)
    plasma_age_hours = _age_hours(plasma.get("time_tag") if plasma else None, now)
    STALE_THRESHOLD_HOURS = 3.0

    report = {
        "generated_at": now.isoformat(),
        "data_sources": sources,
        "solar_wind": {
            "ambient_speed_kms": ambient_speed,
            "density_p_cm3": plasma.get("proton_density") if plasma else None,
            "temperature_k": plasma.get("proton_temperature") if plasma else None,
            "bt_nt": mag.get("bt") if mag else None,
            "bz_gsm_nt": bz,
            "sample_time": plasma.get("time_tag") if plasma else None,
            "data_age_hours": round(plasma_age_hours, 1) if plasma_age_hours is not None else None,
            "stale": plasma_age_hours is not None and plasma_age_hours > STALE_THRESHOLD_HOURS,
        },
        "geomagnetic": {
            "kp_index": latest_kp.get("kp_index") if latest_kp else None,
            "kp_estimated": latest_kp.get("estimated_kp") if latest_kp else None,
            "sample_time": latest_kp.get("time_tag") if latest_kp else None,
        },
        "top_flare_risk_regions": top_regions,
        "recent_mx_flares_cme_arrival": cme_predictions,
        "aditya_l1_cross_validation": {
            "summary": aditya_l1_summary,
            "flares": aditya_l1_flares,
        },
    }
    return report


if __name__ == "__main__":
    import json
    print(json.dumps(build_report(), indent=2, default=str))
