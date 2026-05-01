import warnings
from datetime import datetime, timezone

from . import catalog
from .adapters import get_adapter


def _utc_now():
    return datetime.now(timezone.utc).isoformat()


def check_product(product, probe_remote=False):
    """Return health status for one catalog product."""
    config = catalog.get(product)

    if config.get("deprecated"):
        successor = config.get("successor")
        successor_msg = f" Migrate to: {successor}." if successor else " No successor identified yet."
        warnings.warn(
            f"{product} is deprecated (sunset: {config['deprecated_after']}).{successor_msg}",
            DeprecationWarning,
            stacklevel=2,
        )

    if config.get("pending_url"):
        return {
            "product": product,
            "adapter": config["adapter"],
            "checked_at": _utc_now(),
            "healthy": False,
            "kind": "config",
            "message": config.get("pending_url_note", "Source URL not yet confirmed. See issue tracker."),
            "probe_remote": bool(probe_remote),
        }

    adapter_name = config["adapter"]
    adapter = get_adapter(adapter_name)
    result = adapter.health_check(config, probe_remote=probe_remote)
    return {
        "product": product,
        "adapter": adapter_name,
        "checked_at": _utc_now(),
        **result,
    }


def check_all_products(probe_remote=False):
    """Return health status for all catalog products."""
    statuses = []
    for product in catalog.list_products():
        try:
            statuses.append(check_product(product, probe_remote=probe_remote))
        except Exception as e:
            config = catalog.get(product)
            statuses.append(
                {
                    "product": product,
                    "adapter": config.get("adapter", "unknown"),
                    "checked_at": _utc_now(),
                    "healthy": False,
                    "kind": "runtime",
                    "message": f"Health check failed: {e}",
                    "probe_remote": bool(probe_remote),
                }
            )
    return statuses
