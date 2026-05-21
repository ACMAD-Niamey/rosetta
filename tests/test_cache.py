def _read_fetch_src():
    from pathlib import Path
    return (Path(__file__).parent.parent / "src/rosetta/fetch.py").read_text()


def test_fetch_has_no_local_cache_dir():
    src = _read_fetch_src()
    assert ".cache/rosetta" not in src, "Old cache directory still referenced in fetch.py"
    assert "_CACHE_DIR" not in src, "_CACHE_DIR (old cache) still in fetch.py"
    assert "set_cache" not in src, "set_cache() (old cache toggle) still in fetch.py"


def test_fetch_raw_is_nuthatch_cached():
    """Caching lives in fetch._fetch_raw_cached, not in individual adapters."""
    src = _read_fetch_src()
    assert "from nuthatch import cache" in src, "fetch.py should import nuthatch cache"
    assert "_fetch_raw_cached" in src, "fetch.py should define _fetch_raw_cached"
    assert "@cache" in src, "fetch._fetch_raw_cached should be decorated with @cache"
    assert 'cache_args=["product"' in src, "cache key must include product"


def test_adapters_do_not_have_nuthatch_cache():
    """Adapters should NOT have their own @cache — caching is in fetch._fetch_raw."""
    import inspect
    from rosetta.adapters.cds import CDSAdapter
    from rosetta.adapters.http import HTTPAdapter
    from rosetta.adapters.opendap import OPeNDAPAdapter
    from rosetta.adapters.s3 import S3Adapter
    from rosetta.adapters.ncei import NCEIAdapter

    for AdapterClass in [CDSAdapter, HTTPAdapter, OPeNDAPAdapter, S3Adapter, NCEIAdapter]:
        src = inspect.getsource(AdapterClass)
        assert "from nuthatch" not in src, \
            f"{AdapterClass.__name__} should not import nuthatch directly"


def test_nuthatch_config_in_pyproject():
    import tomllib
    from pathlib import Path
    with open(Path(__file__).parent.parent / "pyproject.toml", "rb") as f:
        config = tomllib.load(f)
    assert "nuthatch" in config.get("tool", {}), \
        "Missing [tool.nuthatch] section in pyproject.toml"


def test_cli_cache_list_invokable():
    from click.testing import CliRunner
    from rosetta.cli import cli
    runner = CliRunner()
    result = runner.invoke(cli, ["cache", "list"])
    assert result.exit_code in (0, 1), \
        f"CLI exited with unexpected code {result.exit_code}: {result.output}"


def test_fetch_cache_false_bypasses_nuthatch():
    """fetch(cache=False) calls the adapter directly, skipping _fetch_raw."""
    import numpy as np
    import xarray as xr
    from unittest.mock import patch, MagicMock

    fake_ds = xr.Dataset(
        {"precip": (["lat", "lon"], np.ones((3, 3), dtype=np.float32))},
        coords={"lat": [0.0, 1.0, 2.0], "lon": [30.0, 31.0, 32.0]},
    )
    fake_ds["precip"].attrs["units"] = "mm/day"

    with patch("rosetta.fetch._fetch_raw_cached") as mock_cached, \
         patch("rosetta.fetch.get_adapter") as mock_get_adapter:
        mock_adapter = MagicMock()
        mock_adapter.fetch_data.return_value = fake_ds
        mock_get_adapter.return_value = mock_adapter

        from rosetta.fetch import fetch
        fetch("obs/chirps", variable="precip", cache=False)

        mock_cached.assert_not_called()
        mock_adapter.fetch_data.assert_called_once()


def test_fetch_cache_true_uses_nuthatch():
    """fetch(cache=True) routes through _fetch_raw."""
    import numpy as np
    import xarray as xr
    from unittest.mock import patch

    fake_ds = xr.Dataset(
        {"precip": (["lat", "lon"], np.ones((3, 3), dtype=np.float32))},
        coords={"lat": [0.0, 1.0, 2.0], "lon": [30.0, 31.0, 32.0]},
    )
    fake_ds["precip"].attrs["units"] = "mm/day"

    with patch("rosetta.fetch._fetch_raw_cached", return_value=fake_ds) as mock_cached:
        from rosetta.fetch import fetch
        fetch("obs/chirps", variable="precip", cache=True)
        mock_cached.assert_called_once()


