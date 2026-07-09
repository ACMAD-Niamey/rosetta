"""Rosetta — federated data integration for seasonal climate forecasting.

Provides a unified fetch() API across CDS, OPeNDAP, NCEI, S3, HTTP, and
Sheerwater data sources. All outputs are CF-aligned xarray Datasets.

Quick start:
    import rosetta
    ds = rosetta.fetch("c3s/ecmwf", variable="precip", init="2025-02",
                       target="MAM", region=[-12, 6, 28, 42], hindcast=(2010, 2015))
"""

from . import catalog
from .fetch import fetch, parse_target, parse_init
from .assemble import assemble
from .zonal import zonal
from .health import check_product, check_all_products

__all__ = [
    "catalog",
    "fetch",
    "zonal",
    "parse_target",
    "parse_init",
    "assemble",
    "check_product",
    "check_all_products",
]
