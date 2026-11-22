# Copyright (c) 2026, Sean McAvoy
# GNU General Public License v3.0+ (see LICENSES/GPL-3.0-or-later.txt or https://www.gnu.org/licenses/gpl-3.0.txt)
# SPDX-License-Identifier: GPL-3.0-or-later

"""lxd_cluster_member against the in-memory LXD server."""

from __future__ import annotations

import pytest

from ansible_collections.smcavoy.lxd.plugins.modules import lxd_cluster_member

PATH = "/1.0/cluster/members/m1"


@pytest.fixture(params=[False, True], ids=["sync", "async"])
def cluster(request, lxd):
    lxd.async_writes = request.param
    lxd.server_info["environment"]["server_clustered"] = True
    lxd.add(
        PATH,
        {
            "server_name": "m1",
            "status": "Online",
            # A voter that is not the leader, with the role names of LXD 6.10.1 (lxd/db/node.go).
            "roles": ["database-voter", "event-hub"],
            "groups": ["default"],
            "failure_domain": "default",
            "description": "",
            "config": {},
        },
    )
    return lxd


def test_fields_change_without_the_automatic_roles(cluster, run):
    args = {"name": "m1", "roles": ["ovn-chassis", "event-hub"], "groups": ["default", "rack1"], "failure_domain": "rack1", "config": {"user.a": 1}}
    result = run(lxd_cluster_member, args, diff=True)
    assert result["changed"] is True, result
    put = [r for r in cluster.requests if r[0] == "PUT"][-1][2]
    # LXD keeps the database roles itself; the module never sends them.
    assert put["roles"] == ["event-hub", "ovn-chassis"]
    assert put["groups"] == ["default", "rack1"]
    assert put["config"] == {"user.a": "1"}
    assert result["diff"]["before"]["roles"] == ["event-hub"]

    del cluster.requests[:]
    assert run(lxd_cluster_member, args)["changed"] is False
    assert cluster.writes() == []


def test_roles_are_idempotent_on_a_voter(cluster, run):
    # Before: the module took database-voter as a role of the user, and each run reported a change.
    for roles in (["event-hub"], []):
        run(lxd_cluster_member, {"name": "m1", "roles": roles})
        # LXD adds the automatic roles again after a PUT.
        cluster.get(PATH)["roles"] = ["database-voter", *roles]
        del cluster.requests[:]
        result = run(lxd_cluster_member, {"name": "m1", "roles": roles}, diff=True)
        assert result["changed"] is False, result
        assert cluster.writes() == []


def test_evacuate_mode_auto_sends_no_mode(cluster, run):
    # LXD 6.10.1 has the modes stop, migrate and live-migrate. It refuses "auto" when the member has an instance.
    result = run(lxd_cluster_member, {"name": "m1", "state": "evacuated", "evacuate_mode": "auto"})
    assert result["changed"] is True, result
    assert cluster.member_actions == [{"action": "evacuate"}]


def test_evacuate_then_restore(cluster, run):
    evacuate = {"name": "m1", "state": "evacuated", "evacuate_mode": "stop"}
    assert run(lxd_cluster_member, evacuate, check_mode=True)["changed"] is True
    assert cluster.writes() == []

    result = run(lxd_cluster_member, evacuate)
    assert result["changed"] is True, result
    assert cluster.member_actions == [{"action": "evacuate", "mode": "stop"}]
    assert cluster.get(PATH)["status"] == "Evacuated"

    del cluster.requests[:]
    assert run(lxd_cluster_member, evacuate)["changed"] is False
    assert cluster.writes() == []

    result = run(lxd_cluster_member, {"name": "m1", "state": "present"})
    assert result["changed"] is True, result
    assert cluster.member_actions[-1] == {"action": "restore"}
    assert cluster.get(PATH)["status"] == "Online"


def test_forced_evacuation_sends_force(cluster, run):
    run(lxd_cluster_member, {"name": "m1", "state": "evacuated", "force": True})
    assert cluster.member_actions == [{"action": "evacuate", "force": True}]


def test_remove_member(cluster, run):
    result = run(lxd_cluster_member, {"name": "m1", "state": "absent", "force": True})
    assert result["changed"] is True, result
    assert cluster.get(PATH) is None
    assert [r[1] for r in cluster.writes()] == ["/1.0/cluster/members/m1?force=1"]
    assert run(lxd_cluster_member, {"name": "m1", "state": "absent"})["changed"] is False


@pytest.mark.parametrize(
    ("args", "clustered", "text"),
    [
        ({"name": "m9"}, True, "cluster member m9 not found"),
        ({"name": "m1", "roles": ["database"]}, True, "role database is assigned by LXD"),
        ({"name": "m1", "roles": ["database-voter"]}, True, "role database-voter is assigned by LXD"),
        ({"name": "m1"}, False, "not clustered"),
    ],
    ids=["missing-member", "automatic-role", "automatic-role-6.10", "not-clustered"],
)
def test_member_errors(cluster, run, args, clustered, text):
    cluster.server_info["environment"]["server_clustered"] = clustered
    del cluster.requests[:]
    result = run(lxd_cluster_member, args)
    assert result.get("failed") is True, result
    assert text in result["msg"]
    assert cluster.writes() == []
