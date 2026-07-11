"""Filename-embedded date parsing, shared by data/io.py (CSV exports) and
data/reconcile.py (matching a CSV against an already-archived live round).

Split out into its own module so the two don't have to import each other
just to share this one function.
"""
from __future__ import annotations

import logging
import re

import pandas as pd

log = logging.getLogger(__name__)

_DATE_RE = re.compile(r"(\d{2}-\d{2}-\d{2}-\d{2}-\d{2}-\d{2})")


def extract_date_from_filename(filename: str) -> pd.Timestamp | None:
    match = _DATE_RE.search(filename)
    if match:
        try:
            parsed = pd.to_datetime(match.group(1), format="%m-%d-%y-%H-%M-%S")
        except ValueError:
            log.warning("Could not parse date from filename: %s", filename)
            return None
        # Guard against corrupt filenames (e.g. a mistyped year segment
        # parsing as 2030): a "future" session would sit permanently at
        # the top of every Last-N-Sessions filter.
        if parsed > pd.Timestamp.now() + pd.Timedelta(days=1):
            log.warning(
                "Ignoring future date parsed from filename %s (%s); "
                "falling back to file ctime", filename, parsed,
            )
            return None
        return parsed
    return None
