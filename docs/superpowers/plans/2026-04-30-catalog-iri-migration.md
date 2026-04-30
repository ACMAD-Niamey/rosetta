# Catalog & IRI Migration Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Mark IRI-backed catalog entries deprecated, add SPEAR/CanSIPS-IC4 placeholders, add SST variables to existing entries, add PyCPT coverage test, and add migration + dual-domain docs to README.

**Architecture:** All changes are confined to `catalog.yaml` (data), `catalog.py` (API), `health.py` (warnings), `normalize.py` (SST NaN handling), `tests/` (coverage), and `README.md` (docs). No new adapter code — this track is purely catalog + metadata work.

**Tech Stack:** PyYAML (catalog), pytest, standard library warnings module

---

## File Map

| File | Change |
|------|--------|
| `src/rosetta/catalog.yaml` | Add `deprecated_after`/`successor` to 5 IRI entries; add 6 placeholder entries (4 SPEAR, 2 CanSIPS-IC4); add `sst` variable blocks to ~20 existing entries |
| `src/rosetta/catalog.py` | `info()` surfaces `deprecated` bool + `successor`; `list_products()` gains optional `include_deprecated` param |
| `src/rosetta/health.py` | Emit `warnings.warn` when probing a deprecated entry; return `healthy: false` with clear message for `pending_url: true` entries |
| `src/rosetta/normalize.py` | Add SST to `_CONVERSIONS` pass-through (K→K, no-op) and confirm NaN over land is preserved |
| `tests/conftest.py` | Add `PYCPT_REFERENCE_GCMS` mapping constant |
| `tests/test_rosetta.py` | Add `test_catalog_deprecated_entries`, `test_catalog_info_deprecated`, `test_pycpt_reference_coverage` |
| `README.md` | Add "Data source migration" table; add "Dual-domain usage" example |

---

## Task 1: Deprecate IRI-backed entries in catalog.yaml

**Files:**
- Modify: `src/rosetta/catalog.yaml`

The five IRI-backed entries to update are at lines 1, 30, 49, 67 (opendap entries) and 693 (iridl entry). Add two fields after the `adapter:` line in each:

- [ ] **Step 1: Add deprecation fields to `nmme/cfsv2`**

Open `src/rosetta/catalog.yaml`. Find the `nmme/cfsv2:` block (line 1). Add after the `adapter: opendap` line:
```yaml
nmme/cfsv2:
  adapter: opendap
  deprecated_after: "2026-04-30"
  successor: null  # tracking CCSR — see https://github.com/accord-research/rosetta/issues/14
```

- [ ] **Step 2: Add deprecation fields to `nmme/cfsv2-forecast`**

Find `nmme/cfsv2-forecast:` (line ~30). Add:
```yaml
nmme/cfsv2-forecast:
  adapter: opendap
  deprecated_after: "2026-04-30"
  successor: null  # tracking CCSR — see https://github.com/accord-research/rosetta/issues/14
```

- [ ] **Step 3: Add deprecation fields to `nmme/ccsm4-iri`**

Find `nmme/ccsm4-iri:` (line ~49). Add:
```yaml
nmme/ccsm4-iri:
  adapter: opendap
  deprecated_after: "2026-04-30"
  successor: "nmme/ccsm4"
```

- [ ] **Step 4: Add deprecation fields to `nmme/geoss2s-forecast`**

Find `nmme/geoss2s-forecast:` (line ~67). Add:
```yaml
nmme/geoss2s-forecast:
  adapter: opendap
  deprecated_after: "2026-04-30"
  successor: "nmme/geoss2s"
```

- [ ] **Step 5: Add deprecation fields to `c3s/ecmwf-seas51c`**

Find `c3s/ecmwf-seas51c:` (line ~693). Add:
```yaml
c3s/ecmwf-seas51c:
  adapter: iridl
  deprecated_after: "2026-04-30"
  successor: "c3s/ecmwf-monthly"
```

- [ ] **Step 6: Verify catalog still parses**

Run:
```bash
uv run python -c "import yaml; d = yaml.safe_load(open('src/rosetta/catalog.yaml')); print(len(d), 'entries loaded')"
```
Expected: prints number of entries with no error.

---

## Task 2: Surface deprecation in catalog.py

**Files:**
- Modify: `src/rosetta/catalog.py`

