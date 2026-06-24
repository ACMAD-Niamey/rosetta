# Rosetta

**Federated data integration for climate, environmental, and contextual datasets.**

Rosetta is ACCORD's adapter layer. It provides one consistent API across heterogeneous sources while leaving data in situ at provider endpoints (CDS, OPeNDAP, HTTP/FTP, local servers, and others).

## Why this architecture

- **No new central repository:** data stays with source providers.
- **Unified API:** workflows use one interface, not provider-specific code.
- **Extensible adapters:** new datasets/providers are added without rewriting existing workflows.
- **Automatic harmonization:** names, units, coordinates, and metadata are normalized behind the API.

This supports forecasts and hindcasts, observations/reanalysis, station data, satellite/topography, and contextual predictors.

## Quickstart

```bash
git clone https://github.com/jataware/rosetta.git
cd rosetta
uv sync
```

Verify the install:

```python
import rosetta
rosetta.check_all_products()
```

For CDS-based products (`c3s/*`, `obs/era5`), you also need CDS credentials — see [CDS setup](#quick-cds-setup) below.

## Core API

```python
import rosetta

ds = rosetta.fetch(
    product="nmme/cfsv2",
    variable="precip",
    init="2025-02",
    target="MAM",
    region=[-12, 6, 28, 42],
    hindcast=(1993, 2016),
    verbose=True,
    progress=True,
)
```

### Minimal contract

- **Input:** canonical `product` and `variable`, with optional temporal/spatial selectors.
- **Output:** CF-aligned xarray, ready for downstream analysis/modeling.
- **Storage:** return in memory, or write to local path/S3.

### Normalized coordinates

All datasets are returned with canonical coordinate names regardless of the upstream source:

| Coordinate | Applies to | Description |
|------------|-----------|-------------|
| `lat`, `lon` | all products | Spatial axes (latitude ascending) |
| `time` | observations / reanalysis | Monthly time axis (`datetime64`) |
| `init_time` | forecasts | Initialization time (`datetime64`) |
| `lead_time` | forecasts | Lead time (numeric, units vary by source) |
| `member` | forecasts | Ensemble member index |

Numeric time encodings (e.g. "months since 1960-01-01") are automatically decoded to `datetime64`.

### Region input

`region` accepts three forms:

| Form | Example | Behaviour |
|------|---------|-----------|
| bbox | `region=[-12, 6, 28, 42]` | `[lat_s, lat_n, lon_w, lon_e]` |
| shapefile | `region="kenya.shp"` | bounding box slices upstream; result masked to the polygon |
| geometry | `region=gdf.geometry` | shapely geometry / geopandas `GeoSeries`, same masking |

Shapefile and geometry inputs need the `geo` extra (`pip install 'rosetta[geo]'`).
The polygon is reprojected to EPSG:4326 and dissolved, so multi-feature files
(e.g. an archipelago) clip correctly. Cells outside the polygon come back as `NaN`.

```python
import rosetta

# Clip to a country boundary — values outside Kenya become NaN.
ds = rosetta.fetch(
    product="nmme/cfsv2",
    variable="precip",
    init="2025-02",
    target="MAM",
    region="kenya.shp",
    hindcast=(1993, 2016),
)
```

**Boundary rule.** By default a grid cell is included only if its **centre**
lies inside the region (`boundary="center"` — the xarray/CDO/rasterio
convention, and unbiased for area means). Pass `boundary="cover"` to keep every
cell the region *touches*, so it's covered to its true edges (matches rasterio's
`all_touched=True`) — useful for display/masking and coarse grids, where
center-based selection can drop a country's thin tips. Applies to bbox and
shapefile/geometry inputs alike.

```python
ds = rosetta.fetch(..., region="kenya.shp", boundary="cover")
```

> **Note:** polygons that cross the ±180° antimeridian are not yet handled — the
> derived bounding box spans the full longitude range. Split such geometries at
> the antimeridian before passing them in.

## Dual-domain usage (SST + PRCP predictors)

PyCPT's seasonal forecasting workflow uses two predictor domains per GCM: a large SST domain and a regional precipitation domain. Rosetta supports this with orthogonal `fetch()` calls — one per domain.

