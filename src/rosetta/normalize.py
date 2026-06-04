import numpy as np
import pandas as pd
import xarray as xr

_COORD_RENAMES = {
    # Spatial
    "latitude": "lat", "longitude": "lon",
    "LAT": "lat", "LON": "lon",
    "Y": "lat", "X": "lon",
    # Temporal – observational
    "forecast_time": "time", "valid_time": "time", "T": "time", "TIME": "time",
    # Temporal – forecast
    "S": "init_time", "forecast_reference_time": "init_time", "indexing_time": "init_time",
    "L": "lead_time", "forecastMonth": "lead_time", "forecast_period": "lead_time",
    "step": "lead_time",
    # Ensemble
    "M": "member", "number": "member",
}

_CONVERSIONS = {
    ("K", "C"): lambda da: da - 273.15,
    ("kg m-2 s-1", "mm/day"): lambda da: da * 86400,
    ("m s-1", "mm/day"): lambda da: da * 1000 * 86400,
    ("m", "mm/day"): lambda da: da * 1000,
    ("m/s", "mm/day"): lambda da: da * 86_400_000,
    ("mm/month", "mm/day"): lambda da: da / 30.0,
    # Identity: variable is already accumulated mm; after deaccumulation
    # (diff over 24h lead_time), each value is mm per 24h = mm/day.
    ("mm", "mm/day"): lambda da: da,
}


def decode_months_since(units_str, vals):
    """Decode 'months since YYYY-MM-DD' values to (years, months) arrays.

    Returns (years, months) as integer arrays.
    """
    ref_str = units_str.split("months since")[1].strip()
    ref = pd.Timestamp(ref_str)
    ref_total = ref.year * 12 + (ref.month - 1)
    total = ref_total + np.round(vals).astype(int)
    return total // 12, total % 12 + 1


def _decode_numeric_times(ds):
    """Decode numeric time coordinates with CF-style 'X since Y' units to datetime64."""
    for coord in list(ds.coords):
        if coord not in ds.dims:
            continue
        units = ds[coord].attrs.get("units", "")
        if "since" not in units:
            continue
        vals = ds[coord].values
        if not (np.issubdtype(vals.dtype, np.floating)
                or np.issubdtype(vals.dtype, np.integer)):
            continue

        if "months since" in units:
            years, months = decode_months_since(units, vals)
            dates = pd.to_datetime([
                f"{y}-{m:02d}-01" for y, m in zip(years, months)
            ])
            ds = ds.assign_coords({coord: dates})
        elif "days since" in units:
            ref_str = units.split("days since")[1].strip()
            ref = pd.Timestamp(ref_str)
            dates = ref + pd.to_timedelta(vals, unit="D")
            ds = ds.assign_coords({coord: dates})
        elif "hours since" in units:
            ref_str = units.split("hours since")[1].strip()
            ref = pd.Timestamp(ref_str)
            dates = ref + pd.to_timedelta(vals, unit="h")
            ds = ds.assign_coords({coord: dates})

    return ds


def clip_to_geometry(ds, geometry, all_touched=False):
    """Mask a lat/lon dataset to a polygon, NaN-ing cells outside it.

    This is the final, true-polygon clip that refines the coarse bbox crop:
    bbox slicing keeps a rectangle, this keeps only cells inside ``geometry``.
    The dataset must have ``lat``/``lon`` dims; ``geometry`` must be a shapely
    geometry in EPSG:4326 (as returned by :func:`rosetta.region.resolve_region`).

    Uses rioxarray's geometry clip (rioxarray is a core dependency).
    ``all_touched`` selects the boundary rule (matching rasterio's parameter):

    * ``False`` (default): a cell is kept only if its centre lies inside the
      polygon — the xarray/CDO/rasterio convention, and unbiased for area means.
    * ``True``: every cell the polygon touches is kept, so the shape is covered
      to its true edges (given fetch() padded the grid past them).

    ``drop=True`` crops the output to the polygon's bounding box so there's no
    NaN margin from any padding. Cells inside the bbox but excluded by the
    boundary rule remain NaN.
    """
    import rioxarray  # noqa: F401  registers the .rio accessor

    if "lat" not in ds.dims or "lon" not in ds.dims:
        return ds

    clipped = ds.rio.set_spatial_dims(x_dim="lon", y_dim="lat", inplace=False)
    clipped = clipped.rio.write_crs("EPSG:4326", inplace=False)
    clipped = clipped.rio.clip([geometry], crs="EPSG:4326",
                               drop=True, all_touched=all_touched)
    # rio.clip adds a `spatial_ref` coord and a `grid_mapping` encoding; strip
    # them so the result matches the plain (lat, lon, ...) schema callers expect.
    clipped = clipped.drop_vars("spatial_ref", errors="ignore")
    for v in clipped.data_vars:
        clipped[v].encoding.pop("grid_mapping", None)
    # rio.clip can flip lat to descending; restore the ascending convention.
    if "lat" in clipped.dims:
        clipped = clipped.sortby("lat")
    return clipped


