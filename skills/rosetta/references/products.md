# Product catalog

The catalog lives at `src/rosetta/catalog.yaml`. Enumerate at runtime with `catalog.list_products()`; inspect any entry with `catalog.info("<product>")`. Canonical variables are always `precip`, `temp`, `sst` (availability varies per product). Below is the full catalog as of v0.1.0.

## NMME seasonal models (`nmme/*`) — no credentials

| Product | Adapter | Variables | Notes |
|---|---|---|---|
| `nmme/cfsv2` | opendap (IRI DL) | precip, temp, sst | 1° global; split+append hindcast [1982-2011] / forecast [2011-now]; `member_reduce`: mean of first 24 of 28 members, re-expanded to `member=[0]` |
| `nmme/ccsm4` | ccsr | precip, temp, sst | `single_year_fetch`; native names prcp/t2m/sst |
| `nmme/cesm1` | ccsr | precip, temp, sst | |
| `nmme/geoss2s` | ccsr | precip, temp, sst | split streams; forecast M=10, hindcast M=4 |
| `nmme/spear` | ccsr | precip, temp, sst | split streams, `single_year_fetch` |
| `nmme/spearb` | ccsr | sst | |
| `nmme/cansipsic4` | ccsr | precip, temp, sst | |

Deprecated aliases (emit `DeprecationWarning`, resolve to base products): `nmme/cfsv2-forecast`, `nmme/ccsm4-iri`, `nmme/ccsm4-hindcast`, `nmme/geoss2s-forecast`, `nmme/geoss2s-hindcast`, `nmme/cesm1-hindcast`, `nmme/spear-hindcast`, `nmme/spearb-hindcast`, `nmme/cansipsic4-hindcast`.

The CCSR adapter also normalizes longitude from 0-360 to [-180, 180].

Two practical caveats from operational use:

- **Real-time vs hindcast availability differ per model and drift over time** — a model can have a full 1991-2020 hindcast but publish no current-month forecast (SPEAR in mid-2026), or a hindcast too short for a 30-year baseline (GEOSS2S ends 2017). Probe before committing a roster: `check_product(p, probe_remote=True)` or a cheap single-year fetch of the current init. CFSv2 sometimes returns a single (member-reduced) ensemble member — useless for spread-based calibration.
- **CCSR precip has been observed as monthly totals (mm), not mm/day** — check `attrs["units"]` and see the units warning in `data-conventions.md` before mixing with rate-based products.

## C3S seasonal models (`c3s/*`) — Copernicus CDS credentials (`~/.cdsapirc`)

All fetch precip/temp/sst, monthly or daily cadence via the `cds` adapter:

`c3s/ecmwf`, `c3s/ecmwf-monthly`, `c3s/eccc-cansips`, `c3s/eccc-cansipsv3`, `c3s/eccc-daily`, `c3s/meteofrance`, `c3s/meteofrance-daily`, `c3s/cmcc`, `c3s/cmcc-daily`, `c3s/cmcc-sps4`, `c3s/cmcc-sps4-daily`, `c3s/dwd`, `c3s/dwd-daily`, `c3s/dwd-gcfs21`, `c3s/ukmo`, `c3s/ukmo-daily`, `c3s/jma`, `c3s/jma-cps2`.

Notes:
- Each dataset's licence must be accepted once in the CDS web UI; a 403 error names the missing licence.
- Some entries have retired real-time streams (hindcasts still fetch; no new forecasts) — check `catalog.info(p)` for `deprecated_after` / `deprecation_note`.
- `c3s/ecmwf-seas51c` uses the **iridl** adapter (needs `~/.pycpt_dlauth`), is deprecated after 2026-04-30 with successor `c3s/ecmwf-monthly`, and carries precip/sst only.
- CDS accumulated-precip variables are deaccumulated over `lead_time` automatically (`accumulated: true` in the catalog).

## Sub-seasonal (S2S)

