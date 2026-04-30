def _read_fetch_src():
    from pathlib import Path
    return (Path(__file__).parent.parent / "src/rosetta/fetch.py").read_text()


def test_fetch_has_no_local_cache_dir():
    src = _read_fetch_src()
    assert ".cache/rosetta" not in src, "Old cache directory still referenced in fetch.py"
    assert "_CACHE_DIR" not in src, "_CACHE_DIR (old cache) still in fetch.py"
    assert "set_cache" not in src, "set_cache() (old cache toggle) still in fetch.py"


def test_fetch_raw_is_nuthatch_cached():
    """Caching lives in fetch._fetch_raw, not in individual adapters."""
    src = _read_fetch_src()
    assert "from nuthatch import cache" in src, "fetch.py should import nuthatch cache"
    assert "_fetch_raw" in src, "fetch.py should define _fetch_raw"
    assert "@cache" in src, "fetch._fetch_raw should be decorated with @cache"


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

    with patch("rosetta.fetch._fetch_raw") as mock_cached, \
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

    with patch("rosetta.fetch._fetch_raw", return_value=fake_ds) as mock_cached:
        from rosetta.fetch import fetch
        fetch("obs/chirps", variable="precip", cache=True)
        mock_cached.assert_called_once()


def test_cli_is_registered_in_pyproject():
    import tomllib
    from pathlib import Path
    with open(Path(__file__).parent.parent / "pyproject.toml", "rb") as f:
        config = tomllib.load(f)
    scripts = config.get("project", {}).get("scripts", {})
    assert "rosetta" in scripts, \
        "Missing 'rosetta' entry in [project.scripts] in pyproject.toml"
