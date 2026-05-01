# Rosetta v1 Roadmap — Implementation Design

**Date:** 2026-04-30  
**Issues:** #1–17 (excluding #7 §3.2 and #12 §5 — depends-on-deepscale)  
**Approach:** Option C — quick catalog/doc wins batched, heavy infrastructure (Sheerwater, Nuthatch) in parallel agents

---

## Scope

15 of 17 issues are in scope today. Deferred:
- **#7 §3.2** Sheerwater-backed catalog entries — depends-on-deepscale
- **#12 §5** Shapefile region input — depends-on-deepscale

Environment change required first: `requires-python` bumped to `>=3.12`, sheerwater and nuthatch added as dependencies (both require Python ≥3.12). **Done.**

---

## Section 1 — IRI Migration (§6, operationally urgent)

Issues: #13 §6.1, #14 §6.2, #15 §6.3

IRI Data Library sunset as of 2026-04-30. Five existing catalog entries point at IRI URLs.

### Affected entries
Found via `grep "iridl.ldeo.columbia.edu" src/rosetta/catalog.yaml`:
- `nmme/cfsv2` — opendap → IRI
- `nmme/cfsv2-forecast` — opendap → IRI
- `nmme/ccsm4-iri` — opendap → IRI
- `nmme/geoss2s-forecast` — opendap → IRI
- `c3s/ecmwf-seas51c` — iridl adapter

### catalog.yaml changes
Add to each affected entry:
```yaml
deprecated_after: "2026-04-30"
successor: "<product_name_or_TBD>"
```

Successor mappings:
- `nmme/cfsv2` → successor TBD (CCSR tracking)
- `nmme/cfsv2-forecast` → successor TBD (CCSR tracking)
- `nmme/ccsm4-iri` → `nmme/ccsm4` (NCEI-backed already exists)
- `nmme/geoss2s-forecast` → `nmme/geoss2s` (NCEI-backed already exists)
- `c3s/ecmwf-seas51c` → `c3s/ecmwf-monthly` (CDS-backed already exists)

### catalog.py changes
`info()` returns a `deprecated` boolean and `successor` string when present. `list_products()` optionally filters by `deprecated=False`.

### health.py changes
When `check_product()` is called on a deprecated entry, emit `warnings.warn(...)` with the successor name before probing. Do not block or error — existing fetches continue to work while IRI URLs still respond.

### CCSR stub (§6.2)
Skipped — CCSR successor API is not yet publicly documented. No code action. Issue #14 remains open.

### Migration table (§6.3)
New section "Data source migration" added to `README.md` with a table mapping old IRI-backed products to successors and status (migrated / tracking / pending).

---

## Section 2 — GCM Catalog Completion (§1)

Issues: #1 §1.1, #2 §1.2, #3 §1.3, #4 §1.4

### CanSIPS-IC4 entries (§1.2)
Two new entries in `catalog.yaml`: `nmme/cansipsic4` (real-time) and `nmme/cansipsic4-hindcast`.
- **Adapter:** `http` (same as CHIRPS)
- **Source:** ECCC MSC Datamart — base URL `https://dd.meteo.gc.ca/model_cansips/`; exact file layout (directory structure, filename convention, NetCDF variable names) must be confirmed during implementation by browsing the live directory.
- **Variables:** `precip`, `temp`, `sst`
- **Members:** 20 (max; some inits return fewer — documented)
- **Hindcast range:** 1981–2010
- May require a light extension to `adapters/http.py` for MSC file layout (monthly NetCDF per init month).

### SPEAR / SPEARb entries (§1.1)
Four placeholder entries: `nmme/spear`, `nmme/spear-hindcast`, `nmme/spearb`, `nmme/spearb-hindcast`.
- **Adapter:** `opendap` (structurally ready for when URL is confirmed)
- **source_url:** `TBD` with a `note: "awaiting GFDL THREDDS or NODD public path; see https://github.com/accord-research/rosetta/issues/1"`
- **Variables:** `precip` (SPEAR), `sst` (SPEARb)
- **Members:** 15–30 depending on init (set to 30, documented)
- **Hindcast range:** 1991–2020
- Mark `pending_url: true` — health check returns `healthy: false` with a clear message rather than an error.

### SST variable on existing entries (§1.3)
Audit every C3S and NMME entry. Add `sst:` block where upstream exposes it:
```yaml
sst: { native_name: sea_surface_temperature, units: K, target_units: K }
```
- **CDS entries:** `native_name: sea_surface_temperature` matches CDS API variable name
- **OPeNDAP/NCEI entries:** verify variable name in source (typically `sst` or `SST`)
- **S3 hindcast entries:** check s3://acc.ord/nmme-hindcasts/ for SST files
- **normalize.py:** confirm SST passes through with NaN over land preserved (no fill)
- **Pitfall documented:** SST grid may differ from precip grid for the same model

