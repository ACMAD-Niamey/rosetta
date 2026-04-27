from abc import ABC, abstractmethod


class AdapterBase(ABC):
    @abstractmethod
    def fetch_data(self, product_config, variable, date_range=None, region=None):
        ...

    def health_check(self, product_config, probe_remote=False):
        """Return adapter health metadata.

        Subclasses should override this to provide adapter-specific checks.
        """
        return {
            "healthy": True,
            "kind": "config",
            "message": "No adapter-specific health check implemented.",
            "probe_remote": bool(probe_remote),
        }
