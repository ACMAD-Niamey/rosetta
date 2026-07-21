# Rosetta API reference

Import name is `rosetta` (distribution: `accord-rosetta`). Top-level exports: `catalog`, `fetch`, `parse_target`, `parse_init`, `assemble`, `check_product`, `check_all_products`.

At import time rosetta pins the nuthatch cache root via `os.environ.setdefault("NUTHATCH_ROOT_FILESYSTEM", ...)` / `NUTHATCH_LOCAL_FILESYSTEM` to `file://<ROSETTA_CACHE_DIR or ~/.nuthatch/caches>`. Set `ROSETTA_CACHE_DIR` **before** importing rosetta to relocate the cache.

## `fetch()`

```python
def fetch(product, variable, init=None, target=None, region=None,
          hindcast=None, destination=None, format="netcdf", verbose=True,
          progress=True, cache=True, allow_partial=False,
          max_retries=3, retry_backoff=1.0, request_interval=0.0,
          reforecast=False, boundary="center", region_buffer=1.5,
          year_index=False, seasonal=None, grid_res=None, regrid_to=None)
    -> xr.Dataset
```

| Param | Type / default | Meaning |
|---|---|---|
| `product` | str, required | Catalog id, e.g. `"nmme/cfsv2"`, `"obs/era5"`. See `references/products.md`. |
| `variable` | str, required | Canonical variable: `precip`, `temp`, or `sst` (availability per product). |
| `init` | str \| datetime \| None | `"YYYY-MM"` = seasonal monthly init (sets `init_months`); `"YYYY-MM-DD"` = S2S daily issuance (also sets the internal `_init_date`). |
| `target` | str \| (datetime, datetime) \| None | Season string (see season table below) or explicit start/end datetimes. Drives lead-month selection. |
| `region` | list \| str \| geometry \| None | bbox `[lat_s, lat_n, lon_w, lon_e]`, `.shp` path, or shapely/geopandas geometry. |
| `hindcast` | (int, int) \| None | `(start_year, end_year)` year range for the fetch. If omitted with `init`: defaults to `(init_year, init_year)`, or `(init_year-20, init_year-1)` when `reforecast=True`. |
| `destination` | str \| None | Local path or `s3://...` to also write the result. |
| `format` | `"netcdf"` (default) \| `"geotiff"` | Output format for `destination`. GeoTIFF has shape restrictions (see `storage.save` below). |
| `verbose` | bool = True | Logging (also sets nuthatch logger level). |
| `progress` | bool = True | tqdm progress bars. |
| `cache` | bool = True | Route through the nuthatch cache. `False` calls the adapter directly, never touching the cache. |
| `allow_partial` | bool = False | Multi-file adapters: `False` raises `RuntimeError` on any file failure; `True` returns what succeeded. |
| `max_retries` | int = 3 | Transient-failure retries (HTTP, OPeNDAP, CCSR adapters). |
| `retry_backoff` | float = 1.0 | Backoff multiplier between retries. |
| `request_interval` | float = 0.0 | Seconds between requests. This is a **floor** — a per-product catalog value can raise it, a caller cannot undercut it. |
| `reforecast` | bool = False | Fetch the on-the-fly hindcast suite (S2S: switches to the `s2s-reforecasts` collection). |
| `boundary` | `"center"` (default) \| `"cover"` | `"center"`: keep cells whose centre is inside the region (xarray/CDO convention). `"cover"`: keep every cell the region touches (`all_touched=True`). |
| `region_buffer` | float = 1.5 (degrees) | Only used with `boundary="cover"`; pads the fetched bbox so edge cells aren't clipped. Must exceed half the grid spacing. |
| `year_index` | bool = False | Reshape forecast `init_time` dim into an integer `year` dim and mean over `lead_time`. |
| `seasonal` | None \| `"mean"` | `"mean"`: subset the target season's months on `time` and average to one value per calendar year (`time` -> `year`). Requires `target`. Wraparound seasons (NDJ, DJF) raise `NotImplementedError`. |
| `grid_res` | float \| None | Regrid onto a regular lat/lon grid at this resolution spanning `region` (via `.interp`). Requires `region`. Mutually exclusive with `regrid_to`. |
| `regrid_to` | xr.DataArray \| None | Regrid onto this array's `lat`/`lon` coordinates. |

Behavioral notes:

- Requesting `region` on a product whose normalized output has no `lat`/`lon` dims raises `ValueError` (station/tabular data cannot be spatially subset).
- Polygon geometries are applied as a **final NaN mask** in normalization; the upstream request and the cache key only see the bbox. Two requests with the same bbox but different polygons share cached raw data.
- Deprecated products and aliases emit `DeprecationWarning` when resolved.

## `parse_target(target, year=None) -> (datetime, datetime)`

Tuples pass through. Season strings map via `SEASON_MONTHS` (start_month, end_month):

| Season | Months | Season | Months |
|---|---|---|---|
| DJF | (12, 2) | JJA | (6, 8) |
| JFM | (1, 3) | JAS | (7, 9) |
| FMA | (2, 4) | ASO | (8, 10) |
| MAM | (3, 5) | SON | (9, 11) |
| AMJ | (4, 6) | OND | (10, 12) |
| MJJ | (5, 7) | NDJ | (11, 1) |

Current year is used when `year` is None; the end date is the last day of the end month; wraparound seasons (end < start) roll into the next year.

## `parse_init(init) -> datetime`

10-char strings parse as `%Y-%m-%d`; otherwise the first 7 chars parse as `%Y-%m`. A `datetime` passes through.

