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
    with open("pyproject.toml", "rb") as f:
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


def test_cli_is_registered_in_pyproject():
    import tomllib
    with open("pyproject.toml", "rb") as f:
        config = tomllib.load(f)
    scripts = config.get("project", {}).get("scripts", {})
    assert "rosetta" in scripts, \
        "Missing 'rosetta' entry in [project.scripts] in pyproject.toml"
