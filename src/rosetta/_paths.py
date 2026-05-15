"""Filesystem locations used by rosetta adapters."""
import os


def get_tmpdir() -> str:
    """Return the directory adapters should use for scratch downloads.

    Defaults to ``~/.nuthatch/rosetta/_tmp/`` (co-located with the nuthatch
    cache so scratch and cache live in the same tree). Override via the
    ``ROSETTA_TMP_DIR`` environment variable.

    Adapters MUST use this rather than the system tempdir: macOS reaps
    ``/var/folders/.../T/`` on its own schedule, which broke cache entries
    that pickled lazy datasets referencing those temp files (issue #24).
    """
    path = os.environ.get("ROSETTA_TMP_DIR") or os.path.expanduser(
        "~/.nuthatch/rosetta/_tmp"
    )
    os.makedirs(path, exist_ok=True)
    return path
