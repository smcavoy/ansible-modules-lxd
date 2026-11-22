# Copyright (c) 2026, Sean McAvoy
# GNU General Public License v3.0+ (see LICENSES/GPL-3.0-or-later.txt or https://www.gnu.org/licenses/gpl-3.0.txt)
# SPDX-License-Identifier: GPL-3.0-or-later

"""Tests for proxy password masking, target on a single server, cluster groups in use, join_config values, and name with all_projects.

Each test fails on the code before the fix. The in-memory LXD server models what LXD 6.10.1 does, as seen on a live server
for the masking, the cluster group and the all_projects cases.
"""

from __future__ import annotations

import base64
import json

import pytest

from ansible_collections.smcavoy.lxd.plugins.modules import (
    lxd_cluster,
    lxd_cluster_group,
    lxd_instance_info,
    lxd_server_config,
    lxd_server_info,
    lxd_storage_volume_snapshot,
)

PROXY = "http://proxyuser:pr0xy-s3cret@proxy.example:3128"
PROXY_MASKED = "http://proxyuser:********@proxy.example:3128"


@pytest.fixture
def cluster(lxd):
    lxd.server_info["environment"]["server_clustered"] = True
    lxd.local_keys = {"server": {"core.https_address"}}
    for name in ("n1", "n2"):
        lxd.add(f"/1.0/cluster/members/{name}", {"server_name": name, "status": "Online", "roles": [], "groups": ["default"], "config": {}})
    return lxd


# ----------------------------------------------------------------------
# the password in the URL of core.proxy_http and core.proxy_https


@pytest.mark.parametrize("key", ["core.proxy_http", "core.proxy_https"])
def test_server_config_masks_the_proxy_password(lxd, run, key):
    args = {"config": {key: PROXY, "core.proxy_ignore_hosts": "proxyuser.example"}}
    result = run(lxd_server_config, args, diff=True)
    assert result["changed"] is True, result
    # The server gets the real value.
    assert lxd.requests[-2][0] == "PUT" and lxd.requests[-2][2]["config"][key] == PROXY
    assert "pr0xy-s3cret" not in json.dumps(result)
    # Only the password is masked. The user, the host, and the port stay.
    assert result["config"][key] == PROXY_MASKED
    assert result["diff"]["after"]["config"][key] == PROXY_MASKED
    assert result["config"]["core.proxy_ignore_hosts"] == "proxyuser.example"

    # The module compares the real values: the same URL makes no change, another password makes one.
    lxd.server_info["config"] = {key: PROXY}
    del lxd.requests[:]
    result = run(lxd_server_config, args | {"config": {key: PROXY}}, diff=True)
    assert result["changed"] is False, result
    assert lxd.writes() == []
    assert result["config"][key] == PROXY_MASKED
    assert result["diff"]["before"]["config"][key] == PROXY_MASKED

    result = run(lxd_server_config, {"config": {key: PROXY.replace("pr0xy-s3cret", "an0ther-pass")}}, check_mode=True, diff=True)
    assert result["changed"] is True, result
    assert "pr0xy-s3cret" not in json.dumps(result) and "an0ther-pass" not in json.dumps(result)
    assert result["diff"]["before"]["config"][key] == result["diff"]["after"]["config"][key] == PROXY_MASKED


def test_server_config_names_the_proxy_password_to_ansible(lxd, run, monkeypatch):
    seen = {}
    real_init = lxd_server_config.ServerConfigModule.__init__

    def init(self, mod):
        real_init(self, mod)
        seen["no_log"] = set(mod.module.no_log_values)

    monkeypatch.setattr(lxd_server_config.ServerConfigModule, "__init__", init)
    run(lxd_server_config, {"config": {"core.proxy_https": PROXY, "core.proxy_http": "http://onlyuser@proxy.example:3128"}}, check_mode=True)
    assert "pr0xy-s3cret" in seen["no_log"]
    assert not {"onlyuser", "proxyuser", PROXY} & seen["no_log"]


