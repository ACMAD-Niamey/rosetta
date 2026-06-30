from abc import ABC, abstractmethod


class AdapterBase(ABC):
    @abstractmethod
    def fetch_data(self, product_config, variable, date_range=None, region=None):
        ...

    def _resolve_streams(self, product_config, date_range):
        """Resolve a request into [(stream, sub_range)] segments.

        Mirrors today's start-year stream selection. When the product sets
        ``append_streams`` and the requested range spans the end of
        ``grid.hindcast_range``, return both a hindcast and a forecast segment so
        the adapter can fetch and concatenate them on time.
        """
        if not product_config.get("split_streams"):
            return [("hindcast", date_range)]
        hr = (product_config.get("grid") or {}).get("hindcast_range")
        if (product_config.get("append_streams") and hr and date_range
                and date_range[0] <= hr[1] < date_range[1]):
            return [("hindcast", (date_range[0], hr[1])),
                    ("forecast", (hr[1] + 1, date_range[1]))]
        is_forecast = bool(date_range and hr and date_range[0] > hr[1])
        return [("forecast" if is_forecast else "hindcast", date_range)]

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
