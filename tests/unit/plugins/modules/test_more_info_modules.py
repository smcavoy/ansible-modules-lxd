# Copyright (c) 2026, Sean McAvoy
# GNU General Public License v3.0+ (see LICENSES/GPL-3.0-or-later.txt or https://www.gnu.org/licenses/gpl-3.0.txt)
# SPDX-License-Identifier: GPL-3.0-or-later

"""More info modules against the in-memory LXD server: the list, one object, a missing object, the filters, and the queries.

No info module sends a write: the fixture checks that after every test.
"""

from __future__ import annotations

import json

import pytest

from ansible_collections.smcavoy.lxd.plugins.modules import (
    lxd_auth_info,
    lxd_cluster_link_info,
    lxd_cluster_member_info,
    lxd_image_info,
    lxd_image_registry_info,
    lxd_instance_log_info,
    lxd_network_allocation_info,
    lxd_operation_info,
    lxd_replicator_info,
    lxd_warning_info,
)


@pytest.fixture
def ro(lxd):
    """The server with a second project. An info module must not write."""
    lxd.add("/1.0/projects/web", {"name": "web", "description": "", "config": {}})
    yield lxd
    assert lxd.writes() == []


def targets(lxd, prefix: str) -> list[str]:
    """Return the request targets under a path, in order."""
    return [target for _method, target, _body in lxd.requests if target.startswith(prefix)]


# ----------------------------------------------------------------------
# lxd_warning_info


@pytest.fixture
def warned(ro):
    for uuid, project, status, severity in (("w1", "", "new", "low"), ("w2", "web", "acknowledged", "high"), ("w3", "default", "resolved", "moderate")):
        ro.add(f"/1.0/warnings/{uuid}", {"uuid": uuid, "project": project, "status": status, "severity": severity, "type": "t", "count": 1})
    return ro


def uuids(result) -> list[str]:
    return [item["uuid"] for item in result["lxd_warnings"]]


def test_warning_info_lists_all_projects_by_default(warned, run):
    result = run(lxd_warning_info, {})
    assert result["changed"] is False
    assert uuids(result) == ["w1", "w2", "w3"]
    assert targets(warned, "/1.0/warnings") == ["/1.0/warnings?recursion=1"]
    assert result["lxd_warnings"][1] == warned.get("/1.0/warnings/w2")


@pytest.mark.parametrize(
    ("args", "target", "found"),
    [
        ({"project": "web"}, "/1.0/warnings?recursion=1&project=web", ["w2"]),
        # A project wins over the default of all_projects.
        ({"project": "web", "all_projects": True}, "/1.0/warnings?recursion=1&project=web", ["w2"]),
        ({"all_projects": False}, "/1.0/warnings?recursion=1&project=default", ["w3"]),
    ],
    ids=["project", "project-and-all", "default-project"],
)
def test_warning_info_of_one_project(warned, run, args, target, found):
    result = run(lxd_warning_info, args)
    assert uuids(result) == found
    assert targets(warned, "/1.0/warnings") == [target]


@pytest.mark.parametrize(
    ("args", "found"),
    [
        ({"status": ["new", "resolved"]}, ["w1", "w3"]),
        ({"severity": ["high"]}, ["w2"]),
        ({"status": ["new", "acknowledged"], "severity": ["low", "moderate"]}, ["w1"]),
        ({"uuid": "w2"}, ["w2"]),
        ({"uuid": "w2", "status": ["new"]}, []),
        ({"uuid": "w9"}, []),
    ],
)
def test_warning_info_filters(warned, run, args, found):
    assert uuids(run(lxd_warning_info, args)) == found


# ----------------------------------------------------------------------
# lxd_cluster_member_info


def test_cluster_member_info_on_a_standalone_server(ro, run):
    result = run(lxd_cluster_member_info, {"name": "node1", "include_state": True})
    assert result["changed"] is False
    assert result["clustered"] is False and result["members"] == []
    # The module asks a standalone server for no member.
    assert targets(ro, "/1.0/cluster") == []