def test_cache_key_includes_required_dimensions():
    """The @cache decorator must include product, variable, date_range, region, init_months.

    This is the regression test for the cache_args=[] bug where all products
    shared the same cache entry and could return wrong data.
    """
    src = _read_fetch_src()
    for required_arg in ("product", "variable", "date_range", "region", "init_months"):
        assert required_arg in src, \
            f"cache_args must include '{required_arg}' to prevent cross-product cache collisions"


def test_different_products_call_adapter_separately():
    """Two different products must never share a cache entry.

    Regression test for the cache_args=[] bug: if cache_args is empty or wrong,
    the second product fetch returns the first product's cached data.
    """
    import numpy as np
    import pytest
    import xarray as xr
    from unittest.mock import patch, MagicMock, call

    def make_ds(value, native_var="precip"):
        ds = xr.Dataset(
            {native_var: (["lat", "lon"], np.full((2, 2), value, dtype=np.float32))},
            coords={"lat": [0.0, 1.0], "lon": [30.0, 31.0]},
        )
        ds[native_var].attrs["units"] = "mm/day"
        return ds

    chirps_ds = make_ds(1.0)
    era5_ds = make_ds(99.0, native_var="t2m")

    call_log = []

    def fake_cached(product, variable, config, date_range, region, init_months=None, init_date=None):
        call_log.append(product)
        if product == "obs/chirps":
            return chirps_ds
        return era5_ds

    with patch("rosetta.fetch._fetch_raw_cached", side_effect=fake_cached):
        from rosetta.fetch import fetch
        result_chirps = fetch("obs/chirps", variable="precip", cache=True)
        result_era5 = fetch("obs/era5", variable="temp", cache=True)

    assert call_log == ["obs/chirps", "obs/era5"], \
        "Both products must trigger separate cache lookups"
    # CHIRPS has "precip" variable, ERA5 has "temp" — if cache leaked across products,
    # one result would have the wrong variable entirely.
    assert "precip" in result_chirps, "obs/chirps result must have 'precip' variable"
    assert "temp" in result_era5, "obs/era5 result must have 'temp' variable"


def test_different_regions_call_adapter_separately():
    """Two fetches for the same product with different regions are cached separately."""
    import numpy as np
    import xarray as xr
    from unittest.mock import patch

    call_regions = []

    def fake_cached(product, variable, config, date_range, region, init_months=None, init_date=None):
        call_regions.append(region)
        ds = xr.Dataset(
            {"precip": (["lat", "lon"], np.ones((2, 2), dtype=np.float32))},
            coords={"lat": [0.0, 1.0], "lon": [30.0, 31.0]},
        )
        ds["precip"].attrs["units"] = "mm/day"
        return ds

    with patch("rosetta.fetch._fetch_raw_cached", side_effect=fake_cached):
        from rosetta.fetch import fetch
        fetch("obs/chirps", variable="precip", cache=True, region=[-2, 2, 30, 35])
        fetch("obs/chirps", variable="precip", cache=True, region=[-10, 10, 20, 50])

    assert len(call_regions) == 2, "Different regions must each produce a cache lookup"
    assert call_regions[0] != call_regions[1], "Cache keys for different regions must differ"


def test_different_date_ranges_call_adapter_separately():
    """Two fetches for the same product with different hindcast ranges are cached separately."""
    import numpy as np
    import xarray as xr
    from unittest.mock import patch

    call_date_ranges = []

    def fake_cached(product, variable, config, date_range, region, init_months=None, init_date=None):
        call_date_ranges.append(date_range)
        ds = xr.Dataset(
            {"precip": (["lat", "lon"], np.ones((2, 2), dtype=np.float32))},
            coords={"lat": [0.0, 1.0], "lon": [30.0, 31.0]},
        )
        ds["precip"].attrs["units"] = "mm/day"
        return ds

    with patch("rosetta.fetch._fetch_raw_cached", side_effect=fake_cached):
        from rosetta.fetch import fetch
        fetch("obs/chirps", variable="precip", cache=True, hindcast=(2010, 2015))
        fetch("obs/chirps", variable="precip", cache=True, hindcast=(2016, 2020))

    assert len(call_date_ranges) == 2, "Different date ranges must each produce a cache lookup"
    assert call_date_ranges[0] != call_date_ranges[1]