@pytest.mark.parametrize(
    "value",
    ["http://proxy.example:3128", "http://onlyuser@proxy.example:3128", "http://user:@proxy.example:3128", "proxy.example:3128", ""],
)
def test_server_config_keeps_a_proxy_url_without_a_password(lxd, run, value):
    lxd.server_info["config"] = {"core.proxy_http": value}
    result = run(lxd_server_config, {})
    assert result["config"]["core.proxy_http"] == value


def test_server_config_masks_the_proxy_password_of_a_member(cluster, run):
    cluster.server_info["config"] = {"core.proxy_https": PROXY, "core.https_address": "192.0.2.1:8443"}
    result = run(lxd_server_config, {"config": {"core.proxy_https": PROXY}}, diff=True)
    assert result["changed"] is False, result
    assert "pr0xy-s3cret" not in json.dumps(result)
    assert result["config"]["core.proxy_https"] == PROXY_MASKED


def test_server_info_masks_the_proxy_password(lxd, run):
    lxd.server_info["config"] = {"core.proxy_http": PROXY, "core.proxy_https": PROXY, "core.proxy_ignore_hosts": "a.example", "user.url": PROXY}
    result = run(lxd_server_info, {})
    config = result["server"]["config"]
    assert config["core.proxy_http"] == PROXY_MASKED
    assert config["core.proxy_https"] == PROXY_MASKED
    assert config["core.proxy_ignore_hosts"] == "a.example"
    # Only the two proxy keys hold a URL with a password by design.
    assert config["user.url"] == PROXY


# ----------------------------------------------------------------------
# lxd_storage_volume_snapshot with target on a server that is not a cluster

POOL = ("/1.0/storage-pools/tank", {"name": "tank", "driver": "dir", "config": {}})
VOLUME = (POOL[0] + "/volumes/custom/data", {"name": "data", "type": "custom", "config": {}})


@pytest.mark.parametrize("state", ["present", "absent", "restored"])
def test_volume_snapshot_refuses_target_on_a_standalone_server(lxd, run, state):
    lxd.add(*POOL)
    lxd.add(*VOLUME)
    lxd.add(VOLUME[0] + "/snapshots/old", {"name": "old", "description": "", "expires_at": "0001-01-01T00:00:00Z"})
    name = "new" if state == "present" else "old"
    result = run(lxd_storage_volume_snapshot, {"pool": "tank", "volume": "data", "name": name, "state": state, "target": "n1"})
    assert result.get("failed") is True, result
    assert result["msg"] == "target is only valid on a clustered server"
    assert lxd.writes() == []


def test_volume_snapshot_takes_target_on_a_cluster(cluster, run):
    cluster.add(*POOL)
    cluster.add(*VOLUME)
    result = run(lxd_storage_volume_snapshot, {"pool": "tank", "volume": "data", "name": "new", "target": "n1"})
    assert result["changed"] is True, result
    assert "target=n1" in cluster.writes()[0][1]


# ----------------------------------------------------------------------
# lxd_cluster_group with state absent on a group that is in use

GROUP = "/1.0/cluster/groups/rack1"


@pytest.mark.parametrize("check_mode", [False, True])
def test_cluster_group_in_use_is_not_emptied(cluster, run, check_mode):
    used_by = ["/1.0/projects/web", "/1.0/instances/c1"]
    cluster.add(GROUP, {"name": "rack1", "description": "one", "members": ["n1", "n2"], "used_by": used_by})
    result = run(lxd_cluster_group, {"name": "rack1", "state": "absent"}, check_mode=check_mode)
    assert result.get("failed") is True, result
    assert "is in use" in result["msg"]
    assert "/1.0/instances/c1, /1.0/projects/web" in result["msg"]
    # The module changed nothing: the group still has its members.
    assert cluster.writes() == []
    assert cluster.get(GROUP)["members"] == ["n1", "n2"]


def test_cluster_group_with_members_only_is_emptied_and_deleted(cluster, run):
    # LXD 6.10.1 answers "Only empty cluster groups can be removed" for a group with members, so the module still empties it first.
    cluster.add(GROUP, {"name": "rack1", "description": "one", "members": ["n1"], "used_by": []})
    result = run(lxd_cluster_group, {"name": "rack1", "state": "absent"})
    assert result["changed"] is True, result
    assert [r[0] for r in cluster.writes()] == ["PUT", "DELETE"]
    assert cluster.get(GROUP) is None