- [ ] **Step 1: Write the failing tests**

Add to `tests/test_rosetta.py`:
```python
def test_catalog_deprecated_entries():
    from rosetta import catalog
    deprecated = [p for p in catalog.list_products() if catalog.info(p).get("deprecated")]
    assert len(deprecated) >= 5  # at minimum the 5 IRI entries


def test_catalog_info_deprecated():
    from rosetta import catalog
    info = catalog.info("nmme/cfsv2")
    assert info["deprecated"] is True
    assert "deprecated_after" in info
    assert "successor" in info


def test_catalog_info_not_deprecated():
    from rosetta import catalog
    info = catalog.info("c3s/ecmwf")
    assert info.get("deprecated", False) is False
```

- [ ] **Step 2: Run to verify they fail**

```bash
uv run pytest tests/test_rosetta.py::test_catalog_deprecated_entries tests/test_rosetta.py::test_catalog_info_deprecated tests/test_rosetta.py::test_catalog_info_not_deprecated -v
```
Expected: FAIL (KeyError or AssertionError — `deprecated` key not yet in info output).

- [ ] **Step 3: Update `catalog.py` to compute `deprecated` and expose `successor`**

Replace the entire `catalog.py` with:
```python
import yaml
from datetime import date
from pathlib import Path

_CATALOG_PATH = Path(__file__).parent / "catalog.yaml"
with open(_CATALOG_PATH) as f:
    _catalog = yaml.safe_load(f)


def _enrich(entry: dict) -> dict:
    """Add computed fields (deprecated) to a raw catalog entry dict."""
    result = dict(entry)
    deprecated_after = result.get("deprecated_after")
    if deprecated_after:
        result["deprecated"] = date.fromisoformat(deprecated_after) <= date.today()
    else:
        result["deprecated"] = False
    return result


def list_products(include_deprecated: bool = True) -> list[str]:
    if include_deprecated:
        return list(_catalog.keys())
    return [k for k, v in _catalog.items()
            if not (_enrich(v).get("deprecated", False))]


def info(product_name: str) -> dict:
    if product_name not in _catalog:
        raise KeyError(f"Product not found: {product_name}")
    return _enrich(_catalog[product_name])


get = info
```

- [ ] **Step 4: Run the tests — they should pass**

```bash
uv run pytest tests/test_rosetta.py::test_catalog_deprecated_entries tests/test_rosetta.py::test_catalog_info_deprecated tests/test_rosetta.py::test_catalog_info_not_deprecated -v
```
Expected: all 3 PASS.

- [ ] **Step 5: Run full test suite to check for regressions**

```bash
uv run pytest tests/test_rosetta.py -v
```
Expected: all previously passing tests still pass.

- [ ] **Step 6: Commit**

```bash
git add src/rosetta/catalog.yaml src/rosetta/catalog.py tests/test_rosetta.py
git commit -m "feat: mark IRI-backed catalog entries deprecated with successors"
```

---

## Task 3: Emit deprecation warnings in health.py

**Files:**
- Modify: `src/rosetta/health.py`

- [ ] **Step 1: Write the failing test**

Add to `tests/test_rosetta.py`:
```python
import warnings

def test_health_check_deprecated_emits_warning():
    from rosetta import health
    with warnings.catch_warnings(record=True) as w:
        warnings.simplefilter("always")
        result = health.check_product("nmme/cfsv2")
    assert any("deprecated" in str(warning.message).lower() for warning in w), \
        f"Expected deprecation warning, got: {[str(x.message) for x in w]}"


def test_health_check_non_deprecated_no_warning():
    from rosetta import health
    with warnings.catch_warnings(record=True) as w:
        warnings.simplefilter("always")
        health.check_product("c3s/ecmwf")
    deprecation_warnings = [x for x in w if "deprecated" in str(x.message).lower()]
    assert len(deprecation_warnings) == 0
```

- [ ] **Step 2: Run to verify they fail**

```bash
uv run pytest tests/test_rosetta.py::test_health_check_deprecated_emits_warning tests/test_rosetta.py::test_health_check_non_deprecated_no_warning -v
```
Expected: `test_health_check_deprecated_emits_warning` FAIL (no warning emitted yet).

- [ ] **Step 3: Update `health.py` to warn on deprecated entries**

