# Nuthatch Caching Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace Rosetta's custom SHA-256 NetCDF cache in `fetch.py` with `@nuthatch.cache()` at the per-adapter download boundary, add nuthatch config to `pyproject.toml`, and expose a `rosetta cache` CLI subcommand.

**Architecture:** Cache boundary is each adapter's `fetch_data()` method (not end-to-end `fetch()`). This means normalization changes don't bust the cache. The `SheerwaterAdapter` is explicitly excluded — Sheerwater is already Nuthatch-cached upstream. The old `~/.cache/rosetta` NetCDF cache is removed; nuthatch uses `~/.nuthatch/caches` by default (configurable in `[tool.nuthatch]`).

**Tech Stack:** `nuthatch` (already installed, `nuthatch.cache` decorator), `click` (for CLI — check if already installed), `nuthatch.cli` (for cache management commands)

---

## File Map

| File | Change |
|------|--------|
| `src/rosetta/fetch.py` | Remove custom cache (`_CACHE_DIR`, `_CACHE_ENABLED`, `_cache_key`, `_cache_path`, `set_cache`); keep everything else |
| `src/rosetta/adapters/cds.py` | Wrap `fetch_data` with `@nuthatch.cache()` |
| `src/rosetta/adapters/opendap.py` | Wrap download function with `@nuthatch.cache()` |
| `src/rosetta/adapters/s3.py` | Wrap download function with `@nuthatch.cache()` |
| `src/rosetta/adapters/ncei.py` | Wrap download function with `@nuthatch.cache()` |
| `src/rosetta/adapters/http.py` | Wrap `fetch_data` with `@nuthatch.cache()` |
| `src/rosetta/adapters/sheerwater.py` | No change — Sheerwater already cached upstream |
| `src/rosetta/cli.py` | Create — `rosetta cache list` and `rosetta cache clear` subcommands |
| `pyproject.toml` | Add `[tool.nuthatch]` config section; add `[project.scripts]` entry point |
| `tests/test_cache.py` | Create — tests for cache integration and CLI |

---

## Task 1: Remove custom cache from fetch.py

**Files:**
- Modify: `src/rosetta/fetch.py`

- [ ] **Step 1: Write a test that the old cache behavior is gone**

Create `tests/test_cache.py`:
```python
def test_fetch_has_no_local_cache_dir():
    """The old ~/.cache/rosetta NetCDF cache should not be referenced."""
    import inspect
    from rosetta import fetch
    src = inspect.getsource(fetch)
    assert ".cache/rosetta" not in src, \
        "Old cache directory still referenced in fetch.py"
    assert "_CACHE_DIR" not in src, \
        "_CACHE_DIR (old cache) still in fetch.py"
    assert "set_cache" not in src, \
        "set_cache() (old cache toggle) still in fetch.py"
```

- [ ] **Step 2: Run to verify it fails**

```bash
uv run pytest tests/test_cache.py::test_fetch_has_no_local_cache_dir -v
```
Expected: FAIL (old cache code still present).

- [ ] **Step 3: Strip the custom cache out of fetch.py**

Replace the entire `src/rosetta/fetch.py` with this cleaned-up version (removes `_CACHE_DIR`, `_CACHE_ENABLED`, `_cache_key`, `_cache_path`, `set_cache`, and the cache read/write blocks in `fetch()`):

