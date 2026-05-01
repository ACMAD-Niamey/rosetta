# Rosetta v1 Roadmap Issues (1–17)

*Fetched 2026-04-30 from accord-research/rosetta*

---

## #3 — §1.3 SST variable on existing entries

**Labels:** v1-roadmap  
**URL:** https://github.com/accord-research/rosetta/issues/3


### Parent context — §1 GCM catalog completion

Goal: every GCM the PyCPT reference workflow uses is reachable via `rosetta.fetch(...)` for both `precip` and `sst` variables, both hindcast and forecast.

**Goal.** Every C3S and NMME entry in the catalog supports `variable="sst"` in addition to `precip` and `temp` where the upstream provider exposes it.

**Where.**
- `src/rosetta/catalog.yaml` — add `sst` blocks to existing entries
- `src/rosetta/adapters/cds.py`, `opendap.py`, `s3.py`, `iridl.py` — extend each adapter if SST requires different request parameters than precip
- `src/rosetta/normalize.py` — confirm SST normalization (units in K, no conversion)

**Approach.** Audit every entry. For each, check the upstream provider's variable list. Add an `sst` block under `variables:`:

```yaml
variables:
  precip: { native_name: prec, units: "mm/day", target_units: "mm/day" }
  sst:    { native_name: sst,  units: K, target_units: K }
```

For C3S adapters: the CDS request needs the appropriate variable name (e.g. `sea_surface_temperature`). For OPeNDAP/IRI: the URL path or variable selector changes. Document per adapter.

