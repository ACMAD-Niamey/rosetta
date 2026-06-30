"""Adapter for the Columbia CCSR NMME successor service (rosetta #14 / §6.2).

CCSR (https://forecast.ccsr.columbia.edu/data/NMME/) replaced the sunset IRI
Data Library. It serves NMME models over plain OPeNDAP, but with a different
convention from the IRI Ingrid system the `opendap` adapter targets:

  - the variable is part of the path (no Ingrid ``/.<var>/dods`` suffix); the
    variable path *is* the DAP dataset, opened directly;
  - ``S`` (init) and ``target`` are ``hours since 1960-01-01`` (IRI used
    ``months since``);
  - ``L`` is an integer 0..11 lead where L=0 is the init month, paired with a
    self-describing ``target[S, L]`` variable giving each (init, lead)'s target
    time — so season selection reads the target month rather than assuming a
    lead convention;
  - longitude is 0..360.

Layout: ``<var>[S, M, L, Y, X]`` with ``target[S, L]``. The adapter decodes S,
filters by year + init month, selects + averages the leads whose target month
falls in the requested season, wraps longitude to [-180, 180], crops to the
region, and hands ``S/M/Y/X`` to the normalize layer (which renames them to
``init_time/member/lat/lon`` and the native var to the canonical name).
"""
import re

import numpy as np
import xarray as xr

from .base import AdapterBase
from ._robust import _DEFAULT_MAX_RETRIES, _DEFAULT_RETRY_BACKOFF, _with_retry

_TIME_SINCE = re.compile(
    r"(hours?|days?|minutes?|seconds?|months?)\s+since\s+(\d{4})-(\d{1,2})-(\d{1,2})",
    re.IGNORECASE,
)
_UNIT_CODE = {"hour": "h", "day": "D", "minute": "m", "second": "s"}


def _decode_time_since(units: str, vals) -> np.ndarray:
    """Decode CF ``<unit> since YYYY-MM-DD`` integer values to datetime64.

    The CCSR/Columbia NMME server serves different models with different time
    units: most use ``hours since 1960-01-01`` (the IRI convention), but some
    (e.g. SPEAR, CanSIPS-IC4) use ``days since 1960-01-01``. Handles
    hours/days/minutes/seconds/months.
    """
    m = _TIME_SINCE.search(units or "")
    if not m:
        raise ValueError(
            "CCSR adapter expected '<unit> since YYYY-MM-DD' units "
            f"(hours/days/minutes/seconds/months), got {units!r}"
        )
    unit = m.group(1).lower().rstrip("s")
    y, mo, d = (int(g) for g in m.groups()[1:])
    vals = np.asarray(vals)
    if unit == "month":
        ref = np.datetime64(f"{y:04d}-{mo:02d}", "M")
        return ref + vals.astype("timedelta64[M]")
    code = _UNIT_CODE[unit]
    ref = np.datetime64(f"{y:04d}-{mo:02d}-{d:02d}", code)
    return ref + vals.astype("timedelta64[" + code + "]")


def _months_of(dt64: np.ndarray) -> np.ndarray:
    """Calendar month (1..12) of datetime64 values, shape-preserving."""
    return (dt64.astype("datetime64[M]").astype("int64") % 12 + 1)


def _target_months(config: dict):
    """Calendar months of the requested season, from fetch's target_range."""
    tr = config.get("target_range")
    if not tr:
        return None
    s_month, e_month = tr[0].month, tr[1].month
    if s_month <= e_month:
        return list(range(s_month, e_month + 1))
    return list(range(s_month, 13)) + list(range(1, e_month + 1))


