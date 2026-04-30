import xarray as xr
from nuthatch import cache

from . import catalog
from .adapters import get_adapter
from .normalize import normalize
from .storage import save

_CACHE_VERSION = 1  # bump when adapter logic or normalization changes


@cache(namespace="rosetta", version=str(_CACHE_VERSION), backend="basic")
def _fetch_raw(product: str, variable: str, config: dict,
               date_range, region) -> xr.Dataset:
    """Download raw (un-normalized) data from the adapter. Cached by nuthatch."""
    adapter = get_adapter(config["adapter"])
    return adapter.fetch_data(config, variable, date_range=date_range, region=region)

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


def fetch(product, variable, init=None, target=None, region=None,
          hindcast=None, destination=None, format="netcdf", verbose=True,
          progress=True):
    """Fetch, normalize, and optionally save climate data.

    Caching is handled at the adapter level via @nuthatch.cache().
    """
    _log(verbose, f"fetch start: product={product}, variable={variable}")

    config = dict(catalog.get(product))
    config["_verbose"] = verbose
    config["_progress"] = progress

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
            if "cds_model" in config:
                if config.get("cds_dataset") == "seasonal-original-single-levels":
                    from datetime import datetime, timedelta
                    init_date = datetime(init_dt.year, init_dt.month, 1)
                    hours = []
                    for m in lead_months:
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
                    var_cfg = config["variables"][variable]
                    if var_cfg.get("accumulated") and hours:
                        extra = hours[0] - 24
                        if extra > 0:
                            hours = [extra] + hours
                    config["leadtime_hour"] = hours
                else:
                    config["leadtime_month"] = lead_months
            config["target_lead_months"] = lead_months
            config["target_range"] = target_range

    _log(verbose, f"downloading via adapter={config['adapter']}")
    raw = _fetch_raw(product, variable, config, date_range, region)
    _log(verbose, "normalizing dataset")
    clean = normalize(raw, config, variable, region)

    if destination:
        _log(verbose, f"saving output -> {destination}")
        save(clean, destination, format)

    _log(verbose, "fetch complete")
    return clean
