import yaml
from datetime import date
from pathlib import Path

_CATALOG_PATH = Path(__file__).parent / "catalog.yaml"
with open(_CATALOG_PATH) as f:
    _catalog = yaml.safe_load(f)


def _enrich(entry: dict) -> dict:
    result = dict(entry)
    deprecated_after = result.get("deprecated_after")
    if deprecated_after:
        result["deprecated"] = date.fromisoformat(deprecated_after) <= date.today()
    else:
        result["deprecated"] = False
    return result


def list_products(include_deprecated: bool = True) -> list[str]:
    if include_deprecated:
        return list(_catalog.keys())
    return [k for k, v in _catalog.items()
            if not (_enrich(v).get("deprecated", False))]


def info(product_name: str) -> dict:
    if product_name not in _catalog:
        raise KeyError(f"Product not found: {product_name}")
    return _enrich(_catalog[product_name])


get = info