def test_cluster_member_info(ro, run):
    ro.server_info["environment"]["server_clustered"] = True
    for name in ("node1", "node2"):
        ro.add(f"/1.0/cluster/members/{name}", {"server_name": name, "status": "Online", "roles": [], "groups": ["default"], "config": {}})

    result = run(lxd_cluster_member_info, {})
    assert result["clustered"] is True
    assert [member["server_name"] for member in result["members"]] == ["node1", "node2"]
    assert "state" not in result["members"][0]
    assert targets(ro, "/1.0/cluster") == ["/1.0/cluster/members?recursion=1"]

    result = run(lxd_cluster_member_info, {"name": "node2"})
    assert result["members"] == [ro.get("/1.0/cluster/members/node2")]

    result = run(lxd_cluster_member_info, {"name": "node9", "include_state": True})
    assert result["clustered"] is True and result["members"] == []

    del ro.requests[:]
    result = run(lxd_cluster_member_info, {"include_state": True})
    assert [member["state"]["sysinfo"]["logical_cpus"] for member in result["members"]] == [4, 4]
    assert targets(ro, "/1.0/cluster/members/") == ["/1.0/cluster/members/node1/state", "/1.0/cluster/members/node2/state"]


# ----------------------------------------------------------------------
# lxd_cluster_link_info


def test_cluster_link_info(ro, run):
    ro.add("/1.0/cluster/links/active", {"name": "active", "type": "bidirectional", "description": "a", "config": {"volatile.addresses": "192.0.2.2:8443"}})
    ro.add("/1.0/cluster/links/pending", {"name": "pending", "type": "bidirectional", "description": "p", "config": {}})

    result = run(lxd_cluster_link_info, {})
    assert result["changed"] is False
    assert [link["name"] for link in result["links"]] == ["active", "pending"]
    assert "state" not in result["links"][0]
    assert targets(ro, "/1.0/cluster") == ["/1.0/cluster/links?recursion=1"]

    result = run(lxd_cluster_link_info, {"name": "pending"})
    assert result["links"] == [ro.get("/1.0/cluster/links/pending")]

    result = run(lxd_cluster_link_info, {"name": "gone", "include_state": True})
    assert result["links"] == []

    # A pending link has no state: LXD answers an error, and the module returns null for it.
    result = run(lxd_cluster_link_info, {"include_state": True})
    assert result.get("failed") is not True, result
    assert result["links"][0]["state"] == {"cluster_link_members": [{"address": "192.0.2.2:8443", "status": "Active"}]}
    assert result["links"][1]["state"] is None


# ----------------------------------------------------------------------
# lxd_image_registry_info


def test_image_registry_info(ro, run):
    base = "/1.0/image-registries"
    ro.add(f"{base}/ubuntu", {"name": "ubuntu", "protocol": "simplestreams", "builtin": True, "config": {"url": "https://cloud-images.ubuntu.com/releases"}})
    ro.add(f"{base}/dr", {"name": "dr", "protocol": "lxd", "builtin": False, "config": {"cluster": "site-b"}})
    ro.add(f"{base}/ubuntu/images/aaa", {"fingerprint": "aaa", "type": "container", "properties": {"os": "ubuntu", "release": "noble"}})
    ro.add(f"{base}/ubuntu/images/bbb", {"fingerprint": "bbb", "type": "virtual-machine", "properties": {"os": "ubuntu", "release": "noble"}})
    ro.add(f"{base}/ubuntu/images/ccc", {"fingerprint": "ccc", "type": "container", "properties": {"os": "ubuntu", "release": "jammy"}})

    result = run(lxd_image_registry_info, {})
    assert result["changed"] is False
    assert [registry["name"] for registry in result["image_registries"]] == ["dr", "ubuntu"]
    assert "images" not in result["image_registries"][1]

    result = run(lxd_image_registry_info, {"name": "dr"})
    assert result["image_registries"] == [ro.get(f"{base}/dr")]

    result = run(lxd_image_registry_info, {"name": "gone", "include_images": True})
    assert result["image_registries"] == []

    del ro.requests[:]
    result = run(lxd_image_registry_info, {"name": "ubuntu", "include_images": True})
    assert [image["fingerprint"] for image in result["image_registries"][0]["images"]] == ["aaa", "bbb", "ccc"]
    assert f"{base}/ubuntu/images?recursion=1" in targets(ro, base)

    # The filter takes a field or a dotted path. Every key must match.
    result = run(lxd_image_registry_info, {"name": "ubuntu", "include_images": True, "image_filter": {"properties.release": "noble", "type": "container"}})
    assert [image["fingerprint"] for image in result["image_registries"][0]["images"]] == ["aaa"]

    result = run(lxd_image_registry_info, {"name": "ubuntu", "include_images": True, "image_filter": {"properties.release": "plucky"}})
    assert result["image_registries"][0]["images"] == []


