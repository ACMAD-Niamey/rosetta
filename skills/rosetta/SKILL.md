---
name: rosetta
description: Fetch and normalize seasonal/sub-seasonal climate data (NMME, C3S/Copernicus, ERA5, CHIRPS, IMERG, S2S) into canonical CF-aligned xarray Datasets using the accord-rosetta Python package. Use when fetching climate model hindcasts/forecasts or observations, assembling multi-model ensembles, clipping to regions/shapefiles, regridding, plotting quick-look maps of fetched fields, managing the rosetta cache, or debugging CDS/ECDS/IRI credentials and product errors.
license: MIT
metadata:
  author: accord-research
  package: accord-rosetta
compatibility: Requires Python 3.12+. Network access to data providers; some products need credentials (~/.cdsapirc, ~/.pycpt_dlauth, ~/.ecmwfapirc).
---

# Rosetta — canonical climate data acquisition

Rosetta is ACCORD's data adapter layer for seasonal climate forecasting. One call — `fetch()` — retrieves data from many providers (Copernicus CDS, ECMWF Data Store, OPeNDAP/IRI, HTTP, S3, Sheerwater/GCS, CCSR) and returns a **normalized xarray Dataset** with canonical variable names, units, and coordinates. Data stays at the source; rosetta hosts no central copy.

- Install: `pip install accord-rosetta` — **import name is `rosetta`**, not `accord_rosetta`.
- Extras: `[geo]` (shapefile/geometry regions), `[s3]`, `[icechunk]`, `[demo]` (plotting), `[dev]`.
- Downstream: rosetta feeds normalized xarray into **deepscale** (downscaling/forecasting); the interface is plain xarray, no hard coupling.

## Canonical output schema (what every fetch returns)

| Concept | Canonical name | Notes |
|---|---|---|
| Latitude / longitude | `lat`, `lon` | lat always **ascending**; lon in [-180, 180] |
| Obs/reanalysis time | `time` | `datetime64`, monthly/daily |
| Forecast init | `init_time` | `datetime64` (integer `year` if `year_index=True`) |
| Forecast lead | `lead_time` | numeric, source-dependent units |
| Ensemble | `member` | integer index |
| Variables | `precip`, `temp`, `sst` | precip `mm/day`, temp `C`, sst mostly `K` |

Typical shapes: forecasts `(init_time, lead_time, member, lat, lon)`; observations `(time, lat, lon)`; `assemble()` output `(year, member, lat, lon)`.

## Quick start

```python
from rosetta import fetch, catalog

# Observations: ERA5 temperature over the Horn of Africa (needs ~/.cdsapirc)
ds = fetch("obs/era5", "temp", region=[-5, 15, 33, 48], hindcast=(1993, 2016))

# Seasonal hindcast: CFSv2 precip, Feb inits, MAM target, 1993-2016
ds = fetch("nmme/cfsv2", "precip", init="2010-02", target="MAM",
           region=[-5, 15, 33, 48], hindcast=(1993, 2016))

# What products exist?
catalog.list_products(include_deprecated=False)
catalog.info("nmme/cfsv2")   # full config: variables, grid, streams, adapter
```

`fetch(product, variable, ...)` key parameters (full reference: [references/api.md](references/api.md)):

- `product`: catalog id string, e.g. `"nmme/cfsv2"`, `"obs/era5"`, `"c3s/ecmwf-monthly"`. Full list: [references/products.md](references/products.md).
- `variable`: canonical name — `precip`, `temp`, or `sst` (per-product availability varies).
- `init`: `"YYYY-MM"` (seasonal) or `"YYYY-MM-DD"` (S2S daily issuance).
- `target`: season string (`"MAM"`, `"OND"`, `"DJF"`, ...) or `(start_dt, end_dt)` tuple — drives lead-month selection.
- `region`: bbox `[lat_s, lat_n, lon_w, lon_e]` (**lat first**), a `.shp` path, or a shapely/geopandas geometry.
- `hindcast`: `(start_year, end_year)` — the fetch's year range.
- `year_index=True`: reshape `init_time` → integer `year` and mean over `lead_time` (the shape deepscale consumes).
- `seasonal="mean"`: average obs over the target season per calendar year (`time` → `year`); wraparound seasons (NDJ/DJF) raise `NotImplementedError`.
- `grid_res=1.0` or `regrid_to=some_da`: regrid (mutually exclusive; `grid_res` requires `region`).
- `boundary`: `"center"` (default) or `"cover"` (keep every cell the region touches).
- `cache=True` (default): nuthatch-backed local cache; `cache=False` bypasses it.

## Multi-model assembly (feeding deepscale)

```python
from rosetta import assemble

roster = [
    # (label, product, forecast_range, hindcast_range)
    ("CFSv2",   "nmme/cfsv2",   (2011, None), (1993, 2016)),
    ("GEOSS2S", "nmme/geoss2s", (2017, None), (1993, 2016)),
]
models = assemble(roster, "precip", init="2024-02", target="MAM",
                  region=[-5, 15, 33, 48])
# -> {label: (hindcast_da, forecast_da)}, each (year, member, lat, lon),
#    member dim guaranteed even for single-member sources
```

