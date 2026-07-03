"""
Drag-Based Model (DBM) for CME Earth-arrival time.

Implements the analytic solution of Vrsnak et al. (2013, Solar Physics 285),
the same physics model underlying NOAA/ESA operational CME-arrival tools
(e.g. NOAA's WSA-Enlil companion DBM and ESA's DBEM).

Equation of motion for a CME moving through the ambient solar wind:
    dv/dt = -gamma * (v - w) * |v - w|

where v is CME speed, w is ambient solar-wind speed, and gamma is an
empirical drag parameter (km^-1) set by the CME's mass/cross-section and
the ambient wind density. This has a closed-form solution:

    v(t) = w + (v0 - w) / (1 + gamma*(v0 - w)*t)
    r(t) = r0 + w*t + (1/gamma) * ln(1 + gamma*(v0 - w)*t)

When v0 > w the CME decelerates toward the ambient wind speed (drag).
When v0 < w it accelerates toward it. Both cases fall out of the same
formula automatically because (v0 - w) carries the sign.
"""
import math

AU_KM = 1.496e8
R_SUN_KM = 6.96e5
CME_INITIAL_HEIGHT_RS = 20.0  # coronagraph field-of-view height where v0 is measured
CME_INITIAL_HEIGHT_KM = CME_INITIAL_HEIGHT_RS * R_SUN_KM

# Typical operational gamma range (km^-1), per Vrsnak et al. 2013 Table 1.
GAMMA_LOW = 0.1e-7
GAMMA_MID = 0.2e-7
GAMMA_HIGH = 0.5e-7


def _radius_at_time(t_hours, v0, w, gamma, r0=CME_INITIAL_HEIGHT_KM):
    """
    r(t) in km, t in hours. v0, w in km/s, gamma in km^-1.

    Uses |v0-w| inside the denominator/log and a separate sign(v0-w) term,
    per Vrsnak et al. (2013) eq. 4-5. This keeps 1 + gamma*|v0-w|*t > 0 for
    all t >= 0 regardless of whether the CME is faster or slower than the
    ambient wind, so the closed form never breaks down (embedding the
    signed (v0-w) directly in the log argument, as a naive transcription
    of the ODE solution would, makes the argument go negative and blow up
    whenever v0 < w).
    """
    t_s = t_hours * 3600.0
    dv0 = v0 - w
    if abs(dv0) < 1e-9:
        return r0 + w * t_s
    sign = 1.0 if dv0 > 0 else -1.0
    denom = 1 + gamma * abs(dv0) * t_s
    return r0 + w * t_s + (sign / gamma) * math.log(denom)


def _speed_at_time(t_hours, v0, w, gamma):
    t_s = t_hours * 3600.0
    dv0 = v0 - w
    denom = 1 + gamma * abs(dv0) * t_s
    return w + dv0 / denom


def transit_time_hours(v0, w, gamma=GAMMA_MID, target_km=AU_KM, max_hours=400.0):
    """
    Solve r(t) = target_km for t (hours) via bisection on the monotonic
    (for physically valid gamma/regime) r(t) curve.
    Returns None if the CME never reaches the target within max_hours
    (e.g. a slow CME that decays toward an ambient speed too low to
    cover the distance).
    """
    lo, hi = 0.0, max_hours
    r_hi = _radius_at_time(hi, v0, w, gamma)
    if r_hi < target_km:
        return None

    for _ in range(100):
        mid = (lo + hi) / 2.0
        r_mid = _radius_at_time(mid, v0, w, gamma)
        if r_mid < target_km:
            lo = mid
        else:
            hi = mid
        if hi - lo < 1e-4:
            break
    return hi


def predict_arrival(v0_kms, ambient_speed_kms):
    """
    Full prediction: best-estimate transit time plus an uncertainty range
    from sweeping gamma across its typical operational bounds.

    Returns a dict with transit_hours (best/low/high), arrival_speed_kms,
    and the gamma values used.
    """
    results = {}
    for label, gamma in (("low", GAMMA_LOW), ("mid", GAMMA_MID), ("high", GAMMA_HIGH)):
        t = transit_time_hours(v0_kms, ambient_speed_kms, gamma=gamma)
        results[label] = t

    # Higher drag (gamma_high) pulls a fast CME down toward ambient speed
    # faster -> slower transit for v0>w; the low/high transit-time bounds
    # therefore don't map 1:1 to low/high gamma. Just take min/max of the
    # three solved times to build the uncertainty band robustly.
    valid = {k: v for k, v in results.items() if v is not None}
    if not valid:
        return {
            "transit_hours_best": None,
            "transit_hours_low": None,
            "transit_hours_high": None,
            "arrival_speed_kms": None,
            "note": "CME does not reach 1 AU within the modeled window "
                    "(too slow relative to ambient wind and drag).",
        }

    best = valid.get("mid", list(valid.values())[0])
    all_t = list(valid.values())
    t_low, t_high = min(all_t), max(all_t)
    arrival_speed = _speed_at_time(best, v0_kms, ambient_speed_kms, GAMMA_MID) if best else None

    return {
        "transit_hours_best": round(best, 1) if best else None,
        "transit_hours_low": round(t_low, 1),
        "transit_hours_high": round(t_high, 1),
        "arrival_speed_kms": round(arrival_speed, 0) if arrival_speed else None,
        "gamma_range_km-1": [GAMMA_LOW, GAMMA_HIGH],
        "cme_initial_speed_kms": v0_kms,
        "ambient_wind_speed_kms": ambient_speed_kms,
    }


def estimate_geomagnetic_response(arrival_speed_kms, bz_nt=None):
    """
    Very coarse storm-strength heuristic from arrival speed alone
    (used only when Bz is not yet known, i.e. before L1 crossing).
    Real storm strength is dominated by IMF Bz, which is unknowable
    until the CME sheath/ejecta actually reaches the L1 point, ~30-60
    minutes before Earth impact.
    """
    if arrival_speed_kms is None:
        return "unknown"
    if bz_nt is not None and bz_nt < -10:
        return "G3+ (strong) likely - sustained southward Bz"
    if arrival_speed_kms >= 700:
        return "G2-G3 possible if Bz turns southward"
    if arrival_speed_kms >= 500:
        return "G1-G2 possible if Bz turns southward"
    if arrival_speed_kms >= 400:
        return "G1 (minor) possible, or quiet if Bz stays northward"
    return "Likely no storm (sub-storm-threshold arrival speed)"


if __name__ == "__main__":
    # Sanity check: CME slower than ambient wind should accelerate toward it.
    r = predict_arrival(v0_kms=380, ambient_speed_kms=450)
    print("Slow CME (380) into fast wind (450):", r)
    assert r["arrival_speed_kms"] is not None
    assert 380 <= r["arrival_speed_kms"] <= 450, "arrival speed should sit between v0 and ambient"

    r2 = predict_arrival(v0_kms=1500, ambient_speed_kms=400)
    print("Fast CME (1500) into slow wind (400):", r2)
    print("Storm outlook:", estimate_geomagnetic_response(r2["arrival_speed_kms"]))
