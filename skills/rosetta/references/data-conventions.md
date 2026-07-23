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

   **Verify units in practice — conversion is attrs-driven and not bulletproof.** The `mm → mm/day` identity assumes "mm per 24 h" (true for deaccumulated S2S leads); a source serving *monthly totals* labeled `mm` passes through unconverted, and `mm/month ÷ 30` is an approximation. CCSR NMME precip has repeatedly been observed arriving as monthly totals (~100 mm where ERA5 says ~3 mm/day). Before mixing products, check `da.attrs["units"]` and sanity-check magnitudes against a known-rate product; convert totals exactly with days-per-month (`calendar.monthrange`). A cheap guard when looping over mixed rosters: treat the field as a rate only if `"day"`, `"/d"`, or `"d-1"` appears in the units string.
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

### Year labeling at multi-month leads (wraparound bookkeeping)

At an operational lead (e.g. 2 months: MAM initialized in January), early-year targets put the init in the **previous calendar year** — JFM targeted from November, FMA from December. `year_index=True` labels years from `init_time`, so when aligning such forecasts with obs labeled by *target* year, add +1 to the forecast's year for those seasons (compute the init month mod-12 and offset when it wraps). Two further rules from downstream use:

- **Rectangular multi-season cubes:** when stacking several seasons into one `(season, year, ...)` cube (e.g. for deepscale's `seasonal_coefficients`), *intersect* the years available across all seasons rather than union them — wraparound seasons otherwise NaN-pad the cube.
- The `init_time → year` rename is what `year_index=True` does for you; for obs use `seasonal="mean"` (which yields a `year` dim directly). Prefer these over hand-rolled `.dt.year` renames.

## Downstream contract (deepscale)

Deepscale consumes `(year, member, lat, lon)` hindcasts and `(member, lat, lon)` forecasts and calls `hindcast.mean("member")` — which is why `assemble()` guarantees a `member` dim (size 1 if the source has none) and transposes to `(year, member, lat, lon)`. Observations feed deepscale as `(year, lat, lon)` — get there with `fetch(..., seasonal="mean", target=...)` (obs) or `year_index=True` (forecasts).