Replace `health.py` with:
```python
import warnings
from datetime import datetime, timezone

from . import catalog
from .adapters import get_adapter


def _utc_now():
    return datetime.now(timezone.utc).isoformat()


def check_product(product, probe_remote=False):
    """Return health status for one catalog product."""
    config = catalog.get(product)

    if config.get("deprecated"):
        successor = config.get("successor")
        successor_msg = f" Migrate to: {successor}." if successor else " No successor identified yet."
        warnings.warn(
            f"{product} is deprecated (sunset: {config['deprecated_after']}).{successor_msg}",
            DeprecationWarning,
            stacklevel=2,
        )

    if config.get("pending_url"):
        return {
            "product": product,
            "adapter": config["adapter"],
            "checked_at": _utc_now(),
            "healthy": False,
            "kind": "config",
            "message": config.get("pending_url_note", "Source URL not yet confirmed. See issue tracker."),
            "probe_remote": bool(probe_remote),
        }

    adapter_name = config["adapter"]
    adapter = get_adapter(adapter_name)
    result = adapter.health_check(config, probe_remote=probe_remote)
    return {
        "product": product,
        "adapter": adapter_name,
        "checked_at": _utc_now(),
        **result,
    }


def check_all_products(probe_remote=False):
    """Return health status for all catalog products."""
    statuses = []
    for product in catalog.list_products():
        try:
            statuses.append(check_product(product, probe_remote=probe_remote))
        except Exception as e:
            config = catalog.get(product)
            statuses.append(
                {
                    "product": product,
                    "adapter": config.get("adapter", "unknown"),
                    "checked_at": _utc_now(),
                    "healthy": False,
                    "kind": "runtime",
                    "message": f"Health check failed: {e}",
                    "probe_remote": bool(probe_remote),
                }
            )
    return statuses
```

- [ ] **Step 4: Run the tests**

```bash
uv run pytest tests/test_rosetta.py::test_health_check_deprecated_emits_warning tests/test_rosetta.py::test_health_check_non_deprecated_no_warning -v
```
Expected: both PASS.

- [ ] **Step 5: Run full suite**

```bash
uv run pytest tests/test_rosetta.py -v
```
Expected: all pass.

- [ ] **Step 6: Commit**

```bash
git add src/rosetta/health.py tests/test_rosetta.py
git commit -m "feat: emit DeprecationWarning when probing IRI-sunset entries"
```

---

## Task 4: Add SPEAR/SPEARb and CanSIPS-IC4 placeholder entries

**Files:**
- Modify: `src/rosetta/catalog.yaml`

These entries are structural placeholders — correct metadata, adapter type, and variable definitions, but `pending_url: true` because the source URL requires additional work (GFDL THREDDS path for SPEAR; GRIB2 support for CanSIPS-IC4 MSC Datamart).

- [ ] **Step 1: Add `nmme/spear` entry** at end of catalog.yaml

```yaml
# GFDL SPEAR (precipitation) — pending source URL
# Source: GFDL THREDDS or NOAA NODD (GRIB2 or OPeNDAP, path TBD)
# See: https://github.com/accord-research/rosetta/issues/1
nmme/spear:
  adapter: opendap
  pending_url: true
  pending_url_note: "GFDL SPEAR OPeNDAP path not yet confirmed. Track https://github.com/accord-research/rosetta/issues/1"
  source_url: null
  variables:
    precip:
      native_name: prec
      units: "mm/day"
      target_units: "mm/day"
    temp:
      native_name: tref
      units: K
      target_units: C
  grid:
    lat_res: 1.0
    lon_res: 1.0
    members: 30  # 15–30 depending on init; set to max
    hindcast_range: [1991, 2020]
```

- [ ] **Step 2: Add `nmme/spear-hindcast` entry**

```yaml
nmme/spear-hindcast:
  adapter: opendap
  pending_url: true
  pending_url_note: "GFDL SPEAR hindcast OPeNDAP path not yet confirmed. Track https://github.com/accord-research/rosetta/issues/1"
  source_url: null
  variables:
    precip:
      native_name: prec
      units: "mm/day"
      target_units: "mm/day"
    temp:
      native_name: tref
      units: K
      target_units: C
  grid:
    lat_res: 1.0
    lon_res: 1.0
    members: 30
    hindcast_range: [1991, 2020]
```

