# Data conventions and the normalization pipeline

"Rosetta" = translation: every adapter's raw output passes through `normalize.normalize(ds, product_config, variable, region=None, geometry=None, boundary="center", year_index=False)`, which applies the following steps **in order**:

1. **Decode numeric times** — any dim-coordinate with CF `"<unit> since <epoch>"` units becomes `datetime64`. Handles `months since` (e.g. NMME's `S` = "months since 1960-01-01"), `days since`, `hours since`.
2. **S2S scalar-time handling** — a scalar (non-dim) `time` coord is pre-renamed to `init_time` so the later `valid_time -> time` rename cannot collide.
3. **`hdate` handling** — S2S reforecasts carry an `hdate` dim (calendar issuance dates); converted to integer years and renamed `year`.
4. **Coordinate renames** to canonical names:
   - Spatial: `latitude`/`LAT`/`Y` -> `lat`; `longitude`/`LON`/`X` -> `lon`
   - Obs time: `forecast_time`, `valid_time`, `T`, `TIME` -> `time`
   - Forecast init: `S`, `forecast_reference_time`, `indexing_time` -> `init_time`
   - Forecast lead: `L`, `forecastMonth`, `forecast_period`, `step` -> `lead_time`
   - Ensemble: `M`, `number` -> `member`
5. **`member_reduce`** (catalog-driven) — e.g. CFSv2 averages the first 24 of 28 members (`{first: 24, op: mean}`), then re-expands to `member=[0]`.
6. **Variable rename** — `native_name` (or `short_name` fallback) -> canonical `precip`/`temp`/`sst`.
7. **Deaccumulation** — if the catalog marks the variable `accumulated: true` and `lead_time` exists: `.diff("lead_time")` (CDS accumulated precip).
8. **Unit conversion** (`_CONVERSIONS`):

   | From | To | Operation |
   |---|---|---|
   | K | C | subtract 273.15 |
   | kg m-2 s-1 | mm/day | × 86400 |
   | m s-1 | mm/day | × 1000 × 86400 |
   | m | mm/day | × 1000 |
   | m/s | mm/day | × 86,400,000 |
   | mm/month | mm/day | ÷ 30.0 |
   | mm | mm/day | identity (already mm per 24 h) |

   `da.attrs["units"]` is set to `target_units`.
9. **Fill-value masking** — catalog `fill_value` (e.g. -9999) -> NaN.
10. **Latitude ascending** — `ds.sortby("lat")`. Canonical convention: lat always ascending.
11. **Spatial selection** — polygon clip (`clip_to_geometry`, rioxarray `.rio.clip`, `all_touched = (boundary == "cover")`) when a geometry was given; otherwise bbox `.sel(lat=slice, lon=slice)` (cover mode expands by half a grid cell).
12. **CF axis attributes** — `lat.axis="Y"`, `lon.axis="X"`, `time`/`init_time` `.axis="T"`.
13. **`year_index`** — if requested and `init_time` is a dim: replaced by integer `year`, with a mean over `lead_time` (keep_attrs).

## Canonical output schema

- Coordinates: `lat`, `lon` (ascending lat, lon in [-180, 180]); `time` (obs, `datetime64`); `init_time` (forecasts, `datetime64`); `lead_time` (numeric, source-dependent units); `member` (integer ensemble index). With `year_index=True`: integer `year` replaces `init_time`.
- Typical dims — forecasts: `(init_time, lead_time, member, lat, lon)`; observations: `(time, lat, lon)`; `assemble()` output: `(year, member, lat, lon)`.
- Units: precip `mm/day` (native CHIRPS pentad/dekad/annual keep `mm` totals), temp `C`, sst mostly `K` (ERA5 sst is `C`).

## Season strings

`SEASON_MONTHS` (start_month, end_month): DJF (12,2), JFM (1,3), FMA (2,4), MAM (3,5), AMJ (4,6), MJJ (5,7), JJA (6,8), JAS (7,9), ASO (8,10), SON (9,11), OND (10,12), NDJ (11,1). Wraparound seasons (end < start) roll into the following year; `seasonal="mean"` does not support them.

## Downstream contract (deepscale)

Deepscale consumes `(year, member, lat, lon)` hindcasts and `(member, lat, lon)` forecasts and calls `hindcast.mean("member")` — which is why `assemble()` guarantees a `member` dim (size 1 if the source has none) and transposes to `(year, member, lat, lon)`. Observations feed deepscale as `(year, lat, lon)` — get there with `fetch(..., seasonal="mean", target=...)` (obs) or `year_index=True` (forecasts).
