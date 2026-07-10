"""Rosetta — federated data integration for seasonal climate forecasting.

Provides a unified fetch() API across CDS, OPeNDAP, NCEI, S3, HTTP, and
Sheerwater data sources. All outputs are CF-aligned xarray Datasets.

Quick start:
    import rosetta
    ds = rosetta.fetch("c3s/ecmwf", variable="precip", init="2025-02",
                       target="MAM", region=[-12, 6, 28, 42], hindcast=(2010, 2015))
"""

import os as _os
from pathlib import Path as _Path

# Pin nuthatch's cache to a local directory at import time.
#
# nuthatch discovers its config by walking *up* the filesystem from the calling
# module and adopting the first pyproject.toml / nuthatch.toml it finds. When
# rosetta is pip-installed, that search leaves site-packages/rosetta/ and can pick
# up a nuthatch.toml shipped by a co-installed package — notably `sheerwater`, which
# points the cache root at a private GCS bucket (gs://sheerwater-datalake/...).
# Anyone without those credentials then hits a 401 / interactive prompt on their
# first fetch(). We defend against that on two fronts:
#   1. Ship src/rosetta/nuthatch.toml (see there) so the upward search finds *our*
#      local config first and never reaches the ambient one.
#   2. Pin the root/local cache filesystem here via the standard NUTHATCH_* env
#      vars, since an installed package's own config is demoted to a "mirror" and
#      cannot set the actual root.
# The file:// prefix is required: without it fsspec's split_protocol() mis-parses
# the '://' that adapter source URLs embed in cache-key paths. setdefault() means
# ROSETTA_CACHE_DIR, the NUTHATCH_* env vars, and ~/.nuthatch.toml all still win.
_cache_dir = _Path(
    _os.environ.get("ROSETTA_CACHE_DIR", _Path.home() / ".nuthatch" / "caches")
).expanduser()
_cache_uri = f"file://{_cache_dir}"
_os.environ.setdefault("NUTHATCH_ROOT_FILESYSTEM", _cache_uri)
_os.environ.setdefault("NUTHATCH_LOCAL_FILESYSTEM", _cache_uri)

from . import catalog
from .fetch import fetch, parse_target, parse_init
from .assemble import assemble
from .health import check_product, check_all_products

__all__ = [
    "catalog",
    "fetch",
    "parse_target",
    "parse_init",
    "assemble",
    "check_product",
    "check_all_products",
]
