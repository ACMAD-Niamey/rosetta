import os
import random
import re
import tempfile
import threading
import time
import urllib.request
from concurrent.futures import ThreadPoolExecutor, as_completed
import pandas as pd
import xarray as xr
from .base import AdapterBase


_MAX_WORKERS = 8
_DEFAULT_MAX_RETRIES = 3
_DEFAULT_RETRY_BACKOFF = 1.0


class _RateLimiter:
    """Thread-safe minimum-interval gate between requests.

    Used to pace per-file opens so we don't blow through a server's
    requests-per-second budget (CHIRPS rate-limits at >~60 requests/sec when
    GDAL/vsicurl drives many range reads in quick succession).
    """

    def __init__(self, min_interval):
        self.min_interval = float(min_interval or 0.0)
        self._last = 0.0
        self._lock = threading.Lock()

    def wait(self):
        if self.min_interval <= 0:
            return
        with self._lock:
            elapsed = time.monotonic() - self._last
            if elapsed < self.min_interval:
                time.sleep(self.min_interval - elapsed)
            self._last = time.monotonic()


# HTTP 4xx ("client error") responses indicate a problem with our request
# (URL doesn't exist, unauthorized, etc.) and won't fix themselves on retry.
# 5xx and network errors are the ones worth retrying. GDAL/rasterio and
# urllib surface them with different wording, so we match both.
_PERMANENT_HTTP_PATTERNS = (
    re.compile(r"HTTP response code: 4\d{2}"),    # rasterio / vsicurl
    re.compile(r"HTTP Error 4\d{2}"),             # urllib
)


def _is_transient(exc):
    msg = str(exc)
    for pat in _PERMANENT_HTTP_PATTERNS:
        if pat.search(msg):
            return False
    return True


def _with_retry(fn, max_retries, backoff, label, verbose=True, on_failure=None,
                is_transient=_is_transient):
    """Call fn(), retrying transient failures with exponential backoff + jitter.

    Only retries when `is_transient(exc)` is True — by default that means
    "anything except an HTTP 4xx response," since 4xx errors are permanent
    (404 won't become 200 in 2 seconds). Jitter (random factor in [0.5, 1.5))
    desynchronizes retries when many workers fail simultaneously against a
    rate-limited server. `on_failure` runs after each failed attempt before
    the sleep.
    """
    last_err = None
    for attempt in range(max_retries + 1):
        try:
            return fn()
        except Exception as e:
            last_err = e
            if not is_transient(e):
                raise
            if attempt >= max_retries:
                raise
            if on_failure is not None:
                try:
                    on_failure()
                except Exception:
                    pass
            wait = backoff * (2 ** attempt) * (0.5 + random.random())
            if verbose:
                print(f"[rosetta:http] {label} failed "
                      f"(attempt {attempt + 1}/{max_retries + 1}): {e}; "
                      f"retrying in {wait:.2f}s")
            time.sleep(wait)
    raise last_err  # unreachable, but keeps type-checkers honest


def _iter(items, desc, enabled=True):
    if not enabled:
        return items
    try:
        from tqdm.auto import tqdm
        return tqdm(items, desc=desc)
    except Exception:
        return items


def _subset_region(ds, region):
    """Subset a dataset to a region [lat_s, lat_n, lon_w, lon_e] immediately after loading."""
    if region is None:
        return ds
    lat_s, lat_n, lon_w, lon_e = region
    buf = 1.0
    lat_dim = "latitude" if "latitude" in ds.dims else "lat" if "lat" in ds.dims else None
    lon_dim = "longitude" if "longitude" in ds.dims else "lon" if "lon" in ds.dims else None
    if lat_dim and lon_dim:
        ds = ds.sortby(lat_dim)
        ds = ds.sel({
            lat_dim: slice(lat_s - buf, lat_n + buf),
            lon_dim: slice(lon_w - buf, lon_e + buf),
        })
    return ds.load()


