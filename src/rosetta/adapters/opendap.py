import numpy as np
import xarray as xr
from .base import AdapterBase
from ..normalize import decode_months_since



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
        verbose = product_config.get("_verbose", True)
        var_cfg = product_config["variables"][variable]
        native_name = var_cfg["native_name"]
        base = product_config["source_url"].rstrip("/")
        # Stream routing: a split_streams entry carries a `{stream}` placeholder in
        # its source_url; pick HINDCAST vs FORECAST from the requested years (years
        # past the hindcast range are the live forecast, otherwise the reforecast).
        # Mirrors the CCSR adapter's split-stream routing, for the IRI NMME models
        # that file hindcast and forecast at sibling .HINDCAST/.FORECAST paths.
        if product_config.get("split_streams"):
            hr = (product_config.get("grid") or {}).get("hindcast_range")
            is_forecast = bool(date_range and hr and date_range[0] > hr[1])
            base = base.format(stream="FORECAST" if is_forecast else "HINDCAST")
        url = base + f"/.{native_name}/dods"
        if verbose:
            print(f"[rosetta:opendap] opening remote dataset: {url}")
        ds = xr.open_dataset(url, engine="netcdf4", decode_times=False)
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
