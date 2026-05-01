# Health Checks & Documentation Pass Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

> **PREREQUISITE:** This plan runs after the other three parallel plans (catalog-iri-migration, sheerwater-adapter, nuthatch-caching) have been merged. Do not start this plan until those are complete.

**Goal:** Verify every catalog entry has a working health probe, add a `@pytest.mark.network` marker for remote probe tests, and do a final README documentation pass reflecting all new features.

**Architecture:** Pure audit + doc work. No new adapters or infrastructure. `health.py` should already handle all entry types after the parallel plans land; this plan just validates coverage and writes final docs.

**Tech Stack:** pytest, standard library

---

## File Map

| File | Change |
|------|--------|
| `tests/test_integration.py` | Add `@pytest.mark.network` to all remote probe tests; add probe tests for any new entries missing them |
| `README.md` | Final pass: update product tables, add cache config section, verify migration table is current |
| `src/rosetta/__init__.py` | Update module docstring |

---

## Task 1: Audit health probe coverage

**Files:**
- Read: `src/rosetta/catalog.yaml`, `src/rosetta/health.py`, `tests/test_integration.py`

- [ ] **Step 1: List all catalog entries and their adapter types**

```bash
uv run python -c "
from rosetta import catalog
for p in catalog.list_products():
    cfg = catalog.info(p)
    deprecated = '(deprecated)' if cfg.get('deprecated') else ''
    pending = '(pending_url)' if cfg.get('pending_url') else ''
    print(f'{p:45s} adapter={cfg[\"adapter\"]:12s} {deprecated}{pending}')
"
```
Review the output. Every non-deprecated, non-pending entry needs a working probe.

- [ ] **Step 2: Run all config-level health checks (no network)**

```bash
uv run python -c "
from rosetta import health
import warnings
warnings.filterwarnings('ignore', category=DeprecationWarning)
results = health.check_all_products(probe_remote=False)
failures = [r for r in results if not r['healthy']]
if failures:
    for f in failures:
        print('FAIL:', f['product'], '-', f['message'])
else:
    print('All', len(results), 'products pass config-level health checks')
"
```
Expected: all products pass. If any fail, fix the config issue before proceeding.

- [ ] **Step 3: Write a test asserting all non-pending entries pass config health checks**

Add to `tests/test_rosetta.py`:
```python
def test_all_non_pending_entries_pass_config_health_check():
    """Every catalog entry that isn't pending_url should pass a config-level health check."""
    import warnings
    from rosetta import health, catalog

    failures = []
    for product in catalog.list_products():
        cfg = catalog.info(product)
        if cfg.get("pending_url"):
            continue  # pending entries are expected to return healthy=False
        with warnings.catch_warnings():
            warnings.simplefilter("ignore", DeprecationWarning)
            result = health.check_product(product, probe_remote=False)
        if not result["healthy"]:
            failures.append(f"{product}: {result['message']}")

    assert not failures, "Config health check failures:\n" + "\n".join(failures)
```

- [ ] **Step 4: Run the test**

```bash
uv run pytest tests/test_rosetta.py::test_all_non_pending_entries_pass_config_health_check -v
```
Expected: PASS. If any fail, fix the underlying adapter config issue.

- [ ] **Step 5: Commit**

```bash
git add tests/test_rosetta.py
git commit -m "test: assert all non-pending catalog entries pass config health checks (§7)"
```

---

## Task 2: Add @pytest.mark.network to integration tests

**Files:**
- Modify: `tests/test_integration.py`

- [ ] **Step 1: Read current integration test file**

```bash
uv run python -c "
import ast, sys
with open('tests/test_integration.py') as f:
    src = f.read()
print(src[:3000])
"
```
Identify all test functions that hit a real network endpoint.

- [ ] **Step 2: Ensure every network test has @pytest.mark.network**

For every test function in `tests/test_integration.py` that makes a real network call (anything using `probe_remote=True` or actually downloading data), add the marker if missing:

```python
@pytest.mark.network
def test_opendap_probe_cfsv2():
    ...
```

The `network` marker is already registered in `pyproject.toml`:
```toml
markers = [
    "integration: requires network access",
    "cds: requires CDS credentials in ~/.cdsapirc",
]
```
Add `network` to the markers list:
```toml
markers = [
    "integration: requires network access",
    "cds: requires CDS credentials in ~/.cdsapirc",
    "network: requires live network access to remote data sources",
]
```

- [ ] **Step 3: Add probe tests for the Sheerwater adapter (config-level only)**

Add to `tests/test_integration.py`:
```python
@pytest.mark.network
def test_sheerwater_probe_requires_zarr_url():
    """Sheerwater probe with probe_remote=True but no zarr_url returns healthy=False with clear message."""
    from rosetta.adapters.sheerwater import SheerwaterAdapter
    adapter = SheerwaterAdapter()
    entry = {
        "source": "chirps_v3",
        "variables": {},
        "grid": {"hindcast_range": [1981, 2024]},
        # no zarr_url
    }
    result = adapter.health_check(entry, probe_remote=True)
    assert result["healthy"] is False
    assert "zarr_url" in result["message"]
```

- [ ] **Step 4: Verify unit tests still run without network**

```bash
uv run pytest tests/ -v -m "not network and not integration and not cds"
```
Expected: all pass, no network calls.

- [ ] **Step 5: Commit**

```bash
git add tests/test_integration.py pyproject.toml
git commit -m "test: add network marker to integration tests; add Sheerwater probe test (§7)"
```

---

## Task 3: Final README documentation pass