def test_image_registry_info_reads_images_of_one_registry_only(ro, run):
    result = run(lxd_image_registry_info, {"include_images": True})
    assert result["failed"] is True
    assert result["msg"] == "include_images needs name"
    assert targets(ro, "/1.0/image-registries") == []


# ----------------------------------------------------------------------
# lxd_replicator_info


@pytest.fixture
def replicators(ro):
    ro.add("/1.0/replicators/dr1", {"name": "dr1", "description": "", "config": {"cluster": "site-b"}, "last_run_status": "Completed"})
    ro.add("/1.0/replicators/dr2", {"name": "dr2", "description": "", "config": {"cluster": "site-c"}}, "web")
    return ro


def names(result) -> list[tuple[str, str]]:
    return [(item["project"], item["name"]) for item in result["replicators"]]


def test_replicator_info_lists_one_project_or_all(replicators, run):
    result = run(lxd_replicator_info, {})
    assert result["changed"] is False
    assert names(result) == [("default", "dr1")]
    assert "state" not in result["replicators"][0]

    result = run(lxd_replicator_info, {"project": "web"})
    assert names(result) == [("web", "dr2")]

    del replicators.requests[:]
    result = run(lxd_replicator_info, {"all_projects": True})
    assert names(result) == [("default", "dr1"), ("web", "dr2")]
    assert targets(replicators, "/1.0/replicators") == ["/1.0/replicators?all-projects=true&recursion=1"]


def test_replicator_info_of_one_replicator(replicators, run):
    result = run(lxd_replicator_info, {"name": "dr2", "project": "web"})
    assert names(result) == [("web", "dr2")]
    assert result["replicators"][0]["config"] == {"cluster": "site-c"}

    # The same name in another project is another object.
    assert run(lxd_replicator_info, {"name": "dr2"})["replicators"] == []
    assert run(lxd_replicator_info, {"name": "gone", "project": "web", "include_state": True})["replicators"] == []


def test_replicator_info_reads_the_state_in_the_project_of_each_replicator(replicators, run):
    result = run(lxd_replicator_info, {"all_projects": True, "include_state": True})
    assert [item["state"]["status"] for item in result["replicators"]] == ["Completed", "Pending"]
    states = [target for target in targets(replicators, "/1.0/replicators/") if "/state" in target]
    assert states == ["/1.0/replicators/dr1/state?project=default", "/1.0/replicators/dr2/state?project=web"]


@pytest.mark.parametrize("args", [{"name": "dr1", "all_projects": True}, {"project": "web", "all_projects": True}], ids=["name", "project"])
def test_replicator_info_all_projects_goes_with_no_name_and_no_project(replicators, run, args):
    result = run(lxd_replicator_info, args)
    assert result["failed"] is True
    assert "mutually exclusive" in result["msg"]
    assert targets(replicators, "/1.0/replicators") == []


# ----------------------------------------------------------------------
# lxd_operation_info


