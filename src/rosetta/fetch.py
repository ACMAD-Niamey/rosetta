import hashlib
import json
from pathlib import Path

import xarray as xr

from . import catalog
from .adapters import get_adapter
from .normalize import normalize
from .storage import save

_CACHE_DIR = Path.home() / ".cache" / "rosetta"
_CACHE_ENABLED = True

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


def set_cache(enabled=True, cache_dir=None):
    global _CACHE_ENABLED, _CACHE_DIR
    _CACHE_ENABLED = enabled
    if cache_dir is not None:
        _CACHE_DIR = Path(cache_dir)


def _cache_key(product, variable, init, target, region, hindcast):
    blob = json.dumps(
        {"product": product, "variable": variable, "init": str(init),
         "target": str(target), "region": region, "hindcast": hindcast},
        sort_keys=True, default=str,
    )
    return hashlib.sha256(blob.encode()).hexdigest()[:16]


def _cache_path(key):
    return _CACHE_DIR / f"{key}.nc"


def fetch(product, variable, init=None, target=None, region=None,
          hindcast=None, destination=None, format="netcdf", verbose=True,
          progress=True, cache=None):
    """Fetch data, with optional disk cache.

    cache: True/False to override global setting, or None to use global default.
    """
    use_cache = cache if cache is not None else _CACHE_ENABLED

    _log(verbose, f"fetch start: product={product}, variable={variable}")

    if use_cache:
        key = _cache_key(product, variable, init, target, region, hindcast)
        cached = _cache_path(key)
        if cached.exists():
            _log(verbose, f"cache hit: {cached.name}")
            ds = xr.open_dataset(cached)
            if destination:
                _log(verbose, f"saving output -> {destination}")
                save(ds, destination, format)
            _log(verbose, "fetch complete")
            return ds

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
            # CDS adapter uses leadtime_month (monthly) or leadtime_hour (daily)
            if "cds_model" in config:
                if config.get("cds_dataset") == "seasonal-original-single-levels":
                    # Daily dataset: convert lead months to hour ranges
                    from datetime import datetime, timedelta
                    init_date = datetime(init_dt.year, init_dt.month, 1)
                    hours = []
                    for m in lead_months:
                        # Lead month N starts at month init+N-1, ends at init+N
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
                    # For accumulated variables, fetch one extra day before
                    # so we can diff without losing the first timestep
                    var_cfg = config["variables"][variable]
                    if var_cfg.get("accumulated") and hours:
                        extra = hours[0] - 24
                        if extra > 0:
                            hours = [extra] + hours
                    config["leadtime_hour"] = hours
                else:
                    config["leadtime_month"] = lead_months
            # OPeNDAP adapter uses target_lead_months to filter the lead_time dim
            # after opening the raw dataset (NMME uses L = lead_month - 0.5 convention)
            config["target_lead_months"] = lead_months
            config["target_range"] = target_range

    _log(verbose, f"downloading via adapter={config['adapter']}")
    raw = adapter.fetch_data(config, variable, date_range=date_range, region=region)
    _log(verbose, "normalizing dataset")
    clean = normalize(raw, config, variable, region)

    if use_cache:
        _CACHE_DIR.mkdir(parents=True, exist_ok=True)
        clean.to_netcdf(cached)
        _log(verbose, f"cached: {cached.name}")

    if destination:
        _log(verbose, f"saving output -> {destination}")
        save(clean, destination, format)

    _log(verbose, "fetch complete")
    return clean