def test_cache_false_never_uses_cached_result():
    """cache=False always calls the adapter directly, even for a product that has a cached entry."""
    import numpy as np
    import xarray as xr
    from unittest.mock import patch, MagicMock

    call_count = {"adapter": 0, "cached": 0}

    def fake_adapter_fetch(*args, **kwargs):
        call_count["adapter"] += 1
        ds = xr.Dataset(
            {"precip": (["lat", "lon"], np.ones((2, 2), dtype=np.float32))},
            coords={"lat": [0.0, 1.0], "lon": [30.0, 31.0]},
        )
        ds["precip"].attrs["units"] = "mm/day"
        return ds

    def fake_cached(*args, **kwargs):
        call_count["cached"] += 1
        ds = xr.Dataset(
            {"precip": (["lat", "lon"], np.ones((2, 2), dtype=np.float32))},
            coords={"lat": [0.0, 1.0], "lon": [30.0, 31.0]},
        )
        ds["precip"].attrs["units"] = "mm/day"
        return ds

    mock_adapter = MagicMock()
    mock_adapter.fetch_data.side_effect = fake_adapter_fetch

    with patch("rosetta.fetch._fetch_raw_cached", side_effect=fake_cached), \
         patch("rosetta.fetch.get_adapter", return_value=mock_adapter):
        from rosetta.fetch import fetch
        fetch("obs/chirps", variable="precip", cache=False)
        fetch("obs/chirps", variable="precip", cache=False)

    assert call_count["adapter"] == 2, "cache=False must call adapter on every fetch"
    assert call_count["cached"] == 0, "cache=False must never call _fetch_raw_cached"


def test_fetch_uses_cache_on_second_call(tmp_path, monkeypatch):
    """Second fetch with the same args MUST hit the cache, not re-call the adapter.

    Regression test for issue #24: the CDS adapter previously returned lazy
    datasets that pickled as a 'reopen this temp file' recipe. The first fetch
    wrote a 7KB cache pointing at a /var/folders/.../T/ path; macOS reaped that
    path, breaking the cache. This test exercises the real nuthatch round-trip
    (read-after-write, no `_fetch_raw_cached` mock), which a regression to a
    lazy adapter return would fail when the second call accesses .values.
    """
    import numpy as np
    import xarray as xr
    from unittest.mock import patch, MagicMock
    from nuthatch.config import NuthatchConfig

    # Redirect nuthatch to a per-test cache dir. NUTHATCH_* env vars alone
    # aren't enough because nuthatch reads the wrapped module's pyproject.toml
    # AFTER env vars and wrapped_config wins (nuthatch/config.py:290-293).
    # Suppress the pyproject lookup so env vars take effect.
    monkeypatch.setenv("NUTHATCH_ROOT_FILESYSTEM", str(tmp_path))
    monkeypatch.setenv("NUTHATCH_LOCAL_FILESYSTEM", str(tmp_path))
    monkeypatch.setattr(NuthatchConfig, "_find_nuthatch_config",
                        lambda self, p: None)

    ds = xr.Dataset(
        {"precip": (["lat", "lon"],
                    np.arange(24, dtype=np.float32).reshape(6, 4))},
        coords={"lat": np.arange(6.0), "lon": np.arange(4.0)},
    )
    ds["precip"].attrs["units"] = "mm/month"

    adapter = MagicMock()
    adapter.fetch_data.return_value = ds

    with patch("rosetta.fetch.get_adapter", return_value=adapter):
        from rosetta.fetch import fetch
        first = fetch("obs/chirps", variable="precip", cache=True, verbose=False)
        assert adapter.fetch_data.call_count == 1, \
            "First fetch must call the adapter"

        second = fetch("obs/chirps", variable="precip", cache=True, verbose=False)
        assert adapter.fetch_data.call_count == 1, (
            "Second fetch must hit the cache and skip the adapter — "
            "got call_count={}".format(adapter.fetch_data.call_count)
        )

    # Forcing array access catches the issue #24 failure mode: a lazy dataset
    # whose backing file got reaped would raise FileNotFoundError here.
    np.testing.assert_array_equal(
        np.asarray(second["precip"]),
        np.asarray(first["precip"]),
    )


def test_cli_is_registered_in_pyproject():
    import tomllib
    from pathlib import Path
    with open(Path(__file__).parent.parent / "pyproject.toml", "rb") as f:
        config = tomllib.load(f)
    scripts = config.get("project", {}).get("scripts", {})
    assert "rosetta" in scripts, \
        "Missing 'rosetta' entry in [project.scripts] in pyproject.toml"
