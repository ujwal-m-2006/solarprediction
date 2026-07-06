# Solar Flare / CME Prediction

Pulls live data from NOAA's Space Weather Prediction Center (SWPC) and
runs two physics-grounded models to produce a same-day space-weather
outlook: which active regions are most likely to flare in the next 24h,
and — for recent M/X flares — roughly when an associated CME would reach
Earth and what geomagnetic response to expect.

This is not a black-box ML model. Both components are the same class of
model operational forecasters actually use, with published sources noted
below.

## What it pulls (live, NOAA SWPC)

| Dataset | Endpoint |
|---|---|
| Real-time solar wind plasma (speed/density/temp) | `services.swpc.noaa.gov/json/rtsw/rtsw_wind_1m.json` |
| Real-time IMF (Bt, Bz) | `services.swpc.noaa.gov/json/rtsw/rtsw_mag_1m.json` |
| Planetary Kp index | `services.swpc.noaa.gov/json/planetary_k_index_1m.json` |
| GOES X-ray flare events (7-day) | `services.swpc.noaa.gov/json/goes/primary/xray-flares-7-day.json` |
| Solar region summary (McIntosh/Mount Wilson class, NOAA's own flare probabilities) | `services.swpc.noaa.gov/json/solar_regions.json` |
| F10.7 cm solar radio flux | `services.swpc.noaa.gov/json/f107_cm_flux.json` |

Every dataset has a bundled fallback snapshot in `data/` (captured live on
2026-07-03) so the pipeline still runs if outbound network is unavailable.
`outputs/report.json` records, per run, whether each dataset was `live` or
`fallback`.

## The two models

**1. Flare probability (`src/flare_probability.py`)** — for each active
region, blends three signals:
- A McIntosh-classification + Mount Wilson magnetic-class lookup table
  (bigger/more complex spot groups with delta fields flare far more
  often — the same *shape* of table NOAA forecasters have historically
  used). This is a defensible approximation, not a peer-reviewed table —
  treat it as a cross-check.
- NOAA's own issued c/m/x_flare_probability for the region, surfaced
  directly for comparison.
- A Poisson "hot region" term using the region's flares-in-the-last-24h
  count, which reacts faster than the McIntosh table to a region that
  just became active.

**2. CME Earth-arrival time (`src/drag_based_model.py`)** — the analytic
Drag-Based Model of Vršnak et al. (2013, *Solar Physics* 285), the same
physics underlying NOAA/ESA's operational CME-arrival tools. Solves
`dv/dt = -γ(v-w)|v-w|` in closed form for transit time to 1 AU, sweeping
γ across its typical operational range (1×10⁻⁸ to 5×10⁻⁸ km⁻¹) to produce
a low/best/high arrival window instead of a single number.

CME initial speed isn't measured here (no live coronagraph/DONKI feed was
reachable from this environment) — it's estimated from the flare's GOES
class using published CDAW-catalog statistics (Yashiro et al. 2004; Bein
et al. 2012). This is clearly labeled as an estimate in the report output,
not presented as a measurement.

## Run it

```bash
pip install -r requirements.txt
python3 src/report.py
```

Outputs land in `outputs/`:
- `report.json` — full structured data
- `report.txt` — human-readable summary
- `flare_probability_by_region.png`
- `cme_arrival_timeline.png`

Open `index.html` (served over HTTP, not `file://` — e.g. `python3 -m http.server`)
for a live dashboard view of the same data.

## Supabase (optional)

Every run can also be persisted to Supabase for history/trend tracking.
This is entirely optional — with no credentials set, `report.py` runs
exactly as above and just skips the remote save.

1. Create a project at [supabase.com](https://supabase.com).
2. Run `schema.sql` in the Supabase SQL editor (creates `report_runs`,
   `region_predictions`, `cme_predictions`, with RLS enabled and
   public read-only policies).
3. Copy `.env.example` to `.env` and fill in `SUPABASE_URL` and
   `SUPABASE_KEY` (use the **service_role** key — writes happen
   server-side from this machine).
4. `python3 src/report.py` — you'll see `Saved to Supabase: report_runs.id=...`
   instead of the skip message.

## Aditya-L1 (ISRO) independent cross-validation (optional)

ISRO's Aditya-L1 solar observatory (at the Sun-Earth L1 point, same
vantage point as the NOAA/NASA spacecraft above) carries **SoLEXS**, a
soft X-ray spectrometer covering the same band GOES XRS uses to classify
flares — but on a completely different satellite in a completely
different orbit. `src/pradan_client.py` downloads real SoLEXS Level-1
data and flags which GOES-detected flares that day show a matching
SoLEXS count-rate enhancement, as genuine independent confirmation
rather than another mirror of the same NOAA measurement.

Note on naming: the correct ISRO source here is **PRADAN**
(`pradan1.issdc.gov.in`), run by ISSDC. NRSC (National Remote Sensing
Centre) is ISRO's *land* remote-sensing center (Bhuvan, Cartosat/
Resourcesat imagery) and doesn't publish solar or space-weather data at
all — there's nothing from NRSC to integrate for this project.

Setup (optional — everything above works without it):
1. Register at [pradan.issdc.gov.in](https://pradan.issdc.gov.in).
2. Add `PRADAN_USERNAME` and `PRADAN_PASSWORD` to `.env`.
3. `python3 src/report.py` — the report and dashboard will show an
   "Aditya-L1 Independent Cross-Validation" section.

Two things worth knowing about this data:
- **Not real-time.** Level-1 products have a multi-day processing
  latency (observed: ~3 days) — this validates recent history, not
  today.
- **Proxy, not calibrated flux.** The confirmation check compares raw
  SoLEXS total count rate against that day's median (>3x = "enhanced"),
  not a calibrated flux-to-GOES-class conversion. In testing this
  reliably caught every M-class flare and the day's largest C-class
  flare, but missed smaller C-class events below its detection floor —
  a real, physically-expected instrument sensitivity limit, not a bug.

## Honest limitations

- No model can predict the exact moment a region will flare — these are
  probabilities, not timestamps.
- Storm severity depends heavily on IMF Bz (northward vs. southward),
  which is only reliably knowable once a CME's sheath/ejecta reaches the
  L1 point, roughly 30-60 minutes before Earth impact. This is a physical
  limit of the observing geometry, not a gap in the model.
- CME speed is inferred from flare class, not measured — treat transit
  times as order-of-magnitude, not precise forecasts.
- NOAA's real-time solar wind feed can return HTTP 200 with data that's
  hours stale during spacecraft/ground-station gaps — `report.py` checks
  the payload's own timestamp against wall-clock time and flags this as
  `stale` when it happens, rather than trusting a successful HTTP response.