- [ ] **Step 3: Add `nmme/spearb` entry (SST)**

```yaml
# GFDL SPEARb (sea surface temperature) — pending source URL
# PyCPT uses SPEARb specifically for the SST predictor track
nmme/spearb:
  adapter: opendap
  pending_url: true
  pending_url_note: "GFDL SPEARb OPeNDAP path not yet confirmed. Track https://github.com/accord-research/rosetta/issues/1"
  source_url: null
  variables:
    sst:
      native_name: sst
      units: K
      target_units: K
  grid:
    lat_res: 1.0
    lon_res: 1.0
    members: 30
    hindcast_range: [1991, 2020]
```

- [ ] **Step 4: Add `nmme/spearb-hindcast` entry**

```yaml
nmme/spearb-hindcast:
  adapter: opendap
  pending_url: true
  pending_url_note: "GFDL SPEARb hindcast OPeNDAP path not yet confirmed. Track https://github.com/accord-research/rosetta/issues/1"
  source_url: null
  variables:
    sst:
      native_name: sst
      units: K
      target_units: K
  grid:
    lat_res: 1.0
    lon_res: 1.0
    members: 30
    hindcast_range: [1991, 2020]
```

- [ ] **Step 5: Add `nmme/cansipsic4` entry**

```yaml
# CanSIPS-IC4 (precipitation + SST) — pending GRIB2 adapter
# Source: ECCC MSC Datamart https://dd.meteo.gc.ca/today/model_cansips/100km/forecast/
# Format: GRIB2 (per-member files, requires cfgrib). Hindcast source TBD.
# See: https://github.com/accord-research/rosetta/issues/2
nmme/cansipsic4:
  adapter: http
  pending_url: true
  pending_url_note: "CanSIPS-IC4 MSC Datamart is GRIB2 format; HTTP adapter needs cfgrib extension. Track https://github.com/accord-research/rosetta/issues/2"
  source_url: "https://dd.meteo.gc.ca/today/model_cansips/100km/forecast/"
  variables:
    precip:
      native_name: PrecipRate
      units: "mm/day"
      target_units: "mm/day"
    temp:
      native_name: AirTemp
      units: K
      target_units: C
    sst:
      native_name: SeaSfcHeight-Geoid
      units: K
      target_units: K
  grid:
    lat_res: 1.0
    lon_res: 1.0
    members: 20  # P00M–P09M per model (2 models = 20 total)
    hindcast_range: [1981, 2010]
```

- [ ] **Step 6: Add `nmme/cansipsic4-hindcast` entry**

```yaml
nmme/cansipsic4-hindcast:
  adapter: http
  pending_url: true
  pending_url_note: "CanSIPS-IC4 hindcast source not yet identified. Track https://github.com/accord-research/rosetta/issues/2"
  source_url: null
  variables:
    precip:
      native_name: PrecipRate
      units: "mm/day"
      target_units: "mm/day"
    temp:
      native_name: AirTemp
      units: K
      target_units: C
  grid:
    lat_res: 1.0
    lon_res: 1.0
    members: 20
    hindcast_range: [1981, 2010]
```

- [ ] **Step 7: Verify catalog still parses**

```bash
uv run python -c "import yaml; d = yaml.safe_load(open('src/rosetta/catalog.yaml')); print(len(d), 'entries'); assert 'nmme/spear' in d; assert 'nmme/spearb' in d; assert 'nmme/cansipsic4' in d; print('all new entries present')"
```
Expected: prints entry count and "all new entries present".

- [ ] **Step 8: Verify health checks return healthy=false with message (not an exception)**

```bash
uv run python -c "
from rosetta import health
r = health.check_product('nmme/spear')
assert r['healthy'] is False
assert 'pending' in r['message'].lower() or 'url' in r['message'].lower()
print('PASS:', r['message'])
"
```
Expected: PASS with the pending_url_note message.

- [ ] **Step 9: Commit**

```bash
git add src/rosetta/catalog.yaml
git commit -m "feat: add SPEAR, SPEARb, CanSIPS-IC4 placeholder catalog entries"
```

---

## Task 5: Add SST variable blocks to existing catalog entries

**Files:**
- Modify: `src/rosetta/catalog.yaml`

