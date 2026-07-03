"""
Live NOAA SWPC / real-time solar wind data fetcher.

Tries to pull fresh data from NOAA's public JSON endpoints on every call.
If the network is unavailable (offline dev, sandboxed CI, etc.) it falls
back to the bundled snapshots in data/, which were captured live on
2026-07-03 and are shipped with this project so the pipeline always runs.
"""
import json
import os
import urllib.request
import urllib.error

DATA_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "data")

ENDPOINTS = {
    "solar_wind_plasma": "https://services.swpc.noaa.gov/json/rtsw/rtsw_wind_1m.json",
    "solar_wind_mag": "https://services.swpc.noaa.gov/json/rtsw/rtsw_mag_1m.json",
    "planetary_kp": "https://services.swpc.noaa.gov/json/planetary_k_index_1m.json",
    "xray_flares": "https://services.swpc.noaa.gov/json/goes/primary/xray-flares-7-day.json",
    "solar_regions": "https://services.swpc.noaa.gov/json/solar_regions.json",
    "f107_flux": "https://services.swpc.noaa.gov/json/f107_cm_flux.json",
}

TIMEOUT_SECONDS = 12


def _fetch_live(name: str, url: str):
    req = urllib.request.Request(url, headers={"User-Agent": "solar-flare-prediction/1.0"})
    with urllib.request.urlopen(req, timeout=TIMEOUT_SECONDS) as resp:
        raw = resp.read()
    data = json.loads(raw)
    if not data:
        raise ValueError(f"{name}: empty response")
    return data


def _fetch_fallback(name: str):
    path = os.path.join(DATA_DIR, f"{name}.json")
    with open(path, "r") as f:
        return json.load(f)


def load_dataset(name: str):
    """Return (data, source) where source is 'live' or 'fallback'."""
    if name not in ENDPOINTS:
        raise KeyError(f"Unknown dataset: {name}")
    try:
        data = _fetch_live(name, ENDPOINTS[name])
        return data, "live"
    except (urllib.error.URLError, TimeoutError, ValueError, OSError):
        return _fetch_fallback(name), "fallback"


def load_all():
    """Fetch every dataset, reporting per-dataset provenance."""
    out = {}
    sources = {}
    for name in ENDPOINTS:
        data, source = load_dataset(name)
        out[name] = data
        sources[name] = source
    return out, sources


if __name__ == "__main__":
    data, sources = load_all()
    for name, source in sources.items():
        n = len(data[name]) if isinstance(data[name], list) else "n/a"
        print(f"{name:20s} source={source:8s} records={n}")
