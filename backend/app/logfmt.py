"""The backend's log format: every line starts with an ISO 8601 UTC timestamp (2026-11-04T09:15:02.123Z). Nothing else about logging changes."""
import logging
import sys
from datetime import datetime, timezone

LOG_FORMAT = "%(asctime)s %(levelname)s:%(name)s:%(message)s"


class UtcIsoFormatter(logging.Formatter):
    def formatTime(self, record, datefmt=None):
        return datetime.fromtimestamp(record.created, timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.") + f"{int(record.msecs):03d}Z"


def configure_logging(stream=None) -> logging.Handler:
    """The root handler at INFO with the timestamped format; does nothing to a root that already has handlers (a host that configured its own)."""
    handler = logging.StreamHandler(stream or sys.stderr)
    handler.setFormatter(UtcIsoFormatter(LOG_FORMAT))
    root = logging.getLogger()
    if not root.handlers:
        root.addHandler(handler)
        root.setLevel(logging.INFO)
    return handler
