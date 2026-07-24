# ERSSTv5, silent DAP truncation, and zonal aggregation

**Status:** implemented (`rosetta.adapters.opendap`, `rosetta.zonal`)
**Date:** 2026-07-09

Two unrelated pieces of work, recorded together because the first contains a finding that outlives its motivating task.

---

## Part 1 — ERSSTv5, and three IRIDL assumptions

ERSSTv5 is the reference SST for the 1991–2020 baseline that ONI, RONI and the IOD index are verified against. The `ncei` adapter is a dead end for it (hardwired to NMME per-member file scraping). The `opendap` adapter fits, once three assumptions are removed. Each was invisible because every catalogued OPeNDAP product happened to be IRI Data Library-shaped.

1. **URL construction.** The adapter always built IRIDL's Ingrid form, `{base}/.{native_name}/dods`. That is now the *default value* of a `url_template` catalog key. NOAA PSL's THREDDS serves a whole NetCDF at one URL with no variable segment: `url_template: "{base}"`.

2. **Time decoding.** Every dataset was opened with `decode_times=False`, because NMME's `"months since"` axis is not CF-decodable and `decode_months_since` handles it downstream. An observational source with an ordinary `"days since"` axis opts in with `decode_times: true`, and can then be sliced by date.

3. **Latitude direction.** NOAA PSL stores latitude 88°N → 88°S. An ascending `sel(lat=slice(lat_s, lat_n))` against a descending coordinate selects **nothing at all**, with no error and no warning. The adapter sorts before slicing.

### The finding: DAP2 truncation is silent

A DAP2 response above the server's size cap comes back **truncated**. `netCDF4` prints

```
ERR: DAP DATADDS packet is apparently too short
```

to *stderr*, returns a zero-filled array, and **does not raise**.

Probed against NOAA PSL on 2026-07-09 with global 2° monthly ERSSTv5:

| request | result |
|---|---|
| 120 months | real data |
| 240 months | every value `0.0`, land mask gone |
| 360 months | every value `0.0`, land mask gone |

This is worse than a failure. Thirty years of 0 °C sea-surface temperature is a plausible-looking array of the right shape and dtype. It reached the nuthatch cache during development of this very change, and every RONI value computed from it came out as exactly `0.0` — a perfectly reasonable-looking number for an anomaly index. Nothing in the stack noticed. The corrupt entry was then served from cache on every subsequent run, so re-running "to check" reproduced the wrong answer.

Two defences, both generic and neither ERSST-specific:

- **Chunked requests.** Observational time axes are fetched in `max_request_years` blocks (default 5), *after* the region slice, so each DAP response stays far below any plausible cap. The catalog can lower it per product.
- **A degeneracy check.** Each block is materialized and inspected. A multi-step gridded geophysical field that is bitwise constant, or has no finite values at all, is a truncated packet and raises. It runs **inside** the adapter, before `_fetch_raw` returns, so a corrupt response can never be written to the cache.

The second is the important one. The chunk size is tuned to one server's current behaviour; the check holds regardless of which server, which cap, or what changes next year.

### A note on caching corrupt data

This episode is the cache-poisoning failure mode the HTTP adapter's `allow_partial` guard already warns about, arriving through a different door. The general rule it suggests: **validate before the cache boundary, never after.** A cache that can hold a wrong answer will keep serving it long after the source has recovered, and the only symptom is that the numbers look slightly odd.

---

## Part 2 — zonal aggregation

`fetch(region=...)` dissolves a shapefile's features into one mask, because a fetch answers "give me the data over this area". Reporting asks the other question — *one number per district* — and there was no way to ask it except a Python loop over a thousand woreda polygons, each rasterizing the same grid again.

`rosetta.zonal(data, geometries, by="ADM3_EN")` burns every geometry into a single integer label grid and reduces with one `groupby`: one pass, whatever the number of regions.

```python
per_district = zonal(rain, woredas, by="ADM3_EN")   # (time, region)
```

### Why it lives here and not in deepscale

It is geometry-to-grid work, and Rosetta already owns `region.py` and the `geo` extra. deepscale's optional dependency on Rosetta stays one-directional.

### Why the output shape is the whole point

`zonal` adds a `region` dim and leaves every other dim alone. deepscale's completion engine reduces along `time` and touches nothing else. Therefore a `(time, region)` array drops into it unchanged, and **per-district accumulation curves need no admin-unit code path in either library**. A cross-library test in `tests/test_zonal.py` pins this, because it is the property most likely to be broken by a well-meaning refactor.

### Decisions

- **Area weighting is the default.** On a regular lat/lon grid a cell's area falls off as `cos(lat)`, so an unweighted mean over a tall region over-counts its poleward cells. Order statistics ignore weights.
- **A region with no valid cells yields NaN, not a dropped row.** The output always mirrors the input geometries. A silently shorter result stops lining up with the caller's region list, and nothing downstream can detect it.
- **NaN cells are excluded**, so a district that is half ocean is averaged over its land.
- **A district smaller than one grid cell raises**, pointing at `all_touched=True`, rather than returning an empty region. Sub-cell administrative units are common and contain no cell centre.
- **Overlapping geometries: last one wins**, matching `rasterio.features.rasterize`. Administrative units rarely overlap, and when they do there is no non-arbitrary answer.