@pytest.fixture
def busy(ro):
    ro.add_operation({"id": "task-1", "class": "task", "status": "Running", "metadata": {"progress": "50%"}, "err": ""})
    token = {"request": {"name": "laptop"}, "secret": "t0ken-s3cret", "fingerprint": "c" * 64, "addresses": ["192.0.2.1:8443"]}
    ro.add_operation({"id": "token-1", "class": "token", "status": "Running", "metadata": token, "err": ""})
    ro.add_operation(
        {"id": "exec-1", "class": "websocket", "status": "Running", "metadata": {"fds": {"0": "fd-s3cret", "control": "fd-s3cret"}}, "err": ""}, "web"
    )
    child = {"id": "child-1", "class": "task", "status": "Success", "metadata": {"secret": "ch1ld-s3cret", "instance": "c1"}, "err": ""}
    ro.add_operation({"id": "done-1", "class": "task", "status": "Success", "metadata": {}, "err": "", "children": [child]})
    return ro


def ids(result) -> list[str]:
    return sorted(item["id"] for item in result["operations"])


def test_operation_info_lists_one_project_or_all(busy, run):
    result = run(lxd_operation_info, {})
    assert result["changed"] is False
    assert ids(result) == ["done-1", "task-1", "token-1"]
    assert targets(busy, "/1.0/operations") == ["/1.0/operations?recursion=1"]

    del busy.requests[:]
    result = run(lxd_operation_info, {"project": "web"})
    assert ids(result) == ["exec-1"]
    assert targets(busy, "/1.0/operations") == ["/1.0/operations?project=web&recursion=1"]

    del busy.requests[:]
    result = run(lxd_operation_info, {"all_projects": True})
    assert ids(result) == ["done-1", "exec-1", "task-1", "token-1"]
    assert targets(busy, "/1.0/operations") == ["/1.0/operations?recursion=1&all-projects=true"]


def test_operation_info_hides_the_secrets(busy, run):
    result = run(lxd_operation_info, {"all_projects": True, "include_children": True})
    text = json.dumps(result)
    assert "s3cret" not in text
    by_id = {item["id"]: item for item in result["operations"]}
    # The rest of the metadata of a token stays. A websocket operation has only secrets.
    assert by_id["token-1"]["metadata"] == {"request": {"name": "laptop"}, "fingerprint": "c" * 64, "addresses": ["192.0.2.1:8443"]}
    assert by_id["exec-1"]["metadata"] == {}
    assert by_id["task-1"]["metadata"] == {"progress": "50%"}
    assert by_id["done-1"]["children"][0]["metadata"] == {"instance": "c1"}


@pytest.mark.parametrize(
    ("args", "found"),
    [
        ({"status": ["Running"]}, ["task-1", "token-1"]),
        ({"status": ["success", "failure"]}, ["done-1"]),
        ({"class": "token"}, ["token-1"]),
        ({"class": "task", "status": ["running"]}, ["task-1"]),
        ({"class": "durable"}, []),
        ({"id": "task-1"}, ["task-1"]),
        ({"id": "task-1", "class": "token"}, []),
        ({"id": "gone"}, []),
    ],
)
def test_operation_info_filters(busy, run, args, found):
    assert ids(run(lxd_operation_info, args)) == found


def test_operation_info_asks_for_the_children_with_a_higher_recursion(busy, run):
    result = run(lxd_operation_info, {"include_children": True})
    assert targets(busy, "/1.0/operations") == ["/1.0/operations?recursion=2"]
    done = [item for item in result["operations"] if item["id"] == "done-1"][0]
    assert [child["id"] for child in done["children"]] == ["child-1"]

    del busy.requests[:]
    result = run(lxd_operation_info, {"id": "done-1", "include_children": True})
    assert targets(busy, "/1.0/operations") == ["/1.0/operations/done-1?recursion=1"]
    assert [child["id"] for child in result["operations"][0]["children"]] == ["child-1"]

    del busy.requests[:]
    run(lxd_operation_info, {"id": "done-1"})
    assert targets(busy, "/1.0/operations") == ["/1.0/operations/done-1"]


def test_operation_info_id_and_all_projects_are_exclusive(busy, run):
    result = run(lxd_operation_info, {"id": "task-1", "all_projects": True})
    assert result["failed"] is True
    assert "mutually exclusive" in result["msg"]


# ----------------------------------------------------------------------
# lxd_network_allocation_info