```python
import xarray as xr

from . import catalog
from .adapters import get_adapter
from .normalize import normalize
from .storage import save

SEASON_MONTHS = {
    "DJF": (12, 2), "JFM": (1, 3), "FMA": (2, 4), "MAM": (3, 5),
    "AMJ": (4, 6), "MJJ": (5, 7), "JJA": (6, 8), "JAS": (7, 9),
    "ASO": (8, 10), "SON": (9, 11), "OND": (10, 12), "NDJ": (11, 1),
}


def _log(verbose, msg):
    if verbose:
        print(f"[rosetta] {msg}")


def parse_target(target, year=None):
    if isinstance(target, tuple) and len(target) == 2:
        return target
    if isinstance(target, str) and target.upper() in SEASON_MONTHS:
        from datetime import datetime
        import calendar
        s, e = SEASON_MONTHS[target.upper()]
        y = year or datetime.now().year
        y_end = y + (1 if e < s else 0)
        return (datetime(y, s, 1), datetime(y_end, e, calendar.monthrange(y_end, e)[1]))
    raise ValueError(f"Unknown target: {target}")


def parse_init(init):
    if isinstance(init, str):
        from datetime import datetime
        return datetime.strptime(init[:7], "%Y-%m")
    return init


def fetch(product, variable, init=None, target=None, region=None,
          hindcast=None, destination=None, format="netcdf", verbose=True,
          progress=True):
    """Fetch, normalize, and optionally save climate data.

    Caching is handled at the adapter level via @nuthatch.cache().
    """
    _log(verbose, f"fetch start: product={product}, variable={variable}")

    config = dict(catalog.get(product))
    config["_verbose"] = verbose
    config["_progress"] = progress
    adapter = get_adapter(config["adapter"])

    date_range = hindcast

    if init:
        init_dt = parse_init(init)
        config["init_months"] = [init_dt.month]
        if date_range is None:
            date_range = (init_dt.year, init_dt.year)

        if target:
            target_range = parse_target(target, year=init_dt.year)
            s_month, e_month = target_range[0].month, target_range[1].month
            if s_month <= e_month:
                target_months = list(range(s_month, e_month + 1))
            else:
                target_months = list(range(s_month, 13)) + list(range(1, e_month + 1))
            lead_months = [(m - init_dt.month) % 12 + 1 for m in target_months]
            if "cds_model" in config:
                if config.get("cds_dataset") == "seasonal-original-single-levels":
                    from datetime import datetime, timedelta
                    init_date = datetime(init_dt.year, init_dt.month, 1)
                    hours = []
                    for m in lead_months:
                        m_start = init_dt.month + m - 1
                        y_start = init_dt.year + (m_start - 1) // 12
                        m_start = (m_start - 1) % 12 + 1
                        m_end = init_dt.month + m
                        y_end = init_dt.year + (m_end - 1) // 12
                        m_end = (m_end - 1) % 12 + 1
                        start = (datetime(y_start, m_start, 1) - init_date).days * 24
                        end = (datetime(y_end, m_end, 1) - init_date).days * 24
                        hours.extend(range(start, end, 24))
                    hours = sorted(set(hours))
                    var_cfg = config["variables"][variable]
                    if var_cfg.get("accumulated") and hours:
                        extra = hours[0] - 24
                        if extra > 0:
                            hours = [extra] + hours
                    config["leadtime_hour"] = hours
                else:
                    config["leadtime_month"] = lead_months
            config["target_lead_months"] = lead_months
            config["target_range"] = target_range

    _log(verbose, f"downloading via adapter={config['adapter']}")
    raw = adapter.fetch_data(config, variable, date_range=date_range, region=region)
    _log(verbose, "normalizing dataset")
    clean = normalize(raw, config, variable, region)

    if destination:
        _log(verbose, f"saving output -> {destination}")
        save(clean, destination, format)

    _log(verbose, "fetch complete")
    return clean
```

- [ ] **Step 4: Run the test**

```bash
uv run pytest tests/test_cache.py::test_fetch_has_no_local_cache_dir -v
```
Expected: PASS.

- [ ] **Step 5: Run full test suite to check for regressions**

```bash
uv run pytest tests/ -v
```
Expected: all pass. (The old `cache=True/False` kwarg is removed — if any test passes it explicitly, update that test to remove the kwarg.)

- [ ] **Step 6: Commit**

```bash
git add src/rosetta/fetch.py tests/test_cache.py
git commit -m "refactor: remove custom NetCDF cache from fetch.py (replaced by nuthatch)"
```

---

## Task 2: Add @nuthatch.cache() to adapters

**Files:**
- Modify: `src/rosetta/adapters/cds.py`, `opendap.py`, `s3.py`, `ncei.py`, `http.py`
- Modify: `pyproject.toml`

The nuthatch `@cache()` decorator wraps a function and persists its return value keyed on arguments. We cache at the `fetch_data()` method level. Each adapter gets a `_CACHE_VERSION` integer constant — bump it when the adapter's download logic changes to invalidate stale entries.

- [ ] **Step 1: Add nuthatch config to pyproject.toml**

Add after the `[tool.pytest.ini_options]` section in `pyproject.toml`:
```toml
[tool.nuthatch]
# Local-only cache for V1. Public mirror is a V2 item.
[tool.nuthatch.local.zarr]
filesystem = "~/.nuthatch/rosetta"
```

- [ ] **Step 2: Add @nuthatch.cache() to CDSAdapter.fetch_data**

In `src/rosetta/adapters/cds.py`, add the import and version constant, then decorate `fetch_data`:

