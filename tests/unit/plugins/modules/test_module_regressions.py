# Copyright (c) 2026, Sean McAvoy
# GNU General Public License v3.0+ (see LICENSES/GPL-3.0-or-later.txt or https://www.gnu.org/licenses/gpl-3.0.txt)
# SPDX-License-Identifier: GPL-3.0-or-later

"""Regression tests for defects that were fixed in several modules.

Each test fails on the code before the fix. The in-memory LXD server models what LXD 6.10.1 does, as seen on a live server.
"""

from __future__ import annotations

import hashlib
import json

import pytest

from ansible_collections.smcavoy.lxd.plugins.modules import (
    lxd_auth_group,
    lxd_auth_identity_token,
    lxd_image,
    lxd_instance_device,
    lxd_instance_exec,
    lxd_instance_file,
    lxd_instance_rebuild,
    lxd_instance_snapshot,
    lxd_network,
    lxd_network_acl,
    lxd_network_forward,
    lxd_network_info,
    lxd_network_load_balancer,
    lxd_storage_pool,
    lxd_storage_pool_info,
    lxd_storage_volume_info,
    lxd_storage_volume_snapshot,
)

NEVER = "0001-01-01T00:00:00Z"
MASK = "********"


# ----------------------------------------------------------------------
# A member-specific key of a network or a pool on a cluster (high)


@pytest.fixture
def cluster(lxd):
    lxd.server_info["environment"]["server_clustered"] = True
    lxd.local_keys = {"network-bridge": {"bgp.ipv4.nexthop"}, "storage-btrfs": {"size", "source"}}
    for name in ("n1", "n2"):
        lxd.add(f"/1.0/cluster/members/{name}", {"server_name": name, "status": "Online", "roles": [], "groups": ["default"], "config": {}})
    return lxd


def test_network_member_key_change_keeps_the_global_config(cluster, run):
    path = "/1.0/networks/br0"
    config = {"ipv4.address": "10.124.0.1/24", "ipv4.nat": "true", "ipv6.address": "none"}
    cluster.add(path, {"name": "br0", "type": "bridge", "managed": True, "status": "Created", "description": "lan", "config": dict(config)})
    cluster.member_config[cluster.key(path, None)] = {"n1": {"bgp.ipv4.nexthop": "192.0.2.21"}, "n2": {"bgp.ipv4.nexthop": "192.0.2.21"}}

    args = {"name": "br0", "member_config": {"n2": {"bgp.ipv4.nexthop": "192.0.2.22"}}}
    result = run(lxd_network, args)
    assert result["changed"] is True, result
    # LXD replaces the whole config on a PUT with a target. The global keys must be in the body.
    assert cluster.get(path)["config"] == config
    assert cluster.get(path)["description"] == "lan"
    assert cluster.member_config[cluster.key(path, None)] == {"n1": {"bgp.ipv4.nexthop": "192.0.2.21"}, "n2": {"bgp.ipv4.nexthop": "192.0.2.22"}}
    assert result["network"]["config"] == config

    del cluster.requests[:]
    assert run(lxd_network, args)["changed"] is False
    assert cluster.writes() == []


def test_network_global_and_member_change_in_one_task(cluster, run):
    path = "/1.0/networks/br0"
    cluster.add(path, {"name": "br0", "type": "bridge", "managed": True, "status": "Created", "description": "", "config": {"ipv4.nat": "true"}})
    args = {"name": "br0", "description": "new", "config": {"ipv4.nat": "false"}, "member_config": {"n1": {"bgp.ipv4.nexthop": "192.0.2.9"}}}
    result = run(lxd_network, args)
    assert result["changed"] is True, result
    assert cluster.get(path)["config"] == {"ipv4.nat": "false"}
    assert cluster.get(path)["description"] == "new"
    assert cluster.member_config[cluster.key(path, None)]["n1"] == {"bgp.ipv4.nexthop": "192.0.2.9"}
    assert run(lxd_network, args)["changed"] is False


