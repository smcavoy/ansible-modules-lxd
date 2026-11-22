# Copyright (c) 2026, Sean McAvoy
# GNU General Public License v3.0+ (see LICENSES/GPL-3.0-or-later.txt or https://www.gnu.org/licenses/gpl-3.0.txt)
# SPDX-License-Identifier: GPL-3.0-or-later

from __future__ import annotations

import typing as t

import pytest

from ansible_collections.smcavoy.lxd.plugins.module_utils._cluster import (
    local_keys,
    member_local_config,
    split_config,
)
from ansible_collections.smcavoy.lxd.plugins.module_utils._config import ConfigValueError


class FakeClient:
    def __init__(self, meta):
        self.meta = meta
        self.calls = 0

    def get(self, path, query=None):
        self.calls += 1
        return self.meta, None


META = {
    "configs": {
        "network-bridge": {
            "network-conf": {
                "keys": [
                    {"ipv4.address": {"scope": "global"}},
                    {"bridge.external_interfaces": {"scope": "local"}},
                    {"bgp.ipv4.nexthop": {"scope": "local"}},
                ]
            }
        }
    }
}


def test_cluster_local_keys_are_read_once():
    client = t.cast(t.Any, FakeClient(META))
    assert local_keys(client, "network-bridge") == {"bridge.external_interfaces", "bgp.ipv4.nexthop"}
    assert local_keys(client, "storage-zfs") == set()
    assert client.calls == 1


def test_cluster_split():
    global_part, local_part = split_config({"ipv4.address": "auto", "bgp.ipv4.nexthop": "1.2.3.4"}, {"bgp.ipv4.nexthop"})
    assert global_part == {"ipv4.address": "auto"}
    assert local_part == {"bgp.ipv4.nexthop": "1.2.3.4"}


def test_cluster_member_config_overrides_defaults():
    result = member_local_config(["m1", "m2"], {"bgp.ipv4.nexthop": "1.1.1.1"}, {"m2": {"bgp.ipv4.nexthop": "2.2.2.2"}})
    assert result == {"m1": {"bgp.ipv4.nexthop": "1.1.1.1"}, "m2": {"bgp.ipv4.nexthop": "2.2.2.2"}}


def test_member_local_config_rejects_unknown_members():
    with pytest.raises(ConfigValueError, match="does not have: node9"):
        member_local_config(["node1", "node2"], {}, {"node9": {"source": "/x"}})
