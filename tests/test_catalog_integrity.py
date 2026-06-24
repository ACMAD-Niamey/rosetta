"""Structural integrity of the product catalog (catalog.yaml).

These are deterministic, no-network invariants that guard against the classes of
catalog bug that are easy to introduce and embarrassing to ship: malformed or
inconsistent coverage ranges, metadata placed where the code can't read it,
dangling aliases, and entries missing the fields their adapter needs.

This is the automated counterpart to a manual catalog review — it runs in the
normal unit suite, so a bad edit fails CI instead of reaching users.
"""
import datetime

import pytest

from rosetta.adapters import _ADAPTERS
from rosetta.catalog import _catalog

CUR_YEAR = datetime.date.today().year
REAL = {k: v for k, v in _catalog.items() if isinstance(v, dict) and "alias_of" not in v}
ALIASES = {k: v for k, v in _catalog.items() if isinstance(v, dict) and "alias_of" in v}


def _fmt(violations):
    return "\n".join(f"  - {k}: {m}" for k, m in violations)


def test_aliases_resolve_to_canonical_products():
    """Every alias_of points at a real product, not a missing entry or another alias."""
    bad = []
    for k, v in ALIASES.items():
        tgt = v["alias_of"]
        if tgt not in _catalog:
            bad.append((k, f"alias_of -> missing product {tgt!r}"))
        elif tgt in ALIASES:
            bad.append((k, f"alias_of -> another alias {tgt!r} (must point at a canonical product)"))
    assert not bad, "Dangling/chained aliases:\n" + _fmt(bad)


def test_products_have_required_fields_for_their_adapter():
    bad = []
    for k, v in REAL.items():
        ad = v.get("adapter")
        if not ad:
            bad.append((k, "missing 'adapter'")); continue
        if ad not in _ADAPTERS:
            bad.append((k, f"adapter {ad!r} not registered {sorted(_ADAPTERS)}"))
        # the "where does the data come from" field is adapter-specific
        if ad == "sheerwater" and not v.get("source"):
            bad.append((k, "sheerwater entry missing 'source'"))
        elif ad == "cds" and not v.get("cds_dataset"):
            bad.append((k, "cds entry missing 'cds_dataset'"))
        elif ad == "iridl" and not v.get("iridl_path"):
            bad.append((k, "iridl entry missing 'iridl_path'"))
        elif ad not in ("sheerwater", "cds", "iridl") and not v.get("source_url"):
            bad.append((k, f"{ad} entry missing 'source_url'"))
        # variables with native names
        vars = v.get("variables")
        if not vars:
            bad.append((k, "no 'variables' defined"))
        else:
            for vn, vc in vars.items():
                if not isinstance(vc, dict) or not vc.get("native_name"):
                    bad.append((k, f"variable {vn!r} missing native_name"))
    assert not bad, "Products missing required fields:\n" + _fmt(bad)


def test_coverage_metadata_lives_under_grid():
    """Ensemble/coverage metadata must be under `grid`. If placed at the entry top
    level it is silently invisible to the adapters and validate.py, which only ever
    read `config['grid']`."""
    bad = []
    for k, v in REAL.items():
        grid = v.get("grid") or {}
        for key in ("members", "forecast_members", "hindcast_members", "hindcast_range", "forecast_range"):
            if key in v and key not in grid:
                bad.append((k, f"{key!r} is at the top level, not under 'grid' (invisible to code)"))
    assert not bad, "Misplaced coverage metadata:\n" + _fmt(bad)


def test_legacy_members_field_is_gone():
    """The ambiguous single `members` was split into forecast_members/hindcast_members
    (a model's real-time and reforecast ensembles differ). No entry should still carry it."""
    bad = [(k, "still has the legacy ambiguous 'members' field — use forecast_members/hindcast_members")
           for k, v in REAL.items() if "members" in (v.get("grid") or {})]
    assert not bad, "Legacy members field:\n" + _fmt(bad)


