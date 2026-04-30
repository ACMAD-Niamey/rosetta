# Sheerwater Adapter Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Implement a `SheerwaterAdapter` that wraps Sheerwater's data accessors, register it in the adapter registry, and add a health probe that checks the underlying Zarr store without pulling data.

**Architecture:** `SheerwaterAdapter` conforms to `AdapterBase` (same interface as `CDSAdapter`, `HTTPAdapter`, etc.). The catalog `source:` field names the Sheerwater function to call (e.g. `chirps_v3`). A helper converts Rosetta's time arguments to Sheerwater's `start_time`/`end_time`. No catalog entries use this adapter yet (those are deferred pending deepscale coordination).

**Tech Stack:** `sheerwater` (already installed), `xarray`, `zarr`, standard `unittest.mock`

---

## File Map

| File | Change |
|------|--------|
| `src/rosetta/adapters/sheerwater.py` | Create — `SheerwaterAdapter` class + `_to_time_range()` helper |
| `src/rosetta/adapters/__init__.py` | Register `SheerwaterAdapter` under key `"sheerwater"` |
| `src/rosetta/health.py` | Already handles `pending_url` — no change needed for this adapter |
| `tests/test_sheerwater.py` | Create — unit tests with mocked sheerwater.data |

---

## Task 1: Create SheerwaterAdapter

**Files:**
- Create: `src/rosetta/adapters/sheerwater.py`
- Test: `tests/test_sheerwater.py`

- [ ] **Step 1: Write the failing tests**

Create `tests/test_sheerwater.py`:
```python
import numpy as np
import pandas as pd
import pytest
import xarray as xr
from unittest.mock import MagicMock, patch


def _make_raw_ds(variable="precip"):
    """Synthetic dataset shaped like Sheerwater output."""
    times = pd.date_range("2010-01-01", "2010-03-01", freq="MS")
    lat = np.arange(-2.0, 3.0, 1.0)
    lon = np.arange(36.0, 41.0, 1.0)
    data = np.random.rand(len(times), len(lat), len(lon)).astype(np.float32)
    return xr.Dataset(
        {variable: (["time", "lat", "lon"], data)},
        coords={"time": times, "lat": lat, "lon": lon},
    )


def test_sheerwater_adapter_fetch_calls_correct_function():
    """Adapter looks up the function named in entry['source'] and calls it."""
    from rosetta.adapters.sheerwater import SheerwaterAdapter

    raw = _make_raw_ds("precip")
    mock_fn = MagicMock(return_value=raw)

    entry = {
        "source": "chirps_v3",
        "variables": {
            "precip": {"native_name": "precip", "units": "mm/day", "target_units": "mm/day"}
        },
        "grid": {"hindcast_range": [2010, 2010]},
    }

    with patch("sheerwater.data.chirps_v3", mock_fn, create=True):
        adapter = SheerwaterAdapter()
        result = adapter.fetch_data(
            entry, "precip",
            date_range=(2010, 2010),
            region=[-2, 2, 36, 40],
        )

    mock_fn.assert_called_once()
    call_kwargs = mock_fn.call_args.kwargs
    assert "start_time" in call_kwargs
    assert "end_time" in call_kwargs
    assert isinstance(result, xr.Dataset)


def test_sheerwater_adapter_passes_region():
    """Adapter forwards region to the Sheerwater function."""
    from rosetta.adapters.sheerwater import SheerwaterAdapter

    raw = _make_raw_ds("precip")
    mock_fn = MagicMock(return_value=raw)

    entry = {
        "source": "chirps_v3",
        "variables": {
            "precip": {"native_name": "precip", "units": "mm/day", "target_units": "mm/day"}
        },
        "grid": {"hindcast_range": [2010, 2010]},
    }

    with patch("sheerwater.data.chirps_v3", mock_fn, create=True):
        adapter = SheerwaterAdapter()
        adapter.fetch_data(entry, "precip", date_range=(2010, 2010), region=[-2, 2, 36, 40])

    call_kwargs = mock_fn.call_args.kwargs
    assert "region" in call_kwargs
    assert call_kwargs["region"] == [-2, 2, 36, 40]


def test_sheerwater_adapter_passes_source_kwargs():
    """source_kwargs from the catalog entry are forwarded to the function."""
    from rosetta.adapters.sheerwater import SheerwaterAdapter

    raw = _make_raw_ds("precip")
    mock_fn = MagicMock(return_value=raw)

    entry = {
        "source": "chirps_v3",
        "source_kwargs": {"agg_days": 1},
        "variables": {
            "precip": {"native_name": "precip", "units": "mm/day", "target_units": "mm/day"}
        },
        "grid": {"hindcast_range": [2010, 2010]},
    }

    with patch("sheerwater.data.chirps_v3", mock_fn, create=True):
        adapter = SheerwaterAdapter()
        adapter.fetch_data(entry, "precip", date_range=(2010, 2010), region=None)

    call_kwargs = mock_fn.call_args.kwargs
    assert call_kwargs.get("agg_days") == 1


def test_sheerwater_adapter_returns_xarray_dataset():
    from rosetta.adapters.sheerwater import SheerwaterAdapter

    raw = _make_raw_ds("precip")

    entry = {
        "source": "chirps_v3",
        "variables": {
            "precip": {"native_name": "precip", "units": "mm/day", "target_units": "mm/day"}
        },
        "grid": {"hindcast_range": [2010, 2010]},
    }

    with patch("sheerwater.data.chirps_v3", MagicMock(return_value=raw), create=True):
        adapter = SheerwaterAdapter()
        result = adapter.fetch_data(entry, "precip", date_range=(2010, 2010), region=None)

    assert isinstance(result, xr.Dataset)
```