def test_storage_pool_member_key_change_keeps_the_global_config(cluster, run):
    path = "/1.0/storage-pools/p1"
    cluster.add(path, {"name": "p1", "driver": "btrfs", "status": "Created", "description": "", "config": {"rsync.bwlimit": "10MB"}})
    members = {name: {"size": "1GiB", "source": f"/var/snap/lxd/common/lxd/disks/p1-{name}.img"} for name in ("n1", "n2")}
    cluster.member_config[cluster.key(path, None)] = json.loads(json.dumps(members))

    args = {"name": "p1", "member_config": {"n1": {"size": "2GiB"}}}
    result = run(lxd_storage_pool, args)
    assert result["changed"] is True, result
    assert cluster.get(path)["config"] == {"rsync.bwlimit": "10MB"}
    assert cluster.member_config[cluster.key(path, None)]["n1"] == dict(members["n1"], size="2GiB")
    assert cluster.member_config[cluster.key(path, None)]["n2"] == members["n2"]

    del cluster.requests[:]
    assert run(lxd_storage_pool, args)["changed"] is False
    assert cluster.writes() == []


# ----------------------------------------------------------------------
# lxd_instance_file: directories, links and modes


@pytest.fixture
def web(lxd):
    lxd.add("/1.0/instances/web", {"name": "web", "type": "container", "status": "Running", "config": {}, "devices": {}, "profiles": ["default"]})
    return lxd


def test_directory_that_exists_with_another_owner_fails(web, run):
    key = ("default", "web", "/srv/www")
    web.files[key] = {"type": "directory", "uid": 0, "gid": 0, "mode": "0755", "content": b""}
    del web.requests[:]
    args = {"instance": "web", "path": "/srv/www", "type": "directory", "owner_uid": 1000, "mode": "0750"}
    for check_mode in (True, False):
        result = run(lxd_instance_file, args, check_mode=check_mode)
        # Before: changed on every run, and LXD changed nothing.
        assert result.get("failed") is True, result
        assert "LXD cannot change the owner or the mode of a directory that exists" in result["msg"]
    assert web.writes() == []
    assert run(lxd_instance_file, {"instance": "web", "path": "/srv/www", "type": "directory"})["changed"] is False
    assert run(lxd_instance_file, {"instance": "web", "path": "/srv/www", "type": "directory", "mode": "0755", "owner_uid": 0})["changed"] is False


def test_new_directory_gets_owner_and_mode(web, run):
    args = {"instance": "web", "path": "/srv/new", "type": "directory", "owner_uid": 1000, "mode": "0750"}
    assert run(lxd_instance_file, args)["changed"] is True
    stored = web.files[("default", "web", "/srv/new")]
    assert (stored["type"], stored["uid"], stored["mode"]) == ("directory", 1000, "0750")
    assert run(lxd_instance_file, args)["changed"] is False


def test_relative_link_target_is_idempotent(web, run):
    args = {"instance": "web", "path": "/etc/runlevels/default/local", "type": "link", "link_target": "../../init.d/local", "owner_uid": 1000}
    result = run(lxd_instance_file, args)
    assert result["changed"] is True, result
    assert web.files[("default", "web", "/etc/runlevels/default/local")]["content"] == b"../../init.d/local"
    del web.requests[:]
    # LXD returns /etc/init.d/local for this link, and does not set the owner of a link.
    assert run(lxd_instance_file, args)["changed"] is False
    assert web.writes() == []


def test_new_link_target_replaces_the_link(web, run):
    key = ("default", "web", "/srv/current")
    web.files[key] = {"type": "symlink", "uid": 0, "gid": 0, "mode": "0777", "content": b"/srv/v1"}
    del web.requests[:]
    args = {"instance": "web", "path": "/srv/current", "type": "link", "link_target": "/srv/v2"}
    assert run(lxd_instance_file, args, check_mode=True)["changed"] is True
    assert web.writes() == []
    result = run(lxd_instance_file, args)
    # Before: LXD answered "file exists", and the task failed.
    assert result.get("failed") is not True, result
    assert result["changed"] is True
    assert [request[0] for request in web.writes()] == ["DELETE", "POST"]
    assert web.files[key]["content"] == b"/srv/v2"
    assert run(lxd_instance_file, args)["changed"] is False


