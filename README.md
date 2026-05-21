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
| `time` | obs/reanalysis | Monthly time axis (`datetime64`) |
| `init_time` | forecasts | Initialization time (`datetime64`) |
| `lead_time` | forecasts | Lead time (numeric, units vary by source) |
| `member` | forecasts | Ensemble member index |

Numeric time encodings (e.g. "months since 1960-01-01") are automatically decoded to `datetime64`.

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
    product="obs/chirps-v2",
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

IRI Data Library (ldeo.columbia.edu) sunset in April 2026. The table below maps affected Rosetta products to their successors.

| Old product | Old source | New product | New source | Status |
|---|---|---|---|---|
| `nmme/cfsv2` | IRI DL OPeNDAP | TBD | CCSR | tracking |
| `nmme/cfsv2-forecast` | IRI DL OPeNDAP | TBD | CCSR | tracking |
| `nmme/ccsm4-iri` | IRI DL OPeNDAP | `nmme/ccsm4` | NCEI | migrated |
| `nmme/geoss2s-forecast` | IRI DL OPeNDAP | `nmme/geoss2s` | NCEI | migrated |
| `c3s/ecmwf-seas51c` | IRI DL (iridl adapter) | `c3s/ecmwf-monthly` | CDS | migrated |

Deprecated products remain in the catalog and still function while IRI URLs respond, but `rosetta.check_product()` emits a `DeprecationWarning` indicating the successor. Use `catalog.list_products(include_deprecated=False)` to exclude them.

## Available products

### C3S seasonal forecasts (CDS)

| Product | Model | Frequency | Variables | Hindcast range |
|---------|-------|-----------|-----------|----------------|
| `c3s/ecmwf` | ECMWF SEAS51 | daily | precip, temp, sst | 1981–2016 |
| `c3s/ecmwf-monthly` | ECMWF SEAS51 | monthly | precip, temp, sst | 1981–2016 |
| `c3s/eccc-cansips` | ECCC CanSIPS (sys 3) | monthly | precip, temp, sst | 1981–2010 |
| `c3s/eccc-cansipsv3` | ECCC CanSIPS (sys 4) | monthly | precip, temp, sst | 1993–2020 |
| `c3s/meteofrance` | Météo-France (sys 9) | monthly | precip, temp, sst | 1993–2018 |
| `c3s/cmcc` | CMCC SPSv3.5 | monthly | precip, temp, sst | 1993–2016 |
| `c3s/dwd` | DWD GCFS 2.2 (sys 22) | monthly | precip, temp, sst | 1993–2023 |
| `c3s/dwd-gcfs21` | DWD GCFS 2.1 (sys 21) | monthly | precip, temp, sst | 1993–2016 |
| `c3s/ukmo` | UK Met Office (sys 604) | monthly | precip, temp, sst | 1993–2016 |
| `c3s/jma` | JMA CPS3 (sys 3) | monthly | precip, temp, sst | 1993–2020 |
| `c3s/jma-cps2` | JMA CPS2 (sys 2) | monthly | precip, temp, sst | 1993–2016 |

### C3S sub-seasonal forecasts (ECDS)

| Product | Model | Frequency | Lead horizon | Variables | Endpoint |
|---------|-------|-----------|--------------|-----------|----------|
| `c3s/ecmwf-s2s` | ECMWF S2S | twice weekly (Mon/Thu) | 0–46 days | precip | ECMWF Data Store (`ecds.ecmwf.int`) |

S2S issuances are date-keyed: call with `init="YYYY-MM-DD"` (the issuance date) rather than `init="YYYY-MM"`. The catalog entry overrides `cds_url` to point at the ECMWF Data Store, which is a separate service from the Copernicus CDS — see [ECMWF Data Store (ECDS) setup](#ecmwf-data-store-ecds-setup) for credentials and licence acceptance.

### NMME forecasts (NCEI)

Daily forecast data from NCEI. Real-time forecasts only (2018+, no hindcasts from this source).

| Product | Model | Members | Variables |
|---------|-------|---------|-----------|
| `nmme/ccsm4` | NCAR CCSM4 | 10 | precip, temp, sst |
| `nmme/geoss2s` | NASA GEOS-S2S | 4 | precip, temp, sst |
| `nmme/gemnemo` | CMC GEM-NEMO | 10 | precip, temp, sst |

### NMME hindcasts (S3)

Monthly hindcast data archived from IRI Data Library to S3 (`s3://acc.ord/nmme-hindcasts/`). No IRI dependency at runtime.

| Product | Model | Members | Leads | Hindcast range |
|---------|-------|---------|-------|----------------|
| `nmme/ccsm4-hindcast` | NCAR CCSM4 | 10 | 12 | 1982–2020 |
| `nmme/geoss2s-hindcast` | NASA GEOS-S2S | 10 | 9 | 1981–2020 |
| `nmme/gemnemo-hindcast` | CMC GEM-NEMO | 10 | 12 | 1982–2020 |
| `nmme/cesm1-hindcast` | NCAR CESM1 | 10 | 12 | 1991–2020 |
| `nmme/canesm5-hindcast` | CMC CanESM5 | 20 | 12 | 1991–2020 |
| `nmme/gem52nemo-hindcast` | CMC GEM5.2-NEMO | 20 | 12 | 1991–2020 |

### NMME placeholders (pending source URL)

| Product | Model | Variables | Notes |
|---------|-------|-----------|-------|
| `nmme/spear` | GFDL SPEAR | precip, temp, sst | Awaiting GFDL THREDDS/NODD public path |
| `nmme/spear-hindcast` | GFDL SPEAR | precip, temp, sst | Awaiting GFDL THREDDS/NODD public path |
| `nmme/spearb` | GFDL SPEARb | sst | Awaiting GFDL THREDDS/NODD public path |
| `nmme/spearb-hindcast` | GFDL SPEARb | sst | Awaiting GFDL THREDDS/NODD public path |
| `nmme/cansipsic4` | CanSIPS-IC4 | precip, temp, sst | MSC Datamart GRIB2, needs cfgrib work |
| `nmme/cansipsic4-hindcast` | CanSIPS-IC4 | precip, temp | Hindcast source TBD |

### Other

| Product | Source | Frequency | Variables |
|---------|--------|-----------|-----------|
| `nmme/cfsv2` | IRI/NMME (OPeNDAP) | monthly | precip, temp |
| `c3s/ecmwf-seas51c` | IRI Data Library | monthly | precip |
| `obs/chirps` | UCSB (HTTP/COG) | monthly | precip |
| `obs/chirps-v2` | UCSB (HTTP/COG) | monthly | precip |
| `obs/era5` | CDS | monthly | temp |

Output is always NetCDF (extensible to Zarr/GeoTIFF).

Most growth should come from catalog entries and adapters, not core workflow changes. See [TODO.md](TODO.md) for planned products, storage evolution, and federated deployment roadmap.

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
