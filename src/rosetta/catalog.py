import yaml
from pathlib import Path

_CATALOG_PATH = Path(__file__).parent / "catalog.yaml"
with open(_CATALOG_PATH) as f:
    _catalog = yaml.safe_load(f)


def list_products():
    return list(_catalog.keys())


def info(product_name):
    if product_name not in _catalog:
        raise KeyError(f"Product not found: {product_name}")
    return _catalog[product_name]


get = info