```python
import rosetta

# SST predictor: large tropical domain
sst_predictor = rosetta.fetch(
    product="nmme/geoss2s",
    variable="sst",
    init="2025-02",
    target="MAM",
    region=[-20, 20, 30, 180],
    hindcast=(1993, 2016),
)

# PRCP predictor: regional domain
prcp_predictor = rosetta.fetch(
    product="nmme/geoss2s",
    variable="precip",
    init="2025-02",
    target="MAM",
    region=[-20, 20, 10, 75],
    hindcast=(1993, 2016),
)

# Predictand: observations
predictand = rosetta.fetch(
    product="obs/chirps-v2-monthly",
    variable="precip",
    target="MAM",
    region=[-12, 15, 22, 52],
    hindcast=(1993, 2016),
)
```

`rosetta.fetch()` is a single-call API by design — there is no `fetch_predictor_pair()` wrapper. The two domains have different extents and variables per use case.

## Data hub concept (control plane)

With a federated adapter model, the main risk is upstream drift (API changes, hosting changes, auth/license changes, schema drift). The data hub should be a lightweight **control plane** for observability:

- scheduled adapter checks
- optional live remote probes
- near-real-time status dashboard
- actionable failure logs for maintainer triage

The objective is not to centralize data. It is to centralize operational visibility so maintainers know which adapter issue to address first.

### Built-in health checks

```python
import rosetta

rosetta.check_product("nmme/cfsv2")             # config check
rosetta.check_all_products()                    # all config checks
rosetta.check_all_products(probe_remote=True)   # include live probes
```

Each result includes `product`, `adapter`, `healthy`, `kind`, `message`, and `checked_at`.

## Data source migration

The IRI Data Library (ldeo.columbia.edu) is being sunset. Most affected NMME models moved to the Columbia CCSR successor service; the table below maps the old product ids to their canonical replacements. The old ids remain as deprecated `alias_of` stubs that resolve to the new product.

| Old product(s) | Old source | New product | New source | Status |
|---|---|---|---|---|
| `nmme/ccsm4-iri`, `nmme/ccsm4-hindcast` | IRI DL / S3 | `nmme/ccsm4` | CCSR | migrated |
| `nmme/geoss2s-forecast`, `nmme/geoss2s-hindcast` | IRI DL / S3 | `nmme/geoss2s` | CCSR | migrated |
| `nmme/spear-hindcast` | IRI DL | `nmme/spear` | CCSR | migrated |
| `nmme/cansipsic4-hindcast` | IRI DL | `nmme/cansipsic4` | CCSR | migrated |
| `nmme/cesm1-hindcast` | S3 | `nmme/cesm1` | CCSR | migrated |
| `c3s/ecmwf-seas51c` | IRI DL (iridl adapter) | `c3s/ecmwf-monthly` | CDS | migrated |
| `nmme/cfsv2`, `nmme/cfsv2-forecast` | IRI DL OPeNDAP | none | stays on IRI DL | deprecated, no successor |

CFSv2 is the exception: it is being retired from NMME and is not hosted on CCSR or any other faithful source, so it stays on the IRI Data Library as a best-effort, deprecated product until that archive goes down.

Deprecated products remain in the catalog and still function while IRI URLs respond, but resolving one (via `rosetta.fetch()` or `rosetta.check_product()`) emits a `DeprecationWarning`. Use `catalog.list_products(include_deprecated=False)` to exclude them.

## Available products

> **How to read this.** **Hindcast** is each model's fixed reforecast period — *not* a fetch cap; real-time forecasts run past it to the present. **Forecast** is the live-verified real-time availability: `year–present` (ongoing) or **`start–end (retired)`** when the pinned C3S system version was superseded (hindcasts still fetch; no new forecasts issue). **Members (F/H)** are the real-time-forecast and reforecast ensemble sizes (they differ). `†` marks a deprecated access route. Full field conventions are documented at the top of [`src/rosetta/catalog.yaml`](src/rosetta/catalog.yaml). Deprecation aliases are omitted.

> ⚠ **Retired-system entries.** Several C3S entries pin a `system` version whose real-time stream has ended (live-verified — a 2026 forecast init returns no data). They still fetch hindcasts, but **CMCC, JMA, and UKMO currently have no active-forecast entry** — adding entries on their current systems (CMCC SPS4, JMA CPS4, UKMO 605) is a tracked follow-up.

### Seasonal forecast · NMME