- [ ] **Step 2: Run to verify they fail**

```bash
uv run pytest tests/test_sheerwater.py -v
```
Expected: `ModuleNotFoundError` or `ImportError` — `SheerwaterAdapter` doesn't exist yet.

- [ ] **Step 3: Create `src/rosetta/adapters/sheerwater.py`**

```python
"""Adapter for Sheerwater-backed datasets (public GCS Zarr stores).

Sheerwater (https://github.com/rhiza-research/sheerwater) exposes climate
datasets via plain Python functions that return xarray Datasets. This adapter
translates Rosetta's fetch arguments into Sheerwater's calling convention and
returns the raw dataset for Rosetta's normalization layer to process.

Caching note: Sheerwater is already Nuthatch-cached upstream. Do NOT apply
@nuthatch.cache() here — that would double-store the same data.
"""
import importlib
from datetime import date, timedelta

import xarray as xr

from .base import AdapterBase


def _to_time_range(date_range: tuple[int, int] | None) -> tuple[str, str]:
    """Convert a (start_year, end_year) tuple to ISO date strings.

    Sheerwater expects calendar start_time / end_time strings.
    We request the full year range: Jan 1 of start_year to Dec 31 of end_year.
    """
    if date_range is None:
        from datetime import datetime
        today = datetime.today()
        start = date(today.year - 1, 1, 1)
        end = date(today.year, 12, 31)
    else:
        start_year, end_year = date_range
        start = date(start_year, 1, 1)
        end = date(end_year, 12, 31)
    return start.isoformat(), end.isoformat()


class SheerwaterAdapter(AdapterBase):
    def fetch_data(self, product_config: dict, variable: str,
                   date_range=None, region=None) -> xr.Dataset:
        source_fn_name = product_config["source"]
        sheerwater_data = importlib.import_module("sheerwater.data")
        fn = getattr(sheerwater_data, source_fn_name)

        start_time, end_time = _to_time_range(date_range)
        source_kwargs = product_config.get("source_kwargs", {})

        return fn(
            start_time=start_time,
            end_time=end_time,
            region=region,
            **source_kwargs,
        )

    def health_check(self, product_config: dict, probe_remote: bool = False) -> dict:
        source = product_config.get("source")
        if not source:
            return {
                "healthy": False,
                "kind": "config",
                "message": "Missing 'source' field in product config.",
                "probe_remote": bool(probe_remote),
            }

        if not probe_remote:
            return {
                "healthy": True,
                "kind": "config",
                "message": f"Sheerwater adapter config valid (source={source}).",
                "probe_remote": False,
            }

        zarr_url = product_config.get("zarr_url")
        if not zarr_url:
            return {
                "healthy": False,
                "kind": "config",
                "message": "probe_remote=True requires 'zarr_url' in product config for the Sheerwater probe.",
                "probe_remote": True,
            }

        try:
            import xarray as xr
            # Open metadata only — no data pull
            ds = xr.open_dataset(zarr_url, engine="zarr", chunks={})
            hindcast_range = product_config.get("grid", {}).get("hindcast_range")
            if hindcast_range:
                time_coord = next((c for c in ("time", "T") if c in ds.coords), None)
                if time_coord:
                    import pandas as pd
                    t_min = pd.Timestamp(ds[time_coord].values.min())
                    assert t_min.year <= hindcast_range[0], (
                        f"Zarr store starts {t_min.year}, expected <= {hindcast_range[0]}"
                    )
            return {
                "healthy": True,
                "kind": "remote",
                "message": f"Sheerwater Zarr store reachable: {zarr_url}",
                "probe_remote": True,
            }
        except Exception as e:
            # Distinguish GCS auth/connectivity errors (transient) from broken adapters
            msg = str(e).lower()
            if any(kw in msg for kw in ("403", "permission", "credentials", "timeout", "connection")):
                kind = "transient"
            else:
                kind = "remote"
            return {
                "healthy": False,
                "kind": kind,
                "message": f"Sheerwater probe failed: {e}",
                "probe_remote": True,
            }
```

- [ ] **Step 4: Run the tests**

```bash
uv run pytest tests/test_sheerwater.py -v
```
Expected: all 4 tests PASS.

- [ ] **Step 5: Commit**