## Regions

Three forms (see [references/api.md](references/api.md) for details):
1. **bbox** `[lat_s, lat_n, lon_w, lon_e]` — note lat before lon.
2. **shapefile path** ending `.shp` — needs `[geo]` extra; reprojected to EPSG:4326 and dissolved; bbox drives the upstream request, polygon applied as a final NaN mask.
3. **geometry** — bare shapely geometry (assumed EPSG:4326) or GeoSeries/GeoDataFrame.

There are **no named built-in regions**. For country boundaries, pull ADM0 polygons from geoBoundaries (gbOpen, CC BY 4.0) and pass the geometry straight to `region=` — no shapefile on disk required (needs the `[geo]` extra):

```python
import geopandas as gpd

ISO3 = "KEN"
url = ("https://github.com/wmgeolab/geoBoundaries/raw/main/releaseData/"
       f"gbOpen/{ISO3}/ADM0/geoBoundaries-{ISO3}-ADM0_simplified.geojson")
kenya = gpd.read_file(url).to_crs("EPSG:4326")

ds = fetch("nmme/cfsv2", "precip", init="2024-02", target="MAM", region=kenya)
```

The repo ships `fetch_country_shapefiles.py` under its `scripts/` directory, which does the same thing and writes `.shp` files, if you have the checkout and want them on disk. Polygons crossing the antimeridian are not handled — split them first. Requesting a `region` on a non-gridded product raises `ValueError`.

## Caching

- Local nuthatch cache at `~/.nuthatch/caches` (override with `ROSETTA_CACHE_DIR` before import). Scratch downloads: `~/.nuthatch/rosetta/_tmp` (`ROSETTA_TMP_DIR`).
- Cache key: `(product, variable, date_range, region-bbox, init_months, init_date)`. Polygon masks never affect the key — same-bbox requests share cached raw data.
- CLI: `rosetta cache list`, `rosetta cache clear [--product X] [--yes]`.

## Health checks

```python
from rosetta import check_product, check_all_products
check_product("nmme/cfsv2")                  # config-level check
check_product("obs/era5", probe_remote=True) # also pings the live source
```

## Credentials you may need

| Products | Credential | Notes |
|---|---|---|
| `c3s/*` (not s2s), `obs/era5*` | `~/.cdsapirc` (Copernicus CDS) | Must also accept each dataset licence in the CDS web UI; 403 names the missing one |
| `c3s/ecmwf-s2s` | ECDS account (`https://ecds.ecmwf.int/api`) | Separate from CDS; two licence layers |
| `c3s/ecmwf-seas51c` | `~/.pycpt_dlauth` (IRI) | `cptdl.setup_dlauth("email")`; IRIDL sunsets ~Oct 2026 |
| S2S MARS fallback | `~/.ecmwfapirc` | reforecast-only |
| `nmme/*`, CHIRPS, sheerwater mirrors | none | public |

## Common pitfalls (full list: [references/troubleshooting.md](references/troubleshooting.md))

- CHIRPS at UCSB rate-limits hard (4-hour IP ban above ~2 req/s) — catalog sets `request_interval` floors; for routine daily data prefer `obs/chirps-v3-daily-rhiza` (0.25°, public GCS) over native `obs/chirps-v3-daily` (~23.5 GiB/file).
- `allow_partial=False` (default) raises if any file in a multi-file fetch fails; pass `allow_partial=True` for best-effort.
- Deprecated products emit `DeprecationWarning` and alias to successors — check `catalog.info(p)["deprecated"]`.
- S3 adapter shells out to the AWS **CLI**, not boto3 — `aws` must be configured.
- If nuthatch tries to reach `gs://sheerwater-datalake/...` and 401s, ambient config is shadowing rosetta's — see troubleshooting.

## Runnable examples

- [examples/basic_fetch.py](examples/basic_fetch.py) — obs + hindcast fetch, save to NetCDF/GeoTIFF
- [examples/multi_model_assemble.py](examples/multi_model_assemble.py) — `assemble()` roster → deepscale-ready arrays
- [examples/shapefile_region.py](examples/shapefile_region.py) — country clipping, center vs cover
- [examples/s2s_fetch.py](examples/s2s_fetch.py) — sub-seasonal issuance + on-the-fly reforecasts
- [examples/quick_look.py](examples/quick_look.py) — cartopy map, ensemble facets, weighted time series

## Reference files

- [references/api.md](references/api.md) — complete API: `fetch`, `assemble`, `parse_target`/`parse_init`, `catalog`, health, `validate`, `storage`, CLI
- [references/products.md](references/products.md) — every product id with adapter, variables, resolution, credentials
- [references/data-conventions.md](references/data-conventions.md) — the normalization pipeline step by step, unit conversion table, season strings
- [references/plotting.md](references/plotting.md) — visualizing fetched data: quick-look maps (cartopy), colormap/units conventions, ensemble facets, area-weighted time series, region overlays
- [references/troubleshooting.md](references/troubleshooting.md) — errors, credentials setup, rate limits, cache issues
