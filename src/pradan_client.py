"""
Real Aditya-L1 (ISRO) data integration via PRADAN.

Aditya-L1 is ISRO's solar observatory at the Sun-Earth L1 point. Its
SoLEXS instrument (Solar Low Energy X-ray Spectrometer) measures the
same soft X-ray band GOES XRS uses to classify flares, but from a
completely different satellite in a completely different orbit --
useful as an independent confirmation of GOES-detected flares, not
just another mirror of the same measurement.

Correcting a naming mix-up from earlier in this project: the real ISRO
source for solar/space-weather data is PRADAN (pradan1.issdc.gov.in),
run by ISSDC (Indian Space Science Data Centre). NRSC (National Remote
Sensing Centre) is ISRO's *land* remote-sensing center (Bhuvan,
Cartosat/Resourcesat imagery) and does not publish solar wind, CME, or
flare data at all -- there is nothing to integrate from NRSC for this
use case.

Auth: Keycloak SSO at idp.issdc.gov.in. Registration required at
https://pradan.issdc.gov.in. Credentials read from env vars
PRADAN_USERNAME / PRADAN_PASSWORD (see .env.example). Entirely
optional, like the Supabase integration -- if unset, is_configured()
is False and callers should treat Aditya-L1 data as unavailable rather
than failing.
"""
import os
import re
import zipfile
import gzip
import shutil
from datetime import datetime, timedelta, timezone
from pathlib import Path

import requests

try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass

PRADAN_USERNAME = os.environ.get("PRADAN_USERNAME")
PRADAN_PASSWORD = os.environ.get("PRADAN_PASSWORD")

PORTAL_URL = "https://pradan1.issdc.gov.in/al1/"
PROTECTED_URL = "https://pradan1.issdc.gov.in/al1/protected/payload.xhtml"
BROWSE_URL = "https://pradan1.issdc.gov.in/al1/protected/browse.xhtml"

CACHE_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "data", "pradan_cache")

# SoLEXS FITS TIME column is seconds since the Unix epoch (MJDREFI=40587
# in the file header, which is 1970-01-01).
UNIX_EPOCH = datetime(1970, 1, 1, tzinfo=timezone.utc)

# A count rate this many times the day's median is treated as flare
# activity. 3x is conservative enough to avoid routine background
# fluctuation while still catching M-class-and-up events, which is
# what this cross-check is validating (see README for the caveat that
# this is a total-count-rate proxy, not a calibrated flux).
ENHANCEMENT_THRESHOLD_MULTIPLE = 3.0
# Consecutive above-threshold samples more than this many seconds apart
# are treated as separate events rather than one continuous flare.
GROUP_GAP_SECONDS = 60


def is_configured():
    return bool(PRADAN_USERNAME and PRADAN_PASSWORD)


def _login(session):
    r = session.get(PROTECTED_URL, timeout=20, allow_redirects=True)
    match = re.search(
        r'<form[^>]*id=["\']kc-form-login["\'][^>]*action=["\']([^"\']+)["\']',
        r.text, re.IGNORECASE)
    if not match:
        if "protected" in r.url.lower():
            return True  # session already valid
        return False

    login_url = match.group(1).replace("&amp;", "&").replace("&#38;", "&")
    r2 = session.post(
        login_url,
        data={"username": PRADAN_USERNAME, "password": PRADAN_PASSWORD, "credentialId": ""},
        timeout=30, allow_redirects=True,
        headers={"Referer": r.url, "Content-Type": "application/x-www-form-urlencoded"},
    )
    if "invalid" in r2.text.lower():
        return False

    r3 = session.get(PROTECTED_URL, timeout=15, allow_redirects=True)
    return r3.status_code == 200 and "login" not in r3.url.lower()


def _find_download_url(session, date):
    """Browse SoLEXS listings and find the download URL for a given date's L1 zip."""
    r = session.get(f"{BROWSE_URL}?id=solexs", timeout=20)
    r.raise_for_status()
    fname_fragment = date.strftime("%Y%m%d")
    hrefs = re.findall(r'href="([^"]*downloadData/solexs[^"]*)"', r.text)
    for href in hrefs:
        if fname_fragment in href:
            return "https://pradan1.issdc.gov.in" + href if href.startswith("/") else href
    return None


def _find_latest_download_url(session):
    """
    Return (url, date) for whichever SoLEXS L1 file is most recently
    published. Level-1 products have a multi-day processing latency
    (observed: ~3 days), so "today" or "yesterday" routinely doesn't
    exist yet -- the browse listing itself (sorted newest-first) is the
    only reliable way to know what's actually available.
    """
    r = session.get(f"{BROWSE_URL}?id=solexs", timeout=20)
    r.raise_for_status()
    hrefs = re.findall(r'href="([^"]*downloadData/solexs/[^"]*AL1_SLX_L1_(\d{8})_[^"]*)"', r.text)
    if not hrefs:
        return None, None
    href, date_str = hrefs[0]  # listing is newest-first
    url = "https://pradan1.issdc.gov.in" + href if href.startswith("/") else href
    date = datetime.strptime(date_str, "%Y%m%d").replace(tzinfo=timezone.utc)
    return url, date


