"""IRI OPeNDAP adapter — stream routing.

The IRI NMME CFSv2 hindcast and forecast live at sibling endpoints that differ
only by a mid-path token (`.HINDCAST` vs `.FORECAST`). A `split_streams: true`
entry expresses both as one product whose `source_url` carries a `{stream}`
placeholder; the adapter picks the token from the requested years (past the
hindcast range -> forecast), mirroring the CCSR adapter's split-stream routing.

These tests capture the opened URL (no network).
"""
import numpy as np
import xarray as xr


def _capture_url(monkeypatch):
    """Patch the adapter's xr.open_dataset to record the opened URL and return a
    trivial dataset, so URL routing can be tested without network."""
    from rosetta.adapters import opendap as opendap_mod
    captured = {}

    def fake_open(url, **kwargs):
        captured["url"] = url
        return xr.Dataset({"prec": (("y", "x"), np.zeros((2, 2)))})

    monkeypatch.setattr(opendap_mod.xr, "open_dataset", fake_open)
    return captured


_SPLIT_CFG = {
    "adapter": "opendap",
    "split_streams": True,
    "source_url": "https://iri/SOURCES/.NMME/.NCEP-CFSv2/.{stream}/.PENTAD_SAMPLES/.MONTHLY",
    "variables": {"precip": {"native_name": "prec", "units": "mm/day", "target_units": "mm/day"}},
    "grid": {"hindcast_range": [1982, 2010]},
    "_verbose": False,
}


def test_split_streams_routes_hindcast_year_to_hindcast(monkeypatch):
    from rosetta.adapters.opendap import OPeNDAPAdapter
    captured = _capture_url(monkeypatch)
    OPeNDAPAdapter().fetch_data(_SPLIT_CFG, "precip", date_range=(2010, 2010), region=None)
    assert captured["url"].endswith("/.NCEP-CFSv2/.HINDCAST/.PENTAD_SAMPLES/.MONTHLY/.prec/dods")
    assert "{stream}" not in captured["url"]


def test_split_streams_routes_forecast_year_to_forecast(monkeypatch):
    from rosetta.adapters.opendap import OPeNDAPAdapter
    captured = _capture_url(monkeypatch)
    OPeNDAPAdapter().fetch_data(_SPLIT_CFG, "precip", date_range=(2024, 2024), region=None)
    assert captured["url"].endswith("/.NCEP-CFSv2/.FORECAST/.PENTAD_SAMPLES/.MONTHLY/.prec/dods")
    assert "{stream}" not in captured["url"]


def test_no_split_streams_uses_source_url_verbatim(monkeypatch):
    """Without split_streams, the variable hangs directly off source_url (the
    existing non-CFSv2 IRI behaviour is unchanged)."""
    from rosetta.adapters.opendap import OPeNDAPAdapter
    captured = _capture_url(monkeypatch)
    cfg = {
        "adapter": "opendap",
        "source_url": "https://iri/SOURCES/.NMME/.NCEP-CFSv2/.HINDCAST/.PENTAD_SAMPLES/.MONTHLY",
        "variables": {"precip": {"native_name": "prec", "units": "mm/day", "target_units": "mm/day"}},
        "grid": {"hindcast_range": [1982, 2010]},
        "_verbose": False,
    }
    OPeNDAPAdapter().fetch_data(cfg, "precip", date_range=(2010, 2010), region=None)
    assert captured["url"].endswith("/.HINDCAST/.PENTAD_SAMPLES/.MONTHLY/.prec/dods")


def _ds_for_years(years, months_init=2):
    # S = months since 1960-01-01 for (Feb of each year)
    s = np.array([(y - 1960) * 12 + (months_init - 1) for y in years], dtype=float)
    lat = np.arange(-2, 3, 1.0); lon = np.arange(36, 41, 1.0)
    data = np.zeros((len(s), len(lat), len(lon)), dtype="float32")
    ds = xr.Dataset({"prec": (["S", "Y", "X"], data)},
                    coords={"S": s, "Y": lat, "X": lon})
    ds["S"].attrs["units"] = "months since 1960-01-01"
    return ds


def test_append_streams_concats_both_streams(monkeypatch):
    from rosetta.adapters import opendap as opendap_mod
    from rosetta.adapters.opendap import OPeNDAPAdapter
    calls = []

    def fake_open(url, **kw):
        calls.append(url)
        # hindcast URL -> 2009,2010 ; forecast URL -> 2011,2012
        if "HINDCAST" in url:
            return _ds_for_years([2009, 2010])
        return _ds_for_years([2011, 2012])

    monkeypatch.setattr(opendap_mod.xr, "open_dataset", fake_open)
    cfg = dict(_SPLIT_CFG, append_streams=True)
    out = OPeNDAPAdapter().fetch_data(cfg, "precip", date_range=(2009, 2012), region=None)
    assert any("HINDCAST" in u for u in calls) and any("FORECAST" in u for u in calls)
    # decoded later, but S length should be 4 (2009,2010,2011,2012)
    assert out.sizes["S"] == 4


def test_no_append_flag_single_stream(monkeypatch):
    from rosetta.adapters import opendap as opendap_mod
    from rosetta.adapters.opendap import OPeNDAPAdapter
    calls = []
    monkeypatch.setattr(opendap_mod.xr, "open_dataset",
                        lambda url, **kw: calls.append(url) or _ds_for_years([2009, 2010]))
    # spanning range but NO append_streams -> one open, hindcast only
    OPeNDAPAdapter().fetch_data(_SPLIT_CFG, "precip", date_range=(2009, 2012), region=None)
    assert len(calls) == 1 and "HINDCAST" in calls[0]