@pytest.mark.parametrize("mode", ["1777", "4755", "rwx", "77777"])
def test_mode_with_special_bits_or_bad_text_fails(web, run, mode):
    del web.requests[:]
    result = run(lxd_instance_file, {"instance": "web", "path": "/srv/tmp", "type": "directory", "mode": mode})
    assert result.get("failed") is True, result
    assert "is not valid" in result["msg"]
    assert web.writes() == []


# ----------------------------------------------------------------------
# lxd_instance_exec, lxd_instance_rebuild, lxd_instance_device


def test_exec_removes_on_a_missing_instance_fails(web, run):
    result = run(lxd_instance_exec, {"instance": "wbe", "command": ["true"], "removes": "/tmp/flag"})
    # Before: ok with a skip reason, as if the path did not exist.
    assert result.get("failed") is True, result
    assert "instance wbe not found" in result["msg"]
    result = run(lxd_instance_exec, {"instance": "web", "command": ["true"], "removes": "/tmp/flag"})
    assert result.get("failed") is not True, result
    assert result["changed"] is False


@pytest.mark.parametrize("status", ["Running", "Frozen", "Ready"])
def test_forced_rebuild_stops_an_instance_in_each_run_status(web, run, status):
    web.get("/1.0/instances/web")["status"] = status
    result = run(lxd_instance_rebuild, {"instance": "web", "source": {"empty": True}})
    assert result.get("failed") is True, result
    assert "Set force" in result["msg"]
    result = run(lxd_instance_rebuild, {"instance": "web", "source": {"empty": True}, "force": True})
    # Before: a frozen instance was not stopped, and LXD answered "Instance must be stopped to be rebuilt".
    assert result.get("failed") is not True, result
    assert web.get("/1.0/instances/web")["rebuilt_from"] == {"type": "none"}
    assert web.get("/1.0/instances/web")["status"] == "Running"


@pytest.mark.parametrize("status", ["Running", "Frozen", "Ready"])
def test_device_change_restarts_an_instance_in_each_run_status(web, run, status):
    web.get("/1.0/instances/web")["status"] = status
    web.cold_only.add("web")
    args = {"instance": "web", "name": "data", "properties": {"type": "disk", "path": "/data", "source": "/srv/data"}}
    result = run(lxd_instance_device, args)
    assert result.get("failed") is True, result
    result = run(lxd_instance_device, dict(args, allow_restart=True))
    assert result.get("failed") is not True, result
    assert result["changed"] is True
    assert web.get("/1.0/instances/web")["devices"]["data"]["path"] == "/data"
    assert web.get("/1.0/instances/web")["status"] == "Running"


# ----------------------------------------------------------------------
# Secrets in results and diffs


def test_network_masks_the_bgp_password(lxd, run):
    config = {"ipv4.address": "10.1.0.1/24", "bgp.peers.r1.address": "10.1.0.9", "bgp.peers.r1.asn": "65001", "bgp.peers.r1.password": "s3cretpw"}
    result = run(lxd_network, {"name": "br0", "type": "bridge", "config": config}, diff=True)
    assert result["changed"] is True, result
    assert lxd.get("/1.0/networks/br0")["config"]["bgp.peers.r1.password"] == "s3cretpw"
    assert "s3cretpw" not in json.dumps(result)
    assert result["network"]["config"]["bgp.peers.r1.password"] == MASK
    assert result["diff"]["after"]["config"]["bgp.peers.r1.password"] == MASK
    assert result["network"]["config"]["bgp.peers.r1.asn"] == "65001"

    result = run(lxd_network, {"name": "br0", "config": {"bgp.peers.r1.password": "other-pw"}}, diff=True)
    assert result["changed"] is True, result
    assert lxd.get("/1.0/networks/br0")["config"]["bgp.peers.r1.password"] == "other-pw"
    assert "s3cretpw" not in json.dumps(result)
    assert "other-pw" not in json.dumps(result)

    lxd.get("/1.0/networks/br0")["managed"] = True
    result = run(lxd_network_info, {"name": "br0"})
    assert result["networks"][0]["config"]["bgp.peers.r1.password"] == MASK
    assert "other-pw" not in json.dumps(result)


