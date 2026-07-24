# Issuance-keyed forecast archives

**Status:** implemented (`rosetta.adapters._issuance`, `rosetta.adapters.http`, `rosetta.fetch`)
**Date:** 2026-07-09
**Motivating case:** CHIRPS-GEFS, needed for Stage 2 of `analyses/chc_ethiopia/METHODOLOGY.md`

## The problem

An observational archive is keyed by the time it describes. A forecast archive is keyed by **two** times: when it was issued, and what it is about. CHC's CHIRPS-GEFS puts the first in the directory path and the second in the filename:

```
.../CHIRPS-GEFS/v3/daily/global/2026/07/05/c3g_2026.07.20.tif
                                ^^^^^^^^^^        ^^^^^^^^^^
                                issued 5 July     valid 20 July, lead 15
```

The HTTP adapter could expand `{year}` and `{month:02d}` and nothing else, and always finished with `xr.concat(datasets, dim="time")`. It had no way to express a lead axis and no way to fetch more than one issuance.

The planning note that motivated this work rated it "one catalog entry, effort: S". It is not: Rosetta's canonical forecast contract is `(init_time, lead_time, member, lat, lon)`, and nothing in the HTTP path could produce it.

## Not another adapter

Other archives put the lead number in the filename, or the init date in both places, or serve one accumulated raster per issuance with no lead at all. A new adapter per layout would be four adapters and counting.

Instead a catalog entry declares an `issuance` block, and gets `strftime` templating over three names:

```yaml
issuance:
  path_pattern: "{init:%Y}/{init:%m}/{init:%d}"
  file_pattern: "c3g_{valid:%Y}.{valid:%m}.{valid:%d}.tif"
  leads: [0, 15]          # inclusive
  lead_units: days
```

`{init}` and `{valid}` are datetimes (so any `strftime` code works); `{lead}` is an integer (so `lead{lead:02d}` works). That one grammar covers:

| Archive shape | Expressed as |
|---|---|
| dir = init, file = valid | CHIRPS-GEFS daily (above) |
| one accumulated file per init, no lead | `leads: [0, 0]`, `file_pattern` uses `{init}` |
| lead-numbered filenames | `file_pattern: "fcst_{init:%Y%m%d}_lead{lead:02d}.nc"` |
| hourly leads | `lead_units: hours` |

The templating lives in `adapters/_issuance.py` and knows nothing about HTTP, so an S3 or OPeNDAP archive of the same shape can reuse it. Entries **without** an `issuance` block take exactly the code path they took before.

## Fetching many issuances

Stage 4 of the methodology needs the June-30 forecast of every hindcast year, to score it against what happened. There was no way to ask for that. `fetch(init=...)` now accepts a sequence:

```python
rosetta.fetch("chc/chirps-gefs-daily", "precip",
              init=[f"{y}-06-30" for y in range(2001, 2020)],
              region="ethiopia.shp")
```

The result stacks on `init_time`. Only issuance-keyed products accept a sequence; anything else raises with an explanation rather than silently using the first date.

### Cache compatibility

Adding a cache argument to `_fetch_raw_cached` would change the key of every already-cached fetch, silently discarding gigabytes of CHIRPS. The issuance dates therefore reuse the existing `init_date` slot — a string for one issuance, a tuple for several. A single-issuance fetch hashes exactly as it did before.

## Coordinate decisions

**`lead_time` is a timedelta, not an integer.** An integer lead is ambiguous the moment two products disagree on whether it counts days or hours, and nothing in the data says which. A `timedelta64` cannot be misread.

**`valid_time` is derived in the adapter** (`init_time + lead_time`) rather than left to the caller, so a forecast can be verified without every consumer re-deriving it. `normalize` maps it onto the canonical `time` name.

**A missing lead is reindexed to NaN in place.** Under `allow_partial`, dropping it would shift every later lead down by one and silently relabel a 2-day forecast as a 1-day one. This is the same class of bug as the partial-fetch poisoning the HTTP adapter already guards against.

## Which CHIRPS-GEFS

The planning note pointed at `products/EWX/data/forecasts/CHIRPS-GEFS_precip_v12`. CHC's README says that stream (CHIRPS2-GEFS) was **discontinued on 2026-07-01**. It is deliberately not catalogued.

The live product is CHIRPS3-GEFS at `products/CHIRPS-GEFS/v3/` — GEFSv12 bias-corrected to the CHIRPS3 distribution, downscaled with IMERGv7-Late. Its coverage has a real hole, and the catalog states it rather than smoothing it over:

- GEFS reforecasts start January 2000, but the IMERG used to downscale them starts June 2000.
- The operational GEFSv12 stream begins September 2020.
- CHC therefore publishes complete years only: **2001–2019** (reforecast) and **2021–present**. 2020 does not exist.

The 2001–2019 reforecast span is the good news: it makes a hindcast-skill analysis possible on CHIRPS-GEFS itself, rather than substituting a single ECMWF S2S model and noting the deviation.

## Catalogued

- `chc/chirps-gefs-daily` — 16 daily leads per issuance.
- `chc/chirps-gefs-15day` — one accumulated 15-day total per issuance. `lead_time` is a singleton spanning `[init, init+15d)`, so `valid_time` marks the window's **start**, not its end.

CHC's `dekad_lead_0` product is keyed by target dekad rather than by issuance and does not fit the grammar. Aggregate the daily product with `deepscale.accumulate` instead.

## Verification

Two network-marked integration tests fetch real data from CHC: one issuance of the daily product (16 leads, `valid_time` correct at lead 15), and three June-30 issuances of the 15-day product stacked on `init_time`. They exist to catch an upstream layout change, which is the failure mode a unit test cannot see.
