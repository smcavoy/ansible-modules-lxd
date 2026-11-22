# Copyright (c) 2026, Sean McAvoy
# GNU General Public License v3.0+ (see LICENSES/GPL-3.0-or-later.txt or https://www.gnu.org/licenses/gpl-3.0.txt)
# SPDX-License-Identifier: GPL-3.0-or-later

"""The life cycle of more modules: objects under a parent, auth and cluster groups, snapshots.

Each module runs through main() against the in-memory LXD server: check mode, create, a second run,
an update with a diff and a second run, delete in check mode, delete, and a second delete.
"""

from __future__ import annotations

import typing as t

import pytest

from ansible_collections.smcavoy.lxd.plugins.modules import (
    lxd_auth_group,
    lxd_cluster_group,
    lxd_instance_snapshot,
    lxd_network_forward,
    lxd_network_load_balancer,
    lxd_placement_group,
    lxd_storage_bucket,
    lxd_storage_volume,
    lxd_storage_volume_snapshot,
)

POOL = ("/1.0/storage-pools/p1", {"name": "p1", "driver": "dir", "config": {}, "description": ""})
NETWORK = ("/1.0/networks/br0", {"name": "br0", "type": "bridge", "managed": True, "config": {}, "description": ""})
VOLUME = ("/1.0/storage-pools/p1/volumes/custom/v1", {"name": "v1", "type": "custom", "content_type": "filesystem", "config": {}, "description": ""})
INSTANCE = ("/1.0/instances/web", {"name": "web", "type": "container", "status": "Stopped", "config": {}, "devices": {}, "profiles": ["default"]})


class Case(t.NamedTuple):
    module: t.Any
    parents: list[tuple[str, dict[str, t.Any]]]
    path: str
    ident: dict[str, t.Any]
    create: dict[str, t.Any]
    update: dict[str, t.Any]
    # Checks on the stored object after the update: a key and its value, or ("config", {k: v}).
    expect: dict[str, t.Any]
    clustered: bool = False


CASES = [
    Case(
        lxd_storage_volume,
        [POOL],
        VOLUME[0],
        {"pool": "p1", "name": "v1"},
        {"description": "one"},
        {"config": {"user.team": "a"}},
        {"config": {"user.team": "a"}},
    ),
    Case(
        lxd_storage_volume_snapshot,
        [POOL, VOLUME],
        VOLUME[0] + "/snapshots/s1",
        {"pool": "p1", "volume": "v1", "name": "s1"},
        {"description": "one"},
        {"description": "two"},
        {"description": "two"},
    ),
    Case(
        lxd_storage_bucket,
        [POOL],
        "/1.0/storage-pools/p1/buckets/b1",
        {"pool": "p1", "name": "b1"},
        {"description": "one"},
        {"description": "two"},
        {"description": "two"},
    ),
    Case(
        lxd_network_forward,
        [NETWORK],
        "/1.0/networks/br0/forwards/192.0.2.10",
        {"network": "br0", "listen_address": "192.0.2.10"},
        {"description": "one"},
        {"config": {"target_address": "10.0.0.5"}},
        {"config": {"target_address": "10.0.0.5"}},
    ),
    Case(
        lxd_network_load_balancer,
        [NETWORK],
        "/1.0/networks/br0/load-balancers/192.0.2.150",
        {"network": "br0", "listen_address": "192.0.2.150"},
        {"description": "one"},
        {"description": "two"},
        {"description": "two"},
    ),
    Case(lxd_auth_group, [], "/1.0/auth/groups/ops", {"name": "ops"}, {"description": "one"}, {"description": "two"}, {"description": "two"}),
    Case(
        lxd_cluster_group,
        [],
        "/1.0/cluster/groups/rack1",
        {"name": "rack1"},
        {"description": "one"},
        {"description": "two"},
        {"description": "two"},
        clustered=True,
    ),
    Case(
        lxd_placement_group,
        [],
        "/1.0/placement-groups/pg1",
        {"name": "pg1"},
        {"description": "one", "policy": "spread", "rigor": "strict"},
        {"description": "two"},
        {"description": "two"},
    ),
    Case(lxd_instance_snapshot, [INSTANCE], INSTANCE[0] + "/snapshots/s1", {"instance": "web", "name": "s1"}, {}, {}, {}),
]
IDS = [case.module.__name__.rsplit(".", 1)[-1] for case in CASES]


@pytest.fixture(params=[False, True], ids=["sync", "async"])
def server(request, lxd):
    lxd.async_writes = request.param
    return lxd


def check(stored: dict[str, t.Any], expect: dict[str, t.Any]) -> None:
    for key, value in expect.items():
        if isinstance(value, dict):
            for sub, sub_value in value.items():
                assert stored[key][sub] == sub_value, (key, sub, stored)
        else:
            assert stored[key] == value, (key, stored)


@pytest.mark.parametrize("case", CASES, ids=IDS)
def test_life_cycle(server, run, case):
    server.server_info["environment"]["server_clustered"] = case.clustered
    for path, obj in case.parents:
        server.add(path, obj)
    create = dict(case.ident, **case.create)

    result = run(case.module, create, check_mode=True)
    assert result.get("changed") is True, result
    assert server.writes() == []
    assert server.get(case.path) is None

    result = run(case.module, create)
    assert result.get("changed") is True, result
    assert server.get(case.path) is not None, server.objects.keys()
    assert server.get(case.path).get("description", "") == case.create.get("description", server.get(case.path).get("description", ""))

    del server.requests[:]
    result = run(case.module, create)
    assert result.get("changed") is False, result
    assert server.writes() == []

    if case.update:
        result = run(case.module, dict(create, **case.update), diff=True)
        assert result.get("changed") is True, result
        check(server.get(case.path), case.expect)
        assert result["diff"]["before"] != result["diff"]["after"]

        del server.requests[:]
        result = run(case.module, dict(create, **case.update))
        assert result.get("changed") is False, result
        assert server.writes() == []

    absent = dict(case.ident, state="absent")
    result = run(case.module, absent, check_mode=True)
    assert result.get("changed") is True, result
    assert server.get(case.path) is not None

    result = run(case.module, absent)
    assert result.get("changed") is True, result
    assert server.get(case.path) is None

    result = run(case.module, absent)
    assert result.get("changed") is False, result


@pytest.mark.parametrize("case", [c for c in CASES if c.parents], ids=[i for c, i in zip(CASES, IDS, strict=True) if c.parents])
def test_create_under_a_missing_parent_fails(lxd, run, case):
    # The parent does not exist: the create fails, and nothing is written.
    result = run(case.module, dict(case.ident, **case.create))
    assert result.get("failed") is True, result
    assert lxd.get(case.path) is None
