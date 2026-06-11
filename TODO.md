# Rosetta — TODO

Tracks planned work beyond v0. Organized roughly by priority.

## New products and catalog expansion

Current catalog covers `nmme/cfsv2`, `c3s/ecmwf`, `c3s/ecmwf-monthly`, the `obs/chirps-{v2,v3}-{cadence}` family, `obs/era5`.

### GCM / forecast products to add

- [ ] `nmme/geos_s2s` — NASA GEOS-S2S via OPeNDAP
- [ ] `nmme/cmc1` / `nmme/cmc2` — Canadian seasonal models
- [ ] `nmme/gfdl` — GFDL seasonal forecasts
- [ ] `c3s/meteo_france` — Météo-France System 8 via CDS
- [ ] `c3s/ukmo` — UK Met Office GloSea6 via CDS
- [ ] `c3s/dwd` — DWD seasonal system via CDS
- [ ] `c3s/cmcc` — CMCC seasonal system via CDS
- [ ] `c3s/eccc` — ECCC seasonal system via CDS
- [ ] `c3s/jma` — JMA seasonal system via CDS
- [ ] AI-based forecast products (e.g., GraphCast, Pangu-Weather) as they become available via hosted APIs

### Observation / reanalysis products to add

- [x] `obs/era5-land-monthly` — ERA5-Land higher-resolution (0.1°) monthly reanalysis (done 2026-06-11; precip+temp; daily/hourly cadences are separate CDS datasets, future entries)
- [x] `obs/chirps-{v2,v3}-daily` — daily CHIRPS (done 2026-06-10; pentad/dekad/annual added too)
- [ ] `obs/cpc` — CPC global temperature and precipitation
- [ ] `obs/gpcc` — GPCC precipitation
- [ ] `obs/mswep` — Multi-Source Weighted-Ensemble Precipitation

### Predictor / contextual data

- [ ] `pred/enso` — Nino 3.4 index (NOAA)
- [ ] `pred/iod` — Indian Ocean Dipole index
- [ ] `pred/mjo` — MJO phase indices
- [ ] Topography / elevation datasets (SRTM, GMTED2010)
- [ ] Land cover / land use
- [ ] Socio-economic indicators (population density, agriculture masks)

### Station data

- [ ] Adapter for station-based observation networks (national met service APIs, GHCN)
- [ ] Design decision: how station data fits the current xarray grid contract (point vs gridded)

## New adapter types

- [ ] **Earthdata adapter** — NASA Earthdata / CMR for satellite products
- [ ] **Ingrid adapter** — IRI Data Library Ingrid queries (beyond simple OPeNDAP)
- [ ] **Station adapter** — point observation networks (CSV/API -> xarray with station dim)
- [ ] **Local file adapter** — user points Rosetta at local NetCDF/GRIB files, gets normalized output

## Storage layer evolution

Current: NetCDF only (`ds.to_netcdf()`).

- [ ] **Zarr output support** — add `format="zarr"` to `storage.save()`. Useful when outputs are stored in cloud buckets (S3/GCS) and consumers want partial reads without downloading the whole file.
- [ ] **Icechunk integration** — versioned Zarr store with transactional writes, time-travel, and lineage tracking. Natural fit for the data hub control plane (know exactly which version of each dataset fed into which forecast). Worth adopting when operational pipelines need reproducibility and rollback.
- [ ] **GeoTIFF output** — for interop with GIS tools and non-Python consumers.

Recommendation: Zarr is the next step when cloud storage becomes a real deployment target. Icechunk follows when the data hub needs versioning.

## Federated deployment model

The current architecture assumes Rosetta runs on a single user's machine. For operational use at NMHSs:

- [ ] **Remote Rosetta nodes** — a meteorological organization runs a Rosetta instance on their own infrastructure. It fetches data from providers, normalizes it, and serves it locally (or to a regional cache/store). This avoids every analyst independently downloading the same large datasets over slow connections.
- [ ] **Shared storage backend** — Rosetta writes to a shared Zarr/Icechunk store (on-prem or cloud) that multiple users and tools read from. Eliminates redundant downloads and ensures everyone works from the same normalized data.
- [ ] **Lightweight fetch server** — thin HTTP API in front of `rosetta.fetch()` so downstream tools can request data without importing Rosetta directly. Could be as simple as a FastAPI wrapper.
- [ ] **Caching layer** — smart cache that knows when upstream data has been updated vs when a cached copy is still valid. Avoids unnecessary re-fetches while ensuring freshness.
- [ ] **Auth/credential management** — centralize CDS/Earthdata credentials at the node level so individual users don't each need their own API keys for shared infrastructure.

## Data hub / control plane

- [ ] **Dashboard** — web-based status page showing adapter health (builds on `check_all_products(probe_remote=True)`). Red/yellow/green per product.
- [ ] **Scheduled probes** — cron or similar to run health checks on a schedule and persist results.
- [ ] **Alerting** — notify maintainers when an adapter breaks (email, Slack, webhook).
- [ ] **Provenance tracking** — record which adapter version, catalog entry, and source URL produced each output dataset.

## Code quality / testing

- [ ] Integration test suite that runs against live endpoints (gated behind `@pytest.mark.integration`)
- [ ] Mock adapter for unit tests that don't need network
- [ ] CI pipeline with the mock tests running on every commit