def test_storage_pool_masks_the_driver_secrets(lxd, run):
    lxd.server_info["environment"]["storage_supported_drivers"] = [{"Name": "pure"}, {"Name": "powerflex"}]
    result = run(lxd_storage_pool, {"name": "p1", "driver": "pure", "config": {"pure.api.token": "tok-12345", "pure.gateway": "https://pure"}}, diff=True)
    assert result["changed"] is True, result
    assert lxd.get("/1.0/storage-pools/p1")["config"]["pure.api.token"] == "tok-12345"
    assert "tok-12345" not in json.dumps(result)
    assert result["storage_pool"]["config"] == {"pure.api.token": MASK, "pure.gateway": "https://pure"}
    assert result["diff"]["after"]["config"]["pure.api.token"] == MASK

    lxd.add("/1.0/storage-pools/p2", {"name": "p2", "driver": "powerflex", "config": {"powerflex.user.password": "pf-secret"}, "description": ""})
    result = run(lxd_storage_pool_info, {})
    assert "tok-12345" not in json.dumps(result)
    assert "pf-secret" not in json.dumps(result)
    assert {pool["name"] for pool in result["storage_pools"]} == {"p1", "p2"}


# ----------------------------------------------------------------------
# Values that LXD stores in another form


def test_acl_rule_with_spaces_in_its_lists_is_idempotent(lxd, run):
    # The form that LXD 6.10.1 stores for the task below (read from a live server).
    stored = {"action": "allow", "source": "10.0.0.1,10.0.0.2", "protocol": "tcp", "destination_port": "80,443", "state": "enabled"}
    lxd.add("/1.0/network-acls/web", {"name": "web", "description": "", "egress": [], "ingress": [stored], "config": {}})
    del lxd.requests[:]
    rule = {"action": "allow", "protocol": "tcp", "destination_port": "80, 443", "source": "10.0.0.1, 10.0.0.2"}
    result = run(lxd_network_acl, {"name": "web", "ingress": [rule]})
    assert result["changed"] is False, result
    assert lxd.writes() == []
    result = run(lxd_network_acl, {"name": "web2", "ingress": [rule]})
    assert result["changed"] is True, result
    assert lxd.get("/1.0/network-acls/web2")["ingress"][0]["destination_port"] == "80,443"
    assert lxd.get("/1.0/network-acls/web2")["ingress"][0]["source"] == "10.0.0.1,10.0.0.2"


def test_forward_values_take_the_form_that_lxd_stores(lxd, run):
    lxd.add("/1.0/networks/br0", {"name": "br0", "type": "bridge", "managed": True, "config": {}, "description": ""})
    stored = {"protocol": "tcp", "listen_port": "80,443", "target_address": "fd42::10", "target_port": "80,443", "description": ""}
    lxd.add("/1.0/networks/br0/forwards/2001:db8::1", {"listen_address": "2001:db8::1", "description": "", "config": {}, "ports": [stored]})
    del lxd.requests[:]
    port = {"protocol": "tcp", "listen_port": "80, 443", "target_address": "FD42::10"}
    result = run(lxd_network_forward, {"network": "br0", "listen_address": "2001:DB8::1", "ports": [port]})
    # Before: the module did not find the forward under the upper-case address, and the create failed on LXD.
    assert result.get("failed") is not True, result
    assert result["changed"] is False, result
    assert lxd.writes() == []