| Product | Adapter | Credentials | Notes |
|---|---|---|---|
| `c3s/ecmwf-s2s` | cds (ECDS endpoint `https://ecds.ecmwf.int/api`) | ECDS account — **separate from Copernicus CDS** | precip, sst; 1.5°; date-keyed via `init="YYYY-MM-DD"`; `reforecast=True` switches to the `s2s-reforecasts` collection (on-the-fly hindcasts) |

A legacy MARS adapter exists as an S2S reforecast-only fallback (needs `~/.ecmwfapirc`); it raises unless used with `reforecast=True` plus `hindcast` and `region`.

## Reanalysis (`obs/era5*`) — Copernicus CDS credentials

| Product | CDS dataset | Variables | Resolution | Range |
|---|---|---|---|---|
| `obs/era5` | reanalysis-era5-single-levels-monthly-means | temp, precip, sst | 0.25° | 1940-2025 |
| `obs/era5-land-monthly` | reanalysis-era5-land-monthly-means | precip, temp | 0.1° | 1950-2025 (no sst) |

## CHIRPS native (UCSB, `http` adapter) — no credentials, heavily rate-limited

All precip-only, 0.05°, `fill_value: -9999`:

| Product | Format | Cadence |
|---|---|---|
| `obs/chirps-v2-monthly` / `obs/chirps-v3-monthly` | COG | monthly |
| `obs/chirps-v2-daily` / `obs/chirps-v3-daily` | NetCDF | daily (**v3 daily ≈ 23.5 GiB/file** — downloaded whole, then cropped) |
| `obs/chirps-v2-pentad` / `obs/chirps-v3-pentad` | COG | pentad |
| `obs/chirps-v2-dekad` / `obs/chirps-v3-dekad` | COG | dekad |
| `obs/chirps-v2-annual` / `obs/chirps-v3-annual` | TIF | annual |

`data.chc.ucsb.edu` sits behind CrowdSec: exceeding ~2 req/s earns a **4-hour IP ban** (HTTP 403 "CrowdSec Ban"). The catalog sets `request_interval` floors (3.0 s for COG/TIF, 1.0 s for NetCDF) and `max_workers: 2` caps; for large/continental pulls raise `request_interval` further (rule of thumb: range-reads-per-file / 2 seconds). Native pentad/dekad/annual keep `mm` totals rather than `mm/day`.

## Rhiza / Sheerwater mirrors (`sheerwater` adapter, public GCS Zarr, 0.25°) — no credentials

| Product | Source | Notes |
|---|---|---|
| `obs/chirps-v3-daily-rhiza` | chirps_v3 | preferred over native v3 daily for routine use. 0.25° (coarsened from native 0.05°); archive covers ~2000 to mid-2024 — no current-season data |
| `obs/chirps-v2-dekadal-rhiza` | chirps_v2 (`agg_days: 10`) | 10-day **rolling** aggregate — NOT calendar dekads (native `obs/chirps-v2-dekad` is calendar); used by the deepscale S2S testbed |
| `obs/chirps-live-rhiza` | chirps.chirps_raw_live | 0.05°, near-real-time (~8-day lag), `recompute`/`cache_mode: write`; used by the deepscale S2S testbed. **Known issue:** upstream sheerwater removed `chirps_raw_live` (AttributeError) — see troubleshooting |
| `obs/imerg` | imerg_final | satellite precip |
| `obs/ghcn` | ghcn_avg | station-derived temp |

Sheerwater reads public GCS anonymously (a benign gcsfs "Could not determine bucket type" warning is filtered). Bbox regions become a global lazy fetch + client-side crop. The sheerwater adapter adds no cache of its own (sheerwater is already nuthatch-cached upstream).

## Catalog entry anatomy

Each variable block in a product declares:

```yaml
variables:
  precip:
    native_name: prate      # upstream name (short_name optional fallback)
    units: kg m-2 s-1       # source units
    target_units: mm/day    # canonical output units
    accumulated: true       # optional: deaccumulate over lead_time
    fill_value: -9999       # optional: masked to NaN
```

Product-level keys of interest: `adapter`, `grid`, `hindcast`/`forecast` year ranges, split-stream config, `member_reduce`, `request_interval`, `max_workers`, `alias_of`, `deprecated_after`, `successor`, `deprecation_note`, `pending_url`.