### PyCPT reference coverage test (§1.4)
`tests/conftest.py` gets `PYCPT_REFERENCE_GCMS` dict mapping all 20 PyCPT predictor names to `(rosetta_product, variable)` pairs. `tests/test_rosetta.py` asserts every entry resolves via `catalog.info()`. Entries with `pending_url: true` are asserted to exist in the catalog but skipped for the probe assertion.

---

## Section 3 — Sheerwater Adapter (§3)

Issues: #6 §3.1, #8 §3.3  
Note: §3.2 (catalog entries using this adapter) deferred — depends-on-deepscale

### SheerwaterAdapter (§3.1)
New file `src/rosetta/adapters/sheerwater.py`.

Interface:
```python
class SheerwaterAdapter(AdapterBase):
    def fetch(self, entry, variable, init, target, region, hindcast_range, **kwargs) -> xr.Dataset:
        fn = getattr(sheerwater.data, entry["source"])
        start_time, end_time = _to_time_range(init, target, hindcast_range)
        raw = fn(start_time=start_time, end_time=end_time, region=region, **entry.get("source_kwargs", {}))
        return raw  # normalization layer handles renames
```

- Catalog `source:` field names the Sheerwater function (e.g. `chirps_v3`)
- `_to_time_range()` converts Rosetta's init+target+hindcast_range to calendar start/end
- Does **not** apply `@nuthatch.cache()` — Sheerwater is already Nuthatch-cached upstream
- Registered in `adapters/__init__.py`

### Health check probe (§3.3)
Probe opens the underlying Zarr store URL directly (not via the high-level function), reads coordinate metadata only, asserts time range overlaps catalog's declared range. Target: <5s. GCS connectivity errors classified as transient, not broken.

---

## Section 4 — Nuthatch Caching (§4)

Issues: #9 §4.1, #10 §4.2, #11 §4.3

### Cache integration (§4.1)
Cache boundary: per-adapter raw download functions (not end-to-end `fetch()`). This keeps normalization changes from causing cache misses.

Each adapter's download function wrapped with `@nuthatch.cache(version=<N>)`. Version constant lives in the adapter file; bump it when URL or post-processing changes.

`pyproject.toml` gets:
```toml
[tool.nuthatch]
backend = "zarr"
local_cache = "~/.nuthatch/rosetta"
```

Exclusions:
- `SheerwaterAdapter` — skip, already cached upstream
- Health check probes — must always hit the network

Pre-cache validation: assert non-empty, non-all-NaN, expected dim names before Nuthatch persists a result.

### Public mirror deferred (§4.2)
Decision recorded in README: public/shared cache mirror is a V2 item. V1 is local cache only.

### Cache observability CLI (§4.3)
New `src/rosetta/cli.py` with a `rosetta` entry point:
- `rosetta cache list` — lists cached products with sizes
- `rosetta cache clear --product <name>` — removes specific entries

Thin wrapper over Nuthatch's CLI. Entry point registered in `pyproject.toml` under `[project.scripts]`.

---

## Section 5 — Health Checks + Docs (§7, §8, §2, §10)

Issues: #16 §7, #17 §8, #5 §2, #10 §4.2

### Health checks audit (§7)
After §1 and §3 land: verify every new entry and adapter has a working probe. Add `@pytest.mark.network` to probe tests. Separate integration CI job.

### Documentation pass (§8)
- `README.md`: update available products tables (add CanSIPS-IC4, SPEAR placeholders, Sheerwater-backed obs)
- Add "Cache configuration" section (Nuthatch)
- Add "Data source migration" section (§6.3)
- Add dual-domain usage example (§2): three `rosetta.fetch()` calls showing SST predictor + PRCP predictor + predictand
- Remove `fetch_predictor_pair()` pattern — explicitly document that single orthogonal `fetch()` calls are the convention
- `src/rosetta/__init__.py` docstring updated

---

## Parallel agent groupings

| Agent | Issues | Key files |
|-------|--------|-----------|
| **A — Catalog + IRI migration** | §6.1, §6.2, §6.3, §1.1, §1.2, §1.3, §1.4, §2, §10 | `catalog.yaml`, `catalog.py`, `health.py`, `adapters/ccsr.py`, `README.md`, `tests/` |
| **B — Sheerwater adapter** | §3.1, §3.3 | `adapters/sheerwater.py`, `adapters/__init__.py`, `health.py` |
| **C — Nuthatch caching** | §4.1, §4.2, §4.3 | `fetch.py`, `adapters/*.py`, `cli.py`, `pyproject.toml` |
| **Sequential after A+B+C** | §7, §8 | `health.py`, `README.md`, `__init__.py` |

Agents B and C have no file overlap. Agent A touches `health.py` (deprecation warnings) and Agent B also touches `health.py` (Sheerwater probe) — these changes are in different functions so can be merged cleanly.

---

## Out of scope today
- #7 §3.2 Sheerwater-backed catalog entries (depends-on-deepscale)
- #12 §5 Shapefile region input (depends-on-deepscale)
- #14 §6.2 CCSR stub adapter (CCSR API not yet publicly documented — wait)
- SPEAR live URL (pending GFDL/NODD public path)