| Product | Model / system | Host | Adapter | Variables | Cadence | Members (F/H) | Hindcast | Forecast |
|---|---|---|---|---|---|---|---|---|
| `nmme/cansipsic4` | ECCC CanSIPS-IC4 | Columbia CCSR | `ccsr` | precip, temp, sst | monthly | 40 / 40 | 1990–2024 | 2024–present |
| `nmme/ccsm4` | NCAR/COLA CCSM4 | Columbia CCSR | `ccsr` | precip, temp, sst | monthly | 10 / 10 | 1982–2026 | 2014–present |
| `nmme/cesm1` | NCAR CESM1 | Columbia CCSR | `ccsr` | precip, temp, sst | monthly | 10 / 10 | 1982–2026 | 2017–present |
| `nmme/geoss2s` | NASA GEOS-S2S | Columbia CCSR | `ccsr` | precip, temp, sst | monthly | 4 / 4 | 1981–2017 | 2019–present |
| `nmme/spear` | GFDL SPEAR | Columbia CCSR | `ccsr` | precip, temp, sst | monthly | 15 / 15 | 1991–2020 | 2021–present |
| `nmme/spearb` | GFDL SPEARb | Columbia CCSR | `ccsr` | sst | monthly | 15 / 15 | 1991–2020 | 2021–present |
| `nmme/cfsv2` † | NCEP CFSv2 | IRI Data Library | `opendap` | precip, temp, sst | monthly | 28 / 28 | 1982–2010 | 2011–present |

### Seasonal forecast · C3S

| Product | Model / system | Host | Adapter | Variables | Cadence | Members (F/H) | Hindcast | Forecast |
|---|---|---|---|---|---|---|---|---|
| `c3s/cmcc` | CMCC SPSv3.5 (sys 35) | Copernicus CDS | `cds` | precip, temp, sst | monthly | 50 / 40 | 1993–2016 | **2020–2025 (retired)** |
| `c3s/cmcc-daily` | CMCC SPSv3.5 (sys 35) | Copernicus CDS | `cds` | precip, temp, sst | daily | 50 / 40 | 1993–2016 | **2020–2025 (retired)** |
| `c3s/dwd` | DWD GCFS2.2 (sys 22) | Copernicus CDS | `cds` | precip, temp, sst | monthly | 50 / 30 | 1993–2023 | 2023–present |
| `c3s/dwd-daily` | DWD GCFS2.2 (sys 22) | Copernicus CDS | `cds` | precip, temp, sst | daily | 50 / 30 | 1993–2023 | 2023–present |
| `c3s/dwd-gcfs21` | DWD GCFS2.1 (sys 21) | Copernicus CDS | `cds` | precip, temp, sst | monthly | 50 / 30 | 1993–2019 | **2020–2025 (retired)** |
| `c3s/eccc-cansips` | ECCC GEM5-NEMO (sys 3) | Copernicus CDS | `cds` | precip, temp, sst | monthly | 10 / 10 | 1990–2020 | **2021–2024 (retired)** |
| `c3s/eccc-cansipsv3` | ECCC CanESM5.1 (sys 4) | Copernicus CDS | `cds` | precip, temp, sst | monthly | 20 / 20 | 1980–2023 | 2024–present |
| `c3s/eccc-daily` | ECCC CanESM5.1 (sys 4) | Copernicus CDS | `cds` | precip, temp, sst | daily | 20 / 20 | 1980–2023 | 2024–present |
| `c3s/ecmwf` | ECMWF SEAS5 (sys 51) | Copernicus CDS | `cds` | precip, temp, sst | monthly | 51 / 25 | 1981–2016 | 2017–present |
| `c3s/ecmwf-monthly` | ECMWF SEAS5 (sys 51) | Copernicus CDS | `cds` | precip, temp, sst | monthly | 51 / 25 | 1981–2016 | 2017–present |
| `c3s/jma` | JMA CPS3 (sys 3) | Copernicus CDS | `cds` | precip, temp, sst | monthly | 155 / 10 | 1991–2020 | **2022–2026 (retired)** |
| `c3s/jma-cps2` | JMA CPS2 (sys 2) | Copernicus CDS | `cds` | precip, temp, sst | monthly | 13 / 10 | 1981–2016 | **2015–2022 (retired)** |
| `c3s/meteofrance` | Météo-France Sys 9 | Copernicus CDS | `cds` | precip, temp, sst | monthly | 51 / 31 | 1993–2024 | 2025–present |
| `c3s/meteofrance-daily` | Météo-France Sys 9 | Copernicus CDS | `cds` | precip, temp, sst | daily | 51 / 31 | 1993–2024 | 2025–present |
| `c3s/ukmo` | UKMO GloSea6 GC3.2 (sys 604) | Copernicus CDS | `cds` | precip, temp, sst | monthly | 62 / 28 | 1993–2016 | **2025–2026 (retired)** |
| `c3s/ukmo-daily` | UKMO GloSea6 GC3.2 (sys 604) | Copernicus CDS | `cds` | precip, temp, sst | daily | 7 / 7 | 1993–2016 | **2025–2026 (retired)** |
| `c3s/ecmwf-seas51c` † | — | IRI Data Library | `iridl` | precip, sst | monthly | 51 / 25 | 1993–2016 | — |

