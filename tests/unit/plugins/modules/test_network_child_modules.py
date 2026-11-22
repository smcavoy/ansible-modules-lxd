# Copyright (c) 2026, Sean McAvoy
# GNU General Public License v3.0+ (see LICENSES/GPL-3.0-or-later.txt or https://www.gnu.org/licenses/gpl-3.0.txt)
# SPDX-License-Identifier: GPL-3.0-or-later

"""The modules for objects under a network, a network zone, or a storage bucket, against the in-memory LXD server.

lxd_network_peer, lxd_network_zone_record, lxd_network_load_balancer_pool, and lxd_storage_bucket_key run through main().
The tests check the bodies that the server got, the values of the result, and the rules of each module.
"""

from __future__ import annotations

import json

import pytest

from ansible_collections.smcavoy.lxd.plugins.modules import (
    lxd_network_load_balancer_pool,
    lxd_network_peer,
    lxd_network_zone_record,
    lxd_storage_bucket_key,
)


@pytest.fixture(params=[False, True], ids=["sync", "async"])
def server(request, lxd):
    lxd.async_writes = request.param
    return lxd


# ----------------------------------------------------------------------
# lxd_network_peer

PEERS = "/1.0/networks/ovn1/peers"
PEER = PEERS + "/to-ovn2"


@pytest.fixture
def ovn(server):
    """A project with an OVN network. Every request of the module must name the project."""
    server.add("/1.0/projects/web", {"name": "web", "description": "", "config": {}})
    server.add("/1.0/networks/ovn1", {"name": "ovn1", "type": "ovn", "managed": True, "config": {}, "description": ""}, "web")
    return server


def test_network_peer_life_cycle(ovn, run):
    ident = {"network": "ovn1", "name": "to-ovn2", "project": "web"}
    args = dict(ident, target_network="ovn2", target_project="other", description="one", config={"user.a": 1})
    body = {"name": "to-ovn2", "target_network": "ovn2", "description": "one", "config": {"user.a": "1"}, "target_project": "other"}

    result = run(lxd_network_peer, args, check_mode=True)
    assert result["changed"] is True, result
    assert result["peer"] == dict(body, status="Pending", used_by=[])
    assert ovn.writes() == []

    result = run(lxd_network_peer, args, diff=True)
    assert result["changed"] is True, result
    assert ovn.writes() == [("POST", PEERS + "?project=web", body)]
    assert result["peer"] == ovn.get(PEER, "web")
    assert result["peer"]["status"] == "Pending"
    assert result["diff"] == {"before": {}, "after": {"description": "one", "config": {"user.a": "1"}}}
    # The peer is in the project of the task.
    assert ovn.get(PEER) is None

    del ovn.requests[:]
    result = run(lxd_network_peer, args)
    assert result["changed"] is False, result
    assert ovn.writes() == []
    assert all("project=web" in request[1] for request in ovn.requests if "/networks/" in request[1])

    # An update sends the description and the whole config. LXD keeps the target.
    update = dict(ident, description="two", config={"user.b": "2"}, config_mode="exact")
    result = run(lxd_network_peer, update, check_mode=True)
    assert result["changed"] is True and ovn.writes() == []

    result = run(lxd_network_peer, update, diff=True)
    assert result["changed"] is True, result
    assert ovn.writes() == [("PUT", PEER + "?project=web", {"description": "two", "config": {"user.b": "2"}})]
    assert result["peer"]["target_network"] == "ovn2"
    assert result["diff"]["before"] == {"description": "one", "config": {"user.a": "1"}}
    assert result["diff"]["after"] == {"description": "two", "config": {"user.b": "2"}}

    # The target applies only on create: another one is a warning, not a change.
    del ovn.requests[:]
    result = run(lxd_network_peer, dict(update, target_network="ovn3"))
    assert result["changed"] is False, result
    assert any("target_network applies only on create" in str(w) for w in result["warnings"]), result
    assert ovn.writes() == [] and ovn.get(PEER, "web")["target_network"] == "ovn2"

    absent = dict(ident, state="absent")
    result = run(lxd_network_peer, absent, check_mode=True)
    assert result["changed"] is True and ovn.writes() == []

    result = run(lxd_network_peer, absent)
    assert result["changed"] is True, result
    assert ovn.writes() == [("DELETE", PEER + "?project=web", None)]
    assert result["peer"] is None and ovn.get(PEER, "web") is None

    del ovn.requests[:]
    result = run(lxd_network_peer, absent)
    assert result["changed"] is False, result
    assert ovn.writes() == []


