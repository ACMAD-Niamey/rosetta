import tempfile
import xarray as xr
from .base import AdapterBase



class CDSAdapter(AdapterBase):
    def health_check(self, product_config, probe_remote=False):
        required = ["cds_dataset", "variables"]
        missing = [k for k in required if k not in product_config]
        if missing:
            return {
                "healthy": False,
                "kind": "config",
                "message": f"Missing required config keys: {missing}",
                "probe_remote": bool(probe_remote),
            }

        if not probe_remote:
            return {
                "healthy": True,
                "kind": "config",
                "message": "CDS adapter config is valid.",
                "probe_remote": False,
            }

        try:
            import cdsapi

            cdsapi.Client()
            return {
                "healthy": True,
                "kind": "remote",
                "message": "CDS client initialized successfully.",
                "probe_remote": True,
            }
        except Exception as e:
            return {
                "healthy": False,
                "kind": "remote",
                "message": f"CDS client init failed: {e}",
                "probe_remote": True,
            }

    def fetch_data(self, product_config, variable, date_range=None, region=None):
        verbose = product_config.get("_verbose", True)
        import cdsapi
        # cdsapi's defaults are retry_max=500, sleep_max=120 — designed for long
        # production queues, but they hide real errors behind ~17h of silent retry.
        # 12 × 30s = 6min max covers legit queue waits while failing fast enough to
        # surface the underlying CDS response.
        client = cdsapi.Client(retry_max=12, sleep_max=30, timeout=60,
                               quiet=not verbose)
        var_cfg = product_config["variables"][variable]
        dataset = product_config["cds_dataset"]

        request = {
            "variable": var_cfg["native_name"],
            "data_format": "netcdf",
            "download_format": "unarchived",
        }

        for key in ("product_type", "system"):
            if key in product_config:
                request[key] = product_config[key]

        if date_range:
            years = [str(y) for y in range(date_range[0], date_range[1] + 1)]
        else:
            from datetime import datetime
            years = [str(datetime.now().year)]
        request["year"] = years

        if "init_months" in product_config:
            request["month"] = [f"{m:02d}" for m in product_config["init_months"]]
        else:
            request["month"] = [f"{m:02d}" for m in range(1, 13)]

        if product_config.get("product_type") == "monthly_averaged_reanalysis":
            request["time"] = "00:00"

        if "cds_model" in product_config:
            request["originating_centre"] = product_config["cds_model"]

        if dataset == "seasonal-original-single-levels":
            request["day"] = "01"

        if "leadtime_hour" in product_config:
            request["leadtime_hour"] = [str(h) for h in product_config["leadtime_hour"]]
        elif "leadtime_month" in product_config:
            request["leadtime_month"] = [str(m) for m in product_config["leadtime_month"]]
        elif "cds_model" in product_config:
            request["leadtime_hour"] = [str(h) for h in range(24, 24 * 215, 24)]

        if region:
            lat_s, lat_n, lon_w, lon_e = region
            request["area"] = [lat_n, lon_w, lat_s, lon_e]

        if verbose:
            print(f"[rosetta:cds] request dataset={dataset} years={len(request['year'])}")
        with tempfile.NamedTemporaryFile(suffix=".nc", delete=False) as tmp:
            client.retrieve(dataset, request, tmp.name)
            if verbose:
                print("[rosetta:cds] download complete")
            # decode_timedelta=False works around an xarray 2025.1.0 assertion
            # that fails when pandas returns timedelta64[us] instead of [ns].
            return xr.open_dataset(tmp.name, decode_timedelta=False)
