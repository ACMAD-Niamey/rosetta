"""IRI Data Library adapter — fetches seasonal GCM data via Ingrid/OPeNDAP.

Requires a ~/.pycpt_dlauth file with an IRI auth key.
Set one up at https://iridl.ldeo.columbia.edu/auth/signup then run:
    cptdl.setup_dlauth("your_email")
Or manually: curl the /auth/genkey endpoint after login.
"""
import json
from pathlib import Path
import numpy as np
import xarray as xr
from .base import AdapterBase

DLAUTH_PATH = Path.home() / ".pycpt_dlauth"
IRIDL_BASE = "https://iridl.ldeo.columbia.edu"
THREELETTERS = {
    1: "Jan", 2: "Feb", 3: "Mar", 4: "Apr", 5: "May", 6: "Jun",
    7: "Jul", 8: "Aug", 9: "Sep", 10: "Oct", 11: "Nov", 12: "Dec",
}


def _read_dlauth():
    if not DLAUTH_PATH.is_file():
        raise FileNotFoundError(
            "No ~/.pycpt_dlauth found. Create an IRI account at "
            "https://iridl.ldeo.columbia.edu/auth/signup and run "
            'cptdl.setup_dlauth("your_email") to generate the key.'
        )
    with open(DLAUTH_PATH, "rb") as f:
        return json.loads(f.read())["key"]


def build_url_parts(product_config, variable, date_range=None, region=None):
    """Build the ordered Ingrid URL path segments for an IRIDL request.

    Pure (no I/O) so it is unit-testable. Two shapes are produced:

    * forecast products (default): an ``S`` (init) / ``L`` (lead) cube, selecting
      the init month and averaging over the target leads — the seasonal-GCM path.
    * observed products (``observed: true`` in the entry): a plain ``T`` time
      series over the requested year span, with no init/lead dims — the path an
      observed gridded field (e.g. CAMS-OPI rainfall) needs. Month/season
      selection then happens downstream in ``fetch`` via ``seasonal=``.

    Returns the list of path segments (join with "/" and append "/data.nc").
    """
    var_cfg = product_config["variables"][variable]
    iridl_path = product_config["iridl_path"]
    iridl_var = var_cfg.get("iridl_name", var_cfg.get("native_name"))
    observed = bool(product_config.get("observed", False))

    parts = [f"{IRIDL_BASE}/{iridl_path}/.{iridl_var}"]

    if observed:
        # Observed T-series: restrict the time grid to the year span. Ingrid reads
        # the calendar tokens; RANGEEDGES clips inclusively. normalize() renames
        # T->time, X->lon, Y->lat downstream.
        if date_range:
            y0, y1 = date_range
            parts.append(f"T/%28Jan%20{y0}%29/%28Dec%20{y1}%29/RANGEEDGES")
        if region:
            lat_s, lat_n, lon_w, lon_e = region
            parts.append(f"Y/{lat_s}/{lat_n}/RANGEEDGES")
            parts.append(f"X/{lon_w}/{lon_e}/RANGEEDGES")
        if "iridl_unit_ops" in var_cfg:
            parts.append(var_cfg["iridl_unit_ops"])
        return parts

    # Forecast (S/L) path.
    init_month = product_config.get("init_months", [1])[0]
    mon = THREELETTERS[init_month]
    if date_range:
        y0, y1 = date_range
        parts.append(f"S/%280000%201%20{mon}%20{y0}-{y1}%29/VALUES")
    else:
        import datetime
        y = datetime.datetime.now().year
        parts.append(f"S/%280000%201%20{mon}%20{y}%29/VALUES")

    if "leadtime_range" in product_config:
        lo, hi = product_config["leadtime_range"]
        parts.append(f"L/{lo}/{hi}/RANGEEDGES")
    elif "leadtime_month" in product_config:
        lms = product_config["leadtime_month"]
        lo = min(lms) - 0.5
        hi = max(lms) + 0.5
        parts.append(f"L/{lo}/{hi}/RANGEEDGES")
    parts.append("%5BL%5D//keepgrids/average")

    if region:
        lat_s, lat_n, lon_w, lon_e = region
        parts.append(f"Y/{lat_s}/{lat_n}/RANGEEDGES")
        parts.append(f"X/{lon_w}/{lon_e}/RANGEEDGES")
    if "iridl_unit_ops" in var_cfg:
        parts.append(var_cfg["iridl_unit_ops"])
    return parts


class IRIDLAdapter(AdapterBase):
    def health_check(self, product_config, probe_remote=False):
        if not DLAUTH_PATH.is_file():
            return {"healthy": False, "kind": "config",
                    "message": "Missing ~/.pycpt_dlauth", "probe_remote": False}
        if not probe_remote:
            return {"healthy": True, "kind": "config",
                    "message": "IRIDL adapter config valid.", "probe_remote": False}
        try:
            _read_dlauth()
            return {"healthy": True, "kind": "remote",
                    "message": "IRIDL auth key readable.", "probe_remote": True}
        except Exception as e:
            return {"healthy": False, "kind": "remote",
                    "message": str(e), "probe_remote": True}

    def fetch_data(self, product_config, variable, date_range=None, region=None):
        verbose = product_config.get("_verbose", True)
        key = _read_dlauth()
        var_cfg = product_config["variables"][variable]
        iridl_var = var_cfg.get("iridl_name", var_cfg.get("native_name"))

        # Build Ingrid URL (forecast S/L cube or observed T-series — see builder).
        parts = build_url_parts(product_config, variable, date_range, region)

        if verbose:
            print(f"[rosetta:iridl] fetching {iridl_var} ({date_range})")

        # Configure OPeNDAP auth via .dodsrc
        import os
        import tempfile
        dodsrc = Path.home() / ".dodsrc"
        wrote_dodsrc = False
        if not dodsrc.exists():
            dodsrc.write_text(
                f"HTTP.COOKIEJAR={Path.home()}/.iri_cookies\n"
                f"HTTP.NETRC={Path.home()}/.netrc_iridl\n"
            )
            wrote_dodsrc = True

        # Use requests session with auth cookie for download
        import requests
        session = requests.Session()
        session.cookies.set("__dlauth_id", key, domain="iridl.ldeo.columbia.edu")

        # Download as NetCDF instead of OPeNDAP (simpler auth handling)
        nc_url = "/".join(parts) + "/data.nc"
        if verbose:
            print(f"[rosetta:iridl] URL: {nc_url[:100]}...")
        resp = session.get(nc_url)
        resp.raise_for_status()

        if resp.headers.get("content-type", "").startswith("text/html"):
            raise RuntimeError(
                "IRIDL returned HTML (auth failure?). Check ~/.pycpt_dlauth."
            )

        with tempfile.NamedTemporaryFile(suffix=".nc", delete=False) as tmp:
            tmp.write(resp.content)
            tmp.flush()
            ds = xr.open_dataset(tmp.name)

        if verbose:
            print(f"[rosetta:iridl] got {dict(ds.sizes)}")

        if wrote_dodsrc:
            dodsrc.unlink(missing_ok=True)

        return ds
