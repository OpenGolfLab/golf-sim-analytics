"""
Logging configuration.

The old app used bare print() for every error. That's invisible once
packaged with `pyinstaller --noconsole`, which is how build_exe.bat builds
the distributed exe — so every ingestion/rendering error silently vanished
in the field with no way to diagnose a user's bug report.

Call setup_logging() once at startup; everywhere else just do
`log = logging.getLogger(__name__)` and log normally.
"""
from __future__ import annotations

import logging
from logging.handlers import RotatingFileHandler

from config import LOG_FILE


def setup_logging(level: int = logging.INFO) -> None:
    root = logging.getLogger()
    if root.handlers:
        return  # already configured (e.g. tests importing multiple modules)

    root.setLevel(level)
    fmt = logging.Formatter(
        "%(asctime)s [%(levelname)s] %(name)s: %(message)s", "%Y-%m-%d %H:%M:%S"
    )

    file_handler = RotatingFileHandler(
        LOG_FILE, maxBytes=2_000_000, backupCount=3, encoding="utf-8"
    )
    file_handler.setFormatter(fmt)
    root.addHandler(file_handler)

    # Also echo to stdout when one exists (running from source / a console
    # build); harmless no-op under --noconsole since sys.stdout is None there.
    try:
        stream_handler = logging.StreamHandler()
        stream_handler.setFormatter(fmt)
        root.addHandler(stream_handler)
    except Exception:
        pass