def normalize(ds, product_config, variable, region=None, geometry=None,
              boundary="center"):
    ds = _decode_numeric_times(ds)

    # ECMWF S2S GRIB files use `time` as the (scalar) init issuance and
    # `valid_time` as the per-step forecast time. The rename map below sends
    # `valid_time → time`, which would collide with the existing scalar `time`.
    # If `time` is scalar (not a dim), pre-rename it to `init_time` so the
    # collision can't happen.
    if ("time" in ds.coords and "time" not in ds.dims
            and "init_time" not in ds.coords and "init_time" not in ds.dims):
        ds = ds.rename({"time": "init_time"})

    # ECMWF S2S reforecast responses carry an `hdate` dimension — the
    # calendar issuance dates of each historical reforecast. Convert to
    # integer years and rename to `year` so the output matches the
    # (year, member, lead_time, lat, lon) hindcast convention used
    # downstream. Must run before _COORD_RENAMES.
    if "hdate" in ds.dims:
        years = ds["hdate"].dt.year.values
        ds = ds.assign_coords(hdate=years).rename({"hdate": "year"})

    renames = {k: v for k, v in _COORD_RENAMES.items() if k in ds.dims or k in ds.coords}
    if renames:
        ds = ds.rename(renames)

    var_cfg = product_config["variables"][variable]
    native = var_cfg["native_name"]
    if native not in ds and "short_name" in var_cfg:
        native = var_cfg["short_name"]
    if native in ds:
        ds = ds.rename({native: variable})

    # Deaccumulate variables (e.g. CDS total_precipitation is accumulated from init)
    if var_cfg.get("accumulated") and "lead_time" in ds.dims:
        diffed = ds[variable].diff(dim="lead_time")
        ds = ds.sel(lead_time=diffed.lead_time)
        ds[variable] = diffed

    src, tgt = var_cfg["units"], var_cfg["target_units"]
    if (src, tgt) in _CONVERSIONS:
        ds[variable] = _CONVERSIONS[(src, tgt)](ds[variable])

    ds[variable].attrs["units"] = tgt

    # Optional no-data sentinel masking. Some upstream sources (e.g.
    # CHIRPS via sheerwater's chirps_raw_live) return a numeric sentinel
    # (typically -9999) for ocean/missing cells instead of NaN. Catalog
    # can specify `fill_value` per variable to convert those to NaN so
    # downstream aggregations skip them correctly.
    fill_value = var_cfg.get("fill_value")
    if fill_value is not None:
        ds[variable] = ds[variable].where(ds[variable] != fill_value)

    if "lat" in ds.dims:
        ds = ds.sortby("lat")

    cover = boundary == "cover"

    if geometry is not None and "lat" in ds.dims and "lon" in ds.dims:
        # Polygon mask drives the spatial selection; the boundary rule (centre
        # vs all-touched) follows `boundary`. clip crops to the polygon's bbox.
        ds = clip_to_geometry(ds, geometry, all_touched=cover)
    elif region and "lat" in ds.dims and "lon" in ds.dims:
        lat_s, lat_n, lon_w, lon_e = region
        if cover:
            # Include every cell whose extent overlaps the requested box, i.e.
            # cells whose centre lies within half a grid step of the bounds.
            r_lat = (float(np.median(np.diff(ds.lat.values))) / 2
                     if ds.sizes.get("lat", 0) > 1 else 0.0)
            r_lon = (float(np.median(np.diff(ds.lon.values))) / 2
                     if ds.sizes.get("lon", 0) > 1 else 0.0)
            lat_s, lat_n = lat_s - r_lat, lat_n + r_lat
            lon_w, lon_e = lon_w - r_lon, lon_e + r_lon
        ds = ds.sel(lat=slice(lat_s, lat_n), lon=slice(lon_w, lon_e))

    for coord, attr in [("lat", "Y"), ("lon", "X"), ("time", "T"), ("init_time", "T")]:
        if coord in ds.coords:
            ds[coord].attrs["axis"] = attr

    return ds
