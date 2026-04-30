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
        sheerwater_data = importlib.import_module("sheerwater.data")
        fn = getattr(sheerwater_data, source_fn_name)

        start_time, end_time = _to_time_range(date_range)
        source_kwargs = product_config.get("source_kwargs", {})

        return fn(
            start_time=start_time,
            end_time=end_time,
            region=region,
            **source_kwargs,
        )

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