def test_load_balancer_values_take_the_form_that_lxd_stores(lxd, run):
    lxd.add("/1.0/networks/ovn0", {"name": "ovn0", "type": "ovn", "managed": True, "config": {}, "description": ""})
    backend = {"name": "b1", "target_address": "fd42::10", "target_port": "80,443", "description": ""}
    port = {"protocol": "tcp", "listen_port": "80,443", "target_backend": ["b1"], "description": ""}
    path = "/1.0/networks/ovn0/load-balancers/2001:db8::2"
    lxd.add(path, {"listen_address": "2001:db8::2", "description": "", "config": {}, "backends": [backend], "ports": [port]})
    del lxd.requests[:]
    args = {
        "network": "ovn0",
        "listen_address": "2001:DB8::2",
        "backends": [{"name": "b1", "target_address": "FD42::10", "target_port": "80, 443"}],
        "ports": [{"protocol": "tcp", "listen_port": "80, 443", "target_backend": ["b1"]}],
    }
    result = run(lxd_network_load_balancer, args)
    assert result.get("failed") is not True, result
    assert result["changed"] is False, result
    assert lxd.writes() == []


def test_auth_group_url_without_the_default_project_is_idempotent(lxd, run):
    # The form that LXD 6.10.1 returns for url: /1.0/instances/c1 (read from a live server).
    stored = [
        {"entity_type": "project", "url": "/1.0/projects/default", "entitlement": "can_view"},
        {"entity_type": "instance", "url": "/1.0/instances/c1?project=default", "entitlement": "can_view"},
        {"entity_type": "instance", "url": "/1.0/instances/c2?project=web", "entitlement": "can_view"},
    ]
    lxd.add("/1.0/auth/groups/ops", {"name": "ops", "description": "", "permissions": stored, "identities": {}})
    del lxd.requests[:]
    wanted = [
        {"entity_type": "project", "url": "/1.0/projects/default", "entitlement": "can_view"},
        {"entity_type": "instance", "url": "/1.0/instances/c1", "entitlement": "can_view"},
        {"entity_type": "instance", "url": "/1.0/instances/c2?project=web", "entitlement": "can_view"},
    ]
    for mode in ("exact", "merge"):
        result = run(lxd_auth_group, {"name": "ops", "permissions": wanted, "permissions_mode": mode})
        assert result["changed"] is False, (mode, result)
    assert lxd.writes() == []
    assert result["auth_group"]["permissions"] == stored
    # Another project is still a difference.
    other = [dict(wanted[1], url="/1.0/instances/c1?project=web")]
    assert run(lxd_auth_group, {"name": "ops", "permissions": other, "permissions_mode": "merge"}, check_mode=True)["changed"] is True


# ----------------------------------------------------------------------
# Expiry dates


def test_instance_snapshot_with_an_empty_expiry_sends_the_zero_time(web, run):
    web.get("/1.0/instances/web")["status"] = "Stopped"
    del web.requests[:]
    result = run(lxd_instance_snapshot, {"instance": "web", "name": "s1", "expires_at": ""})
    assert result["changed"] is True, result
    post = [request for request in web.writes() if request[0] == "POST"][-1][2]
    # Before: no expires_at in the body, so LXD used snapshots.expiry of the instance.
    assert post["expires_at"] == NEVER
    post_count = len(web.writes())
    run(lxd_instance_snapshot, {"instance": "web", "name": "s2"})
    assert "expires_at" not in web.writes()[post_count][2]


def test_volume_snapshot_with_an_empty_expiry_sends_the_zero_time(lxd, run):
    lxd.add("/1.0/storage-pools/p1", {"name": "p1", "driver": "dir", "config": {}, "description": ""})
    lxd.add("/1.0/storage-pools/p1/volumes/custom/v1", {"name": "v1", "type": "custom", "content_type": "filesystem", "config": {}, "description": ""})
    del lxd.requests[:]
    result = run(lxd_storage_volume_snapshot, {"pool": "p1", "volume": "v1", "name": "s1", "expires_at": ""})
    assert result["changed"] is True, result
    assert lxd.writes()[-1][2]["expires_at"] == NEVER
    run(lxd_storage_volume_snapshot, {"pool": "p1", "volume": "v1", "name": "s2"})
    assert "expires_at" not in lxd.writes()[-1][2]


