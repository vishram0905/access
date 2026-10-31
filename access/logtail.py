"""Helpers for reading and trimming the agents' log files (tooling).

We read only the end of a log, so the Sentinel and the dashboard stay fast however large a file has grown.
"""
from pathlib import Path

# The Sentinel trims any agent log above MAX_LOG_MB down to its most recent KEEP_MB.
MAX_LOG_MB = 50
KEEP_MB = 5


def tail_lines(path: Path, n: int = 200, max_bytes: int = 2_000_000) -> list[str]:
    """Return the last n lines, reading at most max_bytes from the end of the file."""
    path = Path(path)
    if not path.exists():
        return []
    with open(path, "rb") as fh:
        fh.seek(0, 2)
        size = fh.tell()
        fh.seek(max(0, size - max_bytes))
        data = fh.read().decode("utf-8", errors="ignore")
    lines = data.splitlines()
    if size > max_bytes:
        lines = lines[1:]  # the first line is probably cut in half
    return lines[-n:]


def trim(path: Path, keep_bytes: int = KEEP_MB * 1_000_000) -> bool:
    """Shrink a runaway log to its last keep_bytes and return True if we trimmed it.

    This is safe while agents are still writing, because they open their logs in append mode (O_APPEND).
    """
    path = Path(path)
    if not path.exists() or path.stat().st_size <= MAX_LOG_MB * 1_000_000:
        return False
    with open(path, "rb") as fh:
        fh.seek(-keep_bytes, 2)
        fh.readline()
        tail = fh.read()
    with open(path, "r+b") as fh:
        fh.truncate(0)
        fh.write(b"--- log trimmed by the Sentinel (kept the most recent part) ---\n" + tail)
    return True
