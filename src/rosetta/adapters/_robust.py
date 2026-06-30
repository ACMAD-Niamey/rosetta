"""Shared retry / rate-limit infrastructure for Rosetta adapters.

Extracted from the HTTP adapter so that OPeNDAP and CCSR adapters can also
retry transient network failures (e.g. ``OSError: NetCDF: I/O failure`` from
a brief IRIDL hiccup) without duplicating logic.
"""
import random
import re
import threading
import time

_DEFAULT_MAX_RETRIES = 3
_DEFAULT_RETRY_BACKOFF = 1.0


class _RateLimiter:
    """Thread-safe minimum-interval gate between requests.

    Used to pace per-file opens so we don't blow through a server's
    requests-per-second budget (CHIRPS rate-limits at >~60 requests/sec when
    GDAL/vsicurl drives many range reads in quick succession).
    """

    def __init__(self, min_interval):
        self.min_interval = float(min_interval or 0.0)
        self._last = 0.0
        self._lock = threading.Lock()

    def wait(self):
        if self.min_interval <= 0:
            return
        with self._lock:
            elapsed = time.monotonic() - self._last
            if elapsed < self.min_interval:
                time.sleep(self.min_interval - elapsed)
            self._last = time.monotonic()


# HTTP 4xx ("client error") responses indicate a problem with our request
# (URL doesn't exist, unauthorized, etc.) and won't fix themselves on retry.
# 5xx and network errors are the ones worth retrying. GDAL/rasterio and
# urllib surface them with different wording, so we match both.
_PERMANENT_HTTP_PATTERNS = (
    re.compile(r"HTTP response code: 4\d{2}"),    # rasterio / vsicurl
    re.compile(r"HTTP Error 4\d{2}"),             # urllib
)


def _is_transient(exc):
    """Return True if ``exc`` is worth retrying.

    Any exception whose message does NOT match a known-permanent HTTP 4xx
    pattern is considered transient — this covers ``OSError`` (netcdf I/O
    failure), ``TimeoutError``, and server-side 5xx errors alike.
    """
    msg = str(exc)
    for pat in _PERMANENT_HTTP_PATTERNS:
        if pat.search(msg):
            return False
    return True


def _with_retry(fn, max_retries, backoff, label, verbose=True, on_failure=None,
                is_transient=_is_transient):
    """Call fn(), retrying transient failures with exponential backoff + jitter.

    Only retries when `is_transient(exc)` is True — by default that means
    "anything except an HTTP 4xx response," since 4xx errors are permanent
    (404 won't become 200 in 2 seconds). Jitter (random factor in [0.5, 1.5))
    desynchronizes retries when many workers fail simultaneously against a
    rate-limited server. `on_failure` runs after each failed attempt before
    the sleep.

    Covers both HTTP adapter downloads and OPeNDAP/CCSR ``xr.open_dataset``
    opens, since ``OSError`` (e.g. ``NetCDF: I/O failure``) is not a 4xx and
    is therefore treated as transient.
    """
    last_err = None
    for attempt in range(max_retries + 1):
        try:
            return fn()
        except Exception as e:
            last_err = e
            if not is_transient(e):
                raise
            if attempt >= max_retries:
                raise
            if on_failure is not None:
                try:
                    on_failure()
                except Exception:
                    pass
            wait = backoff * (2 ** attempt) * (0.5 + random.random())
            if verbose:
                print(f"[rosetta] {label} failed "
                      f"(attempt {attempt + 1}/{max_retries + 1}): {e}; "
                      f"retrying in {wait:.2f}s")
            time.sleep(wait)
    raise last_err  # unreachable, but keeps type-checkers honest
