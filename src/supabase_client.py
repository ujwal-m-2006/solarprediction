"""
Optional Supabase persistence for report runs.

Writes are entirely optional -- if SUPABASE_URL / SUPABASE_KEY aren't set,
save_report() is a no-op and report.py continues to work exactly as
before (local JSON/txt/PNG only). This keeps the pipeline runnable with
zero external accounts, per the same fallback philosophy as fetch_data.py.

Setup (once you have a Supabase project):
  1. Run schema.sql in the Supabase SQL editor.
  2. Copy .env.example to .env and fill in SUPABASE_URL and SUPABASE_KEY
     (use the service_role key here, not anon -- this writes server-side).
  3. pip install supabase python-dotenv
"""
import os

try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass

SUPABASE_URL = os.environ.get("SUPABASE_URL")
SUPABASE_KEY = os.environ.get("SUPABASE_KEY")


def is_configured():
    return bool(SUPABASE_URL and SUPABASE_KEY)


def _get_client():
    from supabase import create_client
    return create_client(SUPABASE_URL, SUPABASE_KEY)


def save_report(report):
    """
    Persist one report run to Supabase: one row in report_runs, plus one
    row per active region in region_predictions and one row per CME
    prediction in cme_predictions. Returns the new run's id, or None if
    Supabase isn't configured or the write failed (logged, not raised --
    a Supabase outage should never break local report generation).
    """
    if not is_configured():
        return None

    try:
        client = _get_client()
        sw = report["solar_wind"]
        geo = report["geomagnetic"]
        sources = report["data_sources"]

        run_row = {
            "generated_at": report["generated_at"],
            "solar_wind_plasma_source": sources.get("solar_wind_plasma"),
            "solar_wind_mag_source": sources.get("solar_wind_mag"),
            "planetary_kp_source": sources.get("planetary_kp"),
            "xray_flares_source": sources.get("xray_flares"),
            "solar_regions_source": sources.get("solar_regions"),
            "f107_flux_source": sources.get("f107_flux"),
            "ambient_speed_kms": sw.get("ambient_speed_kms"),
            "density_p_cm3": sw.get("density_p_cm3"),
            "temperature_k": sw.get("temperature_k"),
            "bt_nt": sw.get("bt_nt"),
            "bz_gsm_nt": sw.get("bz_gsm_nt"),
            "solar_wind_sample_time": sw.get("sample_time"),
            "kp_index": geo.get("kp_index"),
            "kp_estimated": geo.get("kp_estimated"),
            "kp_sample_time": geo.get("sample_time"),
        }
        run_res = client.table("report_runs").insert(run_row).execute()
        run_id = run_res.data[0]["id"]

        region_rows = []
        for r in report["top_flare_risk_regions"]:
            m = r["mcintosh_table_pct"]
            p = r["poisson_hot_region_pct"]
            n = r["noaa_official_pct"]
            b = r["blended_estimate_pct"]
            region_rows.append({
                "run_id": run_id,
                "region": r.get("region"),
                "location": r.get("location"),
                "spot_class": r.get("spot_class"),
                "mag_class": r.get("mag_class"),
                "mcintosh_c_pct": m.get("C"), "mcintosh_m_pct": m.get("M"), "mcintosh_x_pct": m.get("X"),
                "poisson_c_pct": p.get("C"), "poisson_m_pct": p.get("M"), "poisson_x_pct": p.get("X"),
                "noaa_c_pct": n.get("C"), "noaa_m_pct": n.get("M"), "noaa_x_pct": n.get("X"),
                "blended_c_pct": b.get("C"), "blended_m_pct": b.get("M"), "blended_x_pct": b.get("X"),
            })
        if region_rows:
            client.table("region_predictions").insert(region_rows).execute()

        cme_rows = []
        for c in report["recent_mx_flares_cme_arrival"]:
            a = c["arrival"]
            cme_rows.append({
                "run_id": run_id,
                "flare_class": c.get("flare_class"),
                "flare_peak_time": c.get("flare_peak_time"),
                "estimated_cme_speed_kms": c.get("estimated_cme_speed_kms"),
                "transit_hours_best": a.get("transit_hours_best"),
                "transit_hours_low": a.get("transit_hours_low"),
                "transit_hours_high": a.get("transit_hours_high"),
                "arrival_speed_kms": a.get("arrival_speed_kms"),
                "geomagnetic_outlook": c.get("geomagnetic_outlook"),
            })
        if cme_rows:
            client.table("cme_predictions").insert(cme_rows).execute()

        return run_id
    except Exception as e:
        print(f"[supabase_client] Skipped Supabase write: {e}")
        return None