```python
import tempfile
import xarray as xr
from nuthatch import cache
from .base import AdapterBase

_CACHE_VERSION = 1  # bump when download URL or post-processing changes


class CDSAdapter(AdapterBase):
    def health_check(self, product_config, probe_remote=False):
        # ... (unchanged) ...

    @cache(namespace="rosetta/cds", version=str(_CACHE_VERSION),
           cache_args=["product_config", "variable", "date_range", "region"],
           backend="zarr")
    def fetch_data(self, product_config, variable, date_range=None, region=None):
        # ... (body unchanged) ...
```

Keep the entire method body exactly as it is — only add the decorator and the import + constant at the top.

- [ ] **Step 3: Add @nuthatch.cache() to HTTPAdapter.fetch_data**

In `src/rosetta/adapters/http.py`:
```python
from nuthatch import cache

_CACHE_VERSION = 1
```

Decorate `fetch_data`:
```python
    @cache(namespace="rosetta/http", version=str(_CACHE_VERSION),
           cache_args=["product_config", "variable", "date_range", "region"],
           backend="zarr")
    def fetch_data(self, product_config, variable, date_range=None, region=None):
        # ... (body unchanged) ...
```

- [ ] **Step 4: Add @nuthatch.cache() to OPeNDAPAdapter.fetch_data**

Open `src/rosetta/adapters/opendap.py`. Add import and constant at top, decorate `fetch_data`:
```python
from nuthatch import cache

_CACHE_VERSION = 1

# In class:
    @cache(namespace="rosetta/opendap", version=str(_CACHE_VERSION),
           cache_args=["product_config", "variable", "date_range", "region"],
           backend="zarr")
    def fetch_data(self, product_config, variable, date_range=None, region=None):
```

- [ ] **Step 5: Add @nuthatch.cache() to S3Adapter.fetch_data**

Open `src/rosetta/adapters/s3.py`. Add import and constant at top, decorate `fetch_data`:
```python
from nuthatch import cache

_CACHE_VERSION = 1

# In class:
    @cache(namespace="rosetta/s3", version=str(_CACHE_VERSION),
           cache_args=["product_config", "variable", "date_range", "region"],
           backend="zarr")
    def fetch_data(self, product_config, variable, date_range=None, region=None):
```

- [ ] **Step 6: Add @nuthatch.cache() to NCEIAdapter.fetch_data**

Open `src/rosetta/adapters/ncei.py`. Add import and constant at top, decorate `fetch_data`:
```python
from nuthatch import cache

_CACHE_VERSION = 1

# In class:
    @cache(namespace="rosetta/ncei", version=str(_CACHE_VERSION),
           cache_args=["product_config", "variable", "date_range", "region"],
           backend="zarr")
    def fetch_data(self, product_config, variable, date_range=None, region=None):
```

- [ ] **Step 7: Write cache decorator tests**

Add to `tests/test_cache.py`:
```python
def test_adapter_fetch_data_is_decorated():
    """All non-Sheerwater adapters should have nuthatch cache applied."""
    import inspect
    from rosetta.adapters.cds import CDSAdapter
    from rosetta.adapters.http import HTTPAdapter
    from rosetta.adapters.opendap import OPeNDAPAdapter
    from rosetta.adapters.s3 import S3Adapter
    from rosetta.adapters.ncei import NCEIAdapter
    from rosetta.adapters.sheerwater import SheerwaterAdapter

    for AdapterClass in [CDSAdapter, HTTPAdapter, OPeNDAPAdapter, S3Adapter, NCEIAdapter]:
        method = AdapterClass.fetch_data
        # nuthatch wraps with a decorator that adds a __wrapped__ attribute
        # or changes __qualname__. Check the module has nuthatch import.
        src = inspect.getsource(AdapterClass)
        assert "nuthatch" in src or "cache" in src, \
            f"{AdapterClass.__name__}.fetch_data is not decorated with nuthatch cache"

    # SheerwaterAdapter should NOT be cached (already cached upstream)
    sheerwater_src = inspect.getsource(SheerwaterAdapter)
    assert "@cache" not in sheerwater_src, \
        "SheerwaterAdapter.fetch_data should NOT have @nuthatch.cache — Sheerwater is already cached upstream"


def test_nuthatch_config_in_pyproject():
    """pyproject.toml should have a [tool.nuthatch] section."""
    import tomllib
    with open("pyproject.toml", "rb") as f:
        config = tomllib.load(f)
    assert "nuthatch" in config.get("tool", {}), \
        "Missing [tool.nuthatch] section in pyproject.toml"
```

