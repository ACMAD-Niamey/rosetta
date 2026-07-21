# Troubleshooting

## Credentials setup

### Copernicus CDS (`c3s/*` except s2s, `obs/era5*`)

`~/.cdsapirc`:
```
url: https://cds.climate.copernicus.eu/api
key: <your-key>
```
Then accept each dataset's licence once in the CDS web UI (a 403 error names the missing dataset licence). Rosetta creates the cdsapi client with `retry_max=12, sleep_max=30, timeout=60` — cdsapi's defaults (500 retries / 120 s sleep) would hide real errors behind ~17 hours of retrying.

### ECMWF Data Store / ECDS (`c3s/ecmwf-s2s`)

A **separate** service from Copernicus CDS — CDS credentials do not work. Create an ECDS account, then point credentials at `https://ecds.ecmwf.int/api` via `~/.cdsapirc` or the `CDSAPI_URL`/`CDSAPI_KEY` env vars. Two licence layers must be accepted: the site-wide Terms of Use and the per-dataset licence.

### IRI Data Library (`c3s/ecmwf-seas51c`, iridl adapter)

Needs `~/.pycpt_dlauth` — create an IRI account and run `cptdl.setup_dlauth("<email>")`. A missing file raises `FileNotFoundError`; an HTML response means auth failed. Rosetta writes a temporary `~/.dodsrc`. IRIDL is expected to sunset around Oct 2026 (`c3s/ecmwf-seas51c` is deprecated after 2026-04-30; successor `c3s/ecmwf-monthly`).

### ECMWF legacy MARS (S2S reforecast fallback)

Needs `~/.ecmwfapirc`. The adapter raises unless called with `reforecast=True` and both `hindcast` and `region`.

### S3 products

The s3 adapter shells out to the **AWS CLI** (`aws s3 ls/cp`) — configure `aws` itself; boto3 is not used for fetching (the `[s3]` extra's boto3 is only for icechunk profile handling and s3fs saving).

## Common errors

| Symptom | Cause / fix |
|---|---|
| 403 from CDS naming a dataset | Licence not accepted — accept it in the CDS web UI |
| HTTP 403 "CrowdSec Ban" from data.chc.ucsb.edu | CHIRPS rate limit tripped; IP banned ~4 h. Raise `request_interval`, reduce parallelism, or switch to `obs/chirps-*-rhiza` mirrors |
| `RuntimeError: N/M file(s) failed; refusing to return partial data` | Default `allow_partial=False`; pass `allow_partial=True` for best-effort, or retry |
| `ValueError` on `region=` | Product is non-gridded (no lat/lon dims) — spatial subset impossible |
| `ImportError` mentioning `accord-rosetta[geo]` | Shapefile/geometry region needs the `geo` extra (geopandas, rasterio) |
| `NotImplementedError` from `seasonal="mean"` | Wraparound season (NDJ/DJF) not supported by seasonal averaging |
| `ValueError`: `grid_res` and `regrid_to` | Mutually exclusive; `grid_res` also requires `region` |
| `KeyError` from `catalog.info` | Unknown product id — check `catalog.list_products()` |
| `DeprecationWarning` on fetch | Product is an alias or date-deprecated — see `catalog.info(p)` for `successor` |
| 401 / interactive auth prompt / fsspec `Protocol not known` touching `gs://sheerwater-datalake/...` | Ambient nuthatch config shadowing — see below |
| GRIB decode errors | MARS/S2S need `cfgrib` + `eccodeslib` (installed by default); rosetta uses `decode_timedelta=False` to avoid an xarray non-nanosecond-timedelta assertion |

## Cache issues

- Cache root: `~/.nuthatch/caches` (override with `ROSETTA_CACHE_DIR` **before importing rosetta**; power users: `NUTHATCH_ROOT_FILESYSTEM` / `NUTHATCH_LOCAL_FILESYSTEM`, which rosetta only `setdefault`s). Scratch downloads: `~/.nuthatch/rosetta/_tmp` (`ROSETTA_TMP_DIR`) — deliberately not the system tempdir, because macOS reaps `/var/folders/.../T/` and breaks pickled lazy datasets.
- Cache key: `(product, variable, date_range, region-bbox, init_months, init_date)` under namespace `rosetta`, versioned by `_CACHE_VERSION` (currently 5). A version bump invalidates all cached entries. Polygon geometries never enter the key.
- `cache=False` bypasses nuthatch entirely (straight to adapter).
- Inspect / clear: `rosetta cache list`, `rosetta cache clear [--product X] [--yes]` (wraps `python -m nuthatch list/delete --namespace rosetta`).
- **Sheerwater shadowing gotcha:** when `sheerwater` is co-installed, nuthatch's upward config search can escape `site-packages/rosetta/` and adopt sheerwater's `nuthatch.toml`, which points the cache root at a private GCS bucket (`gs://sheerwater-datalake/...`) → 401s or fsspec crashes for users without those credentials. Rosetta defends twice: it ships a shadow `src/rosetta/nuthatch.toml` (`filesystem = "file://~/.nuthatch/caches"`) and pins the env vars at import. If you still see GCS errors, check for an ambient `~/.nuthatch.toml` or env vars pointing at GCS.
- Datasets are **eagerly loaded** (`.load()`) before caching on purpose: pickling a lazy dataset stores only a "reopen this temp file" recipe that breaks across sessions.

## Install notes

- `pip install accord-rosetta`; `import rosetta`. Python ≥ 3.12.
- Under **uv**, `[tool.uv] override-dependencies = ["zarr>=3.1.0"]` resolves the sheerwater (`zarr==2.18.3` pin) vs icechunk (`zarr>=3`) conflict. Under plain pip, the `icechunk` extra is opt-in for the same reason.
- Extras: `geo` (shapefile/geometry regions, geotiff band descriptions), `s3`, `icechunk`, `demo` (matplotlib, cartopy, rasterio), `dev` (pytest).
- Tests: `pytest` runs unit tests; markers `integration`, `cds`, `network` gate live-network suites.
