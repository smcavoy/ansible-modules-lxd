# Copyright (c) 2026, Sean McAvoy
# GNU General Public License v3.0+ (see LICENSES/GPL-3.0-or-later.txt or https://www.gnu.org/licenses/gpl-3.0.txt)
# SPDX-License-Identifier: GPL-3.0-or-later

from __future__ import annotations

import pytest

from ansible_collections.smcavoy.lxd.plugins.module_utils._time import NEVER, format_time, parse_time


@pytest.mark.parametrize("value", [None, "", NEVER, "0001-01-01T00:00:00.000000000Z"])
def test_never(value: str | None) -> None:
    assert parse_time(value) is None
    assert format_time(parse_time(value)) == NEVER


def test_same_time_in_two_zones() -> None:
    assert parse_time("2099-01-01T00:00:00Z") == parse_time("2099-01-01T01:00:00+01:00")


def test_nanoseconds_from_lxd() -> None:
    parsed = parse_time("2099-01-01T00:00:00.123456789Z")
    assert parsed is not None
    assert parsed.microsecond == 123456
    assert format_time(parsed) == "2099-01-01T00:00:00Z"


@pytest.mark.parametrize("value", ["next tuesday", "2099-01-01", "2099-01-01T00:00:00"])
def test_bad_time(value: str) -> None:
    with pytest.raises(ValueError):
        parse_time(value)