Audit all C3S (CDS-backed) and NMME entries and add `sst:` blocks. CDS seasonal forecast data includes `sea_surface_temperature` as a requestable variable for all coupled GCMs. S3 hindcast entries: SST is not in the current S3 archive (only precip + temp), so skip those.

- [ ] **Step 1: Add SST to all CDS-backed C3S entries**

The CDS native variable name for SST is `sea_surface_temperature`. Add this block to each of the following entries in `catalog.yaml`:
`c3s/ecmwf`, `c3s/ecmwf-monthly`, `c3s/eccc-cansips`, `c3s/eccc-cansipsv3`, `c3s/meteofrance`, `c3s/cmcc`, `c3s/dwd`, `c3s/ukmo`, `c3s/jma`, `c3s/jma-cps2`, `c3s/dwd-gcfs21`, `c3s/meteofrance-daily`, `c3s/cmcc-daily`, `c3s/dwd-daily`, `c3s/eccc-daily`, `c3s/ukmo-daily`

Under each entry's `variables:` block, add:
```yaml
    sst:
      native_name: sea_surface_temperature
      units: K
      target_units: K
```

- [ ] **Step 2: Add SST to NCEI-backed NMME entries**

The NCEI entries (`nmme/ccsm4`, `nmme/geoss2s`, `nmme/gemnemo`) serve daily forecast data. SST native variable name for NCEI is `sst`. Add to each:
```yaml
    sst:
      native_name: sst
      units: K
      target_units: K
```

- [ ] **Step 3: Confirm S3 hindcast entries do NOT get SST blocks**

The S3 entries (`nmme/ccsm4-hindcast`, `nmme/geoss2s-hindcast`, `nmme/gemnemo-hindcast`, `nmme/cesm1-hindcast`, `nmme/canesm5-hindcast`, `nmme/gem52nemo-hindcast`) only contain precip + temp in the archive. Leave them as-is.

- [ ] **Step 4: Write the SST catalog test**

Add to `tests/test_rosetta.py`:
```python
def test_c3s_entries_have_sst():
    from rosetta import catalog
    c3s_products = [p for p in catalog.list_products() if p.startswith("c3s/") and not catalog.info(p).get("deprecated")]
    for product in c3s_products:
        cfg = catalog.info(product)
        assert "sst" in cfg["variables"], \
            f"{product} is missing sst variable block"
        sst = cfg["variables"]["sst"]
        assert sst["native_name"] == "sea_surface_temperature"
        assert sst["units"] == "K"
        assert sst["target_units"] == "K"


def test_ncei_entries_have_sst():
    from rosetta import catalog
    ncei_products = ["nmme/ccsm4", "nmme/geoss2s", "nmme/gemnemo"]
    for product in ncei_products:
        cfg = catalog.info(product)
        assert "sst" in cfg["variables"], f"{product} is missing sst variable block"
```

- [ ] **Step 5: Run tests**

```bash
uv run pytest tests/test_rosetta.py::test_c3s_entries_have_sst tests/test_rosetta.py::test_ncei_entries_have_sst -v
```
Expected: both PASS.

- [ ] **Step 6: Run full catalog test to confirm no regressions**

```bash
uv run pytest tests/test_rosetta.py::test_catalog_loads tests/test_rosetta.py::test_catalog_variable_mapping -v
```
Expected: PASS.

- [ ] **Step 7: Confirm SST normalization leaves NaN over land intact**

Add to `tests/test_rosetta.py`:
```python
def test_normalize_sst_preserves_nan():
    import numpy as np
    import xarray as xr
    from rosetta.normalize import normalize

    # SST grid: ocean cells have values, land cells are NaN
    data = np.array([[np.nan, 300.0], [301.0, np.nan]], dtype=np.float32)
    ds = xr.Dataset(
        {"sst": (["latitude", "longitude"], data)},
        coords={"latitude": [0.0, 1.0], "longitude": [30.0, 31.0]},
    )
    config = {
        "variables": {
            "sst": {"native_name": "sst", "units": "K", "target_units": "K"}
        }
    }
    result = normalize(ds, config, "sst")
    assert "sst" in result
    assert np.isnan(result["sst"].values[0, 0]), "NaN over land should be preserved"
    assert np.isnan(result["sst"].values[1, 1]), "NaN over land should be preserved"
    assert not np.isnan(result["sst"].values[0, 1]), "Ocean value should not be NaN"
```