def _download_and_cache(session, url, date):
    os.makedirs(CACHE_DIR, exist_ok=True)
    cache_path = os.path.join(CACHE_DIR, f"solexs_{date.strftime('%Y%m%d')}.zip")
    if os.path.exists(cache_path) and os.path.getsize(cache_path) > 0:
        return cache_path
    resp = session.get(url, timeout=90)
    resp.raise_for_status()
    with open(cache_path, "wb") as f:
        f.write(resp.content)
    return cache_path


def _extract_lightcurve_fits(zip_path, date):
    extract_dir = os.path.join(CACHE_DIR, f"extracted_{date.strftime('%Y%m%d')}")
    lc_gz_pattern = f"AL1_SOLEXS_{date.strftime('%Y%m%d')}_SDD2_L1.lc.gz"

    if not os.path.exists(extract_dir):
        with zipfile.ZipFile(zip_path) as z:
            for member in z.namelist():
                if member.endswith(lc_gz_pattern):
                    z.extract(member, extract_dir)
                    gz_path = os.path.join(extract_dir, member)
                    fits_path = gz_path[:-3]  # strip .gz
                    with gzip.open(gz_path, "rb") as fin, open(fits_path, "wb") as fout:
                        shutil.copyfileobj(fin, fout)
                    return fits_path
        return None

    for root, _, files in os.walk(extract_dir):
        for name in files:
            if name.endswith(".lc"):
                return os.path.join(root, name)
    return None


def _detect_enhancements(fits_path):
    """
    Returns a list of {start, end, peak_counts_per_sec} for periods where
    the SoLEXS count rate exceeds ENHANCEMENT_THRESHOLD_MULTIPLE times the
    day's median -- a simple, transparent flare-activity proxy, not a
    calibrated flux-to-GOES-class conversion.
    """
    from astropy.io import fits
    import numpy as np

    with fits.open(fits_path) as hdul:
        data = hdul["RATE"].data
        time = data["TIME"]
        counts = data["COUNTS"]

    baseline = np.nanmedian(counts)
    if not baseline or np.isnan(baseline):
        return [], baseline

    valid = ~np.isnan(counts)
    above = (counts > baseline * ENHANCEMENT_THRESHOLD_MULTIPLE) & valid
    idx = np.where(above)[0]
    if len(idx) == 0:
        return [], baseline

    groups = np.split(idx, np.where(np.diff(idx) > GROUP_GAP_SECONDS)[0] + 1)
    enhancements = []
    for g in groups:
        start = UNIX_EPOCH + timedelta(seconds=float(time[g[0]]))
        end = UNIX_EPOCH + timedelta(seconds=float(time[g[-1]]))
        peak = float(np.nanmax(counts[g]))
        enhancements.append({
            "start": start.isoformat(),
            "end": end.isoformat(),
            "peak_counts_per_sec": peak,
        })
    return enhancements, float(baseline)


def fetch_solexs_enhancements(date=None):
    """
    Full pipeline: login -> find today's (or given date's) SoLEXS L1 file
    -> download+cache -> extract -> parse -> detect flare-like
    enhancements. Returns a dict with 'available' (bool) and, if
    available, 'date', 'baseline_counts_per_sec', 'enhancements'.
    Never raises -- any failure (no credentials, network issue, file not
    yet published for today) results in available=False with a 'reason'.
    """
    if not is_configured():
        return {"available": False, "reason": "PRADAN_USERNAME/PRADAN_PASSWORD not set"}

    try:
        session = requests.Session()
        session.headers.update({"User-Agent": "solar-flare-prediction/1.0"})
        if not _login(session):
            return {"available": False, "reason": "PRADAN login failed"}

        if date is not None:
            url = _find_download_url(session, date)
        else:
            url, date = _find_latest_download_url(session)

        if not url:
            return {"available": False, "reason": "No SoLEXS L1 file found in the PRADAN listing"}

        zip_path = _download_and_cache(session, url, date)
        fits_path = _extract_lightcurve_fits(zip_path, date)
        if not fits_path:
            return {"available": False, "reason": "Could not locate light curve FITS inside SoLEXS zip"}

        enhancements, baseline = _detect_enhancements(fits_path)
        data_age_days = (datetime.now(timezone.utc).date() - date.date()).days
        return {
            "available": True,
            "date": date.strftime("%Y-%m-%d"),
            "data_age_days": data_age_days,
            "baseline_counts_per_sec": baseline,
            "enhancements": enhancements,
            "instrument": "SoLEXS",
            "satellite": "Aditya-L1",
            "source": "ISRO PRADAN (ISSDC)",
        }
    except Exception as e:
        return {"available": False, "reason": f"{type(e).__name__}: {e}"}


if __name__ == "__main__":
    import json
    print(json.dumps(fetch_solexs_enhancements(), indent=2))
