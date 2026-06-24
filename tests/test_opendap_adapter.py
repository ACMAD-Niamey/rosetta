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
