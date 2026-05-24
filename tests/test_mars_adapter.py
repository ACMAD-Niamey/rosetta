"""Unit tests for the legacy-MARS adapter (ecmwf-api-client transport)."""

import pytest
import os
from unittest.mock import MagicMock


def test_mars_adapter_registers():
    """The MARS adapter is reachable via the rosetta adapter registry."""
    from rosetta.adapters.mars import MARSAdapter
    assert MARSAdapter.__name__ == "MARSAdapter"


def _mars_product_config(**overrides):
    """A minimal product config dict matching c3s/ecmwf-s2s for reforecast use."""
    config = {
        "adapter": "mars",
        "cds_model": "ecmf",
        "variables": {
            "precip": {
                "native_name": "total_precipitation",
                "short_name": "tp",
                "mars_param": "228228",
                "units": "m",
                "target_units": "mm/day",
                "accumulated": True,
            },
        },
        "_reforecast": True,
        "_init_date": "2026-05-15",
        "_verbose": False,
    }
    config.update(overrides)
    return config


def test_mars_adapter_builds_reforecast_request(monkeypatch, tmp_path):
    """fetch_data builds the right MARS request and calls ECMWFDataServer.retrieve."""
    import xarray as xr
    captured = {}

    class _FakeServer:
        def retrieve(self, req):
            captured["request"] = dict(req)
            # Write a minimal NetCDF (using xr → netcdf) at the target path.
            import numpy as np
            import pandas as pd
            target = req.get("target")
            hdates = pd.to_datetime(["2020-05-15", "2021-05-15", "2022-05-15"])
            ds = xr.Dataset(
                {"tp": (["hdate", "number", "step", "latitude", "longitude"],
                        np.zeros((3, 2, 4, 2, 2), dtype="float32"))},
                coords={"hdate": hdates, "number": [0, 1],
                        "step": pd.to_timedelta([24, 48, 72, 96], unit="h"),
                        "latitude": [0.0, 1.0], "longitude": [0.0, 1.0]},
            )
            ds.to_netcdf(target)

    monkeypatch.setattr("ecmwfapi.ECMWFDataServer", lambda *a, **kw: _FakeServer())
    # Also monkeypatch the adapter's internal "open downloaded file" if it
    # uses cfgrib by default — the stub writes NetCDF, not GRIB.
    monkeypatch.setattr(
        "rosetta.adapters.mars._open_downloaded",
        lambda path: xr.open_dataset(path, decode_times=False),
    )

    from rosetta.adapters.mars import MARSAdapter
    adapter = MARSAdapter()
    config = _mars_product_config()
    ds = adapter.fetch_data(config, "precip", date_range=(2020, 2022),
                            region=[-2, 2, 36, 40])

    # The MARS request shape:
    req = captured["request"]
    assert req["class"] == "s2"
    assert req["dataset"] == "s2s"
    assert req["expver"] == "prod"
    assert req["stream"] == "enfh"
    assert req["type"] == "pf"
    assert req["origin"] == "ecmf"
    assert req["levtype"] == "sfc"
    assert req["param"] == "228228"
    assert req["date"] == "2026-05-15"
    # hdate is a slash-delimited list of YYYY-MM-DD entries — one per year in
    # the range, calendar-week-aligned to date.
    assert req["hdate"] == "2020-05-15/2021-05-15/2022-05-15"
    # area is N/W/S/E slash-delimited from the [lat_s, lat_n, lon_w, lon_e] region.
    assert req["area"] == "2/36/-2/40"
    # number defaults to all 10 perturbed reforecast members; without this,
    # MARS rejects with "expected N, got 10*N".
    assert req["number"] == "1/to/10"


def test_mars_adapter_rejects_when_reforecast_flag_missing(monkeypatch):
    """The MARS adapter is reforecast-only in v1 — fetch_data raises if _reforecast is unset."""
    from rosetta.adapters.mars import MARSAdapter
    adapter = MARSAdapter()
    config = _mars_product_config(_reforecast=False)
    with pytest.raises(ValueError, match="reforecast"):
        adapter.fetch_data(config, "precip", date_range=(2020, 2022), region=[-2, 2, 36, 40])


def test_mars_adapter_requires_date_range(monkeypatch):
    """date_range is required (per-call hindcast years for hdate construction)."""
    from rosetta.adapters.mars import MARSAdapter
    adapter = MARSAdapter()
    config = _mars_product_config()
    with pytest.raises(ValueError, match="date_range"):
        adapter.fetch_data(config, "precip", date_range=None, region=[-2, 2, 36, 40])


def test_fetch_reforecast_end_to_end_via_mars(monkeypatch, tmp_path):
    """rosetta.fetch(reforecast=True) returns a normalized (year, member, lead_time, lat, lon) Dataset."""
    import rosetta
    import xarray as xr
    import numpy as np
    import pandas as pd

    class _FakeServer:
        def __init__(self, *a, **kw):
            self.calls = []

        def retrieve(self, req):
            self.calls.append(dict(req))
            target = req["target"]
            hdates = pd.to_datetime(["2020-05-15", "2021-05-15"])
            ds = xr.Dataset(
                {"tp": (["hdate", "number", "step", "latitude", "longitude"],
                        np.zeros((2, 2, 3, 2, 2), dtype="float32"))},
                coords={"hdate": hdates, "number": [0, 1],
                        "step": pd.to_timedelta([24, 48, 72], unit="h"),
                        "latitude": [0.0, 1.0], "longitude": [0.0, 1.0]},
            )
            ds.to_netcdf(target)

    fake = _FakeServer()
    monkeypatch.setattr("ecmwfapi.ECMWFDataServer", lambda *a, **kw: fake)
    monkeypatch.setattr(
        "rosetta.adapters.mars._open_downloaded",
        lambda path: xr.open_dataset(path, decode_times=False),
    )

    result = rosetta.fetch(
        product="c3s/ecmwf-s2s",
        variable="precip",
        init="2026-05-15",
        region=[-2, 2, 36, 40],
        reforecast=True,
        hindcast=(2020, 2021),
        cache=False,
        verbose=False,
    )

    assert "year" in result.dims
    assert list(result["year"].values) == [2020, 2021]
    assert "member" in result.dims
    assert "lead_time" in result.dims
    assert "lat" in result.dims
    assert "lon" in result.dims

    assert len(fake.calls) == 1
    req = fake.calls[0]
    assert req["stream"] == "enfh"
    assert req["type"] == "pf"
    assert req["hdate"] == "2020-05-15/2021-05-15"