def test_image_expiry_cannot_be_removed(lxd, run):
    fingerprint = hashlib.sha256(b"image").hexdigest()
    image = {"fingerprint": fingerprint, "aliases": [], "properties": {}, "public": False, "auto_update": False, "profiles": ["default"]}
    lxd.add(f"/1.0/images/{fingerprint}", dict(image, expires_at="2030-01-01T00:00:00Z"))
    del lxd.requests[:]
    result = run(lxd_image, {"fingerprint": fingerprint, "expires_at": ""})
    # Before: changed on every run, and LXD kept the date.
    assert result.get("failed") is True, result
    assert "LXD cannot remove the expiry date of an image" in result["msg"]
    assert lxd.writes() == []
    assert run(lxd_image, {"fingerprint": fingerprint, "expires_at": "2031-01-01T00:00:00Z"})["changed"] is True

    lxd.get(f"/1.0/images/{fingerprint}")["expires_at"] = NEVER
    assert run(lxd_image, {"fingerprint": fingerprint, "expires_at": ""})["changed"] is False


# ----------------------------------------------------------------------
# An expired bearer token, and the state of an image volume


def test_expired_bearer_token_gets_a_new_token(lxd, run):
    path = "/1.0/auth/identities/bearer/ci"
    lxd.add(path, {"authentication_method": "bearer", "type": "Client token bearer (pending)", "name": "ci", "groups": []})
    lxd.next_token_expires_at = "2020-01-01T00:00:00Z"
    result = run(lxd_auth_identity_token, {"name": "ci", "expiry": "1d"})
    assert result["changed"] is True, result
    assert result["token"] == "token-1"
    # Seen live on LXD 6.10.1: after the expiry time the identity keeps the type "Client token bearer".
    assert lxd.get(path)["type"] == "Client token bearer"

    del lxd.requests[:]
    assert run(lxd_auth_identity_token, {"name": "ci", "expiry": "1d"}, check_mode=True)["changed"] is True
    assert lxd.writes() == []
    lxd.next_token_expires_at = "2999-01-01T00:00:00Z"
    result = run(lxd_auth_identity_token, {"name": "ci", "expiry": "1d"})
    # Before: no change and no token, so the client stayed locked out until force.
    assert result["changed"] is True, result
    assert result["token"] == "token-2"

    del lxd.requests[:]
    result = run(lxd_auth_identity_token, {"name": "ci", "expiry": "1d"})
    assert result["changed"] is False, result
    assert "token" not in result
    assert lxd.writes() == []

    # A token without an expiry time never expires.
    lxd.get(path)["expires_at"] = NEVER
    assert run(lxd_auth_identity_token, {"name": "ci"})["changed"] is False
    assert run(lxd_auth_identity_token, {"name": "ci", "state": "absent"})["changed"] is True
    assert lxd.get(path)["type"] == "Client token bearer (pending)"
    assert run(lxd_auth_identity_token, {"name": "ci", "state": "absent"})["changed"] is False


def test_volume_info_with_state_skips_the_image_volumes(lxd, run):
    lxd.add("/1.0/storage-pools/p1", {"name": "p1", "driver": "btrfs", "config": {}, "description": ""})
    for kind, name in (("custom", "v1"), ("container", "c1"), ("image", "6abf10b731c2")):
        lxd.add(f"/1.0/storage-pools/p1/volumes/{kind}/{name}", {"name": name, "type": kind, "content_type": "filesystem", "config": {}})
    # The fake lists only direct children. Volumes sit two levels down, so the test gives the list as LXD does.
    volumes = [lxd.get(f"/1.0/storage-pools/p1/volumes/{kind}/{name}") for kind, name in (("custom", "v1"), ("container", "c1"), ("image", "6abf10b731c2"))]
    lxd.add("/1.0/storage-pools/p1/volumes", volumes)  # type: ignore[arg-type]
    result = run(lxd_storage_volume_info, {"pool": "p1", "include_state": True})
    # Before: the task failed with: Invalid storage volume type "image".
    assert result.get("failed") is not True, result
    states = {volume["name"]: volume["state"] for volume in result["storage_volumes"]}
    assert states == {"v1": {"usage": {"used": 4096, "total": 0}}, "c1": {"usage": {"used": 4096, "total": 0}}, "6abf10b731c2": None}
