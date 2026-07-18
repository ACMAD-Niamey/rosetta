"""ACMAD predictands: obs/camsopi (iridl observed) and obs/tamsat (http).

Added on the `acmad` branch. Covers catalog registration and the IRIDL adapter's
new `observed: true` T-series URL path (no live network).
"""
from rosetta import catalog
from rosetta.adapters.iridl import build_url_parts


def test_camsopi_registered_as_observed_iridl():
    c = catalog.get("obs/camsopi")
    assert c["adapter"] == "iridl"
    assert c.get("observed") is True
    assert c["iridl_path"].endswith("CAMS_OPI/.v0208")
    assert c["variables"]["precip"]["native_name"] == "prcp"


def test_tamsat_registered_as_http():
    c = catalog.get("obs/tamsat")
    assert c["adapter"] == "http"
    assert c["source_url"].startswith("https://gws-access.jasmin.ac.uk")
    assert "{year}" in c["file_pattern"] and "{month" in c["file_pattern"]
    assert c["variables"]["precip"]["native_name"] == "rfe"


def test_iridl_observed_url_is_a_plain_T_series():
    """Observed products build a T-grid request with NO S(init)/L(lead) segments."""
    parts = build_url_parts(
        catalog.get("obs/camsopi"), "precip",
        date_range=(1991, 2020), region=[-40.0, 40.0, -25.0, 55.0])
    url = "/".join(parts)
    assert "CAMS_OPI/.v0208/.prcp" in url
    assert "/T/" in url and "1991" in url and "2020" in url
    assert "/S/" not in url and "/L/" not in url          # no forecast init/lead
    assert "Y/-40.0/40.0/RANGEEDGES" in url
    assert "X/-25.0/55.0/RANGEEDGES" in url


def test_iridl_forecast_path_still_has_S_and_L():
    """Regression guard: the forecast (S/L) path is unchanged for non-observed entries."""
    fake = {
        "iridl_path": "SOURCES/.Fake",
        "init_months": [1],
        "leadtime_month": [3, 4, 5],
        "variables": {"precip": {"iridl_name": "prcp", "native_name": "prcp"}},
    }
    url = "/".join(build_url_parts(fake, "precip", date_range=(1993, 2016), region=None))
    assert "/S/" in url and "/L/" in url and "average" in url