def _open_cog_subset(url, region, variable=None, fill_value=None):
    """Open a COG via HTTP range reads, subsetting to region without downloading the whole file.

    CHIRPS and similar climate COGs often store a sentinel fill (e.g. -9999) without
    declaring it in the TIFF nodata tag — rasterio then passes it through as data.
    If `fill_value` is provided, mask those cells as NaN before returning.

    GDAL caches vsicurl responses (including transient HTTP errors) keyed by
    URL at the process level. That cache replays a previous 503 on retry, so
    we disable it for the open via CPL_VSIL_CURL_NON_CACHED. Cost is a few
    extra range reads per file; benefit is that the adapter's retry loop
    actually re-hits the server instead of looping on a cached failure.
    """
    import rasterio
    import rioxarray  # noqa: F401
    with rasterio.Env(CPL_VSIL_CURL_NON_CACHED="/vsicurl/"):
        ds = xr.open_dataset(url, engine="rasterio")
    if region:
        lat_s, lat_n, lon_w, lon_e = region
        buf = 1.0
        # COGs use x/y coords (lon/lat), y is descending
        ds = ds.sel(y=slice(lat_n + buf, lat_s - buf), x=slice(lon_w - buf, lon_e + buf))
    ds = ds.load()
    if fill_value is not None and "band_data" in ds:
        ds["band_data"] = ds["band_data"].where(ds["band_data"] != fill_value)
    # Rename COG default coords/vars to standard names
    renames = {}
    if "x" in ds.dims:
        renames["x"] = "longitude"
    if "y" in ds.dims:
        renames["y"] = "latitude"
    if "band_data" in ds and variable:
        renames["band_data"] = variable
    if renames:
        ds = ds.rename(renames)
    # Drop band dim if it's size 1
    if "band" in ds.dims and ds.sizes["band"] == 1:
        ds = ds.squeeze("band", drop=True)
    # Add time coordinate from filename
    m = re.search(r'(\d{4})\.(\d{2})', url)
    if m and "time" not in ds.dims:
        ts = pd.Timestamp(f"{m.group(1)}-{m.group(2)}-01")
        ds = ds.expand_dims(time=[ts])
    return ds