@pytest.fixture
def allocated(ro):
    ro.allocations = [
        {"addresses": "10.0.0.1/24", "used_by": "/1.0/networks/lxdbr0", "type": "network", "nat": True, "network": "lxdbr0", "project": "default"},
        {"addresses": "10.0.0.5/32", "used_by": "/1.0/instances/c1", "type": "instance", "nat": True, "network": "lxdbr0", "project": "default"},
        {"addresses": "10.1.0.5/32", "used_by": "/1.0/instances/c2?project=web", "type": "instance", "nat": False, "network": "ovn1", "project": "web"},
    ]
    return ro


def addresses(result) -> list[str]:
    return [item["addresses"] for item in result["allocations"]]


def test_network_allocation_info_lists_one_project_or_all(allocated, run):
    result = run(lxd_network_allocation_info, {})
    assert result["changed"] is False
    assert addresses(result) == ["10.0.0.1/24", "10.0.0.5/32"]
    assert result["allocations"][1] == {"addresses": "10.0.0.5/32", "used_by": "/1.0/instances/c1", "type": "instance", "nat": True, "network": "lxdbr0"}
    assert targets(allocated, "/1.0/network-allocations") == ["/1.0/network-allocations"]

    del allocated.requests[:]
    assert addresses(run(lxd_network_allocation_info, {"project": "web"})) == ["10.1.0.5/32"]
    assert targets(allocated, "/1.0/network-allocations") == ["/1.0/network-allocations?project=web"]

    del allocated.requests[:]
    assert addresses(run(lxd_network_allocation_info, {"all_projects": True})) == ["10.0.0.1/24", "10.0.0.5/32", "10.1.0.5/32"]
    assert targets(allocated, "/1.0/network-allocations") == ["/1.0/network-allocations?all-projects=true"]


@pytest.mark.parametrize(
    ("args", "found"),
    [
        ({"type": "instance"}, ["10.0.0.5/32"]),
        ({"network": "lxdbr0", "type": "network"}, ["10.0.0.1/24"]),
        ({"all_projects": True, "network": "ovn1"}, ["10.1.0.5/32"]),
        ({"network": "ovn1"}, []),
        ({"type": "uplink"}, []),
    ],
)
def test_network_allocation_info_filters(allocated, run, args, found):
    assert addresses(run(lxd_network_allocation_info, args)) == found


def test_network_allocation_info_all_projects_goes_with_no_project(allocated, run):
    result = run(lxd_network_allocation_info, {"project": "web", "all_projects": True})
    assert result["failed"] is True
    assert result["msg"] == "all_projects and project are mutually exclusive"
    assert targets(allocated, "/1.0/network-allocations") == []


# ----------------------------------------------------------------------
# lxd_instance_log_info

INSTANCE = {"name": "c1", "type": "container", "status": "Running", "config": {}, "devices": {}, "profiles": ["default"]}


@pytest.fixture
def logged(ro):
    ro.add("/1.0/instances/c1", INSTANCE)
    ro.add("/1.0/instances/c1", INSTANCE, "web")
    ro.logs[("default", "c1")] = {"lxc.log": b"one\ntwo\nthree\n", "console.log": b"boot \xff\n"}
    ro.logs[("web", "c1")] = {"lxc.log": b"web\n"}
    return ro


def test_instance_log_info_lists_the_files(logged, run):
    result = run(lxd_instance_log_info, {"instance": "c1"})
    assert result["changed"] is False
    assert result["logs"] == ["console.log", "lxc.log"]
    assert "content" not in result and "lines" not in result
    assert targets(logged, "/1.0/instances") == ["/1.0/instances/c1/logs"]