def test_network_peer_create_without_a_target_project_sends_none(ovn, run):
    result = run(lxd_network_peer, {"network": "ovn1", "name": "to-ovn2", "project": "web", "target_network": "ovn2"})
    assert result["changed"] is True, result
    assert ovn.writes()[0][2] == {"name": "to-ovn2", "target_network": "ovn2", "description": "", "config": {}}


@pytest.mark.parametrize(
    ("args", "text"),
    [
        ({}, "target_network is required to create peer to-ovn2"),
        ({"target_network": "ovn2", "config": {"ipv4.x": "1"}}, "config key ipv4.x is not a user.* key"),
    ],
    ids=["no-target", "not-a-user-key"],
)
def test_network_peer_refusals(ovn, run, args, text):
    result = run(lxd_network_peer, dict(args, network="ovn1", name="to-ovn2", project="web"))
    assert result["failed"] is True
    assert result["msg"] == text
    assert ovn.writes() == []


def test_network_peer_on_a_missing_network_fails(lxd, run):
    result = run(lxd_network_peer, {"network": "gone", "name": "to-ovn2", "target_network": "ovn2"})
    assert result["failed"] is True
    assert lxd.get("/1.0/networks/gone/peers/to-ovn2") is None


# ----------------------------------------------------------------------
# lxd_network_zone_record

ZONE = "/1.0/network-zones/example.org"
RECORDS = ZONE + "/records"
RECORD = RECORDS + "/www"
A1 = {"type": "A", "value": "192.0.2.1", "ttl": 0}
A2 = {"type": "A", "value": "192.0.2.2", "ttl": 0}
AAAA = {"type": "AAAA", "value": "2001:db8::1", "ttl": 300}


@pytest.fixture
def zone(server):
    server.add(ZONE, {"name": "example.org", "description": "", "config": {}})
    return server


def test_zone_record_life_cycle(zone, run):
    ident = {"zone": "example.org", "name": "www"}
    # The task gives the types in lower case, no TTL, and another order than LXD stores.
    args = dict(ident, description="one", entries=[{"type": "aaaa", "value": "2001:db8::1", "ttl": 300}, {"type": "a", "value": "192.0.2.1"}])
    body = {"name": "www", "description": "one", "entries": [A1, AAAA], "config": {}}

    result = run(lxd_network_zone_record, args, check_mode=True)
    assert result["changed"] is True, result
    assert result["record"] == body
    assert zone.writes() == []

    result = run(lxd_network_zone_record, args, diff=True)
    assert result["changed"] is True, result
    assert zone.writes() == [("POST", RECORDS, body)]
    assert result["record"]["entries"] == [A1, AAAA]
    assert result["diff"] == {"before": {}, "after": {"description": "one", "entries": [A1, AAAA], "config": {}}}

    # LXD returns the entries in its own order. That is no change.
    zone.get(RECORD)["entries"] = [AAAA, A1]
    del zone.requests[:]
    result = run(lxd_network_zone_record, args)
    assert result["changed"] is False, result
    assert zone.writes() == []

    # Without entries the task does not manage them: only the description changes, and the PUT keeps the entries.
    result = run(lxd_network_zone_record, dict(ident, description="two", config={"user.team": "a"}))
    assert result["changed"] is True, result
    assert zone.writes() == [("PUT", RECORD, {"description": "two", "entries": [A1, AAAA], "config": {"user.team": "a"}})]

    del zone.requests[:]
    update = dict(ident, entries=[{"type": "A", "value": "192.0.2.2"}, {"type": "A", "value": "192.0.2.1"}])
    result = run(lxd_network_zone_record, update, check_mode=True, diff=True)
    assert result["changed"] is True and zone.writes() == []
    assert result["diff"]["before"]["entries"] == [A1, AAAA]
    assert result["diff"]["after"]["entries"] == [A1, A2]

    result = run(lxd_network_zone_record, update)
    assert result["changed"] is True, result
    assert zone.writes() == [("PUT", RECORD, {"description": "two", "entries": [A1, A2], "config": {"user.team": "a"}})]
    assert result["record"]["entries"] == [A1, A2]

    # An empty list removes every entry.
    del zone.requests[:]
    result = run(lxd_network_zone_record, dict(ident, entries=[]))
    assert result["changed"] is True, result
    assert zone.writes()[0][2]["entries"] == []
    assert zone.get(RECORD)["entries"] == []

    del zone.requests[:]
    absent = dict(ident, state="absent")
    result = run(lxd_network_zone_record, absent, check_mode=True)
    assert result["changed"] is True and zone.writes() == []

    result = run(lxd_network_zone_record, absent)
    assert result["changed"] is True, result
    assert zone.writes() == [("DELETE", RECORD, None)]
    assert result["record"] is None and zone.get(RECORD) is None

    del zone.requests[:]
    result = run(lxd_network_zone_record, absent)
    assert result["changed"] is False, result
    assert zone.writes() == []


