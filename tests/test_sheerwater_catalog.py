"""§3.2 Sheerwater-backed catalog entries (rosetta #7) + ERA5 enrichment.

obs/chirps now routes through the Sheerwater adapter (chirps_v3); the old
direct UCSB COG path is preserved as obs/chirps-direct (deprecated). obs/imerg
and obs/ghcn are new Sheerwater-backed precip entries. obs/era5 (cds) gains a
precip variable so ERA5 stays broadly usable without Sheerwater (the installed
sheerwater build exposes no era5 data function).
"""
import numpy as np
import pandas as pd
import pytest
import xarray as xr
from unittest.mock import MagicMock, patch

from rosetta import catalog


def test_obs_chirps_routes_to_sheerwater():
    e = catalog.info("obs/chirps")
    assert e["adapter"] == "sheerwater"
    assert e["source"] == "chirps_v3"
    assert "precip" in e["variables"]


def test_obs_chirps_direct_preserved_and_deprecated():
    e = catalog.info("obs/chirps-direct")
    assert e["adapter"] == "http"            # original UCSB COG path retained
    assert e["deprecated"] is True           # deprecated_after is in the past
    assert e.get("successor") == "obs/chirps"


@pytest.mark.parametrize("prod,src", [
    ("obs/imerg", "imerg_final"),
    ("obs/ghcn", "ghcn_avg"),
])
def test_new_sheerwater_obs_entries(prod, src):
    e = catalog.info(prod)
    assert e["adapter"] == "sheerwater"
    assert e["source"] == src
    assert "precip" in e["variables"]


def test_obs_era5_enriched_with_precip():
    e = catalog.info("obs/era5")
    assert e["adapter"] == "cds"             # stays on CDS (no sheerwater era5 fn)
    assert "precip" in e["variables"]
    assert "temp" in e["variables"]          # original variable preserved


@pytest.mark.parametrize("prod", ["obs/chirps", "obs/imerg", "obs/ghcn"])
def test_new_entries_config_health_ok(prod):
    from rosetta.adapters import get_adapter
    e = catalog.info(prod)
    adapter = get_adapter(e["adapter"])
    result = adapter.health_check(e, probe_remote=False)
    assert result["healthy"] is True
    assert result["kind"] == "config"


def _raw_monthly(variable="precip"):
    times = pd.date_range("2010-01-01", "2010-12-01", freq="MS")
    lat = np.arange(-3.0, 4.0, 1.0)
    lon = np.arange(29.0, 36.0, 1.0)
    data = np.random.rand(len(times), len(lat), len(lon)).astype(np.float32)
    return xr.Dataset({variable: (["time", "lat", "lon"], data)},
                      coords={"time": times, "lat": lat, "lon": lon})


def test_fetch_obs_chirps_through_sheerwater():
    """End-to-end (mocked sheerwater fn): catalog -> adapter -> normalize."""
    import rosetta
    with patch("sheerwater.data.chirps_v3",
               MagicMock(return_value=_raw_monthly("precip")), create=True):
        ds = rosetta.fetch("obs/chirps", "precip",
                           hindcast=(2010, 2010), region=[-2, 2, 30, 34],
                           cache=False, verbose=False)
    assert ds is not None
    assert ("lat" in ds.coords) or ("latitude" in ds.coords)
    da = ds["precip"] if "precip" in getattr(ds, "data_vars", {}) else ds[list(ds.data_vars)[0]]
    assert float(np.isfinite(da).mean()) > 0.0
