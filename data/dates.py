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
        now = pd.Timestamp.now()
        # A future year in the filename is almost always a mistyped year
        # segment (e.g. "...-30-..." parsing as 2030). Rather than discard
        # the round's date, assume it happened this year — or, if that
        # month/day hasn't come around yet this year, the most recent past
        # year — so the round keeps a real, sortable date instead of
        # falling back to the imprecise file ctime.
        if parsed.year > now.year:
            for year in (now.year, now.year - 1):
                try:
                    candidate = parsed.replace(year=year)
                except ValueError:
                    continue  # e.g. Feb 29 landing on a non-leap year
                if candidate <= now + pd.Timedelta(days=1):
                    log.info(
                        "Filename %s has a future year (%d); assuming %s",
                        filename, parsed.year, candidate.date(),
                    )
                    return candidate
            log.warning(
                "Could not repair future date in filename %s (%s); "
                "falling back to file ctime", filename, parsed,
            )
            return None
        # Guard against any other corrupt future date (e.g. a bad month/day
        # in the current year): a "future" session would sit permanently at
        # the top of every Last-N-Sessions filter.
        if parsed > now + pd.Timedelta(days=1):
            log.warning(
                "Ignoring future date parsed from filename %s (%s); "
                "falling back to file ctime", filename, parsed,
            )
            return None
        return parsed
    return None
