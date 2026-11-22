# Copyright (c) 2026, Sean McAvoy
# GNU General Public License v3.0+ (see LICENSES/GPL-3.0-or-later.txt or https://www.gnu.org/licenses/gpl-3.0.txt)
# SPDX-License-Identifier: GPL-3.0-or-later

"""The info modules against the in-memory LXD server: list, one by name, a missing name, no writes."""

from __future__ import annotations

import pytest

from ansible_collections.smcavoy.lxd.plugins.modules import (
    lxd_network_acl_info,
    lxd_network_info,
    lxd_profile_info,
    lxd_project_info,
    lxd_storage_pool_info,
)

CASES = [
    # module, collection path, result key, objects that the fake server has at the start
    (lxd_profile_info, "/1.0/profiles", "profiles", ["default"]),
    (lxd_project_info, "/1.0/projects", "projects", ["default"]),
    (lxd_network_info, "/1.0/networks", "networks", []),
    (lxd_storage_pool_info, "/1.0/storage-pools", "storage_pools", []),
    (lxd_network_acl_info, "/1.0/network-acls", "acls", []),
]
IDS = [case[0].__name__.rsplit(".", 1)[-1] for case in CASES]


@pytest.mark.parametrize(("module", "collection", "key", "existing"), CASES, ids=IDS)
def test_info(lxd, run, module, collection, key, existing):
    for name in ("alpha", "beta"):
        lxd.add(f"{collection}/{name}", {"name": name, "description": name, "config": {}, "used_by": [], "managed": True})

    result = run(module, {})
    assert result["changed"] is False
    assert sorted(item["name"] for item in result[key]) == sorted(existing + ["alpha", "beta"])

    result = run(module, {"name": "beta"})
    assert [item["name"] for item in result[key]] == ["beta"]
    assert result[key][0]["description"] == "beta"

    result = run(module, {"name": "gamma"})
    assert result[key] == []

    assert lxd.writes() == []


@pytest.mark.parametrize("module", [lxd_profile_info, lxd_network_info, lxd_network_acl_info], ids=lambda m: m.__name__.rsplit(".", 1)[-1])
def test_info_in_a_project_that_does_not_exist_fails(lxd, run, module):
    # A wrong project name is not an empty result.
    result = run(module, {"name": "alpha", "project": "pord"})
    assert result["failed"] is True
    assert 'Project "pord" does not exist' in result["msg"]
