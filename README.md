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

## Available products

### C3S seasonal forecasts (CDS)

| Product | Model | Frequency | Variables | Hindcast range |
|---------|-------|-----------|-----------|----------------|
| `c3s/ecmwf` | ECMWF SEAS51 | daily | precip, temp | 1981–2016 |
| `c3s/ecmwf-monthly` | ECMWF SEAS51 | monthly | precip, temp | 1981–2016 |
| `c3s/eccc-cansips` | ECCC CanSIPS (sys 3) | monthly | precip, temp | 1981–2010 |
| `c3s/eccc-cansipsv3` | ECCC CanSIPS (sys 4) | monthly | precip, temp | 1993–2020 |
| `c3s/meteofrance` | Météo-France (sys 9) | monthly | precip, temp | 1993–2018 |
| `c3s/cmcc` | CMCC SPSv3.5 | monthly | precip, temp | 1993–2016 |
| `c3s/dwd` | DWD GCFS 2.2 (sys 22) | monthly | precip, temp | 1993–2023 |
| `c3s/dwd-gcfs21` | DWD GCFS 2.1 (sys 21) | monthly | precip, temp | 1993–2016 |
| `c3s/ukmo` | UK Met Office (sys 604) | monthly | precip, temp | 1993–2016 |
| `c3s/jma` | JMA CPS3 (sys 3) | monthly | precip, temp | 1993–2020 |
| `c3s/jma-cps2` | JMA CPS2 (sys 2) | monthly | precip, temp | 1993–2016 |

### NMME forecasts (NCEI)

Daily forecast data from NCEI. Real-time forecasts only (2018+, no hindcasts from this source).

| Product | Model | Members | Variables |
|---------|-------|---------|-----------|
| `nmme/ccsm4` | NCAR CCSM4 | 10 | precip, temp |
| `nmme/geoss2s` | NASA GEOS-S2S | 4 | precip, temp |
| `nmme/gemnemo` | CMC GEM-NEMO | 10 | precip, temp |

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

## Quick CDS setup

For products using the `cds` adapter (all `c3s/*` products and `obs/era5`):

1. Create a CDS account and API key at <https://cds.climate.copernicus.eu>.
2. Add credentials to `~/.cdsapirc`:

```bash
cat > ~/.cdsapirc << 'EOF'
url: https://cds.climate.copernicus.eu/api
key: <YOUR-API-KEY>
EOF
```

3. Accept required dataset licenses in CDS before first download.
4. Install project dependencies:

```bash
cd rosetta
uv sync
```

## Relationship to DeepScale

Rosetta handles ingestion and normalization. DeepScale handles downscaling and skill. Their interface is standardized xarray.

## Repository hygiene

`rosetta/.gitignore` excludes local-only artifacts and sensitive files (virtualenvs, caches, downloaded data, `.env*`, keys, credential JSONs). Keep secrets out of the repository.
