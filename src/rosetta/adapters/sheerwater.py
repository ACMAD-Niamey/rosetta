"""Adapter for Sheerwater-backed datasets (public GCS Zarr stores).

Sheerwater (https://github.com/rhiza-research/sheerwater) exposes climate
datasets via plain Python functions that return xarray Datasets. This adapter
translates Rosetta's fetch arguments into Sheerwater's calling convention and
returns the raw dataset for Rosetta's normalization layer to process.

Caching note: Sheerwater is already Nuthatch-cached upstream. Do NOT apply
@nuthatch.cache() here — that would double-store the same data.
"""
import importlib
from datetime import date

import xarray as xr

from .base import AdapterBase


def _to_time_range(date_range: tuple[int, int] | None) -> tuple[str, str]:
    """Convert a (start_year, end_year) tuple to ISO date strings."""
    if date_range is None:
        from datetime import datetime
        today = datetime.today()
        start = date(today.year - 1, 1, 1)
        end = date(today.year, 12, 31)
    else:
        start_year, end_year = date_range
        start = date(start_year, 1, 1)
        end = date(end_year, 12, 31)
    return start.isoformat(), end.isoformat()


class SheerwaterAdapter(AdapterBase):
    def fetch_data(self, product_config: dict, variable: str,
                   date_range=None, region=None) -> xr.Dataset:
        source_fn_name = product_config["source"]
        # Support both top-level (e.g. "chirps_v2") and dotted submodule
        # paths (e.g. "chirps.chirps_raw_live") since not all sheerwater
        # functions are re-exported at the package root.
        if "." in source_fn_name:
            module_path, attr = source_fn_name.rsplit(".", 1)
            module = importlib.import_module(f"sheerwater.data.{module_path}")
            fn = getattr(module, attr)
        else:
            sheerwater_data = importlib.import_module("sheerwater.data")
            fn = getattr(sheerwater_data, source_fn_name)

        start_time, end_time = _to_time_range(date_range)
        source_kwargs = product_config.get("source_kwargs", {})

        # Sheerwater functions expect ``region`` to be a string identifier
        # (e.g. ``'global'``, country code, or a registered subdivision name).
        # Rosetta's calling convention passes a [lat_s, lat_n, lon_w, lon_e]
        # bbox list. When we get a bbox, fetch the global Sheerwater dataset
        # and crop client-side; pass strings through unchanged.
        if isinstance(region, (list, tuple)):
            bbox = list(region)
            sheerwater_region = "global"
        else:
            bbox = None
            sheerwater_region = region if region is not None else "global"

        ds = fn(
            start_time=start_time,
            end_time=end_time,
            region=sheerwater_region,
            **source_kwargs,
        )

        # Sheerwater returns a lazy dask graph that includes the agg_days
        # rolling. Cropping a lazy graph before computing can leave chunks
        # smaller than the rolling window, which dask refuses with
        # "depth N > chunk 0". Force eager evaluation BEFORE cropping so
        # the rolling executes on the full global grid in one shot, then
        # we slice the materialized result. For obs/chirps-dekadal this
        # is ~30y × 721 × 1440 × 4B ≈ 1.5GB — manageable on dev machines.
        if hasattr(ds, "compute"):
            ds = ds.compute()

        if bbox is not None:
            lat_s, lat_n, lon_w, lon_e = bbox
            lat_name = "lat" if "lat" in ds.dims else "latitude"
            lon_name = "lon" if "lon" in ds.dims else "longitude"
            # Some sheerwater grids have descending lat; build the slice in
            # the dataset's native order so .sel() returns a non-empty subset.
            lat_vals = ds[lat_name].values
            if lat_vals[0] > lat_vals[-1]:
                lat_slice = slice(lat_n, lat_s)
            else:
                lat_slice = slice(lat_s, lat_n)
            ds = ds.sel({lat_name: lat_slice, lon_name: slice(lon_w, lon_e)})

        return ds

    def health_check(self, product_config: dict, probe_remote: bool = False) -> dict:
        source = product_config.get("source")
        if not source:
            return {
                "healthy": False,
                "kind": "config",
                "message": "Missing 'source' field in product config.",
                "probe_remote": bool(probe_remote),
            }

        if not probe_remote:
            return {
                "healthy": True,
                "kind": "config",
                "message": f"Sheerwater adapter config valid (source={source}).",
                "probe_remote": False,
            }

        zarr_url = product_config.get("zarr_url")
        if not zarr_url:
            return {
                "healthy": False,
                "kind": "config",
                "message": "probe_remote=True requires 'zarr_url' in product config for the Sheerwater probe.",
                "probe_remote": True,
            }

        try:
            import xarray as xr
            ds = xr.open_dataset(zarr_url, engine="zarr", chunks={})
            hindcast_range = product_config.get("grid", {}).get("hindcast_range")
            if hindcast_range:
                time_coord = next((c for c in ("time", "T") if c in ds.coords), None)
                if time_coord:
                    import pandas as pd
                    t_min = pd.Timestamp(ds[time_coord].values.min())
                    assert t_min.year <= hindcast_range[0], (
                        f"Zarr store starts {t_min.year}, expected <= {hindcast_range[0]}"
                    )
            return {
                "healthy": True,
                "kind": "remote",
                "message": f"Sheerwater Zarr store reachable: {zarr_url}",
                "probe_remote": True,
            }
        except Exception as e:
            msg = str(e).lower()
            if any(kw in msg for kw in ("403", "permission", "credentials", "timeout", "connection")):
                kind = "transient"
            else:
                kind = "remote"
            return {
                "healthy": False,
                "kind": kind,
                "message": f"Sheerwater probe failed: {e}",
                "probe_remote": True,
            }
