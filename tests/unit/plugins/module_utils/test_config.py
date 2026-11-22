# Copyright (c) 2026, Sean McAvoy
# GNU General Public License v3.0+ (see LICENSES/GPL-3.0-or-later.txt or https://www.gnu.org/licenses/gpl-3.0.txt)
# SPDX-License-Identifier: GPL-3.0-or-later

from __future__ import annotations

import pytest

from ansible_collections.smcavoy.lxd.plugins.module_utils._config import (
    ConfigValueError,
    merge_config,
    merge_devices,
    normalize_config,
    to_lxd_value,
)


def test_config_normalize():
    assert normalize_config({"a": True, "b": 2, "c": "x", "d": None, "e": 1.5}) == {
        "a": "true",
        "b": "2",
        "c": "x",
        "d": None,
        "e": "1.5",
    }
    assert normalize_config(None) is None
    with pytest.raises(ConfigValueError):
        to_lxd_value("bad", ["list"])
    with pytest.raises(ConfigValueError):
        to_lxd_value("bad", {"a": 1})


def test_config_merge_keeps_unmanaged_keys():
    new, changed = merge_config({"a": "1", "other": "x"}, {"a": "2"}, "merge")
    assert new == {"a": "2", "other": "x"}
    assert changed == ["a"]


def test_config_exact_removes_unmanaged_keys_but_keeps_computed():
    current = {"a": "1", "other": "x", "volatile.uuid": "u"}
    new, changed = merge_config(current, {"a": "1"}, "exact", computed=["volatile.*"])
    assert new == {"a": "1", "volatile.uuid": "u"}
    assert changed == ["other"]


def test_config_null_and_empty_remove_keys():
    new, changed = merge_config({"a": "1", "b": "2"}, {"a": None, "b": ""}, "merge")
    assert new == {}
    assert changed == ["a", "b"]
    new, changed = merge_config({}, {"a": None, "b": ""}, "merge")
    assert new == {}
    assert changed == []


def test_config_not_managed():
    new, changed = merge_config({"a": "1"}, None, "exact")
    assert new == {"a": "1"}
    assert changed == []


def test_devices_change_as_a_whole():
    current = {"eth0": {"type": "nic", "network": "br0", "name": "eth0"}}
    new, changed = merge_devices(current, {"eth0": {"type": "nic", "network": "br1"}}, "merge")
    assert new == {"eth0": {"type": "nic", "network": "br1"}}
    assert changed == ["eth0"]


def test_devices_exact_and_null():
    current = {"a": {"type": "disk", "path": "/a", "source": "/x"}, "b": {"type": "none"}}
    new, changed = merge_devices(current, {"a": None}, "merge")
    assert new == {"b": {"type": "none"}}
    assert changed == ["a"]
    new, changed = merge_devices(current, {"a": {"type": "disk", "path": "/a", "source": "/x"}}, "exact")
    assert new == {"a": {"type": "disk", "path": "/a", "source": "/x"}}
    assert changed == ["b"]


def test_devices_need_type():
    with pytest.raises(ConfigValueError):
        merge_devices({}, {"x": {"path": "/"}}, "merge")
