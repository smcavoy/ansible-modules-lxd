# Copyright (c) 2026, Sean McAvoy
# GNU General Public License v3.0+ (see LICENSES/GPL-3.0-or-later.txt or https://www.gnu.org/licenses/gpl-3.0.txt)
# SPDX-License-Identifier: GPL-3.0-or-later

"""Tests for a restart of a frozen instance, the target address of a network forward, and the state of a volume on a cluster.

Each test fails on the code before the fix. The test for the error text of a failed HEAD is in tests/unit/plugins/module_utils/test_client.py.
"""

from __future__ import annotations

import typing as t
from urllib.parse import parse_qs, urlsplit

import pytest

from ansible_collections.smcavoy.lxd.plugins.modules import lxd_instance, lxd_network_forward, lxd_storage_volume_info

# ----------------------------------------------------------------------
# state=restarted on a frozen instance

INSTANCE = "/1.0/instances/web"


def add_instance(lxd, status: str) -> None:
    inst: dict[str, t.Any] = {"name": "web", "type": "container", "description": "", "config": {}, "devices": {}, "profiles": ["default"]}
    inst.update(ephemeral=False, status=status, location="none", used_by=[])
    lxd.add(INSTANCE, inst)


def state_actions(lxd) -> list[str]:
    return [body["action"] for method, target, body in lxd.requests if method == "PUT" and urlsplit(target).path == INSTANCE + "/state"]


def test_restarted_restarts_a_frozen_instance(lxd, run):
    # Seen live on LXD 6.10.1: a restart of a frozen instance fails with "Instance is not running"; unfreeze, then restart works.
    add_instance(lxd, "Frozen")
    result = run(lxd_instance, {"name": "web", "state": "restarted"})
    assert result["changed"] is True, result
    assert result["instance"]["status"] == "Running"
    # Before: the module sent only "unfreeze", so the instance did not restart.
    assert state_actions(lxd) == ["unfreeze", "restart"]
    assert lxd.get(INSTANCE)["restarts"] == 1


@pytest.mark.parametrize(("status", "actions"), [("Running", ["restart"]), ("Stopped", ["start"])])
def test_restarted_keeps_one_action_for_other_states(lxd, run, status, actions):
    add_instance(lxd, status)
    result = run(lxd_instance, {"name": "web", "state": "restarted"})
    assert result["changed"] is True, result
    assert state_actions(lxd) == actions
    assert lxd.get(INSTANCE)["status"] == "Running"


def test_restarted_on_a_frozen_instance_in_check_mode_sends_nothing(lxd, run):
    add_instance(lxd, "Frozen")
    result = run(lxd_instance, {"name": "web", "state": "restarted"}, check_mode=True)
    assert result["changed"] is True, result
    assert lxd.writes() == []
    assert lxd.get(INSTANCE)["status"] == "Frozen"


# ----------------------------------------------------------------------
# lxd_network_forward, the default target address

FORWARDS = "/1.0/networks/br0/forwards"


def add_bridge(lxd) -> None:
    lxd.add("/1.0/networks/br0", {"name": "br0", "type": "bridge", "managed": True, "status": "Created", "description": "", "config": {}})


def test_forward_default_target_compares_in_the_canonical_form(lxd, run):
    # Seen live on LXD 6.10.1: a create with FD42:99:0::0010 stores fd42:99::10.
    add_bridge(lxd)
    stored = {"listen_address": "2001:db8::78", "description": "", "config": {"target_address": "fd42:99::10"}, "ports": []}
    lxd.add(f"{FORWARDS}/2001:db8::78", stored)
    args = {"network": "br0", "listen_address": "2001:DB8:0::78", "config": {"target_address": "FD42:99:0::0010"}}
    result = run(lxd_network_forward, args)
    # Before: the module compared the text of the task, and sent a PUT on every run.
    assert result["changed"] is False, result
    assert lxd.writes() == []
    assert run(lxd_network_forward, dict(args, config_mode="exact"))["changed"] is False
    assert lxd.writes() == []


def test_forward_create_sends_the_canonical_default_target(lxd, run):
    add_bridge(lxd)
    args = {"network": "br0", "listen_address": "192.0.2.10", "config": {"target_address": " FD42:99:0::0010 "}}
    result = run(lxd_network_forward, args)
    assert result["changed"] is True, result
    assert lxd.get(f"{FORWARDS}/192.0.2.10")["config"] == {"target_address": "fd42:99::10"}
    del lxd.requests[:]
    assert run(lxd_network_forward, args)["changed"] is False
    assert lxd.writes() == []


def test_forward_changes_a_default_target_that_differs(lxd, run):
    add_bridge(lxd)
    lxd.add(f"{FORWARDS}/192.0.2.10", {"listen_address": "192.0.2.10", "description": "", "config": {"target_address": "10.0.0.5"}, "ports": []})
    result = run(lxd_network_forward, {"network": "br0", "listen_address": "192.0.2.10", "config": {"target_address": "10.0.0.6"}})
    assert result["changed"] is True, result
    assert lxd.get(f"{FORWARDS}/192.0.2.10")["config"] == {"target_address": "10.0.0.6"}