def test_zone_record_in_a_zone_that_does_not_exist(lxd, run):
    result = run(lxd_network_zone_record, {"zone": "example.org", "name": "www", "entries": [A1]})
    assert result["failed"] is True
    assert result["msg"] == "network zone example.org not found"
    assert lxd.writes() == []

    # Absent in a missing zone is no error: the record does not exist.
    result = run(lxd_network_zone_record, {"zone": "example.org", "name": "www", "state": "absent"})
    assert result["changed"] is False, result


def test_zone_record_in_a_project(lxd, run):
    lxd.add("/1.0/projects/web", {"name": "web", "description": "", "config": {}})
    lxd.add(ZONE, {"name": "example.org", "description": "", "config": {}}, "web")
    result = run(lxd_network_zone_record, {"zone": "example.org", "name": "www", "project": "web", "entries": [A1]})
    assert result["changed"] is True, result
    assert lxd.writes()[0][:2] == ("POST", RECORDS + "?project=web")
    assert lxd.get(RECORD, "web")["entries"] == [A1]
    assert lxd.get(RECORD) is None


# ----------------------------------------------------------------------
# lxd_network_load_balancer_pool

LB_POOLS = "/1.0/networks/ovn1/load-balancer-pools"
LB_POOL = LB_POOLS + "/web"
BACKEND_A = {"name": "a", "target_port": ""}
BACKEND_B = {"name": "b", "target_port": "8080"}
BACKEND_C = {"name": "c", "target_port": ""}


@pytest.fixture
def network(server):
    server.add("/1.0/networks/ovn1", {"name": "ovn1", "type": "ovn", "managed": True, "config": {}, "description": ""})
    return server


