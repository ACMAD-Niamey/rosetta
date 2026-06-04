"""CCSR successor OPeNDAP adapter (rosetta #14 / §6.2).

The Columbia CCSR site replaced the sunset IRI Data Library. It serves the
NMME models (SPEAR, CanSIPS-IC4, ...) over plain OPeNDAP with a different
convention from IRI:
  - the variable is part of the path (no Ingrid `/.<var>/dods` suffix)
  - S (init) and target are "hours since 1960-01-01" (not "months since")
  - L is an integer 0..11 lead (L=0 == the init month), with a self-describing
    `target[S,L]` variable giving each (init, lead)'s target month
  - longitude is 0..360

These tests exercise the adapter's coordinate decoding + `target`-driven season
selection on a synthetic CCSR-shaped dataset (no network).
"""
import numpy as np
import pytest
import xarray as xr


def _hours_since_1960(dt64):
    return ((dt64.astype("datetime64[h]") - np.datetime64("1960-01-01", "h"))
            / np.timedelta64(1, "h")).astype("int64")


def _synthetic_ccsr(init_month=2, init_years=(1991, 1992, 1993), n_leads=6,
                    members=3, native="prcp"):
    """Mimic a CCSR hindcast variable dataset: prcp[S, M, L, Y, X] + target[S, L]."""
    S_dt = np.array([np.datetime64(f"{y:04d}-{init_month:02d}-01") for y in init_years])
    S = _hours_since_1960(S_dt)
    L = np.arange(n_leads)
    M = np.arange(1, members + 1)
    Y = np.array([-2.0, -1.0, 0.0, 1.0, 2.0])           # ascending lat
    X = np.array([28.0, 30.0, 35.0, 40.0, 200.0, 359.0])  # 0..360 lon (incl. >180)

    # target[S, L] = init month + L months (L=0 is the init month).
    target = np.empty((len(S), n_leads), dtype="int64")
    for i, y in enumerate(init_years):
        for l in range(n_leads):
            mo = init_month + l
            yy = y + (mo - 1) // 12
            mm = (mo - 1) % 12 + 1
            target[i, l] = _hours_since_1960(np.datetime64(f"{yy:04d}-{mm:02d}-01"))

    rng = np.random.default_rng(0)
    data = rng.standard_normal((len(S), members, n_leads, len(Y), len(X))).astype("float32")
    ds = xr.Dataset(
        {native: (["S", "M", "L", "Y", "X"], data),
         "target": (["S", "L"], target)},
        coords={"S": S, "M": M, "L": L, "Y": Y, "X": X},
    )
    ds["S"].attrs["units"] = "hours since 1960-01-01"
    ds["target"].attrs["units"] = "hours since 1960-01-01"
    return ds


def _mam_config(native="prcp", variable="precip"):
    from datetime import datetime
    return {
        "adapter": "ccsr",
        "source_url": "https://example/NMME/NOAA-GFDL/SPEAR/hindcast",
        "variables": {variable: {"native_name": native, "units": "mm/day",
                                 "target_units": "mm/day"}},
        "init_months": [2],                                  # Feb init
        "target_range": (datetime(1991, 3, 1), datetime(1991, 5, 31)),  # MAM
        "_verbose": False,
    }


def test_adapter_registered():
    from rosetta.adapters import get_adapter
    from rosetta.adapters.ccsr import CCSRAdapter
    assert isinstance(get_adapter("ccsr"), CCSRAdapter)