def test_ensemble_member_fields_are_paired_and_valid():
    """An ensemble product declares BOTH forecast_members and hindcast_members as
    positive ints (observations/reanalysis declare neither)."""
    bad = []
    for k, v in REAL.items():
        grid = v.get("grid") or {}
        f, h = grid.get("forecast_members"), grid.get("hindcast_members")
        present = [x for x in (f, h) if x is not None]
        if not present:
            continue  # non-ensemble product (obs/reanalysis)
        if f is None or h is None:
            bad.append((k, f"only one of forecast_members/hindcast_members set (f={f}, h={h})")); continue
        for name, val in (("forecast_members", f), ("hindcast_members", h)):
            if not isinstance(val, int) or val <= 0:
                bad.append((k, f"{name} not a positive int: {val!r}"))
    assert not bad, "Bad ensemble member fields:\n" + _fmt(bad)


def test_hindcast_ranges_are_well_formed():
    bad = []
    for k, v in REAL.items():
        hr = (v.get("grid") or {}).get("hindcast_range")
        if hr is None:
            continue
        if not (isinstance(hr, list) and len(hr) == 2 and all(isinstance(x, int) for x in hr)):
            bad.append((k, f"hindcast_range not [int, int]: {hr!r}")); continue
        lo, hi = hr
        if lo > hi:
            bad.append((k, f"hindcast_range inverted: {hr}"))
        if lo < 1940:
            # 1940 = start of the ERA5 reanalysis record; anything earlier is a typo.
            bad.append((k, f"hindcast_range starts before 1940: {hr}"))
        if hi > CUR_YEAR + 1:
            bad.append((k, f"hindcast_range ends in the future: {hr} (now {CUR_YEAR})"))
    assert not bad, "Malformed hindcast ranges:\n" + _fmt(bad)


def test_forecast_ranges_are_well_formed():
    """forecast_range is [start, end]: end is an int (the year the real-time stream
    ended — pinned system retired) or null (ongoing). Start <= end when both set."""
    bad = []
    for k, v in REAL.items():
        fr = (v.get("grid") or {}).get("forecast_range")
        if fr is None:
            continue
        if not (isinstance(fr, list) and len(fr) == 2 and isinstance(fr[0], int)
                and (fr[1] is None or isinstance(fr[1], int))):
            bad.append((k, f"forecast_range not [int, int|null]: {fr!r}")); continue
        s, e = fr
        if e is not None and s > e:
            bad.append((k, f"forecast_range inverted: {fr}"))
        if s < 1990 or (e is not None and e > CUR_YEAR + 1):
            bad.append((k, f"forecast_range years implausible: {fr} (now {CUR_YEAR})"))
    assert not bad, "Malformed forecast ranges:\n" + _fmt(bad)


def test_same_c3s_system_has_same_hindcast_range():
    """A C3S (originating_centre, system) pair is one physical model; its reforecast
    *period* is a property of the system, so every catalog entry on that system must
    declare the same hindcast_range.

    Note: ensemble sizes are deliberately NOT checked here — the delivered member
    count varies by product (a monthly product aggregates a lagged/burst ensemble
    into more members than the daily product; e.g. c3s/ukmo=28 vs c3s/ukmo-daily=7),
    so forecast_members/hindcast_members are per-product, not per-system."""
    from collections import defaultdict
    by_sys = defaultdict(dict)
    for k, v in REAL.items():
        if v.get("adapter") == "cds" and v.get("cds_model") and v.get("system") is not None:
            hr = (v.get("grid") or {}).get("hindcast_range")
            by_sys[(v["cds_model"], str(v["system"]))][k] = tuple(hr) if hr else None
    bad = []
    for syskey, entries in by_sys.items():
        if len(set(entries.values())) > 1:
            bad.append(("/".join(entries), f"C3S {syskey} has mismatched hindcast_range: {entries}"))
    assert not bad, "Inconsistent reforecast periods within one C3S system:\n" + _fmt(bad)