def test_load_balancer_pool_life_cycle(network, run):
    ident = {"network": "ovn1", "name": "web"}
    args = dict(ident, description="one", config={"target_port": 80}, instances=[{"name": "b", "target_port": "8080"}, {"name": "a"}])
    body = {"name": "web", "description": "one", "config": {"target_port": "80"}, "instances": [BACKEND_A, BACKEND_B]}

    result = run(lxd_network_load_balancer_pool, args, check_mode=True)
    assert result["changed"] is True, result
    assert result["load_balancer_pool"] == dict(body, used_by=[])
    assert network.writes() == []

    result = run(lxd_network_load_balancer_pool, args, diff=True)
    assert result["changed"] is True, result
    # The instances go to LXD sorted by name, and the port as text.
    assert network.writes() == [("POST", LB_POOLS, body)]
    assert result["diff"] == {"before": {}, "after": {"description": "one", "config": {"target_port": "80"}, "instances": [BACKEND_A, BACKEND_B]}}
    assert "state" not in result["load_balancer_pool"]

    # Another order of the instances on the server is no change. The result has the state when LXD gives one.
    network.get(LB_POOL)["instances"] = [BACKEND_B, BACKEND_A]
    network.add(LB_POOL + "/state", {"instances": {"a": {"status": "online"}}})
    del network.requests[:]
    result = run(lxd_network_load_balancer_pool, args)
    assert result["changed"] is False, result
    assert network.writes() == []
    assert result["load_balancer_pool"]["state"] == {"instances": {"a": {"status": "online"}}}

    # Without instances the task does not manage them.
    result = run(lxd_network_load_balancer_pool, dict(ident, description="two"))
    assert result["changed"] is True, result
    assert network.writes() == [("PUT", LB_POOL, {"description": "two", "config": {"target_port": "80"}, "instances": [BACKEND_A, BACKEND_B]})]

    del network.requests[:]
    update = dict(ident, instances=[{"name": "c"}, {"name": "a"}])
    result = run(lxd_network_load_balancer_pool, update, check_mode=True, diff=True)
    assert result["changed"] is True and network.writes() == []
    assert result["diff"]["before"]["instances"] == [BACKEND_A, BACKEND_B]
    assert result["diff"]["after"]["instances"] == [BACKEND_A, BACKEND_C]

    result = run(lxd_network_load_balancer_pool, update)
    assert result["changed"] is True, result
    assert network.writes() == [("PUT", LB_POOL, {"description": "two", "config": {"target_port": "80"}, "instances": [BACKEND_A, BACKEND_C]})]
    assert result["load_balancer_pool"]["instances"] == [BACKEND_A, BACKEND_C]

    del network.requests[:]
    result = run(lxd_network_load_balancer_pool, dict(ident, instances=[]))
    assert result["changed"] is True, result
    assert network.writes()[0][2]["instances"] == []

    del network.requests[:]
    absent = dict(ident, state="absent")
    result = run(lxd_network_load_balancer_pool, absent, check_mode=True)
    assert result["changed"] is True and network.writes() == []

    result = run(lxd_network_load_balancer_pool, absent)
    assert result["changed"] is True, result
    assert network.writes() == [("DELETE", LB_POOL, None)]
    assert result["load_balancer_pool"] is None and network.get(LB_POOL) is None

    del network.requests[:]
    result = run(lxd_network_load_balancer_pool, absent)
    assert result["changed"] is False, result
    assert network.writes() == []


@pytest.mark.parametrize("config", [None, {"user.team": "a"}, {"target_port": ""}], ids=["no-config", "other-key", "empty-port"])
def test_load_balancer_pool_needs_a_target_port_on_create(network, run, config):
    result = run(lxd_network_load_balancer_pool, {"network": "ovn1", "name": "web", "config": config})
    assert result["failed"] is True
    assert result["msg"] == "config.target_port is required on create"
    assert network.writes() == []


def test_load_balancer_pool_on_a_missing_network_fails(lxd, run):
    result = run(lxd_network_load_balancer_pool, {"network": "gone", "name": "web", "config": {"target_port": "80"}})
    assert result["failed"] is True
    assert lxd.get("/1.0/networks/gone/load-balancer-pools/web") is None


# ----------------------------------------------------------------------
# lxd_storage_bucket_key

BUCKET = "/1.0/storage-pools/p1/buckets/b1"
KEYS = BUCKET + "/keys"
KEY = KEYS + "/k1"
MASK = "********"


@pytest.fixture
def bucket(server):
    server.add("/1.0/storage-pools/p1", {"name": "p1", "driver": "ceph", "config": {}, "description": ""})
    server.add(BUCKET, {"name": "b1", "config": {}, "description": ""})
    return server


