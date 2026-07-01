"""Multi-model fan-out over fetch: assemble aligned {label: (hindcast, forecast)}."""
from __future__ import annotations
from .fetch import fetch


def _canonicalize(da):
    """Shape a year_index=True fetch result to canonical (year, member, lat, lon).

    Mirrors the reference pipeline's `_to_year_member` tail: guarantees a
    `member` dim and drops stray non-dim coords (number/member/spatial_ref)
    that `fetch`/`normalize`'s year_index branch does not itself handle.
    """
    if "member" not in da.dims:
        da = da.expand_dims(member=[0])
    da = da.drop_vars(
        [c for c in ("number", "member", "spatial_ref") if c in da.coords and c not in da.dims],
        errors="ignore",
    )
    return da.transpose("year", "member", "lat", "lon")


def assemble(roster, variable, *, init, target, region=None, grid_res=None,
             regrid_to=None, seasonal=None, range_index=2, cache=True,
             verbose=True, boundary="cover"):
    """Fan out `fetch` across a model roster and pair up hindcast/forecast.

    roster: iterable of rows `(label, product, *ranges)` where each range is
    `(start, end)`. `range_index` selects which range tuple in the row to use
    as the hindcast window (default 2 -> the third element, i.e. the first
    range column after label/product).

    Returns `{label: (hindcast, forecast)}`. Per-row fetch failures are not
    swallowed here (caller decides); raises on first failure.
    """
    common = dict(init=init, target=target, region=region, grid_res=grid_res,
                  regrid_to=regrid_to, seasonal=seasonal, cache=cache,
                  verbose=verbose, boundary=boundary, year_index=True)
    out = {}
    for row in roster:
        label, product = row[0], row[1]
        h0, h1 = row[range_index]
        hcst = _canonicalize(fetch(product, variable, hindcast=(h0, h1), **common)[variable])
        fcst = _canonicalize(fetch(product, variable, **common)[variable])
        out[label] = (hcst, fcst)
    return out