**Pitfalls.**
- **Ocean-only grid mismatch.** SST is defined only over ocean — land cells are masked NaN. CCA pipelines downstream need to handle NaN in the predictor. Don't fill with zeros; preserve NaN.
- **SST grid may differ from PRCP grid for the same model.** Some GCMs run atmosphere and ocean on different grids. Document this — don't assume `lat_res` and `lon_res` from the existing entry apply to SST.
- **Coupled-model SST is what we want, not prescribed-SST.** A few systems (rare in the spec's catalog) use prescribed SST as forcing rather than as a coupled output; in those, "GCM SST" is just the input data, not a prediction. Verify the upstream documentation. CFSv2, GEOS-S2S, SPEAR(b), CanSIPS, ECMWF SEAS5, etc. are all coupled.
- **CDS request size limits.** A whole-tropics SST domain over 30 years can exceed CDS's per-request limit. Adapters should chunk per-year if needed. The existing CDS adapter likely already does this for precip; confirm it works for SST too.
- **Day-of-month convention for monthly SST.** Some providers timestamp monthly means as the 1st, some as the 15th. Normalize to month-start.

**Testing.**
- Unit: extend `test_catalog_variable_mapping` to require all NMME and C3S forecast products (per spec's model inventory) expose `sst`.
- Integration: per-product smoke test that fetches `variable="sst"` for a small region and asserts NaN over land + non-NaN over ocean for a known grid cell.

**Done when.** Every product in the spec's NMME and C3S model inventory tables can fetch `variable="sst"` with non-trivial coverage. Health checks pass.

---
_Imported from `rosetta-plan.md` §1.3._


---

## #4 — §1.4 Verify all PyCPT reference GCMs

**Labels:** v1-roadmap  
**URL:** https://github.com/accord-research/rosetta/issues/4


### Parent context — §1 GCM catalog completion

Goal: every GCM the PyCPT reference workflow uses is reachable via `rosetta.fetch(...)` for both `precip` and `sst` variables, both hindcast and forecast.

**Goal.** All ten GCMs in `pycpt-reference/pycpt_seasonal_forecast.py` (`PRCP_PREDICTOR_NAMES` and `SST_PREDICTOR_NAMES`) have a Rosetta equivalent.

**Where.** `tests/test_rosetta.py` — add a test that asserts coverage.

**Approach.** Maintain a mapping table in `tests/conftest.py`:

```python
PYCPT_REFERENCE_GCMS = {
    "GEOSS2S.PRCP":    ("nmme/geoss2s", "precip"),
    "SPEAR.PRCP":      ("nmme/spear", "precip"),
    "CCSM4.PRCP":      ("nmme/ccsm4-iri", "precip"),
    "CFSv2.PRCP":      ("nmme/cfsv2", "precip"),
    "CanSIPSIC4.PRCP": ("nmme/cansipsic4", "precip"),
    "SEAS51c.PRCP":    ("c3s/ecmwf-seas51c", "precip"),
    "SPSv3p5.PRCP":    ("c3s/cmcc", "precip"),
    "GCFS2p1.PRCP":    ("c3s/dwd-gcfs21", "precip"),
    "CPS2.PRCP":       ("c3s/jma-cps2", "precip"),
    "METEOFRANCE9.PRCP": ("c3s/meteofrance", "precip"),
    "GEOSS2S.SST":     ("nmme/geoss2s", "sst"),
    "SPEARb.SST":      ("nmme/spearb", "sst"),
    # ... etc
}
```

Test asserts every entry resolves via `catalog.info()` and exposes the correct variable.

**Done when.** `pytest tests/test_rosetta.py::test_pycpt_reference_coverage` passes for all 20 (10 PRCP + 10 SST) PyCPT predictor names.

### Dependencies

deps: §1.1, §1.2, §1.3

---
_Imported from `rosetta-plan.md` §1.4._


---

## #5 — §2 Dual-domain support (documentation only)

**Labels:** v1-roadmap  
**URL:** https://github.com/accord-research/rosetta/issues/5


**Goal.** PyCPT's two-predictor-domain pattern (large SST domain + regional PRCP domain over the same predictand) is documented as a calling convention, not enshrined in code.

**Where.** `README.md` and `docs/dual_domain.md` (new, optional).

**Approach.** No code change. The current `rosetta.fetch(region=...)` already accepts arbitrary regions per call. Document that the canonical seasonal-forecasting pattern is:

```python
sst_predictor  = rosetta.fetch(product, variable="sst",    region=[-20, 20, 30, 180], ...)
prcp_predictor = rosetta.fetch(product, variable="precip", region=[-20, 20, 10, 75], ...)
predictand     = rosetta.fetch("obs/chirps-v2", region=[-12, 15, 22, 52], ...)
```

DeepScale's `seasonal_mme()` (deepscale-plan §1) orchestrates this; Rosetta stays single-call.

**Pitfalls.**
- Don't add a `fetch_predictor_pair()` convenience wrapper. It encodes assumptions (which two domains, which two variables) that change per use case. Keep `fetch()` orthogonal.

**Done when.** Pattern is documented with a worked example in the README.

---
_Imported from `rosetta-plan.md` §2._


---

## #6 — §3.1 Adapter implementation

**Labels:** v1-roadmap  
**URL:** https://github.com/accord-research/rosetta/issues/6


### Parent context — §3 Sheerwater data adapter

**Goal.** Cloud-native CHIRPS, ERA5, IMERG, and GHCN are reachable via Rosetta by delegating to Sheerwater (Rhiza Research, MIT-licensed). Repo: <https://github.com/rhiza-research/sheerwater>.

**Goal.** A `SheerwaterAdapter` class wraps Sheerwater's data accessors and conforms to Rosetta's adapter contract.

**Where.**
- `src/rosetta/adapters/sheerwater.py` (new)
- `src/rosetta/adapters/__init__.py` — register the new adapter

**Approach.** Sheerwater exposes data via plain Python functions (e.g. `sheerwater.data.chirps_v3(start_time, end_time, agg_days, variable, grid, mask, region)`). The adapter:

1. Reads catalog config (`source` field naming the Sheerwater function, plus default kwargs).
2. Translates Rosetta's `(init, target, region, hindcast_range)` arguments into Sheerwater's `(start_time, end_time, ...)` shape.
3. Calls the Sheerwater function.
4. Returns the raw xarray (Rosetta's normalization layer handles renames).

Add `sheerwater` to `pyproject.toml` as a required dependency (it's small and pure Python). Nuthatch comes along as a transitive dep — that's fine, see §4.

**Pitfalls.**
- **Sheerwater's S2S framing leaks into the API.** `start_time`/`end_time` are calendar timestamps, not init+lead. For seasonal use, you typically want monthly or seasonal aggregates over the obs record (e.g. 1981-01 through 2020-12); just pass that range and let normalization handle it.
- **`agg_days` parameter.** Sheerwater accumulates over N days. For monthly seasonal use, set `agg_days` such that you're getting daily output you then aggregate to monthly in normalization, OR find the aggregation that aligns with monthly. Read `sheerwater/data/chirps.py` to confirm the available aggregations (the README lists 1, 5, 7, 10).
- **Grid choice.** Sheerwater offers regridded variants (`global0_25`, `global1_5`, native). For seasonal forecasting against fine-resolution CHIRPS, use the native CHIRPS grid (~0.05°) and let the user opt in to coarser grids via a catalog parameter.
- **Auth.** Public bucket needs no creds. Some Sheerwater data sources require GCS auth (TAHMO especially). Catalog should expose an `auth_required: true` flag for those entries; the health check should distinguish "unreachable" from "needs auth".
- **Caching.** Sheerwater is Nuthatch-backed — calls are cached upstream. Don't cache again at Rosetta's layer for Sheerwater-routed calls (would be redundant and double-cost storage).

**Testing.**
- Unit: mock `sheerwater.data.chirps_v3` and verify Rosetta passes through correct kwargs and applies normalization on the return.
- Integration: small region + small date range fetch; assert non-empty, non-NaN-dominant.

**Done when.** Adapter is in place, registered, and one real fetch round-trips successfully on the public bucket.

---
_Imported from `rosetta-plan.md` §3.1._


---

## #7 — §3.2 Sheerwater-backed catalog entries

**Labels:** v1-roadmap, depends-on-deepscale  
**URL:** https://github.com/accord-research/rosetta/issues/7


### Parent context — §3 Sheerwater data adapter

**Goal.** Cloud-native CHIRPS, ERA5, IMERG, and GHCN are reachable via Rosetta by delegating to Sheerwater (Rhiza Research, MIT-licensed). Repo: <https://github.com/rhiza-research/sheerwater>.

**Goal.** The four data sources Sheerwater covers are exposed under canonical Rosetta product names, with Sheerwater-backed entries taking priority over existing direct adapters where they overlap.

**Where.** `src/rosetta/catalog.yaml`.

**Approach.** Add:

```yaml
obs/chirps:
  adapter: sheerwater
  source: chirps_v3            # function name in sheerwater.data
  variables:
    precip: { native_name: precip, units: "mm/day", target_units: "mm/day" }
  grid: { lat_res: 0.05, lon_res: 0.05, members: null, hindcast_range: [1981, 2024] }
  notes: "Default CHIRPS source. Sheerwater-backed (public Zarr bucket)."

obs/era5:
  adapter: sheerwater
  source: era5
  variables:
    precip: { native_name: precip, units: "mm/day", target_units: "mm/day" }
    temp:   { native_name: tmp2m,  units: K, target_units: C }
  grid: { lat_res: 0.25, lon_res: 0.25, members: null, hindcast_range: [1950, 2024] }

obs/imerg:
  adapter: sheerwater
  source: imerg_final
  variables: { precip: { ... } }

obs/ghcn:
  adapter: sheerwater
  source: ghcn_avg
  variables: { precip: {...}, temp: {...} }
```

**Pitfalls.**
- **Don't break existing users of `obs/chirps` and `obs/era5`.** If `obs/chirps` already routes via the direct HTTP adapter, switching it to Sheerwater changes (subtly) what users get. Choose one of two strategies, document it, stick with it:
  - (a) Keep direct adapter as `obs/chirps-direct`; rename Sheerwater-backed to `obs/chirps`. Mark old entry deprecated.
  - (b) Keep both, document the difference, default new docs/examples to the Sheerwater entry.
  Recommend (a) for cleanliness.
- **ERA5 variables.** Sheerwater serves ERA5 from Google ARCO. Only `tmp2m` and `precip` are pre-regridded per the README; other variables (geopotential, winds) may need a different code path or aren't available. Document scope.
- **`hindcast_range`** is misleading for obs — it's really "data availability range". Either rename the field or document that for obs entries it means the available years.

**Testing.**
- Catalog probe tests for each new entry.
- One end-to-end fetch per entry over a tiny region.

**Done when.** All four entries pass health checks; documentation reflects which is the default for each source.

### Dependencies

deps: §3.1; deps-deepscale: §20 (metric proxy reads same dep)

---
_Imported from `rosetta-plan.md` §3.2._


---

## #8 — §3.3 Health check probe

**Labels:** v1-roadmap  
**URL:** https://github.com/accord-research/rosetta/issues/8


### Parent context — §3 Sheerwater data adapter

**Goal.** Cloud-native CHIRPS, ERA5, IMERG, and GHCN are reachable via Rosetta by delegating to Sheerwater (Rhiza Research, MIT-licensed). Repo: <https://github.com/rhiza-research/sheerwater>.

**Goal.** `rosetta.check_product(...)` covers Sheerwater-backed entries.

**Where.** `src/rosetta/health.py`.

**Approach.** A Sheerwater probe is: open the source's underlying Zarr store via xarray, read coordinate metadata only (no data), assert the time range overlaps the catalog's `hindcast_range`. Should complete in < 5 s.

**Pitfalls.**
- Don't call the high-level `sheerwater.data.chirps_v3()` for probing — it can pull non-trivial data slices. Use the underlying Zarr store URL directly.
- GCS connectivity errors should be classified as "transient" not "broken adapter".

**Done when.** All four new `obs/*` entries return `healthy: true` from `check_product(probe_remote=True)`.

### Dependencies

deps: §3.1, §3.2

---
_Imported from `rosetta-plan.md` §3.3._


---

## #9 — §4.1 Replace local cache with `@nuthatch.cache()`

**Labels:** v1-roadmap  
**URL:** https://github.com/accord-research/rosetta/issues/9


### Parent context — §4 Nuthatch caching integration

**Goal.** Rosetta uses Nuthatch (Rhiza Research, MIT) as its caching layer, gaining shared/cloud-mirror cache support. Repo: <https://github.com/rhiza-research/nuthatch>.

**Where.**
- `src/rosetta/fetch.py`
- `src/rosetta/adapters/*.py` — per-adapter download functions
- `pyproject.toml` — add `nuthatch` dep
- New `[tool.nuthatch]` config section in `pyproject.toml`

**Approach.** Nuthatch's `@cache()` decorator wraps a function and persists its return based on a fingerprint of arguments. Identify the cache-eligible boundaries in Rosetta:

- Per-adapter raw download (good cache boundary — return raw xarray, normalize separately)
- Whole-`fetch()` end-to-end (also a fine cache boundary, but more cache misses on minor arg variation)

Recommend caching at the adapter-download level: stable, large enough to be worth caching, immune to changes in normalization logic.

Add to `pyproject.toml`:

```toml
[tool.nuthatch]
backend = "zarr"               # for xarray returns
local_cache = "~/.nuthatch/rosetta"
# Optional: read-only mirror or shared write target
# remote_cache = "gs://accord-rosetta-cache"
```

**Pitfalls.**
- **Cache key versioning.** When an adapter's logic changes (different URL, different post-processing), bump a version constant in the adapter so old cache entries are invalidated. Don't rely on the function name — Nuthatch keys include args, but if your code transformation changes, callers won't know.
- **Don't double-cache.** Sheerwater-routed calls are already Nuthatch-cached upstream. If you wrap them again at the Rosetta layer, you store the same data twice. Either skip caching for the Sheerwater adapter or cache at a different boundary.
- **Don't cache health checks.** A health probe needs to actually probe.
- **Local cache can grow unbounded.** Nuthatch doesn't auto-evict. Document the user CLI for inspection/cleanup.
- **Cache poisoning from upstream errors.** If an adapter occasionally returns a partial/corrupt response, it gets cached as truth. Add basic validation (non-empty, non-all-NaN, expected dim names) before letting Nuthatch persist a result.

**Testing.**
- Unit: cache hit returns identical xarray to the uncached call. Cache key changes when arguments change.
- Cache invalidation via version bump works (manually edit version, expect refetch).

**Done when.** A second identical fetch is observably faster (no network) and produces identical xarray.

### Dependencies

deps: §3 stable (avoid double-caching Sheerwater path)

---
_Imported from `rosetta-plan.md` §4.1._


---

## #10 — §4.2 Public cache mirror (deferred)

**Labels:** v1-roadmap  
**URL:** https://github.com/accord-research/rosetta/issues/10


### Parent context — §4 Nuthatch caching integration

**Goal.** Rosetta uses Nuthatch (Rhiza Research, MIT) as its caching layer, gaining shared/cloud-mirror cache support. Repo: <https://github.com/rhiza-research/nuthatch>.

**Goal.** Decided as a V2 item. V1 stays with private/local caches only.

**Done when.** Decision recorded in `README.md`, no further code action for V1.

### Dependencies

deferred to V2; record decision

---
_Imported from `rosetta-plan.md` §4.2._


---

## #11 — §4.3 Cache observability

**Labels:** v1-roadmap  
**URL:** https://github.com/accord-research/rosetta/issues/11


### Parent context — §4 Nuthatch caching integration

**Goal.** Rosetta uses Nuthatch (Rhiza Research, MIT) as its caching layer, gaining shared/cloud-mirror cache support. Repo: <https://github.com/rhiza-research/nuthatch>.

**Goal.** Users can inspect what's cached.

**Where.** `src/rosetta/cli.py` (may be new).

**Approach.** Wrap Nuthatch's CLI as a Rosetta subcommand: `rosetta cache list`, `rosetta cache clear --product <name>`. Nuthatch ships a CLI; thin wrapper sufficient.

**Done when.** `rosetta cache list` lists cached products with sizes; `rosetta cache clear` removes specific entries.

### Dependencies

deps: §4.1

---
_Imported from `rosetta-plan.md` §4.3._


---

## #12 — §5 Shapefile region input

**Labels:** v1-roadmap, depends-on-deepscale  
**URL:** https://github.com/accord-research/rosetta/issues/12


**Goal.** `rosetta.fetch(region=...)` accepts a shapefile path in addition to a bbox.

**Where.**
- `src/rosetta/validate.py` — region resolution
- `src/rosetta/fetch.py` — pass through
- `pyproject.toml` — add `geopandas` and `rasterio` to a `geo` extra
- `tests/test_rosetta.py` — add shapefile path test

**Approach.** Centralize region resolution in `validate.py::resolve_region()`:

- If `region` is a 4-tuple/list of floats → bbox `[lat_s, lat_n, lon_w, lon_e]`.
- If `region` is a string ending `.shp` → load via geopandas, dissolve geometries, return the geometry's bbox **plus** the geometry itself (for clipping).
- If `region` is a `shapely.geometry`/`geopandas.GeoSeries` → same.

Adapters operate on the bbox (for upstream slicing, where supported). Final clipping by geometry (true polygon, not just bbox) happens in `normalize.py::clip_to_geometry()`.

**Pitfalls.**
- **CRS handling.** Shapefiles can be in any CRS. Reproject to EPSG:4326 (lat/lon) before extracting bbox/geometry. Use `gdf.to_crs("EPSG:4326")`.
- **Multi-polygon / disjoint geometries.** Use `gdf.unary_union` to dissolve before extracting bbox. Otherwise you can get geometrically wrong bboxes for, e.g., a multi-island country.
- **Antimeridian crossing.** A polygon spanning -180/180 (Russia, Fiji) needs special handling. xarray's `where()` with the geometry mask handles it correctly only if longitudes are normalized consistently. Document and test.
- **Shapefile dependencies are heavy.** Don't make `geopandas` a required dep — extras only. The `resolve_region()` function should detect missing geopandas and fail with a clear error.
- **Don't re-clip if upstream already clipped.** Some adapters (CDS, OPeNDAP) accept bbox in the request; the result is already bbox-clipped. The geometry-mask step then refines further. If the upstream adapter doesn't accept bbox, do bbox-clip in-memory before geometry-mask.

**Testing.**
- Unit: resolve a synthetic shapefile (write one with `geopandas` in a fixture) and assert bbox + geometry are extracted correctly.
- Unit: bbox input passes through unchanged.
- Unit: missing geopandas yields clear ImportError with install hint.
- Integration: fetch a small region using a real country shapefile (Kenya, say — MAM-relevant) and assert the result is masked outside Kenya.

**Done when.** All three input forms (bbox, .shp path, geometry) work; tests pass; doc example added.

### Dependencies

deps-deepscale: shared region utility consumed by deepscale-plan §29

---
_Imported from `rosetta-plan.md` §5._


---

## #13 — §6.1 Catalog audit and deprecation flags

**Labels:** v1-roadmap  
**URL:** https://github.com/accord-research/rosetta/issues/13


### Parent context — §6 IRI DL sunset migration

Context: IRI Data Library sunset is scheduled April 2026. As of `2026-04-27`, it is past sunset. Successor services at Columbia CCSR are coming online. This section is operationally urgent.

**Goal.** Every catalog entry whose `source_url` points to IRI DL is marked deprecated with a sunset date; health checks emit warnings.

**Where.**
- `src/rosetta/catalog.yaml` — add `deprecated_after: "2026-04-30"` to affected entries
- `src/rosetta/health.py` — emit a warning when a deprecated product is probed
- `src/rosetta/catalog.py` — `list_products()` shows deprecation status

**Approach.**

1. `grep -l "iridl.ldeo.columbia.edu" src/rosetta/catalog.yaml` to find affected entries.
2. Add `deprecated_after` and `successor: <product_name>` (where one exists) to each.
3. Health check warning includes the successor name.

**Pitfalls.**
- **Don't break existing fetches** by deleting entries. Mark them deprecated; preserve functionality for as long as IRI DL responds. Some IRI URLs may still work past the sunset date for varying periods.
- **Surface warnings prominently** but don't make them block. A user running a hindcast pipeline doesn't want a deprecation warning to fail their run.

**Testing.**
- Unit: deprecated entries return a `deprecated` flag from `catalog.info()`.
- Unit: `check_product(...)` emits a warning containing successor name.

**Done when.** Every IRI-DL-backed entry is marked; the warning surface shows successor where known.

### Dependencies

deps: §1 (so the full catalog is in place before audit)

---
_Imported from `rosetta-plan.md` §6.1._


---

## #14 — §6.2 CCSR successor adapter

**Labels:** v1-roadmap, awaiting-external-dep  
**URL:** https://github.com/accord-research/rosetta/issues/14


### Parent context — §6 IRI DL sunset migration

Context: IRI Data Library sunset is scheduled April 2026. As of `2026-04-27`, it is past sunset. Successor services at Columbia CCSR are coming online. This section is operationally urgent.

**Goal.** As Columbia CCSR's NMME / SubX / S2S successor services come online, Rosetta has an adapter to access them.

**Where.**
- `src/rosetta/adapters/ccsr.py` (new)
- catalog entries with `adapter: ccsr` for each migrated product

**Approach.** This task depends on the CCSR services' actual API, which (as of writing) is in active development. Until the API is documented:

1. Create the adapter file as a stub conforming to `AdapterBase`, raising `NotImplementedError` from `fetch()` with an explanatory message linking to the CCSR docs.
2. Track the CCSR rollout — coordinate with whoever is in contact with CCSR (Rhiza, the team, etc.).
3. When the API is documented, wire it through.

**Pitfalls.**
- **CCSR may use different protocols for different datasets.** It might be Zarr, OPeNDAP, REST, or a mix. The adapter may end up dispatching to existing protocol adapters. Don't pre-commit to one design.
- **Authentication.** CCSR may require API keys. Plumb through the existing creds machinery; don't store keys in code.

**Testing.** Defer until API is real.

**Done when.** First CCSR service has a working adapter and one product migrated to use it.

### Dependencies

external (CCSR API publication); ship stub now

---
_Imported from `rosetta-plan.md` §6.2._


---

## #15 — §6.3 Migration table documentation

**Labels:** v1-roadmap  
**URL:** https://github.com/accord-research/rosetta/issues/15


### Parent context — §6 IRI DL sunset migration

Context: IRI Data Library sunset is scheduled April 2026. As of `2026-04-27`, it is past sunset. Successor services at Columbia CCSR are coming online. This section is operationally urgent.

**Goal.** Users have a single table mapping each IRI-DL-backed Rosetta product to its successor.

**Where.** `README.md`, new section "Data source migration".

**Approach.** Maintain a table:

| Old product | Old source | New product | New source | Status |
|---|---|---|---|---|
| `obs/chirps` | IRI DL | `obs/chirps` | Sheerwater (GCS Zarr) | migrated |
| `nmme/cfsv2` | IRI DL OPeNDAP | TBD | CCSR | tracking |
| ... | | | | |

Update each time a successor lands.

**Done when.** Table is current as of last week.

### Dependencies

deps: §6.1; reopen each time §6.2 lands a new successor

---
_Imported from `rosetta-plan.md` §6.3._


---

## #16 — §7 Health checks for new entries

**Labels:** v1-roadmap  
**URL:** https://github.com/accord-research/rosetta/issues/16


**Goal.** Every catalog entry added across §1, §3, §6 has a working health check.

**Where.** `src/rosetta/health.py`, `tests/test_rosetta.py`.

**Approach.** The existing `check_product` and `check_all_products` machinery scales as long as each adapter implements a fast probe. Verify per-adapter probe implementation; add probe support to any adapter that lacks it.

**Pitfalls.**
- **Probes must be fast.** ≤ 30 s per product; ≤ 5 s ideally. A 2-hour CDS request is not a probe.
- **Network-dependent CI.** Mark probe tests with `@pytest.mark.network` so unit CI can skip them; keep a separate "integration" CI job for them.
- **Authenticated probes.** CDS, GCS, etc. — CI needs creds. Use a service account with read-only access; rotate quarterly.

**Testing.** `pytest tests/test_integration.py -m network` should pass for every catalog entry.

**Done when.** All catalog entries pass `check_all_products(probe_remote=True)` in the integration job.

### Dependencies

deps: §1, §3, §6.1 (entries exist)

---
_Imported from `rosetta-plan.md` §7._


---

## #17 — §8 Documentation pass

**Labels:** v1-roadmap  
**URL:** https://github.com/accord-research/rosetta/issues/17


**Goal.** README and module docs reflect the new state.

**Where.** `README.md`, `src/rosetta/__init__.py` docstring, per-module docstrings.

**Approach.** Update:

- Available products tables — add SPEAR, CanSIPS-IC4, Sheerwater-backed obs entries.
- New "Data source migration" section (§6.3).
- "Region input" section showing bbox and shapefile forms.
- Cache configuration section explaining Nuthatch.

**Done when.** README reflects ground truth; an external user can install Rosetta and run an end-to-end fetch from the README.

### Dependencies

deps: most other sections

---
_Imported from `rosetta-plan.md` §8._