**Files:**
- Modify: `README.md`

- [ ] **Step 1: Update the "Available products" tables**

In the `README.md` "Available products" section, add the new entries from this release cycle:

Under **NMME hindcasts (S3)** — no change (S3 entries unchanged).

Add a new subsection **NMME placeholders (pending source URL)**:
```markdown
### NMME placeholders (pending source URL)

These entries are in the catalog with correct metadata but no live source URL yet.

| Product | Model | Variables | Notes |
|---------|-------|-----------|-------|
| `nmme/spear` | GFDL SPEAR | precip, temp | Awaiting GFDL THREDDS/NODD public path |
| `nmme/spear-hindcast` | GFDL SPEAR | precip, temp | Awaiting GFDL THREDDS/NODD public path |
| `nmme/spearb` | GFDL SPEARb | sst | Awaiting GFDL THREDDS/NODD public path |
| `nmme/spearb-hindcast` | GFDL SPEARb | sst | Awaiting GFDL THREDDS/NODD public path |
| `nmme/cansipsic4` | CanSIPS-IC4 | precip, temp, sst | MSC Datamart (GRIB2, needs cfgrib work) |
| `nmme/cansipsic4-hindcast` | CanSIPS-IC4 | precip, temp | Hindcast source TBD |
```

- [ ] **Step 2: Add SST to all product table entries that now support it**

In the C3S and NMME NCEI tables, update the Variables column to include `sst` for all GCM entries (e.g. `precip, temp, sst`).

- [ ] **Step 3: Add "Cache configuration" section**

Add after the "Quick CDS setup" section:

```markdown
## Cache configuration

Rosetta caches adapter downloads locally using [Nuthatch](https://github.com/rhiza-research/nuthatch). Cache files live in `~/.nuthatch/rosetta` by default.

```toml
# pyproject.toml (already configured)
[tool.nuthatch.local.zarr]
filesystem = "~/.nuthatch/rosetta"
```

**Inspect the cache:**
```bash
rosetta cache list
```

**Clear a specific product's cache:**
```bash
rosetta cache clear --product nmme/cfsv2
```

Sheerwater-backed products (`obs/chirps`, `obs/era5`, etc.) are already cached upstream by Sheerwater/Nuthatch — Rosetta does not double-cache them.

> **V2:** A public read-only cache mirror for shared infrastructure is planned for V2. V1 is local-only.
```

- [ ] **Step 4: Verify the "Data source migration" table is present and current**

```bash
grep -n "Data source migration" README.md
```
Expected: finds the section added in the catalog plan. If missing, add it now (see `2026-04-30-catalog-iri-migration.md` Task 7 Step 1 for the table content).

- [ ] **Step 5: Verify the "Dual-domain usage" section is present**

```bash
grep -n "Dual-domain usage" README.md
```
Expected: finds the section. If missing, add it (see `2026-04-30-catalog-iri-migration.md` Task 7 Step 2).

- [ ] **Step 6: Verify README is internally consistent**

```bash
uv run python -c "
with open('README.md') as f:
    content = f.read()

checks = [
    ('## Data source migration', 'migration table'),
    ('## Dual-domain usage', 'dual-domain example'),
    ('## Cache configuration', 'cache config section'),
    ('nmme/spear', 'SPEAR placeholder entry'),
    ('sst', 'SST variable mentioned'),
    ('nuthatch', 'Nuthatch mentioned'),
]
for marker, desc in checks:
    assert marker in content, f'README missing: {desc} ({marker!r})'
    print(f'OK: {desc}')
"
```
Expected: all checks print OK.

- [ ] **Step 7: Commit**

```bash
git add README.md
git commit -m "docs: final README pass — products table, cache config, SST (§8)"
```

---

## Task 4: Update __init__.py docstring

**Files:**
- Modify: `src/rosetta/__init__.py`

- [ ] **Step 1: Read current __init__.py**

```bash
uv run python -c "import rosetta; help(rosetta)"
```

- [ ] **Step 2: Update the module docstring to reflect new features**

Open `src/rosetta/__init__.py` and update or add a module-level docstring:

```python
"""Rosetta — federated data integration for seasonal climate forecasting.

Provides a unified fetch() API across CDS, OPeNDAP, NCEI, S3, HTTP, and
Sheerwater data sources. All outputs are CF-aligned xarray Datasets.

New in this release:
- SST variable support on all C3S and NMME NCEI entries
- Sheerwater adapter for cloud-native CHIRPS, ERA5, IMERG, GHCN (adapter ready;
  catalog entries pending deepscale coordination)
- Nuthatch caching at the adapter level (local cache at ~/.nuthatch/rosetta)
- IRI Data Library entries marked deprecated with successor references
- SPEAR and CanSIPS-IC4 catalog placeholders (pending source URL confirmation)

Quick start:
    import rosetta
    ds = rosetta.fetch("nmme/cfsv2", variable="precip", init="2025-02",
                       target="MAM", region=[-12, 6, 28, 42], hindcast=(2010, 2015))
"""
```

- [ ] **Step 3: Run import check**

```bash
uv run python -c "import rosetta; print(rosetta.__doc__[:100])"
```
Expected: prints first 100 chars of the docstring.

- [ ] **Step 4: Run full test suite one final time**

```bash
uv run pytest tests/ -v -m "not network and not integration and not cds"
```
Expected: all pass.

- [ ] **Step 5: Final commit**

```bash
git add src/rosetta/__init__.py
git commit -m "docs: update __init__.py module docstring for v1 release (§8)"
```