# ----------------------------------------------------------------------
# a boolean value in join_config of lxd_cluster


def test_cluster_join_config_sends_booleans_as_lxd_strings(lxd, run, monkeypatch):
    lxd.add("/1.0/cluster", {"server_name": "", "enabled": False, "member_config": []})
    monkeypatch.setattr(lxd_cluster, "fetch_certificate", lambda address, fingerprint, timeout: "PEM")
    token = base64.b64encode(json.dumps({"server_name": "n2", "fingerprint": "ab" * 32, "addresses": ["192.0.2.1:8443"], "secret": "s"}).encode()).decode()
    join_config = [
        {"entity": "storage-pool", "name": "tank", "key": "zfs.export", "value": False},
        {"entity": "storage-pool", "name": "tank", "key": "zfs.clone_copy", "value": True},
        {"entity": "storage-pool", "name": "tank", "key": "size", "value": 0},
        {"entity": "storage-pool", "name": "tank", "key": "source", "value": "/dev/sdb"},
        {"entity": "network", "name": "br0", "key": "bridge.external_interfaces", "value": None},
    ]
    args = {
        # The unix socket has no certificate, so the module reads the result on the same connection.
        "url": "unix:/run/lxd-test.socket",
        "state": "joined",
        "server_name": "n2",
        "server_address": "192.0.2.2:8443",
        "cluster_token": token,
        "join_config": join_config,
    }
    result = run(lxd_cluster, args)
    assert result["changed"] is True, result
    body = [r for r in lxd.requests if r[0] == "PUT"][0][2]
    assert [item["value"] for item in body["member_config"]] == ["false", "true", "0", "/dev/sdb", ""]
    assert body["member_config"][0] == {"entity": "storage-pool", "name": "tank", "key": "zfs.export", "value": "false"}


# ----------------------------------------------------------------------
# lxd_instance_info with name and all_projects


@pytest.fixture
def two_projects(lxd):
    lxd.add("/1.0/projects/dev", {"name": "dev", "description": "", "config": {}, "used_by": []})
    lxd.add("/1.0/instances/web", {"name": "web", "type": "container", "status": "Running", "config": {}})
    lxd.add("/1.0/instances/web", {"name": "web", "type": "container", "status": "Stopped", "config": {}}, project="dev")
    # The filter of LXD ignores the case of the value, so the module also compares the name itself.
    lxd.add("/1.0/instances/WEB", {"name": "WEB", "type": "container", "status": "Stopped", "config": {}}, project="dev")
    lxd.add("/1.0/instances/db", {"name": "db", "type": "container", "status": "Stopped", "config": {}}, project="dev")
    return lxd


def test_instance_info_name_in_all_projects(two_projects, run):
    result = run(lxd_instance_info, {"name": "web", "all_projects": True, "include_state": False})
    assert sorted((item["name"], item["project"], item["status"]) for item in result["instances"]) == [
        ("web", "default", "Running"),
        ("web", "dev", "Stopped"),
    ]
    # LXD has no request for one instance in all projects (HTTP 400), so the module reads the list with a filter.
    gets = [r[1] for r in two_projects.requests if "/1.0/instances" in r[1]]
    assert len(gets) == 1 and "all-projects=true" in gets[0] and "filter=name+eq+web" in gets[0], gets

    result = run(lxd_instance_info, {"name": "db", "all_projects": True})
    assert [(item["name"], item["project"]) for item in result["instances"]] == [("db", "dev")]
    assert run(lxd_instance_info, {"name": "no-such", "all_projects": True})["instances"] == []


def test_instance_info_name_in_one_project_is_unchanged(two_projects, run):
    result = run(lxd_instance_info, {"name": "web", "include_state": False})
    assert [(item["name"], item["project"], item["status"]) for item in result["instances"]] == [("web", "default", "Running")]
    result = run(lxd_instance_info, {"name": "web", "project": "dev", "include_state": False})
    assert [(item["name"], item["project"], item["status"]) for item in result["instances"]] == [("web", "dev", "Stopped")]