class CCSRAdapter(AdapterBase):
    def fetch_data(self, product_config, variable, date_range=None, region=None):
        var_cfg = product_config["variables"][variable]
        native = var_cfg["native_name"]
        verbose = product_config.get("_verbose", True)
        max_retries = int(product_config.get("_max_retries", _DEFAULT_MAX_RETRIES))
        retry_backoff = float(product_config.get("_retry_backoff", _DEFAULT_RETRY_BACKOFF))
        base = product_config["source_url"].rstrip("/")
        if product_config.get("single_year_fetch") and date_range:
            y0, y1 = date_range
            pieces = []
            for year in range(y0, y1 + 1):
                # Route each year independently: with single_year_fetch we open
                # one stream per year, so the subdir must be chosen per year (a
                # boundary-spanning range otherwise sends every year to the
                # date_range[0] stream and silently drops the other side).
                url = self._stream_url(base, native, product_config, (year, year))
                if verbose:
                    print(f"[rosetta:ccsr] opening remote dataset: {url}")
                ds_y = _with_retry(
                    lambda url=url: xr.open_dataset(url, engine="netcdf4", decode_times=False),
                    max_retries, retry_backoff,
                    label=f"CCSR open {url}", verbose=verbose,
                )
                ds_y = self._process(ds_y, native, product_config,
                                     date_range=(year, year), region=region)
                if ds_y.sizes.get("S", 0):
                    pieces.append(ds_y)
            if not pieces:
                raise ValueError(f"single_year_fetch: no data for {y0}-{y1}")
            return xr.concat(pieces, dim="S")
        url = self._stream_url(base, native, product_config, date_range)
        if verbose:
            print(f"[rosetta:ccsr] opening remote dataset: {url}")
        ds = _with_retry(
            lambda: xr.open_dataset(url, engine="netcdf4", decode_times=False),
            max_retries, retry_backoff,
            label=f"CCSR open {url}", verbose=verbose,
        )
        return self._process(ds, native, product_config, date_range, region)

    @staticmethod
    def _stream_url(base, native, product_config, date_range):
        """Build the variable URL, routing split_streams models to the forecast/
        or hindcast/ subdir from the requested years.

        Some CCSR models split into forecast/ and hindcast/ subdirectories
        (split_streams: true); others serve one combined series. For split
        models, years past hindcast_range[1] are the live forecast, otherwise the
        reforecast.
        """
        if product_config.get("split_streams"):
            hr = (product_config.get("grid") or {}).get("hindcast_range")
            is_forecast = bool(date_range and hr and date_range[0] > hr[1])
            base = f"{base}/{'forecast' if is_forecast else 'hindcast'}"
        return f"{base}/{native}"

    def _process(self, ds, native, config, date_range=None, region=None):
        # ---- decode S (time since 1960) and filter by year + init month ----
        s_dt = _decode_time_since(ds["S"].attrs.get("units", ""), ds["S"].values)
        ds = ds.assign_coords(S=("S", s_dt))

        s_years = ds["S"].dt.year.values
        s_months = ds["S"].dt.month.values
        mask = np.ones(ds.sizes["S"], dtype=bool)
        if date_range:
            y0, y1 = date_range
            mask &= (s_years >= y0) & (s_years <= y1)
        init_months = config.get("init_months")
        if init_months:
            mask &= np.isin(s_months, init_months)
        ds = ds.isel(S=np.where(mask)[0])

        # ---- target-driven season selection: average the leads whose target
        #      month falls in the requested season (no lead-convention guess) ---
        target_months = _target_months(config)
        if (target_months and "target" in ds.variables
                and "L" in ds.dims and ds.sizes["S"] > 0):
            tgt_dt = _decode_time_since(ds["target"].attrs.get("units", ""),
                                        ds["target"].values)          # (S, L)
            tgt_month = _months_of(tgt_dt)                             # (S, L)
            # All retained inits share the init month, so the lead→target-month
            # mapping is identical across S; read it off the first init.
            keep = np.isin(tgt_month[0], target_months)
            if keep.any():
                ds = ds.isel(L=np.where(keep)[0]).mean("L")
        ds = ds.drop_vars([v for v in ("target", "target_bnds") if v in ds.variables])

        # ---- longitude 0..360 -> [-180, 180], then crop to region ----
        if "X" in ds.coords:
            x = ds["X"].values
            if np.nanmax(x) > 180.0:
                ds = ds.assign_coords(X=(((x + 180.0) % 360.0) - 180.0)).sortby("X")
        if region:
            lat_s, lat_n, lon_w, lon_e = region
            y = ds["Y"].values
            lat_slice = slice(lat_s, lat_n) if y[0] <= y[-1] else slice(lat_n, lat_s)
            ds = ds.sel(Y=lat_slice, X=slice(lon_w, lon_e))

        return ds

    def health_check(self, product_config, probe_remote=False):
        url = product_config.get("source_url")
        if not url:
            return {"healthy": False, "kind": "config",
                    "message": "Missing source_url in CCSR product config.",
                    "probe_remote": bool(probe_remote)}
        if not probe_remote:
            return {"healthy": True, "kind": "config",
                    "message": "CCSR adapter config is valid.",
                    "probe_remote": False}
        try:
            native = next(iter(product_config["variables"].values()))["native_name"]
            ds = xr.open_dataset(url.rstrip("/") + f"/{native}",
                                 engine="netcdf4", decode_times=False)
            ds.close()
            return {"healthy": True, "kind": "remote",
                    "message": "CCSR OPeNDAP dataset opened successfully.",
                    "probe_remote": True}
        except Exception as e:
            return {"healthy": False, "kind": "remote",
                    "message": f"CCSR probe failed: {e}", "probe_remote": True}