def test_instance_log_info_reads_a_file(logged, run):
    result = run(lxd_instance_log_info, {"instance": "c1", "filename": "lxc.log"})
    assert result["logs"] == ["console.log", "lxc.log"]
    assert result["content"] == "one\ntwo\nthree\n"
    assert result["lines"] == ["one", "two", "three"]

    result = run(lxd_instance_log_info, {"instance": "c1", "filename": "lxc.log", "tail": 2})
    assert result["content"] == "two\nthree\n" and result["lines"] == ["two", "three"]

    result = run(lxd_instance_log_info, {"instance": "c1", "filename": "lxc.log", "tail": 10})
    assert result["lines"] == ["one", "two", "three"]

    result = run(lxd_instance_log_info, {"instance": "c1", "filename": "lxc.log", "tail": 0})
    assert result["content"] == "" and result["lines"] == []

    # A file that is not there is empty, not an error. Bytes that are not UTF-8 do not stop the read.
    result = run(lxd_instance_log_info, {"instance": "c1", "filename": "gone.log"})
    assert result["content"] == "" and result["lines"] == []
    result = run(lxd_instance_log_info, {"instance": "c1", "filename": "console.log"})
    assert result["lines"][0].startswith("boot ")


def test_instance_log_info_in_a_project(logged, run):
    result = run(lxd_instance_log_info, {"instance": "c1", "project": "web", "filename": "lxc.log"})
    assert result["logs"] == ["lxc.log"] and result["content"] == "web\n"
    assert targets(logged, "/1.0/instances") == ["/1.0/instances/c1/logs?project=web", "/1.0/instances/c1/logs/lxc.log?project=web"]


def test_instance_log_info_refusals(logged, run):
    result = run(lxd_instance_log_info, {"instance": "c1", "filename": "lxc.log", "tail": -1})
    assert result["failed"] is True
    assert result["msg"] == "tail must be 0 or more"

    result = run(lxd_instance_log_info, {"instance": "gone"})
    assert result["failed"] is True


# ----------------------------------------------------------------------
# lxd_image_info

FP1, FP2 = "1" * 64, "2" * 64


@pytest.fixture
def images(ro):
    ro.add(f"/1.0/images/{FP1}", {"fingerprint": FP1, "type": "container", "public": False, "properties": {"os": "ubuntu"}})
    ro.add(f"/1.0/images/{FP2}", {"fingerprint": FP2, "type": "virtual-machine", "public": False, "properties": {"os": "ubuntu"}}, "web")
    ro.add("/1.0/images/aliases/noble", {"name": "noble", "description": "", "target": FP1, "type": "container"})
    return ro


def prints(result) -> list[tuple[str, str]]:
    return [(item["project"], item["fingerprint"]) for item in result["images"]]


def test_image_info_lists_one_project_or_all(images, run):
    result = run(lxd_image_info, {})
    assert result["changed"] is False
    assert prints(result) == [("default", FP1)]

    assert prints(run(lxd_image_info, {"project": "web"})) == [("web", FP2)]

    del images.requests[:]
    assert prints(run(lxd_image_info, {"all_projects": True})) == [("default", FP1), ("web", FP2)]
    assert targets(images, "/1.0/images") == ["/1.0/images?all-projects=true&recursion=1"]

    # The filter goes to LXD as it is.
    del images.requests[:]
    assert prints(run(lxd_image_info, {"all_projects": True, "filter": "type eq virtual-machine"})) == [("web", FP2)]
    assert targets(images, "/1.0/images") == ["/1.0/images?filter=type+eq+virtual-machine&all-projects=true&recursion=1"]


def test_image_info_of_one_image(images, run):
    result = run(lxd_image_info, {"fingerprint": FP1})
    assert prints(result) == [("default", FP1)]
    assert result["images"][0]["aliases"] == [{"name": "noble", "description": ""}]

    # An alias is read first, then the image that it names.
    del images.requests[:]
    assert prints(run(lxd_image_info, {"alias": "noble"})) == [("default", FP1)]
    assert targets(images, "/1.0/images") == ["/1.0/images/aliases/noble", f"/1.0/images/{FP1}"]

    assert run(lxd_image_info, {"alias": "gone"})["images"] == []
    assert run(lxd_image_info, {"fingerprint": FP2})["images"] == []
    assert prints(run(lxd_image_info, {"fingerprint": FP2, "project": "web"})) == [("web", FP2)]