Run:
```bash
uv run pytest tests/test_rosetta.py::test_normalize_sst_preserves_nan -v
```
Expected: PASS (normalize already passes NaN through; no code change needed — this test verifies the invariant).

- [ ] **Step 8: Commit**

```bash
git add src/rosetta/catalog.yaml tests/test_rosetta.py
git commit -m "feat: add sst variable block to all C3S and NCEI catalog entries"
```

---

## Task 6: PyCPT reference coverage test

**Files:**
- Modify: `tests/conftest.py`, `tests/test_rosetta.py`

- [ ] **Step 1: Add `PYCPT_REFERENCE_GCMS` to conftest.py**

Append to `tests/conftest.py`:
```python
# Mapping of PyCPT predictor names to (rosetta_product, variable) pairs.
# Source: pycpt-reference/pycpt_seasonal_forecast.py PRCP_PREDICTOR_NAMES + SST_PREDICTOR_NAMES
PYCPT_REFERENCE_GCMS = {
    # PRCP predictors
    "GEOSS2S.PRCP":       ("nmme/geoss2s",         "precip"),
    "SPEAR.PRCP":         ("nmme/spear",            "precip"),
    "CCSM4.PRCP":         ("nmme/ccsm4-iri",        "precip"),
    "CFSv2.PRCP":         ("nmme/cfsv2",            "precip"),
    "CanSIPSIC4.PRCP":    ("nmme/cansipsic4",       "precip"),
    "SEAS51c.PRCP":       ("c3s/ecmwf-seas51c",     "precip"),
    "SPSv3p5.PRCP":       ("c3s/cmcc",              "precip"),
    "GCFS2p1.PRCP":       ("c3s/dwd-gcfs21",        "precip"),
    "CPS2.PRCP":          ("c3s/jma-cps2",          "precip"),
    "METEOFRANCE9.PRCP":  ("c3s/meteofrance",       "precip"),
    # SST predictors
    "GEOSS2S.SST":        ("nmme/geoss2s",           "sst"),
    "SPEARb.SST":         ("nmme/spearb",            "sst"),
    "CCSM4.SST":          ("nmme/ccsm4",             "sst"),
    "CFSv2.SST":          ("nmme/cfsv2",             "sst"),
    "CanSIPSIC4.SST":     ("nmme/cansipsic4",        "sst"),
    "SEAS51c.SST":        ("c3s/ecmwf-seas51c",      "sst"),
    "SPSv3p5.SST":        ("c3s/cmcc",               "sst"),
    "GCFS2p1.SST":        ("c3s/dwd-gcfs21",         "sst"),
    "CPS2.SST":           ("c3s/jma-cps2",           "sst"),
    "METEOFRANCE9.SST":   ("c3s/meteofrance",        "sst"),
}
```

- [ ] **Step 2: Write the coverage test**

Add to `tests/test_rosetta.py`:
```python
def test_pycpt_reference_coverage():
    """Every PyCPT reference GCM maps to a resolvable Rosetta catalog entry."""
    from rosetta import catalog
    from tests.conftest import PYCPT_REFERENCE_GCMS

    missing_products = []
    missing_variables = []

    for pycpt_name, (product, variable) in PYCPT_REFERENCE_GCMS.items():
        try:
            cfg = catalog.info(product)
        except KeyError:
            missing_products.append(f"{pycpt_name} -> {product} (not in catalog)")
            continue

        if variable not in cfg["variables"]:
            missing_variables.append(
                f"{pycpt_name} -> {product}.{variable} (variable not defined)"
            )

    assert not missing_products, "Missing catalog entries:\n" + "\n".join(missing_products)
    assert not missing_variables, "Missing variable definitions:\n" + "\n".join(missing_variables)
```

- [ ] **Step 3: Run the test**

```bash
uv run pytest tests/test_rosetta.py::test_pycpt_reference_coverage -v
```
Expected: PASS. If any product or variable is missing, the error message will list exactly what's needed.

- [ ] **Step 4: Fix any failures surfaced by the test**

If the test fails, add the missing variable blocks to the catalog (following the patterns in Tasks 4 and 5) until the test passes.

