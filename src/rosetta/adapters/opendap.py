import numpy as np
import xarray as xr
from .base import AdapterBase
from ..normalize import decode_months_since
from ._robust import _DEFAULT_MAX_RETRIES, _DEFAULT_RETRY_BACKOFF, _with_retry



class OPeNDAPAdapter(AdapterBase):
    def health_check(self, product_config, probe_remote=False):
        url = product_config.get("source_url")
        if not url:
            return {
                "healthy": False,
                "kind": "config",
                "message": "Missing source_url in product config.",
                "probe_remote": bool(probe_remote),
            }

        if not probe_remote:
            return {
                "healthy": True,
                "kind": "config",
                "message": "OPeNDAP adapter config is valid.",
                "probe_remote": False,
            }

        # split_streams entries carry a `{stream}` placeholder; probe the hindcast
        # endpoint (always present) so the literal braces don't reach the server.
        probe_url = url.format(stream="HINDCAST") if product_config.get("split_streams") else url
        try:
            ds = xr.open_dataset(probe_url, engine="netcdf4")
            ds.close()
            return {
                "healthy": True,
                "kind": "remote",
                "message": "OPeNDAP dataset opened successfully.",
                "probe_remote": True,
            }
        except Exception as e:
            return {
                "healthy": False,
                "kind": "remote",
                "message": f"OPeNDAP probe failed: {e}",
                "probe_remote": True,
            }

    def fetch_data(self, product_config, variable, date_range=None, region=None):
        # Resolve the request into one or more (stream, sub_range) segments. A
        # single segment reproduces today's start-year routing exactly; an
        # `append_streams` product spanning the hindcast/forecast boundary yields
        # two segments that we fetch separately and stitch on S.
        segments = self._resolve_streams(product_config, date_range)
        parts = [self._fetch_one_stream(product_config, variable, stream, rng, region)
                 for stream, rng in segments]
        if len(parts) == 1:
            return parts[0]
        # validate concat compatibility, then stitch on S
        ref = parts[0]
        for p in parts[1:]:
            for d in ("Y", "X", "M", "L"):
                if d in ref.dims and d in p.dims and ref.sizes[d] != p.sizes[d]:
                    raise ValueError(
                        f"append_streams: stream segments disagree on dim {d!r} "
                        f"({ref.sizes[d]} vs {p.sizes[d]}); cannot concat.")
        return xr.concat(parts, dim="S")

    def _fetch_one_stream(self, product_config, variable, stream, date_range, region):
        verbose = product_config.get("_verbose", True)
        max_retries = int(product_config.get("_max_retries", _DEFAULT_MAX_RETRIES))
        retry_backoff = float(product_config.get("_retry_backoff", _DEFAULT_RETRY_BACKOFF))
        var_cfg = product_config["variables"][variable]
        native_name = var_cfg["native_name"]
        base = product_config["source_url"].rstrip("/")
        # Stream routing: a split_streams entry carries a `{stream}` placeholder in
        # its source_url; the (HINDCAST/FORECAST) token is now chosen upstream by
        # `_resolve_streams` and passed in as `stream`. Mirrors the CCSR adapter's
        # split-stream routing, for the IRI NMME models that file hindcast and
        # forecast at sibling .HINDCAST/.FORECAST paths.
        if product_config.get("split_streams"):
            base = base.format(stream=stream.upper())
        url = base + f"/.{native_name}/dods"
        if verbose:
            print(f"[rosetta:opendap] opening remote dataset: {url}")
        ds = _with_retry(
            lambda: xr.open_dataset(url, engine="netcdf4", decode_times=False),
            max_retries, retry_backoff,
            label=f"OPeNDAP open {url}", verbose=verbose,
        )
        if "S" in ds.coords:
            # NMME OPeNDAP: S is encoded as "months since YYYY-MM-DD"
            units = ds["S"].attrs.get("units", "")
            if "months since" in units:
                s_years, s_months = decode_months_since(units, ds.S.values)
                mask = np.ones(len(ds.S), dtype=bool)
                if date_range:
                    y0, y1 = date_range
                    mask &= (s_years >= y0) & (s_years <= y1)
                if "init_months" in product_config:
                    mask &= np.isin(s_months, product_config["init_months"])
                ds = ds.sel(S=ds.S[mask])
                if verbose:
                    n = int(mask.sum())
                    print(f"[rosetta:opendap] filtered S to {n} init times")
        elif date_range:
            y0, y1 = date_range
            if "year" in ds.dims or "year" in ds.coords:
                ds = ds.sel(year=slice(y0, y1))
            elif "time" in ds.coords:
                ds = ds.sel(time=slice(f"{y0}-01-01", f"{y1}-12-31"))
        if region:
            lat_s, lat_n, lon_w, lon_e = region
            lat_name = "Y" if "Y" in ds.dims else "lat"
            lon_name = "X" if "X" in ds.dims else "lon"
            ds = ds.sel(
                {lat_name: slice(lat_s, lat_n), lon_name: slice(lon_w, lon_e)}
            )

        # Select and average only the target-season lead months when specified.
        # NMME PENTAD_SAMPLES/.MONTHLY uses L = (lead_month - 0.5) half-integer
        # convention: L=0.5 → month 1 after init, L=1.5 → month 2, etc.
        # Without this, all 10 leads are returned and callers get an annual mean
        # instead of the correct seasonal mean.
        if "target_lead_months" in product_config and "L" in ds.dims:
            lead_months = product_config["target_lead_months"]
            target_L = [m - 0.5 for m in lead_months]
            avail_L = set(float(v) for v in ds.L.values)
            sel_L = [lt for lt in target_L if lt in avail_L]
            if sel_L:
                ds = ds.sel(L=sel_L).mean("L")
            # If none of the target leads are available fall through unchanged
            # (caller's existing post-processing will handle it)

        return ds
