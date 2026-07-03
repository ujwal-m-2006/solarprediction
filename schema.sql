-- Solar Flare / CME Prediction — Supabase schema
-- Run this once in the Supabase SQL editor (or via `supabase db push`)
-- before the pipeline writes any data.

create table if not exists report_runs (
    id uuid primary key default gen_random_uuid(),
    generated_at timestamptz not null,
    solar_wind_plasma_source text,
    solar_wind_mag_source text,
    planetary_kp_source text,
    xray_flares_source text,
    solar_regions_source text,
    f107_flux_source text,
    ambient_speed_kms numeric,
    density_p_cm3 numeric,
    temperature_k numeric,
    bt_nt numeric,
    bz_gsm_nt numeric,
    solar_wind_sample_time timestamptz,
    kp_index numeric,
    kp_estimated numeric,
    kp_sample_time timestamptz,
    created_at timestamptz not null default now()
);

create table if not exists region_predictions (
    id uuid primary key default gen_random_uuid(),
    run_id uuid not null references report_runs(id) on delete cascade,
    region integer,
    location text,
    spot_class text,
    mag_class text,
    mcintosh_c_pct numeric,
    mcintosh_m_pct numeric,
    mcintosh_x_pct numeric,
    poisson_c_pct numeric,
    poisson_m_pct numeric,
    poisson_x_pct numeric,
    noaa_c_pct numeric,
    noaa_m_pct numeric,
    noaa_x_pct numeric,
    blended_c_pct numeric,
    blended_m_pct numeric,
    blended_x_pct numeric
);

create table if not exists cme_predictions (
    id uuid primary key default gen_random_uuid(),
    run_id uuid not null references report_runs(id) on delete cascade,
    flare_class text,
    flare_peak_time timestamptz,
    estimated_cme_speed_kms numeric,
    transit_hours_best numeric,
    transit_hours_low numeric,
    transit_hours_high numeric,
    arrival_speed_kms numeric,
    geomagnetic_outlook text
);

create index if not exists idx_region_predictions_run_id on region_predictions(run_id);
create index if not exists idx_cme_predictions_run_id on cme_predictions(run_id);
create index if not exists idx_report_runs_generated_at on report_runs(generated_at desc);

-- Row Level Security: enable and allow read-only access to anon/public.
-- Writes should go through the service_role key (used server-side by
-- src/supabase_client.py), never the anon key.
alter table report_runs enable row level security;
alter table region_predictions enable row level security;
alter table cme_predictions enable row level security;

create policy "Public read access" on report_runs for select using (true);
create policy "Public read access" on region_predictions for select using (true);
create policy "Public read access" on cme_predictions for select using (true);
