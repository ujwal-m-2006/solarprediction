"""
Main entry point. Run with:  python3 src/report.py

Pulls live NOAA data (falls back to bundled snapshots if offline), runs
the flare-probability and CME drag-based-arrival models, writes:
  outputs/report.json              - full structured data
  outputs/report.txt               - human-readable summary
  outputs/flare_probability_by_region.png
  outputs/cme_arrival_timeline.png
"""
import json
import os

import model
import visualize
import supabase_client

OUTPUT_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "outputs")


def format_text_report(report):
    lines = []
    lines.append("=" * 70)
    lines.append("SOLAR FLARE / CME PREDICTION REPORT")
    lines.append(f"Generated: {report['generated_at']}")
    lines.append("=" * 70)

    lines.append("\nDATA PROVENANCE")
    for name, source in report["data_sources"].items():
        lines.append(f"  {name:20s} {source}")

    sw = report["solar_wind"]
    lines.append("\nCURRENT SOLAR WIND (L1, near-Earth)")
    lines.append(f"  Speed:        {sw['ambient_speed_kms']} km/s")
    lines.append(f"  Density:      {sw['density_p_cm3']} p/cm3")
    lines.append(f"  Temperature:  {sw['temperature_k']} K")
    lines.append(f"  IMF Bt:       {sw['bt_nt']} nT")
    lines.append(f"  IMF Bz (GSM): {sw['bz_gsm_nt']} nT")
    lines.append(f"  Sample time:  {sw['sample_time']}")

    geo = report["geomagnetic"]
    lines.append("\nGEOMAGNETIC STATE")
    lines.append(f"  Planetary Kp: {geo['kp_index']} (estimated {geo['kp_estimated']})")
    lines.append(f"  Sample time:  {geo['sample_time']}")

    lines.append("\nTOP FLARE-RISK ACTIVE REGIONS (next 24h)")
    lines.append(f"  {'Region':8s} {'Loc':8s} {'McIntosh':10s} {'Mag':6s} "
                  f"{'C%':>6s} {'M%':>6s} {'X%':>6s}  (blended vs NOAA official)")
    for r in report["top_flare_risk_regions"]:
        b = r["blended_estimate_pct"]
        n = r["noaa_official_pct"]
        spot_class = r["spot_class"] or "?"
        mag_class = r["mag_class"] or "?"
        lines.append(
            f"  AR{r['region']:<6d} {r['location']:8s} {spot_class:10s} {mag_class:6s} "
            f"{b['C']:>5.1f}% {b['M']:>5.1f}% {b['X']:>5.1f}%   "
            f"(NOAA: C{n['C']}% M{n['M']}% X{n['X']}%)"
        )

    lines.append("\nRECENT M/X FLARES -> ESTIMATED CME EARTH-ARRIVAL")
    for c in report["recent_mx_flares_cme_arrival"]:
        a = c["arrival"]
        if a.get("transit_hours_best") is None:
            lines.append(f"  {c['flare_class']:6s} @ {c['flare_peak_time']}: "
                          f"CME too slow relative to ambient wind - {a.get('note', '')}")
            continue
        lines.append(
            f"  {c['flare_class']:6s} @ {c['flare_peak_time']}  "
            f"est. CME v0={c['estimated_cme_speed_kms']:.0f} km/s -> "
            f"arrival in {a['transit_hours_best']:.0f}h "
            f"[{a['transit_hours_low']:.0f}-{a['transit_hours_high']:.0f}h], "
            f"arrival speed ~{a['arrival_speed_kms']:.0f} km/s"
        )
        lines.append(f"         Outlook: {c['geomagnetic_outlook']}")

    lines.append("\nLIMITATIONS")
    lines.append("  - CME initial speed is estimated from flare GOES class (CDAW-catalog")
    lines.append("    statistics), not measured by coronagraph -- treat transit times as")
    lines.append("    order-of-magnitude, not precise forecasts.")
    lines.append("  - No model can predict the exact moment a region will flare.")
    lines.append("  - Storm severity depends heavily on IMF Bz, which is only reliably")
    lines.append("    knowable once a CME sheath reaches L1, ~30-60 min before Earth impact.")
    lines.append("=" * 70)
    return "\n".join(lines)


def main():
    os.makedirs(OUTPUT_DIR, exist_ok=True)
    report = model.build_report()

    json_path = os.path.join(OUTPUT_DIR, "report.json")
    with open(json_path, "w") as f:
        json.dump(report, f, indent=2, default=str)

    text = format_text_report(report)
    txt_path = os.path.join(OUTPUT_DIR, "report.txt")
    with open(txt_path, "w") as f:
        f.write(text)

    chart1 = visualize.plot_flare_probabilities(report["top_flare_risk_regions"])
    chart2 = visualize.plot_cme_arrival_timeline(report["recent_mx_flares_cme_arrival"])

    run_id = supabase_client.save_report(report)

    print(text)
    print(f"\nWritten: {json_path}")
    print(f"Written: {txt_path}")
    print(f"Written: {chart1}")
    if chart2:
        print(f"Written: {chart2}")
    if run_id:
        print(f"Saved to Supabase: report_runs.id={run_id}")
    else:
        print("Supabase not configured (SUPABASE_URL/SUPABASE_KEY unset) - skipped remote save.")


if __name__ == "__main__":
    main()