```bash
git add src/rosetta/adapters/sheerwater.py tests/test_sheerwater.py
git commit -m "feat: add SheerwaterAdapter (§3.1)"
```

---

## Task 2: Register SheerwaterAdapter in the adapter registry

**Files:**
- Modify: `src/rosetta/adapters/__init__.py`

- [ ] **Step 1: Write the failing test**

Add to `tests/test_rosetta.py`:
```python
def test_get_adapter_sheerwater():
    from rosetta.adapters import get_adapter
    from rosetta.adapters.sheerwater import SheerwaterAdapter
    adapter = get_adapter("sheerwater")
    assert isinstance(adapter, SheerwaterAdapter)
```

- [ ] **Step 2: Run to verify it fails**

```bash
uv run pytest tests/test_rosetta.py::test_get_adapter_sheerwater -v
```
Expected: FAIL — `KeyError: 'Unknown adapter: sheerwater'`

- [ ] **Step 3: Register the adapter**

Replace `src/rosetta/adapters/__init__.py` with:
```python
from .cds import CDSAdapter
from .opendap import OPeNDAPAdapter
from .http import HTTPAdapter
from .iridl import IRIDLAdapter
from .ncei import NCEIAdapter
from .s3 import S3Adapter
from .sheerwater import SheerwaterAdapter

_ADAPTERS = {
    "cds": CDSAdapter,
    "opendap": OPeNDAPAdapter,
    "http": HTTPAdapter,
    "iridl": IRIDLAdapter,
    "ncei": NCEIAdapter,
    "s3": S3Adapter,
    "sheerwater": SheerwaterAdapter,
}


def get_adapter(name):
    if name not in _ADAPTERS:
        raise KeyError(f"Unknown adapter: {name}")
    return _ADAPTERS[name]()
```

- [ ] **Step 4: Run the test**

```bash
uv run pytest tests/test_rosetta.py::test_get_adapter_sheerwater -v
```
Expected: PASS.

- [ ] **Step 5: Run full test suite**

```bash
uv run pytest tests/ -v
```
Expected: all pass.

- [ ] **Step 6: Commit**

```bash
git add src/rosetta/adapters/__init__.py tests/test_rosetta.py
git commit -m "feat: register SheerwaterAdapter in adapter registry (§3.1)"
```

---

## Task 3: Health probe tests

**Files:**
- Test: `tests/test_sheerwater.py`

- [ ] **Step 1: Write health probe tests**

Add to `tests/test_sheerwater.py`:
```python
def test_sheerwater_health_check_config_only():
    from rosetta.adapters.sheerwater import SheerwaterAdapter
    adapter = SheerwaterAdapter()
    entry = {
        "source": "chirps_v3",
        "variables": {"precip": {"native_name": "precip", "units": "mm/day", "target_units": "mm/day"}},
        "grid": {"hindcast_range": [1981, 2024]},
    }
    result = adapter.health_check(entry, probe_remote=False)
    assert result["healthy"] is True
    assert result["kind"] == "config"
    assert result["probe_remote"] is False


def test_sheerwater_health_check_missing_source():
    from rosetta.adapters.sheerwater import SheerwaterAdapter
    adapter = SheerwaterAdapter()
    result = adapter.health_check({}, probe_remote=False)
    assert result["healthy"] is False
    assert "source" in result["message"]


def test_sheerwater_health_check_remote_requires_zarr_url():
    from rosetta.adapters.sheerwater import SheerwaterAdapter
    adapter = SheerwaterAdapter()
    entry = {
        "source": "chirps_v3",
        "variables": {},
        "grid": {},
        # no zarr_url
    }
    result = adapter.health_check(entry, probe_remote=True)
    assert result["healthy"] is False
    assert "zarr_url" in result["message"]


def test_sheerwater_health_check_remote_success():
    from rosetta.adapters.sheerwater import SheerwaterAdapter
    import xarray as xr
    import pandas as pd
    import numpy as np

    adapter = SheerwaterAdapter()
    entry = {
        "source": "chirps_v3",
        "zarr_url": "gs://fake-bucket/chirps",
        "variables": {},
        "grid": {"hindcast_range": [1981, 2024]},
    }

    mock_ds = xr.Dataset(
        {"precip": (["time", "lat", "lon"], np.zeros((3, 2, 2)))},
        coords={
            "time": pd.date_range("1981-01-01", periods=3, freq="MS"),
            "lat": [0.0, 1.0],
            "lon": [30.0, 31.0],
        },
    )

    with patch("xarray.open_dataset", return_value=mock_ds):
        result = adapter.health_check(entry, probe_remote=True)

    assert result["healthy"] is True
    assert result["kind"] == "remote"
```

- [ ] **Step 2: Run the tests**

```bash
uv run pytest tests/test_sheerwater.py -v
```
Expected: all tests PASS.

- [ ] **Step 3: Commit**

```bash
git add tests/test_sheerwater.py
git commit -m "test: add SheerwaterAdapter health probe tests (§3.3)"
```
