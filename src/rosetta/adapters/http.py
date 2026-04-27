import os
import re
import tempfile
import urllib.request
from concurrent.futures import ThreadPoolExecutor, as_completed
import pandas as pd
import xarray as xr
from .base import AdapterBase

_MAX_WORKERS = 8


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
    """
    import rioxarray  # noqa: F401
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
            print(f"[rosetta:http] downloading {len(urls)} file(s) (format={fmt}, workers={min(_MAX_WORKERS, len(urls))})")

        if fmt == "cog":
            var_cfg = product_config.get("variables", {}).get(variable, {})
            native_name = var_cfg.get("native_name", variable)
            fill_value = var_cfg.get("fill_value")
            datasets = []
            for url in _iter(urls, "Rosetta HTTP download", enabled=progress):
                try:
                    datasets.append(_open_cog_subset(
                        url, region, variable=native_name, fill_value=fill_value))
                except Exception as e:
                    print(f"Error fetching {url}: {e}")
        else:
            datasets = self._fetch_netcdf_parallel(urls, region, progress)

        if not datasets:
            raise RuntimeError("No data files retrieved")
        return xr.concat(datasets, dim="time") if len(datasets) > 1 else datasets[0]

    @staticmethod
    def _download_one(url, region):
        """Download a single NetCDF file and return (url, xr.Dataset)."""
        with tempfile.NamedTemporaryFile(suffix=".nc", delete=False) as tmp:
            urllib.request.urlretrieve(url, tmp.name)
            ds = xr.open_dataset(tmp.name)
            ds = _subset_region(ds, region)
            os.unlink(tmp.name)
        return url, ds

    def _fetch_netcdf_parallel(self, urls, region, progress):
        results = {}
        errors = []
        with ThreadPoolExecutor(max_workers=min(_MAX_WORKERS, len(urls))) as pool:
            futures = {pool.submit(self._download_one, u, region): u for u in urls}
            for fut in _iter(as_completed(futures), "Rosetta HTTP download", enabled=progress):
                try:
                    url, ds = fut.result()
                    results[url] = ds
                except Exception as e:
                    errors.append((futures[fut], e))
                    print(f"Error fetching {futures[fut]}: {e}")
        return [results[u] for u in urls if u in results]
