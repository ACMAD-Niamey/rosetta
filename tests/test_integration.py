"""Integration tests that fetch a small sample from each data product.

These require network access and, for CDS products, valid credentials in ~/.cdsapirc.

Run all:       pytest -m integration tests/test_integration.py
Run non-CDS:   pytest -m "integration and not cds" tests/test_integration.py
"""

import pytest
import rosetta

# Small region (East Africa) to keep downloads minimal
REGION = [-2, 2, 36, 40]


def _check_dataset(ds, variable, region=None):
    """Common assertions for any fetched dataset."""
    assert variable in ds, f"Expected variable '{variable}' in dataset, got {list(ds.data_vars)}"
    assert ds[variable].size > 0, "Variable has no data"
    assert "units" in ds[variable].attrs, "Variable missing units attribute"
    assert "lat" in ds.coords, "Missing 'lat' coordinate after normalization"
    assert "lon" in ds.coords, "Missing 'lon' coordinate after normalization"
    if region:
        lat_s, lat_n, lon_w, lon_e = region
        assert float(ds.lat.min()) >= lat_s - 1, "Latitude below requested region"
        assert float(ds.lat.max()) <= lat_n + 1, "Latitude above requested region"


# ── OPeNDAP ─────────────────────────────────────────────────────────────────

@pytest.mark.integration
def test_fetch_nmme_cfsv2_precip():
    ds = rosetta.fetch(
        product="nmme/cfsv2",
        variable="precip",
        init="2024-01",
        region=REGION,
        verbose=True,
    )
    _check_dataset(ds, "precip", REGION)
    assert ds["precip"].attrs["units"] == "mm/day"


@pytest.mark.integration
def test_fetch_nmme_cfsv2_temp():
    ds = rosetta.fetch(
        product="nmme/cfsv2",
        variable="temp",
        init="2024-01",
        region=REGION,
        verbose=True,
    )
    _check_dataset(ds, "temp", REGION)
    assert ds["temp"].attrs["units"] == "C"


# ── NCEI ─────────────────────────────────────────────────────────────────────

@pytest.mark.integration
def test_fetch_nmme_ccsm4_precip():
    ds = rosetta.fetch(
        product="nmme/ccsm4",
        variable="precip",
        init="2024-01",
        target="MAM",
        region=REGION,
        hindcast=(2024, 2024),
        verbose=True,
    )
    _check_dataset(ds, "precip", REGION)
    assert ds["precip"].attrs["units"] == "mm/day"
    assert "member" in ds.dims


@pytest.mark.integration
def test_fetch_nmme_ccsm4_temp():
    ds = rosetta.fetch(
        product="nmme/ccsm4",
        variable="temp",
        init="2024-01",
        target="MAM",
        region=REGION,
        hindcast=(2024, 2024),
        verbose=True,
    )
    _check_dataset(ds, "temp", REGION)
    assert ds["temp"].attrs["units"] == "C"
    assert "member" in ds.dims


@pytest.mark.integration
def test_fetch_nmme_geoss2s_precip():
    ds = rosetta.fetch(
        product="nmme/geoss2s",
        variable="precip",
        init="2024-01",
        target="MAM",
        region=REGION,
        hindcast=(2024, 2024),
        verbose=True,
    )
    _check_dataset(ds, "precip", REGION)
    assert ds["precip"].attrs["units"] == "mm/day"
    assert "member" in ds.dims


@pytest.mark.integration
def test_fetch_nmme_geoss2s_temp():
    ds = rosetta.fetch(
        product="nmme/geoss2s",
        variable="temp",
        init="2024-01",
        target="MAM",
        region=REGION,
        hindcast=(2024, 2024),
        verbose=True,
    )
    _check_dataset(ds, "temp", REGION)
    assert ds["temp"].attrs["units"] == "C"
    assert "member" in ds.dims


@pytest.mark.integration
def test_fetch_nmme_gemnemo_precip():
    ds = rosetta.fetch(
        product="nmme/gemnemo",
        variable="precip",
        init="2024-01",
        target="MAM",
        region=REGION,
        hindcast=(2024, 2024),
        verbose=True,
    )
    _check_dataset(ds, "precip", REGION)
    assert ds["precip"].attrs["units"] == "mm/day"
    assert "member" in ds.dims


