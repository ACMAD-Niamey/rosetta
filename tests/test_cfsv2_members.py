"""Task A3: generic `member_reduce` catalog knob (CFSv2 first-24-mean).

Pushes the CFSv2 "average the first 24 PENTAD members" special-case
(run_pipeline.py:379-383: `da.isel(member=slice(0, 24)).mean("member")`)
out of the consumer and into rosetta as a data-driven catalog knob so
`rosetta.assemble` needs no CFSv2-specific code.
"""
import numpy as np
import pandas as pd
import xarray as xr

from rosetta.normalize import normalize


def _member_ds(n_members, n_time=1):
    """A minimal (S, L, M, Y, X) NMME-style raw dataset with n_members members."""
    s_vals = np.array([601.0])  # months since 1960-01-01 -> Feb 2010
    l_vals = np.array([0.5])
    m_vals = np.arange(n_members)
    lat = np.arange(-2, 3, 1.0)
    lon = np.arange(36, 41, 1.0)
    shape = (len(s_vals), len(l_vals), len(m_vals), len(lat), len(lon))
    # member index broadcast into the data so a mean over a known slice is
    # checkable: value at member i is i (float), so mean(0..23) = 11.5
    data = np.broadcast_to(
        m_vals.astype(np.float32)[None, None, :, None, None], shape
    ).copy()
    ds = xr.Dataset(
        {"prec": (["S", "L", "M", "Y", "X"], data)},
        coords={"S": s_vals, "L": l_vals, "M": m_vals, "Y": lat, "X": lon},
    )
    ds["S"].attrs["units"] = "months since 1960-01-01"
    return ds


_CFSV2_LIKE_CONFIG = {
    "variables": {
        "precip": {
            "native_name": "prec",
            "units": "mm/day",
            "target_units": "mm/day",
        }
    },
    "member_reduce": {"first": 24, "op": "mean"},
}

_NO_REDUCE_CONFIG = {
    "variables": {
        "precip": {
            "native_name": "prec",
            "units": "mm/day",
            "target_units": "mm/day",
        }
    },
}


def test_member_reduce_averages_first_24_members():
    """With member_reduce: {first: 24, op: mean}, 28 members collapse to the
    mean of the first 24 (native order), matching
    isel(member=slice(0, 24)).mean("member")."""
    raw = _member_ds(28)
    clean = normalize(raw, _CFSV2_LIKE_CONFIG, "precip")
    da = clean["precip"]

    assert "member" in da.dims
    assert da.sizes["member"] == 1
    # member values are 0..27 broadcast; mean of first 24 (0..23) = 11.5
    expected = np.mean(np.arange(24))
    np.testing.assert_allclose(da.isel(member=0).values, expected)


def test_member_reduce_matches_manual_isel_mean():
    """Directly matches the reference's isel(member=slice(0,24)).mean('member')."""
    raw = _member_ds(28)
    clean = normalize(raw, _CFSV2_LIKE_CONFIG, "precip")
    got = clean["precip"]

    baseline_raw = _member_ds(28)
    baseline = normalize(baseline_raw, _NO_REDUCE_CONFIG, "precip")
    want = (
        baseline["precip"]
        .isel(member=slice(0, 24))
        .mean("member")
        .expand_dims(member=[0])
    )
    xr.testing.assert_allclose(
        got.transpose(*want.dims), want, rtol=0, atol=1e-6
    )


def test_member_reduce_applies_under_year_index():
    """The reduce must run whether or not year_index reshaping is requested,
    since assemble()/prepare_inputs() both fetch with year_index=True."""
    raw = _member_ds(28)
    clean = normalize(raw, _CFSV2_LIKE_CONFIG, "precip", year_index=True)
    da = clean["precip"]

    assert "member" in da.dims
    assert da.sizes["member"] == 1
    expected = np.mean(np.arange(24))
    np.testing.assert_allclose(da.isel(member=0).values, expected)


def test_member_reduce_absent_is_a_no_op():
    """Backward-compat: a product WITHOUT member_reduce keeps all its members
    (proves the knob is opt-in and default behaviour is unchanged)."""
    raw = _member_ds(28)
    clean = normalize(raw, _NO_REDUCE_CONFIG, "precip")
    da = clean["precip"]

    assert "member" in da.dims
    assert da.sizes["member"] == 28
    np.testing.assert_allclose(sorted(da["member"].values), np.arange(28))