- [ ] **Step 5: Commit**

```bash
git add tests/conftest.py tests/test_rosetta.py
git commit -m "test: add PyCPT reference GCM coverage test"
```

---

## Task 7: Migration table and dual-domain docs in README.md

**Files:**
- Modify: `README.md`

- [ ] **Step 1: Add "Data source migration" section**

After the "Available products" section in `README.md`, add:

```markdown
## Data source migration

IRI Data Library (ldeo.columbia.edu) sunset in April 2026. The table below maps affected Rosetta products to their successors.

| Old product | Old source | New product | New source | Status |
|---|---|---|---|---|
| `nmme/cfsv2` | IRI DL OPeNDAP | TBD | CCSR | tracking |
| `nmme/cfsv2-forecast` | IRI DL OPeNDAP | TBD | CCSR | tracking |
| `nmme/ccsm4-iri` | IRI DL OPeNDAP | `nmme/ccsm4` | NCEI | migrated |
| `nmme/geoss2s-forecast` | IRI DL OPeNDAP | `nmme/geoss2s` | NCEI | migrated |
| `c3s/ecmwf-seas51c` | IRI DL (iridl adapter) | `c3s/ecmwf-monthly` | CDS | migrated |

Deprecated products remain in the catalog and still function while IRI URLs respond, but `rosetta.check_product()` emits a `DeprecationWarning` indicating the successor. Use `catalog.list_products(include_deprecated=False)` to exclude them.
```

- [ ] **Step 2: Add "Dual-domain usage" section**

After the "Core API" section, add:

```markdown
## Dual-domain usage (SST + PRCP predictors)

PyCPT's seasonal forecasting workflow uses two predictor domains per GCM: a large SST domain and a regional precipitation domain over the same predictand area. Rosetta supports this with orthogonal `fetch()` calls — one per domain.

```python
import rosetta

# SST predictor: large tropical domain
sst_predictor = rosetta.fetch(
    product="nmme/geoss2s",
    variable="sst",
    init="2025-02",
    target="MAM",
    region=[-20, 20, 30, 180],
    hindcast=(1993, 2016),
)

# PRCP predictor: regional domain
prcp_predictor = rosetta.fetch(
    product="nmme/geoss2s",
    variable="precip",
    init="2025-02",
    target="MAM",
    region=[-20, 20, 10, 75],
    hindcast=(1993, 2016),
)

# Predictand: observations for verification
predictand = rosetta.fetch(
    product="obs/chirps-v2",
    variable="precip",
    target="MAM",
    region=[-12, 15, 22, 52],
    hindcast=(1993, 2016),
)
```

`rosetta.fetch()` is a single-call API by design. There is no `fetch_predictor_pair()` convenience wrapper — the two domains have different extents and variables per use case. DeepScale's `seasonal_mme()` orchestrates the two-domain pattern; Rosetta stays orthogonal.
```

- [ ] **Step 3: Verify README renders properly (check markdown)**

```bash
uv run python -c "
with open('README.md') as f:
    content = f.read()
assert '## Data source migration' in content
assert '## Dual-domain usage' in content
assert 'nmme/cfsv2' in content
assert 'sst_predictor' in content
print('README sections present')
"
```
Expected: "README sections present"

- [ ] **Step 4: Record V2 cache mirror decision in README**

In the "Storage layer" or end of the README, add one line under a "Caching" heading (or append to the architecture notes):

```markdown
> **Cache mirror (V2):** A public or shared read-only Nuthatch cache mirror is planned for V2. V1 uses local-only caching via `~/.nuthatch/rosetta`.
```

- [ ] **Step 5: Commit**

```bash
git add README.md
git commit -m "docs: add IRI migration table and dual-domain usage example to README"
```

---

## Task 8: Final check — run all unit tests

- [ ] **Step 1: Run full unit test suite**

```bash
uv run pytest tests/test_rosetta.py tests/test_validate.py -v
```
Expected: all pass, no regressions.

- [ ] **Step 2: Verify deprecated entries still pass catalog_loads**

```bash
uv run pytest tests/test_rosetta.py::test_catalog_loads -v
```
Expected: PASS (deprecated entries still have required fields).

- [ ] **Step 3: Final commit if any loose changes**

```bash
git status
# stage and commit any uncommitted changes
```