@pytest.mark.parametrize("address", ["0.0.0.0", "::", "0:0:0:0:0:0:0:0"])
@pytest.mark.parametrize("state", ["present", "absent"])
def test_forward_refuses_the_unspecified_listen_address(lxd, run, address, state):
    # Seen live on LXD 6.10.1: LXD reads 0.0.0.0 and :: as "allocate a listen address" (a bridge answers
    # "Automatic listen address allocation not supported"), so the forward never has the address of the task.
    add_bridge(lxd)
    del lxd.requests[:]
    result = run(lxd_network_forward, {"network": "br0", "listen_address": address, "state": state})
    assert result.get("failed") is True, result
    assert "listen_address" in result["msg"] and "unspecified address" in result["msg"]
    assert "allocate" in result["msg"]
    # Before: the module sent the create, and LXD allocated an address or refused.
    assert lxd.writes() == []


@pytest.mark.parametrize(
    ("extra", "option"),
    [
        ({"config": {"target_address": "0.0.0.0"}}, "config.target_address"),
        ({"config": {"target_address": "::"}}, "config.target_address"),
        (
            {
                "ports": [
                    {"protocol": "tcp", "listen_port": "80", "target_address": "10.0.0.5"},
                    {"protocol": "udp", "listen_port": "53", "target_address": "::0"},
                ]
            },
            "ports[1]",
        ),
    ],
)
def test_forward_refuses_the_unspecified_target_address(lxd, run, extra, option):
    # Seen live on LXD 6.10.1: "Default target address is not within the network subnet" and
    # "Target address is not within the network subnet in port specification 0".
    add_bridge(lxd)
    del lxd.requests[:]
    result = run(lxd_network_forward, dict({"network": "br0", "listen_address": "192.0.2.10"}, **extra), check_mode=True)
    assert result.get("failed") is True, result
    assert option in result["msg"] and "unspecified address" in result["msg"]
    assert lxd.writes() == []


# ----------------------------------------------------------------------
# lxd_storage_volume_info, the member that answers for the state of a volume


def add_volumes(lxd, locations: dict[str, str]) -> None:
    lxd.add("/1.0/storage-pools/p1", {"name": "p1", "driver": "dir", "config": {}})
    for name, location in locations.items():
        volume = {"name": name, "type": "custom", "content_type": "filesystem", "config": {}, "location": location}
        lxd.add(f"/1.0/storage-pools/p1/volumes/custom/{name}", volume)
    # The fake lists only direct children. Volumes sit two levels down, so the test gives the list as LXD does.
    volumes = [lxd.get(f"/1.0/storage-pools/p1/volumes/custom/{name}") for name in locations]
    lxd.add("/1.0/storage-pools/p1/volumes", volumes)  # type: ignore[arg-type]


def state_targets(lxd) -> dict[str, str | None]:
    """Return the ?target= of each state request, by volume name."""
    found = {}
    for method, target, _body in lxd.requests:
        url = urlsplit(target)
        parts = url.path.split("/")
        if method == "GET" and parts[-1] == "state" and parts[2] == "storage-pools":
            found[parts[-2]] = parse_qs(url.query).get("target", [None])[0]
    return found


def test_volume_state_goes_to_the_member_of_the_volume(lxd, run):
    lxd.server_info["environment"]["server_clustered"] = True
    add_volumes(lxd, {"v1": "n1", "v2": "n2"})
    result = run(lxd_storage_volume_info, {"pool": "p1", "include_state": True})
    assert [vol["state"] for vol in result["storage_volumes"]] == [{"usage": {"used": 4096, "total": 0}}] * 2, result
    # Before: the state request had no target, or the target of the task for every volume.
    assert state_targets(lxd) == {"v1": "n1", "v2": "n2"}


def test_volume_state_of_one_volume_ignores_another_task_target(lxd, run):
    lxd.server_info["environment"]["server_clustered"] = True
    add_volumes(lxd, {"v2": "n2"})
    run(lxd_storage_volume_info, {"pool": "p1", "name": "v2", "include_state": True, "target": "n1"})
    assert state_targets(lxd) == {"v2": "n2"}


def test_volume_state_of_a_remote_volume_keeps_the_task_target(lxd, run):
    # A volume on remote storage (Ceph) has no location on a cluster.
    lxd.server_info["environment"]["server_clustered"] = True
    add_volumes(lxd, {"v1": ""})
    run(lxd_storage_volume_info, {"pool": "p1", "name": "v1", "include_state": True, "target": "n1"})
    assert state_targets(lxd) == {"v1": "n1"}
    del lxd.requests[:]
    run(lxd_storage_volume_info, {"pool": "p1", "name": "v1", "include_state": True})
    assert state_targets(lxd) == {"v1": None}


def test_volume_state_on_a_single_server_has_no_target(lxd, run):
    # A server that is not clustered reports the location "none".
    add_volumes(lxd, {"v1": "none"})
    run(lxd_storage_volume_info, {"pool": "p1", "include_state": True})
    assert state_targets(lxd) == {"v1": None}