- [ ] **Step 8: Run the tests**

```bash
uv run pytest tests/test_cache.py -v
```
Expected: all pass.

- [ ] **Step 9: Run full test suite**

```bash
uv run pytest tests/ -v
```
Expected: all pass.

- [ ] **Step 10: Commit**

```bash
git add src/rosetta/adapters/cds.py src/rosetta/adapters/http.py \
        src/rosetta/adapters/opendap.py src/rosetta/adapters/s3.py \
        src/rosetta/adapters/ncei.py pyproject.toml tests/test_cache.py
git commit -m "feat: add @nuthatch.cache() to all adapters (§4.1)"
```

---

## Task 3: Cache observability CLI

**Files:**
- Create: `src/rosetta/cli.py`
- Modify: `pyproject.toml`

- [ ] **Step 1: Check if click is available**

```bash
uv run python -c "import click; print('click', click.__version__)"
```
If click is not installed, add it:
```bash
uv add click
```

- [ ] **Step 2: Write the failing test**

Add to `tests/test_cache.py`:
```python
def test_cli_cache_list_invokable():
    from click.testing import CliRunner
    from rosetta.cli import cli
    runner = CliRunner()
    result = runner.invoke(cli, ["cache", "list"])
    # Should not crash (exit code 0 or nuthatch says cache is empty — both ok)
    assert result.exit_code in (0, 1), \
        f"CLI exited with unexpected code {result.exit_code}: {result.output}"


def test_cli_is_registered_in_pyproject():
    import tomllib
    with open("pyproject.toml", "rb") as f:
        config = tomllib.load(f)
    scripts = config.get("project", {}).get("scripts", {})
    assert "rosetta" in scripts, \
        "Missing 'rosetta' entry in [project.scripts] in pyproject.toml"
```

- [ ] **Step 3: Run to verify they fail**

```bash
uv run pytest tests/test_cache.py::test_cli_cache_list_invokable tests/test_cache.py::test_cli_is_registered_in_pyproject -v
```
Expected: both FAIL (module doesn't exist yet).

- [ ] **Step 4: Create `src/rosetta/cli.py`**

```python
"""Rosetta command-line interface.

Usage:
    rosetta cache list
    rosetta cache clear --product <name>
"""
import click
from nuthatch.cli import cli as nuthatch_cli


@click.group()
def cli():
    """Rosetta — climate data integration CLI."""


@cli.group()
def cache():
    """Inspect and manage the local Nuthatch cache."""


@cache.command("list")
@click.option("--namespace", default=None, help="Filter by namespace prefix (e.g. rosetta/cds)")
def cache_list(namespace):
    """List cached entries with sizes."""
    from click.testing import CliRunner
    runner = CliRunner()
    args = ["list"]
    if namespace:
        args += ["--namespace", namespace]
    result = runner.invoke(nuthatch_cli, args, catch_exceptions=False)
    click.echo(result.output)


@cache.command("clear")
@click.option("--product", required=True, help="Rosetta product name (e.g. nmme/cfsv2)")
def cache_clear(product):
    """Remove cached entries for a specific product."""
    namespace = f"rosetta/{product.split('/')[0]}"
    click.echo(f"Clearing cache for product={product} (namespace={namespace})")
    from click.testing import CliRunner
    runner = CliRunner()
    result = runner.invoke(nuthatch_cli, ["delete", "--namespace", namespace],
                           catch_exceptions=False)
    click.echo(result.output)
```

- [ ] **Step 5: Add entry point to pyproject.toml**

Add after the `[project.optional-dependencies]` section:
```toml
[project.scripts]
rosetta = "rosetta.cli:cli"
```

- [ ] **Step 6: Reinstall the package so the entry point is registered**

```bash
uv sync
```

- [ ] **Step 7: Run the tests**

```bash
uv run pytest tests/test_cache.py::test_cli_cache_list_invokable tests/test_cache.py::test_cli_is_registered_in_pyproject -v
```
Expected: both PASS.

- [ ] **Step 8: Smoke-test the CLI manually**

```bash
uv run rosetta cache list
```
Expected: output from nuthatch (may say "no entries" if cache is empty — that's fine).

- [ ] **Step 9: Run full test suite**

```bash
uv run pytest tests/ -v
```
Expected: all pass.

- [ ] **Step 10: Commit**

```bash
git add src/rosetta/cli.py pyproject.toml uv.lock tests/test_cache.py
git commit -m "feat: add rosetta cache list/clear CLI subcommand (§4.3)"
```