class HTTPAdapter(AdapterBase):
    def health_check(self, product_config, probe_remote=False):
        url = product_config.get("source_url")
        if not url:
            return {
                "healthy": False,
                "kind": "config",
                "message": "Missing source_url in product config.",
                "probe_remote": bool(probe_remote),
            }

        if not (url.startswith("http://") or url.startswith("https://")):
            return {
                "healthy": False,
                "kind": "config",
                "message": f"Unsupported source_url protocol: {url}",
                "probe_remote": bool(probe_remote),
            }

        if not probe_remote:
            return {
                "healthy": True,
                "kind": "config",
                "message": "HTTP adapter config is valid.",
                "probe_remote": False,
            }

        try:
            request = urllib.request.Request(url, method="HEAD")
            with urllib.request.urlopen(request, timeout=10):
                pass
            return {
                "healthy": True,
                "kind": "remote",
                "message": "HTTP source reachable.",
                "probe_remote": True,
            }
        except Exception as e:
            return {
                "healthy": False,
                "kind": "remote",
                "message": f"HTTP source unreachable: {e}",
                "probe_remote": True,
            }

    def fetch_data(self, product_config, variable, date_range=None, region=None):
        verbose = product_config.get("_verbose", True)
        progress = product_config.get("_progress", True)
        # Strict by default: any per-file fetch error aborts the whole pull.
        # Partial results have silently poisoned downstream caches and skill
        # metrics in the past (e.g. CHIRPS rate-limit losing two decades of
        # months but pipeline still claiming success). Callers that genuinely
        # want best-effort fetches can opt in via fetch(..., allow_partial=True).
        allow_partial = product_config.get("_allow_partial", False)
        max_retries = int(product_config.get("_max_retries", _DEFAULT_MAX_RETRIES))
        retry_backoff = float(product_config.get("_retry_backoff", _DEFAULT_RETRY_BACKOFF))
        request_interval = float(product_config.get("_request_interval", 0.0))
        rate_limiter = _RateLimiter(request_interval)
        base_url = product_config["source_url"]
        fmt = product_config.get("format", "netcdf")

        file_pattern = product_config.get("file_pattern")
        if not file_pattern:
            raise ValueError("HTTP adapter requires 'file_pattern' in product config")

        if date_range:
            y0, y1 = date_range
            if "{month" in file_pattern:
                files = [file_pattern.format(year=y, month=m) for y in range(y0, y1 + 1) for m in range(1, 13)]
            else:
                files = [file_pattern.format(year=y) for y in range(y0, y1 + 1)]
        else:
            # Default to 2 months ago to account for observational data processing lag
            from datetime import datetime, timedelta
            recent = datetime.now().replace(day=1) - timedelta(days=60)
            if "{month" in file_pattern:
                files = [file_pattern.format(year=recent.year, month=recent.month)]
            else:
                files = [file_pattern.format(year=recent.year)]

        urls = [base_url.rstrip("/") + "/" + f for f in files]
        if verbose:
            # The COG path is sequential; only the netcdf path uses workers.
            workers = min(_MAX_WORKERS, len(urls)) if fmt != "cog" else 1
            print(f"[rosetta:http] downloading {len(urls)} file(s) "
                  f"(format={fmt}, workers={workers}, "
                  f"max_retries={max_retries}, request_interval={request_interval}s)")

        if fmt == "cog":
            var_cfg = product_config.get("variables", {}).get(variable, {})
            native_name = var_cfg.get("native_name", variable)
            fill_value = var_cfg.get("fill_value")
            datasets = []
            failures = []
            for url in _iter(urls, "Rosetta HTTP download", enabled=progress):
                rate_limiter.wait()
                try:
                    ds = _with_retry(
                        lambda u=url: _open_cog_subset(
                            u, region, variable=native_name, fill_value=fill_value),
                        max_retries, retry_backoff,
                        label=f"COG open {url}", verbose=verbose,
                    )
                    datasets.append(ds)
                except Exception as e:
                    failures.append((url, e))
                    print(f"Error fetching {url}: {e}")
        else:
            datasets, failures = self._fetch_netcdf_parallel(
                urls, region, progress, rate_limiter, max_retries, retry_backoff, verbose)

        if failures and not allow_partial:
            raise RuntimeError(
                f"HTTP adapter: {len(failures)}/{len(urls)} file(s) failed; "
                f"refusing to return partial data (pass allow_partial=True to "
                f"fetch() to override). First failure: {failures[0][0]}: {failures[0][1]}"
            )
        if not datasets:
            raise RuntimeError("No data files retrieved")
        return xr.concat(datasets, dim="time") if len(datasets) > 1 else datasets[0]

    @staticmethod
    def _download_one(url, region, rate_limiter=None, max_retries=0, backoff=0.0,
                      verbose=True):
        """Download a single NetCDF file and return (url, xr.Dataset).

        Per-file retries + an optional shared rate limiter live here so they
        apply to each worker thread; the pool itself only bounds concurrency.
        """
        def _do():
            with tempfile.NamedTemporaryFile(suffix=".nc", delete=False) as tmp:
                urllib.request.urlretrieve(url, tmp.name)
                ds = xr.open_dataset(tmp.name)
                ds = _subset_region(ds, region)
                os.unlink(tmp.name)
            return ds

        if rate_limiter is not None:
            rate_limiter.wait()
        ds = _with_retry(_do, max_retries, backoff,
                         label=f"NetCDF download {url}", verbose=verbose)
        return url, ds

    def _fetch_netcdf_parallel(self, urls, region, progress, rate_limiter,
                               max_retries, retry_backoff, verbose):
        results = {}
        errors = []
        with ThreadPoolExecutor(max_workers=min(_MAX_WORKERS, len(urls))) as pool:
            futures = {
                pool.submit(self._download_one, u, region,
                            rate_limiter, max_retries, retry_backoff, verbose): u
                for u in urls
            }
            for fut in _iter(as_completed(futures), "Rosetta HTTP download", enabled=progress):
                try:
                    url, ds = fut.result()
                    results[url] = ds
                except Exception as e:
                    errors.append((futures[fut], e))
                    print(f"Error fetching {futures[fut]}: {e}")
        datasets = [results[u] for u in urls if u in results]
        return datasets, errors