def test_target_driven_season_selection_means_mam_leads():
    """For a Feb init, MAM = target months {3,4,5} = leads L∈{1,2,3}; the
    adapter must select exactly those leads and average them."""
    from rosetta.adapters.ccsr import CCSRAdapter
    ds = _synthetic_ccsr(init_month=2, n_leads=6)
    out = CCSRAdapter()._process(ds.copy(deep=True), "prcp", _mam_config(),
                                 date_range=(1991, 1993), region=None)
    # L collapsed (season-averaged), S/M/Y/X retained.
    assert "L" not in out.dims
    # Expected mean over leads 1,2,3 of the original data. Compare reduced over
    # the spatial+member axes so the comparison is independent of the adapter's
    # longitude re-ordering (0..360 -> ±180 + sortby), which has its own test.
    expected = ds["prcp"].isel(L=[1, 2, 3]).mean("L").mean(["M", "Y", "X"])
    got = out["prcp"].mean(["M", "Y", "X"])
    np.testing.assert_allclose(got.values, expected.values, rtol=1e-5)
    # Selecting the wrong leads (e.g. all 6) would give a different mean:
    wrong = ds["prcp"].mean("L").mean(["M", "Y", "X"])
    assert not np.allclose(got.values, wrong.values)


def test_S_decoded_to_datetime_and_year_filtered():
    from rosetta.adapters.ccsr import CCSRAdapter
    ds = _synthetic_ccsr(init_years=(1991, 1992, 1993))
    out = CCSRAdapter()._process(ds.copy(deep=True), "prcp", _mam_config(),
                                 date_range=(1992, 1993), region=None)
    assert np.issubdtype(out["S"].dtype, np.datetime64)
    assert list(out["S"].dt.year.values) == [1992, 1993]


def test_longitude_wrapped_to_pm180_and_region_cropped():
    from rosetta.adapters.ccsr import CCSRAdapter
    ds = _synthetic_ccsr()
    out = CCSRAdapter()._process(ds.copy(deep=True), "prcp", _mam_config(),
                                 date_range=(1991, 1993), region=[-1, 1, 29, 41])
    assert float(out["X"].min()) >= 29.0 and float(out["X"].max()) <= 41.0
    assert float(out["Y"].min()) >= -1.0 and float(out["Y"].max()) <= 1.0
    # the 200/359 (->-160/-1) lons are cropped out of the 29..41 window
    assert float(out["X"].max()) <= 41.0


def test_health_check_config_and_missing_url():
    from rosetta.adapters.ccsr import CCSRAdapter
    a = CCSRAdapter()
    ok = a.health_check({"source_url": "https://example/x", "variables": {}}, probe_remote=False)
    assert ok["healthy"] is True and ok["kind"] == "config"
    bad = a.health_check({"variables": {}}, probe_remote=False)
    assert bad["healthy"] is False


@pytest.mark.integration
@pytest.mark.network
@pytest.mark.parametrize("product,variable,members,region", [
    ("nmme/spear-hindcast", "precip", 15, [-2, 2, 34, 40]),
    ("nmme/spearb-hindcast", "sst", 15, [-5, 5, 55, 70]),      # ocean bbox for SST
    ("nmme/cansipsic4-hindcast", "precip", 40, [-2, 2, 34, 40]),
])
def test_ccsr_hindcast_entries_live_fetch(product, variable, members, region):
    """End-to-end against the real CCSR server for each wired hindcast entry:
    decode + Feb-init filter + target-driven MAM lead selection + normalize."""
    import rosetta
    ds = rosetta.fetch(product, variable, init="2016-02", target="MAM",
                       hindcast=(2014, 2016), region=region, cache=False, verbose=False)
    da = ds[variable] if variable in getattr(ds, "data_vars", {}) else ds
    assert ds.sizes.get("member") == members
    assert "L" not in da.dims                       # season leads collapsed
    assert float(np.isfinite(da).mean()) > 0.5


@pytest.mark.integration
@pytest.mark.network
@pytest.mark.parametrize("product", ["nmme/spear", "nmme/spearb", "nmme/cansipsic4"])
def test_ccsr_forecast_paths_reachable(product):
    """The CCSR forecast endpoints are live (catalog source_url opens)."""
    from rosetta import catalog
    from rosetta.adapters import get_adapter
    entry = catalog.info(product)
    result = get_adapter(entry["adapter"]).health_check(entry, probe_remote=True)
    assert result["healthy"] is True, result