### Sub-seasonal forecast

| Product | Model / system | Host | Adapter | Variables | Cadence | Members (F/H) | Hindcast | Forecast |
|---|---|---|---|---|---|---|---|---|
| `c3s/ecmwf-s2s` | ECMWF S2S | ECMWF Data Store | `cds` | precip, sst | twice weekly | 50 / 11 | — | on-the-fly |

`c3s/ecmwf-s2s` is date-keyed — call with `init="YYYY-MM-DD"` (issuance date); its reforecasts are generated on-the-fly, so there is no fixed hindcast window. It uses the ECMWF Data Store (`ecds.ecmwf.int`), a separate service — see [ECMWF Data Store (ECDS) setup](#ecmwf-data-store-ecds-setup).

### Reanalysis

| Product | Model / system | Host | Adapter | Variables | Cadence | Members (F/H) | Hindcast | Forecast |
|---|---|---|---|---|---|---|---|---|
| `obs/era5` | — | Copernicus CDS | `cds` | temp, precip, sst | monthly | — | 1940–2025 | — |
| `obs/era5-land-monthly` | — | Copernicus CDS | `cds` | precip, temp | monthly | — | 1950–2025 | — |

### Observation

| Product | Model / system | Host | Adapter | Variables | Cadence | Members (F/H) | Hindcast | Forecast |
|---|---|---|---|---|---|---|---|---|
| `obs/chirps-live-rhiza` | — | Rhiza/Sheerwater | `sheerwater` | precip | daily | — | — | — |
| `obs/chirps-v2-annual` | — | UCSB CHC | `http` | precip | annual | — | 1981–2024 | — |
| `obs/chirps-v2-daily` | — | UCSB CHC | `http` | precip | daily | — | 1981–2025 | — |
| `obs/chirps-v2-dekad` | — | UCSB CHC | `http` | precip | dekad | — | 1981–2025 | — |
| `obs/chirps-v2-dekadal-rhiza` | — | Rhiza/Sheerwater | `sheerwater` | precip | dekadal-rolling | — | 1997–2024 | — |
| `obs/chirps-v2-monthly` | — | UCSB CHC | `http` | precip | monthly | — | 1981–2025 | — |
| `obs/chirps-v2-pentad` | — | UCSB CHC | `http` | precip | pentad | — | 1981–2025 | — |
| `obs/chirps-v3-annual` | — | UCSB CHC | `http` | precip | annual | — | 1981–2025 | — |
| `obs/chirps-v3-daily` | — | UCSB CHC | `http` | precip | daily | — | 1998–2025 | — |
| `obs/chirps-v3-daily-rhiza` | — | Rhiza/Sheerwater | `sheerwater` | precip | daily | — | 2000–2024 | — |
| `obs/chirps-v3-dekad` | — | UCSB CHC | `http` | precip | dekad | — | 1981–2025 | — |
| `obs/chirps-v3-monthly` | — | UCSB CHC | `http` | precip | monthly | — | 1981–2025 | — |
| `obs/chirps-v3-pentad` | — | UCSB CHC | `http` | precip | pentad | — | 1981–2025 | — |
| `obs/ghcn` | — | Rhiza/Sheerwater | `sheerwater` | precip | monthly | — | 1981–2024 | — |
| `obs/imerg` | — | Rhiza/Sheerwater | `sheerwater` | precip | monthly | — | 2000–2024 | — |

> **`nmme/cfsv2` †:** the *model* is still an active NMME member (live on CPC FTP) — only its IRI Data Library access route is deprecated (IRIDL shutdown ~Oct 2026), with no successor yet. `nmme/cfsv2-forecast` and the various `*-hindcast` ids remain as deprecated aliases.

Output is always NetCDF (extensible to Zarr/GeoTIFF).

Most growth should come from catalog entries and adapters, not core workflow changes. Planned products, storage evolution, and the federated deployment roadmap are tracked as GitHub issues.

## CDS / ECDS setup

Rosetta's `cds` adapter talks to two distinct ECMWF endpoints:

- **Copernicus Climate Data Store** (`cds.climate.copernicus.eu`) — most `c3s/*` products and `obs/era5`.
- **ECMWF Data Store** (`ecds.ecmwf.int`) — newer service, currently used by `c3s/ecmwf-s2s` (sub-seasonal forecasts) and likely future S2S/TIGGE products.

They are separate services with separate accounts, separate API keys, and separate licence-acceptance flows. The catalog entry per product specifies which endpoint to use via a `cds_url` override; you need credentials and accepted licences for each endpoint you intend to fetch from.

### Copernicus CDS setup

For Copernicus CDS products (all `c3s/*` except `c3s/ecmwf-s2s`, plus `obs/era5`):

1. Create a CDS account and API key at <https://cds.climate.copernicus.eu>.
2. Add credentials to `~/.cdsapirc`:

   ```bash
   cat > ~/.cdsapirc << 'EOF'
   url: https://cds.climate.copernicus.eu/api
   key: <YOUR-CDS-API-KEY>
   EOF
   ```

3. **Accept required dataset licences** in the CDS web UI before your first download. Each dataset page has a "Terms of use" section near the bottom of the page; you must tick the boxes there once per account. If `rosetta.fetch()` fails with a 403, the error message names the specific dataset(s) missing acceptance.

### ECMWF Data Store (ECDS) setup

Required for `c3s/ecmwf-s2s` (and any future product whose catalog entry has `cds_url: "https://ecds.ecmwf.int/api"`). ECDS is a separate service from the Copernicus CDS — you cannot reuse Copernicus CDS credentials.

1. Create an ECMWF account at <https://www.ecmwf.int/> if you don't have one. Log in to <https://ecds.ecmwf.int/> and retrieve your API key from your profile/account settings (the link appears in the top-right after login).

2. Configure `cdsapi` to use the ECDS endpoint. The simplest setup, if you only use ECDS, is to replace `~/.cdsapirc`:

   ```bash
   cat > ~/.cdsapirc << 'EOF'
   url: https://ecds.ecmwf.int/api
   key: <YOUR-ECDS-API-KEY>
   EOF
   ```

   If you also use the Copernicus CDS, maintain both endpoints — for example by keeping the Copernicus CDS in `~/.cdsapirc` and passing the ECDS URL+key explicitly via the `CDSAPI_URL` / `CDSAPI_KEY` environment variables, or by switching `~/.cdsapirc` per session.

3. **Accept the two layers of ECDS licences.** ECDS rejects requests with HTTP 403 until both are accepted:

   a. **Site-wide Terms of Use.** Required once per account. Accepted from the ECDS profile/settings UI after login. The current revision (as of mid-2026) is **"Terms of use of the ECMWF Data Store (rev. 12)"**.

   b. **Dataset-specific licence.** Each dataset has an additional licence that must be ticked on the dataset's own page. For S2S, that page is:

      <https://ecds.ecmwf.int/datasets/s2s-forecasts?tab=download#manage-licences>

      Tick every licence listed in the "Manage licences" section. The pattern for other datasets is the same: `https://ecds.ecmwf.int/datasets/<dataset-id>?tab=download#manage-licences`.

   If you skip step 3, the first `fetch()` will fail with a 403 and a message naming exactly which licence(s) are missing and linking to the manage-licences page — so this is easy to fix iteratively.

4. Test the connection:

   ```bash
   uv run pytest tests/test_integration.py::test_fetch_c3s_ecmwf_s2s_precip -v
   ```

> **Heads up — ECDS is in transitional beta.** Both the old WEB-API and the new CDS-API are available to S2S/TIGGE users for a limited time as ECMWF migrates from the old Public Datasets service. Rosetta's CDS adapter uses the new CDS-API path. See <https://confluence.ecmwf.int/x/-wUiEw> for ECMWF's migration notes.

### Install dependencies

```bash
cd rosetta
uv sync
```

## Cache configuration

Rosetta caches adapter downloads locally using [Nuthatch](https://github.com/rhiza-research/nuthatch). Cache files live in `~/.nuthatch/rosetta` by default (configured in `pyproject.toml`).

**Inspect the cache:**
```bash
rosetta cache list
```

**Clear the cache:**
```bash
rosetta cache clear          # clears all
rosetta cache clear --product nmme/cfsv2  # clears one product (with confirmation)
```

> **V2:** A public read-only shared cache mirror is planned for V2. V1 is local-only.

## Relationship to DeepScale

Rosetta handles ingestion and normalization. DeepScale handles downscaling and skill. Their interface is standardized xarray.

## Repository hygiene

`rosetta/.gitignore` excludes local-only artifacts and sensitive files (virtualenvs, caches, downloaded data, `.env*`, keys, credential JSONs). Keep secrets out of the repository.
