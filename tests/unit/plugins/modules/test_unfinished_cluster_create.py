# Copyright (c) 2026, Sean McAvoy
# GNU General Public License v3.0+ (see LICENSES/GPL-3.0-or-later.txt or https://www.gnu.org/licenses/gpl-3.0.txt)
# SPDX-License-Identifier: GPL-3.0-or-later

"""A network or a pool whose cluster create did not finish.

On a live LXD 6.10.1 cluster, a create that stops after the member step leaves the object C(Pending). A create whose
cluster step fails (for example a macvlan network with a parent that does not exist) leaves it C(Errored). LXD cannot
use the object. Before the fix, the modules reported C(ok) for it.
"""

from __future__ import annotations

import pytest

from ansible_collections.smcavoy.lxd.plugins.modules import lxd_network, lxd_storage_pool

CASES = [
    (lxd_network, "/1.0/networks/br0", {"name": "br0", "type": "bridge", "managed": True, "description": "", "config": {}}, "network"),
    (lxd_storage_pool, "/1.0/storage-pools/p1", {"name": "p1", "driver": "dir", "description": "", "config": {}}, "storage pool"),
]


@pytest.fixture
def cluster(lxd):
    lxd.server_info["environment"]["server_clustered"] = True
    for name in ("n1", "n2"):
        lxd.add(f"/1.0/cluster/members/{name}", {"server_name": name, "status": "Online", "roles": [], "groups": ["default"], "config": {}})
    return lxd


@pytest.mark.parametrize("status", ["Pending", "Errored"])
@pytest.mark.parametrize("check_mode", [False, True])
@pytest.mark.parametrize(("module", "path", "obj", "kind"), CASES)
def test_unfinished_create_fails(cluster, run, module, path, obj, kind, status, check_mode):
    name = obj["name"]
    cluster.add(path, dict(obj, status=status, locations=["n1", "n2"]))
    result = run(module, {"name": name}, check_mode=check_mode)
    assert result.get("failed") is True, result
    assert f"The {kind} {name} has the status {status}" in result["msg"]
    assert "members: n1, n2" in result["msg"]
    assert f"remove the {kind} with state=absent" in result["msg"]
    assert cluster.writes() == []


@pytest.mark.parametrize(("module", "path", "obj", "kind"), CASES)
def test_unfinished_create_can_be_removed(cluster, run, module, path, obj, kind):
    cluster.add(path, dict(obj, status="Pending", locations=["n1"]))
    result = run(module, {"name": obj["name"], "state": "absent"})
    assert result["changed"] is True, result
    assert cluster.get(path) is None


@pytest.mark.parametrize(("module", "path", "obj", "kind"), CASES)
def test_created_object_is_ok(cluster, run, module, path, obj, kind):
    cluster.add(path, dict(obj, status="Created", locations=["n1", "n2"]))
    result = run(module, {"name": obj["name"]})
    assert result.get("failed") is not True, result
    assert result["changed"] is False