def test_bucket_key_that_lxd_generates(bucket, run):
    ident = {"pool": "p1", "bucket": "b1", "name": "k1"}
    args = dict(ident, description="one")

    result = run(lxd_storage_bucket_key, args, check_mode=True)
    assert result["changed"] is True, result
    assert result["key"] == {"name": "k1", "description": "one", "role": "read-only"}
    assert bucket.writes() == []

    result = run(lxd_storage_bucket_key, args, diff=True)
    assert result["changed"] is True, result
    assert bucket.writes() == [("POST", KEYS, {"name": "k1", "description": "one", "role": "read-only"})]
    # The run that creates the key returns the keys that LXD made. The key object never shows the secret.
    assert result["access_key"] == "generated-access-k1"
    assert result["secret_key"] == "generated-secret-k1"
    assert result["key"]["secret-key"] == MASK
    assert result["key"]["access-key"] == "generated-access-k1"
    assert result["diff"]["after"] == {"description": "one", "role": "read-only", "access_key": "generated-access-k1"}

    # A later run does not show the secret anywhere.
    del bucket.requests[:]
    result = run(lxd_storage_bucket_key, args)
    assert result["changed"] is False, result
    assert bucket.writes() == []
    assert result["access_key"] == "generated-access-k1"
    assert "secret_key" not in result and "generated-secret-k1" not in json.dumps(result)

    # A change of the role sends the whole key, with the secret that the server has, and returns no secret.
    update = dict(ident, role="admin")
    result = run(lxd_storage_bucket_key, update, check_mode=True)
    assert result["changed"] is True and bucket.writes() == []
    assert "generated-secret-k1" not in json.dumps(result)

    result = run(lxd_storage_bucket_key, update, diff=True)
    assert result["changed"] is True, result
    put = {"description": "one", "role": "admin", "access-key": "generated-access-k1", "secret-key": "generated-secret-k1"}
    assert bucket.writes() == [("PUT", KEY, put)]
    assert result["diff"]["before"]["role"] == "read-only" and result["diff"]["after"]["role"] == "admin"
    assert "secret_key" not in result and "generated-secret-k1" not in json.dumps(result)

    del bucket.requests[:]
    absent = dict(ident, state="absent")
    result = run(lxd_storage_bucket_key, absent, check_mode=True)
    assert result["changed"] is True and bucket.writes() == []

    result = run(lxd_storage_bucket_key, absent)
    assert result["changed"] is True, result
    assert bucket.writes() == [("DELETE", KEY, None)]
    assert result["key"] is None and bucket.get(KEY) is None

    del bucket.requests[:]
    result = run(lxd_storage_bucket_key, absent)
    assert result["changed"] is False, result
    assert bucket.writes() == []


def shown(result):
    """Return the parts of the result in which the module itself must hide the secret: key, diff and messages.

    The return value ``secret_key`` and the task arguments in ``invocation`` hold the secret of the task by design. Ansible
    masks them: in the module up to ansible-core 2.21, on the controller from 2.22 (the module names the value in
    ``_ansible_new_secrets``). So they are left out here.
    """
    hidden = ("invocation", "secret_key")
    return json.dumps({key: value for key, value in result.items() if key not in hidden and not key.startswith("_ansible_")})


def test_bucket_key_with_keys_of_the_task(bucket, run):
    ident = {"pool": "p1", "bucket": "b1", "name": "k1"}
    args = dict(ident, role="admin", access_key="AKIA-mine", secret_key="my-0wn-s3cret")

    result = run(lxd_storage_bucket_key, args, check_mode=True)
    assert result["changed"] is True, result
    assert result["key"]["secret-key"] == MASK
    assert "my-0wn-s3cret" not in shown(result)

    result = run(lxd_storage_bucket_key, args)
    assert result["changed"] is True, result
    assert bucket.writes() == [("POST", KEYS, {"name": "k1", "description": "", "role": "admin", "access-key": "AKIA-mine", "secret-key": "my-0wn-s3cret"})]
    assert result["access_key"] == "AKIA-mine"
    # The secret of the task is known to the caller. The result does not repeat it.
    assert "my-0wn-s3cret" not in shown(result)

    del bucket.requests[:]
    result = run(lxd_storage_bucket_key, args)
    assert result["changed"] is False, result
    assert bucket.writes() == []

    # Another secret is a change that the diff names without the value.
    new = dict(args, secret_key="an0ther-s3cret")
    result = run(lxd_storage_bucket_key, new, check_mode=True, diff=True)
    assert result["changed"] is True and bucket.writes() == []
    assert result["diff"]["after"]["secret_key"] == "changed"

    result = run(lxd_storage_bucket_key, new, diff=True)
    assert result["changed"] is True, result
    assert bucket.writes() == [("PUT", KEY, {"description": "", "role": "admin", "access-key": "AKIA-mine", "secret-key": "an0ther-s3cret"})]
    assert result["diff"]["after"]["secret_key"] == "changed"
    assert "an0ther-s3cret" not in shown(result) and "my-0wn-s3cret" not in shown(result)


def test_bucket_key_in_a_bucket_that_does_not_exist(lxd, run):
    lxd.add("/1.0/storage-pools/p1", {"name": "p1", "driver": "ceph", "config": {}, "description": ""})
    result = run(lxd_storage_bucket_key, {"pool": "p1", "bucket": "b1", "name": "k1"})
    assert result["failed"] is True
    assert result["msg"] == "bucket b1 not found in pool p1"
    assert lxd.writes() == []