@pytest.mark.parametrize(
    ("args", "text"),
    [
        ({"fingerprint": FP1, "alias": "noble"}, "mutually exclusive"),
        ({"project": "web", "all_projects": True}, "all_projects and project are mutually exclusive"),
    ],
    ids=["two-selectors", "project-and-all"],
)
def test_image_info_refusals(images, run, args, text):
    result = run(lxd_image_info, args)
    assert result["failed"] is True
    assert text in result["msg"]


# ----------------------------------------------------------------------
# lxd_auth_info


@pytest.fixture
def auth(ro):
    ro.add("/1.0/auth/identities/tls/ci", {"name": "ci", "authentication_method": "tls", "type": "Client certificate", "groups": ["ops"]})
    ro.add("/1.0/auth/identities/bearer/bot", {"name": "bot", "authentication_method": "bearer", "type": "Client token bearer", "groups": []})
    ro.add("/1.0/auth/identities/tls/ci/state", {"effective_groups": ["ops", "everyone"]})
    ro.add("/1.0/auth/groups/ops", {"name": "ops", "description": "", "permissions": []})
    ro.add("/1.0/auth/identity-provider-groups/devs", {"name": "devs", "groups": ["ops"]})
    ro.permissions = [
        {"entity_type": "server", "url": "/1.0", "entitlement": "admin"},
        {"entity_type": "instance", "url": "/1.0/instances/c1?project=default", "entitlement": "can_exec"},
        {"entity_type": "instance", "url": "/1.0/instances/c2?project=web", "entitlement": "can_exec"},
        {"entity_type": "profile", "url": "/1.0/profiles/default?project=web", "entitlement": "can_edit"},
    ]
    return ro


def test_auth_info_reads_only_the_caller_by_default(auth, run):
    result = run(lxd_auth_info, {})
    assert result["changed"] is False
    assert result["current"] == auth.current_identity
    assert not {"identities", "groups", "identity_provider_groups", "permissions"} & set(result)
    assert targets(auth, "/1.0/auth") == ["/1.0/auth/identities/current"]


def test_auth_info_identities(auth, run):
    result = run(lxd_auth_info, {"gather": ["identities"]})
    assert "current" not in result
    assert [(item["authentication_method"], item["name"]) for item in result["identities"]] == [("bearer", "bot"), ("tls", "ci")]
    assert "effective_groups" not in result["identities"][0]

    result = run(lxd_auth_info, {"gather": ["identities"], "identity_type": "tls"})
    assert [item["name"] for item in result["identities"]] == ["ci"]

    assert run(lxd_auth_info, {"gather": ["identities"], "identity_type": "oidc"})["identities"] == []

    # The effective groups come from the state of each identity. An identity without a state has none.
    result = run(lxd_auth_info, {"gather": ["identities"], "include_effective_groups": True})
    assert [item["effective_groups"] for item in result["identities"]] == [[], ["ops", "everyone"]]
    assert "/1.0/auth/identities/tls/ci/state" in targets(auth, "/1.0/auth")


def test_auth_info_groups_and_permissions(auth, run):
    result = run(lxd_auth_info, {"gather": ["groups", "identity_provider_groups", "permissions"]})
    assert result["groups"] == [auth.get("/1.0/auth/groups/ops")]
    assert result["identity_provider_groups"] == [{"name": "devs", "groups": ["ops"]}]
    assert result["permissions"] == auth.permissions
    assert "current" not in result and "identities" not in result

    del auth.requests[:]
    result = run(lxd_auth_info, {"gather": ["permissions"], "entity_type": "instance", "project": "web"})
    assert result["permissions"] == [{"entity_type": "instance", "url": "/1.0/instances/c2?project=web", "entitlement": "can_exec"}]
    assert targets(auth, "/1.0/auth") == ["/1.0/auth/permissions?recursion=1&entity-type=instance&project=web"]

    result = run(lxd_auth_info, {"gather": ["permissions"], "entity_type": "profile"})
    assert [item["url"] for item in result["permissions"]] == ["/1.0/profiles/default?project=web"]