@pytest.mark.integration
def test_fetch_nmme_gemnemo_temp():
    ds = rosetta.fetch(
        product="nmme/gemnemo",
        variable="temp",
        init="2024-01",
        target="MAM",
        region=REGION,
        hindcast=(2024, 2024),
        verbose=True,
    )
    _check_dataset(ds, "temp", REGION)
    assert ds["temp"].attrs["units"] == "C"
    assert "member" in ds.dims


# ── HTTP ─────────────────────────────────────────────────────────────────────

@pytest.mark.integration
def test_fetch_chirps_precip():
    ds = rosetta.fetch(
        product="obs/chirps",
        variable="precip",
        region=REGION,
        verbose=True,
    )
    _check_dataset(ds, "precip", REGION)
    assert ds["precip"].attrs["units"] == "mm/day"


# ── Observational SST (ERSST v5, NOAA NCEI HTTP) ────────────────────────────
# Tests cover: two geographies, two non-adjacent years, multi-year series.

@pytest.mark.integration
def test_fetch_ersst_v5_east_africa_recent():
    ds = rosetta.fetch(
        product="sst/ersst-v5",
        variable="sst",
        hindcast=(2020, 2020),
        region=[-20, 20, 20, 55],
        verbose=False, progress=False, cache=False,
    )
    _check_dataset(ds, "sst", [-20, 20, 20, 55])
    assert ds["sst"].attrs["units"] == "C"
    assert ds.sizes["time"] == 12
    vmin, vmax = float(ds["sst"].min(skipna=True)), float(ds["sst"].max(skipna=True))
    assert -3.0 <= vmin and vmax <= 45.0, f"sst out of range: {vmin}..{vmax}"


@pytest.mark.integration
def test_fetch_ersst_v5_west_pacific_historical():
    # Warm-pool region, well inside 0..360 longitude convention
    region = [-10, 10, 140, 180]
    ds = rosetta.fetch(
        product="sst/ersst-v5",
        variable="sst",
        hindcast=(2000, 2000),
        region=region,
        verbose=False, progress=False, cache=False,
    )
    _check_dataset(ds, "sst", region)
    assert ds.sizes["time"] == 12
    # Warm pool SSTs are typically 27-30 C
    mean_sst = float(ds["sst"].mean(skipna=True))
    assert 25.0 < mean_sst < 32.0, f"warm pool mean sst implausible: {mean_sst}"


@pytest.mark.integration
def test_fetch_ersst_v5_multiyear_timeseries():
    ds = rosetta.fetch(
        product="sst/ersst-v5",
        variable="sst",
        hindcast=(2010, 2012),
        region=[-20, 20, 20, 55],
        verbose=False, progress=False, cache=False,
    )
    _check_dataset(ds, "sst", None)
    assert ds.sizes["time"] == 36, f"expected 36 months, got {ds.sizes['time']}"
    # Time should be strictly increasing
    import numpy as np
    t = ds["time"].values
    assert (np.diff(t) > np.timedelta64(0, "ns")).all(), "time not monotonic"


# ── CDS (require credentials) ───────────────────────────────────────────────

@pytest.mark.integration
@pytest.mark.cds
def test_fetch_c3s_ecmwf_precip():
    ds = rosetta.fetch(
        product="c3s/ecmwf",
        variable="precip",
        init="2000-01",
        target="MAM",
        region=REGION,
        hindcast=(2000, 2000),
        verbose=True,
    )
    _check_dataset(ds, "precip", REGION)
    assert ds["precip"].attrs["units"] == "mm/day"
    assert "lead_time" in ds.dims


@pytest.mark.integration
@pytest.mark.cds
def test_fetch_c3s_ecmwf_temp():
    ds = rosetta.fetch(
        product="c3s/ecmwf",
        variable="temp",
        init="2000-01",
        target="MAM",
        region=REGION,
        hindcast=(2000, 2000),
        verbose=True,
    )
    _check_dataset(ds, "temp", REGION)
    assert ds["temp"].attrs["units"] == "C"
    assert "lead_time" in ds.dims