## `assemble()`

```python
def assemble(roster, variable, *, init, target, region=None, grid_res=None,
             regrid_to=None, seasonal=None, range_index=2, cache=True,
             verbose=True, boundary="cover")
    -> dict[str, tuple[xr.DataArray, xr.DataArray]]
```

Multi-model fan-out over `fetch`, always with `year_index=True`.

- `roster`: iterable of rows `(label, product, *ranges)` where each range is a `(start, end)` tuple; `range_index` (default 2 = third element) selects which range column is the hindcast window.
- Returns `{label: (hindcast_da, forecast_da)}`. Each DataArray is canonicalized: a `member` dim is guaranteed (expanded to size 1 if absent — downstream code like deepscale does `hindcast.mean("member")`), stray non-dim coords (`number`/`member`/`spatial_ref`) are dropped, and dims are transposed to `(year, member, lat, lon)`.
- Raises on the first per-row failure.

## `catalog` module

- `catalog.list_products(include_deprecated=True) -> list[str]` — all catalog product ids; `include_deprecated=False` filters aliases and date-deprecated entries.
- `catalog.info(product_name) -> dict` (alias: `catalog.get`) — resolved config for a product. Follows `alias_of` chains (emitting `DeprecationWarning`), adds a computed `deprecated` bool (from `deprecated_after` vs today). Raises `KeyError` for unknown products. Config keys of interest: `adapter`, `variables` (each with `native_name`, `units`, `target_units`, optional `accumulated`, `fill_value`), `grid`, `hindcast`/`forecast` ranges, `member_reduce`, `request_interval`, `max_workers`.

## Health checks (`health.py`)

- `check_product(product, probe_remote=False) -> dict` — keys: `product`, `adapter`, `checked_at` (UTC ISO), `healthy` (bool), `kind` (`"config" | "remote" | "transient" | "runtime"`), `message`, plus adapter-specific fields. Returns early with a `pending_url` message when the catalog marks a product as not yet live. `probe_remote=True` also opens/pings the live source.
- `check_all_products(probe_remote=False) -> list[dict]` — iterates the whole catalog, converting exceptions into `kind="runtime"` failures.

## `validate` module (not re-exported; `from rosetta import validate`)

For checking rosetta output against independent references:

- `ValidationResult` dataclass — fields include `product`, `variable`, `reference`, `r_timeseries`, `r_spatial`, `status`, `threshold=0.95`, `structural_checks`, `error`, `timestamp`; methods `passed()`, `to_report_entry()`.
- `check_structure(ds, product, variable, product_config=None) -> dict` — variable presence, units attr, spatial dims, not-all-NaN, plausible value ranges (precip 0-500 mm/day, temp -90-70 C, sst -3-45 C, ±50 tolerance), member count vs catalog, hindcast range.
- `compare(rosetta_da, reference_da, threshold=0.95) -> (r_ts, r_spatial, status)` — regrids to a common grid, computes temporal and spatial Pearson correlations; status `PASS`/`CHECK`/`ERROR`.
- `regrid_to_common(da1, da2)`, `compute_correlations(ros_da, ref_da)` (needs `(init_time, lat, lon)`), `validate_product(...)`, `write_report(results, path=None)` / `read_report(path=None)` (default `output/validation_report.json`).

## `storage.save(ds, destination, format="netcdf")`

- `"netcdf"`: `ds.to_netcdf`; `s3://` destinations go through `s3fs`.
- `"geotiff"`: reduces to `(bands, lat, lon)` — means over `member`, squeezes length-1 `init_time`; the one remaining non-spatial dim becomes bands (values become band descriptions). Requires exactly one data var, `lat`/`lon` dims, and at most one extra dim after reduction. S3 GeoTIFF is `NotImplementedError`. Needs the `geo` extra for band descriptions.

## CLI (`rosetta`, Click)

```
rosetta cache list                      # python -m nuthatch list --namespace rosetta
rosetta cache clear [--product X] [--yes]
```

`clear` prompts for confirmation unless `--yes`; `--product` maps to a nuthatch `--cache-key` filter.

## Region resolution (`region.resolve_region(region) -> (bbox, geometry)`)

1. **bbox** — list/tuple/np.array of exactly 4 real numbers `[lat_s, lat_n, lon_w, lon_e]` (lat before lon; south, north, west, east). Returned as floats with `geometry=None`.
2. **shapefile** — string/`Path` ending `.shp` (anything else raises `ValueError`). Read with geopandas, reprojected to EPSG:4326, dissolved via `union_all()` (so multi-feature files clip as one region); bbox from `.bounds`.
3. **geometry** — bare shapely `BaseGeometry` (assumed EPSG:4326) or geopandas `GeoSeries`/`GeoDataFrame` (reprojected + dissolved).

`None` -> `(None, None)`. Shapefile/geometry input requires the `geo` extra (raises `ImportError` with a `pip install 'accord-rosetta[geo]'` hint). Antimeridian-crossing polygons are not special-cased — split them first.

## Adapters (internal, for debugging)

Registry (`rosetta.adapters.get_adapter(name)`): `cds`, `opendap`, `http`, `iridl`, `mars`, `ncei`, `s3`, `sheerwater`, `ccsr`, `icechunk`. All subclass `AdapterBase` with abstract `fetch_data(product_config, variable, date_range=None, region=None)`, plus `_resolve_streams` (hindcast/forecast split-stream stitching) and `health_check`. Caching happens **only** in `fetch._fetch_raw_cached`, never inside adapters.
