"""
Naive short-term trend forecasting from recent historical data.

This is deliberately simple: an ordinary-least-squares linear fit over
the most recent window of a time series, extrapolated forward a few
hours. It is a statistical extrapolation of recent behavior, not a
physics-based space-weather forecast -- solar wind speed and Kp do not
actually evolve linearly, and this will visibly diverge from reality
whenever a CME, sector boundary, or corotating interaction region
changes the picture. It exists to answer "if nothing changes, where is
this headed," clearly labeled as such, not to replace the drag-based or
flare-probability models elsewhere in this project.
"""
from datetime import datetime, timedelta, timezone


def _to_epoch_minutes(time_tag):
    if "T" in time_tag and not time_tag.endswith("Z") and "+" not in time_tag:
        dt = datetime.fromisoformat(time_tag).replace(tzinfo=timezone.utc)
    else:
        dt = datetime.fromisoformat(time_tag.replace("Z", "+00:00"))
    return dt.timestamp() / 60.0


def linear_forecast(history, value_key, time_key="time_tag",
                     window_minutes=180, forecast_hours=6, num_points=12):
    """
    history: list of dicts each containing a time_key and value_key.
    Fits a line to the last `window_minutes` of data and projects it
    forward `forecast_hours`, sampled at num_points.
    Returns {available, slope_per_hour, forecast: [{time, value}, ...]}
    or {available: False, reason} if there isn't enough recent data.
    """
    points = []
    for r in history:
        if r.get(value_key) is None or not r.get(time_key):
            continue
        try:
            t = _to_epoch_minutes(r[time_key])
        except ValueError:
            continue
        points.append((t, r[value_key]))

    if len(points) < 5:
        return {"available": False, "reason": "not enough historical points"}

    points.sort(key=lambda p: p[0])
    latest_t = points[-1][0]
    window = [(t, v) for t, v in points if t >= latest_t - window_minutes]
    if len(window) < 5:
        window = points[-30:]

    n = len(window)
    mean_t = sum(t for t, _ in window) / n
    mean_v = sum(v for _, v in window) / n
    num = sum((t - mean_t) * (v - mean_v) for t, v in window)
    den = sum((t - mean_t) ** 2 for t, _ in window)
    slope = num / den if den else 0.0
    intercept = mean_v - slope * mean_t

    forecast = []
    start_dt = datetime.fromtimestamp(latest_t * 60, tz=timezone.utc)
    for i in range(1, num_points + 1):
        minutes_ahead = (forecast_hours * 60 / num_points) * i
        t = latest_t + minutes_ahead
        value = slope * t + intercept
        forecast.append({
            "time": (start_dt + timedelta(minutes=minutes_ahead)).isoformat(),
            "value": round(value, 3),
        })

    return {
        "available": True,
        "slope_per_hour": round(slope * 60, 4),
        "window_minutes_used": window_minutes,
        "forecast": forecast,
        "method": "linear ordinary-least-squares extrapolation of recent trend "
                  "-- not a physics-based forecast",
    }


if __name__ == "__main__":
    history = [
        {"time_tag": "2026-07-06T08:00:00", "kp_index": 1},
        {"time_tag": "2026-07-06T08:30:00", "kp_index": 2},
        {"time_tag": "2026-07-06T09:00:00", "kp_index": 2},
        {"time_tag": "2026-07-06T09:30:00", "kp_index": 3},
        {"time_tag": "2026-07-06T10:00:00", "kp_index": 3},
        {"time_tag": "2026-07-06T10:30:00", "kp_index": 4},
    ]
    result = linear_forecast(history, "kp_index", window_minutes=180, forecast_hours=6, num_points=6)
    import json
    print(json.dumps(result, indent=2))