@pytest.mark.integration
@pytest.mark.cds
def test_fetch_c3s_ecmwf_monthly_temp():
    ds = rosetta.fetch(
        product="c3s/ecmwf-monthly",
        variable="temp",
        init="2024-01",
        region=REGION,
        verbose=True,
    )
    _check_dataset(ds, "temp", REGION)
    assert ds["temp"].attrs["units"] == "C"


@pytest.mark.integration
@pytest.mark.cds
def test_fetch_eccc_cansips_temp():
    ds = rosetta.fetch(
        product="c3s/eccc-cansips",
        variable="temp",
        init="2000-01",
        target="MAM",
        region=REGION,
        hindcast=(2000, 2000),
        verbose=True,
    )
    _check_dataset(ds, "temp", REGION)
    assert ds["temp"].attrs["units"] == "C"
    assert "member" in ds.dims


@pytest.mark.integration
@pytest.mark.cds
def test_fetch_eccc_cansipsv3_temp():
    ds = rosetta.fetch(
        product="c3s/eccc-cansipsv3",
        variable="temp",
        init="2000-01",
        target="MAM",
        region=REGION,
        hindcast=(2000, 2000),
        verbose=True,
    )
    _check_dataset(ds, "temp", REGION)
    assert ds["temp"].attrs["units"] == "C"
    assert "member" in ds.dims


@pytest.mark.integration
@pytest.mark.cds
def test_fetch_meteofrance_temp():
    ds = rosetta.fetch(
        product="c3s/meteofrance",
        variable="temp",
        init="2000-01",
        target="MAM",
        region=REGION,
        hindcast=(2000, 2000),
        verbose=True,
    )
    _check_dataset(ds, "temp", REGION)
    assert ds["temp"].attrs["units"] == "C"
    assert "member" in ds.dims


@pytest.mark.integration
@pytest.mark.cds
def test_fetch_cmcc_temp():
    ds = rosetta.fetch(
        product="c3s/cmcc",
        variable="temp",
        init="2000-01",
        target="MAM",
        region=REGION,
        hindcast=(2000, 2000),
        verbose=True,
    )
    _check_dataset(ds, "temp", REGION)
    assert ds["temp"].attrs["units"] == "C"
    assert "member" in ds.dims


@pytest.mark.integration
@pytest.mark.cds
def test_fetch_dwd_temp():
    ds = rosetta.fetch(
        product="c3s/dwd",
        variable="temp",
        init="2000-01",
        target="MAM",
        region=REGION,
        hindcast=(2000, 2000),
        verbose=True,
    )
    _check_dataset(ds, "temp", REGION)
    assert ds["temp"].attrs["units"] == "C"
    assert "member" in ds.dims


@pytest.mark.integration
@pytest.mark.cds
def test_fetch_ukmo_temp():
    ds = rosetta.fetch(
        product="c3s/ukmo",
        variable="temp",
        init="2000-01",
        target="MAM",
        region=REGION,
        hindcast=(2000, 2000),
        verbose=True,
    )
    _check_dataset(ds, "temp", REGION)
    assert ds["temp"].attrs["units"] == "C"
    assert "member" in ds.dims


@pytest.mark.integration
@pytest.mark.cds
def test_fetch_jma_temp():
    ds = rosetta.fetch(
        product="c3s/jma",
        variable="temp",
        init="2000-01",
        target="MAM",
        region=REGION,
        hindcast=(2000, 2000),
        verbose=True,
    )
    _check_dataset(ds, "temp", REGION)
    assert ds["temp"].attrs["units"] == "C"
    assert "member" in ds.dims
    assert "init_time" in ds.coords


@pytest.mark.integration
@pytest.mark.cds
def test_fetch_era5_temp():
    ds = rosetta.fetch(
        product="obs/era5",
        variable="temp",
        init="2024-01",
        region=REGION,
        verbose=True,
    )
    _check_dataset(ds, "temp", REGION)
    assert ds["temp"].attrs["units"] == "C"
