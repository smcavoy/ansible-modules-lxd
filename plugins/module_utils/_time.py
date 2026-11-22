# Copyright (c) 2026, Sean McAvoy
# GNU General Public License v3.0+ (see LICENSES/GPL-3.0-or-later.txt or https://www.gnu.org/licenses/gpl-3.0.txt)
# SPDX-License-Identifier: GPL-3.0-or-later

# Note that this module util is **PRIVATE** to the collection. It can have breaking changes at any time.
# Do not use this from other collections or standalone plugins/modules!

"""RFC 3339 times as LXD uses them, for example in expires_at."""

from __future__ import annotations

import datetime
import re

# LXD returns the zero time for "never".
NEVER = "0001-01-01T00:00:00Z"
_RFC3339 = re.compile(r"^(\d{4}-\d{2}-\d{2})[Tt ](\d{2}:\d{2}:\d{2})(\.\d+)?([Zz]|[+-]\d{2}:\d{2})$")


def parse_time(value: str | None) -> datetime.datetime | None:
    """Parse an RFC 3339 time in UTC. Return None for "never": an empty string or the zero time. Raise ValueError for a bad value."""
    if value is None or value == "":
        return None
    match = _RFC3339.match(value.strip())
    if not match:
        raise ValueError(value)
    date, clock, fraction, zone = match.groups()
    micro = (fraction or ".0")[1:7].ljust(6, "0")
    offset = "+00:00" if zone in ("Z", "z") else zone
    parsed = datetime.datetime.fromisoformat(f"{date}T{clock}.{micro}{offset}")
    if parsed.year <= 1:
        return None
    return parsed.astimezone(datetime.timezone.utc)


def format_time(value: datetime.datetime | None) -> str:
    """Return a time in the form that LXD returns, or the zero time for None."""
    if value is None:
        return NEVER
    return value.astimezone(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
