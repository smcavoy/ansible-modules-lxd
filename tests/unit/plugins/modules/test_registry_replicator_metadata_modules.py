# Copyright (c) 2026, Sean McAvoy
# GNU General Public License v3.0+ (see LICENSES/GPL-3.0-or-later.txt or https://www.gnu.org/licenses/gpl-3.0.txt)
# SPDX-License-Identifier: GPL-3.0-or-later

"""lxd_auth_identity_provider_group, lxd_image_registry, lxd_replicator, lxd_replicator_run, and lxd_instance_metadata.

Each module runs through main() against the in-memory LXD server. The tests check the requests that the server got,
the values of the result, and the rules of each module.
"""

from __future__ import annotations

import hashlib

import pytest

from ansible_collections.smcavoy.lxd.plugins.modules import (
    lxd_auth_identity_provider_group,
    lxd_image_registry,
    lxd_instance_metadata,
    lxd_replicator,
    lxd_replicator_run,
)


@pytest.fixture(params=[False, True], ids=["sync", "async"])
def server(request, lxd):
    lxd.async_writes = request.param
    return lxd


@pytest.fixture
def web(lxd):
    lxd.add("/1.0/projects/web", {"name": "web", "description": "", "config": {}})
    return lxd


# ----------------------------------------------------------------------
# lxd_auth_identity_provider_group

IDP_GROUPS = "/1.0/auth/identity-provider-groups"
IDP_GROUP = IDP_GROUPS + "/devs"


def test_identity_provider_group_life_cycle(server, run):
    args = {"name": "devs", "groups": ["b", "a", "b"]}
    result = run(lxd_auth_identity_provider_group, args, check_mode=True)
    assert result["changed"] is True, result
    assert result["identity_provider_group"] == {"name": "devs", "groups": ["a", "b"]}
    assert server.writes() == []

    result = run(lxd_auth_identity_provider_group, args, diff=True)
    assert result["changed"] is True, result
    # The groups go to LXD once each, sorted.
    assert server.writes() == [("POST", IDP_GROUPS, {"name": "devs", "groups": ["a", "b"]})]
    assert result["identity_provider_group"]["groups"] == ["a", "b"]
    assert result["diff"] == {"before": {}, "after": {"groups": ["a", "b"]}}

    # The groups are a set, and a task without groups does not manage them.
    del server.requests[:]
    for same in ({"name": "devs", "groups": ["a", "b"]}, {"name": "devs", "groups": ["b", "a"]}, {"name": "devs"}):
        result = run(lxd_auth_identity_provider_group, same)
        assert result["changed"] is False, result
        assert result["identity_provider_group"]["groups"] == ["a", "b"]
    assert server.writes() == []

    update = {"name": "devs", "groups": ["c"]}
    result = run(lxd_auth_identity_provider_group, update, check_mode=True)
    assert result["changed"] is True and server.writes() == []

    result = run(lxd_auth_identity_provider_group, update, diff=True)
    assert result["changed"] is True, result
    assert server.writes() == [("PUT", IDP_GROUP, {"groups": ["c"]})]
    assert result["diff"] == {"before": {"groups": ["a", "b"]}, "after": {"groups": ["c"]}}
    assert result["identity_provider_group"] == server.get(IDP_GROUP)

    # An empty list removes every group. That is not the same as no list.
    del server.requests[:]
    result = run(lxd_auth_identity_provider_group, {"name": "devs", "groups": []})
    assert result["changed"] is True, result
    assert server.writes() == [("PUT", IDP_GROUP, {"groups": []})]

    del server.requests[:]
    absent = {"name": "devs", "state": "absent"}
    result = run(lxd_auth_identity_provider_group, absent, check_mode=True)
    assert result["changed"] is True and server.writes() == []

    result = run(lxd_auth_identity_provider_group, absent)
    assert result["changed"] is True, result
    assert server.writes() == [("DELETE", IDP_GROUP, None)]
    assert result["identity_provider_group"] is None and server.get(IDP_GROUP) is None

    del server.requests[:]
    result = run(lxd_auth_identity_provider_group, absent)
    assert result["changed"] is False, result
    assert server.writes() == []


def test_identity_provider_group_without_groups_is_created_empty(lxd, run):
    result = run(lxd_auth_identity_provider_group, {"name": "devs"})
    assert result["changed"] is True, result
    assert lxd.writes() == [("POST", IDP_GROUPS, {"name": "devs", "groups": []})]


# ----------------------------------------------------------------------
# lxd_image_registry

REGISTRIES = "/1.0/image-registries"
REGISTRY = REGISTRIES + "/mirror"
URL = "https://images.example.org"


def test_image_registry_life_cycle(server, run):
    args = {"name": "mirror", "description": "one", "config": {"url": URL}}
    body = {"name": "mirror", "description": "one", "config": {"url": URL}}

    result = run(lxd_image_registry, args, check_mode=True)
    assert result["changed"] is True, result
    # Check mode predicts the protocol from the config.
    assert result["image_registry"] == dict(body, protocol="simplestreams", builtin=False)
    assert server.writes() == []

    result = run(lxd_image_registry, args, diff=True)
    assert result["changed"] is True, result
    assert server.writes() == [("POST", REGISTRIES, body)]
    assert result["image_registry"]["protocol"] == "simplestreams"
    assert result["image_registry"]["builtin"] is False
    assert result["diff"] == {"before": {}, "after": {"description": "one", "config": {"url": URL}}}

    del server.requests[:]
    result = run(lxd_image_registry, args)
    assert result["changed"] is False, result
    assert server.writes() == []

    update = {"name": "mirror", "description": "two", "config": {"user.team": "a"}}
    result = run(lxd_image_registry, update, check_mode=True)
    assert result["changed"] is True and server.writes() == []

    result = run(lxd_image_registry, update, diff=True)
    assert result["changed"] is True, result
    # The PUT holds the whole config: the merged key and the keys of the server.
    assert server.writes() == [("PUT", REGISTRY, {"description": "two", "config": {"url": URL, "user.team": "a"}})]
    assert result["diff"]["before"] == {"description": "one", "config": {"url": URL}}
    assert result["image_registry"]["protocol"] == "simplestreams"

    del server.requests[:]
    absent = {"name": "mirror", "state": "absent"}
    result = run(lxd_image_registry, absent, check_mode=True)
    assert result["changed"] is True and server.writes() == []

    result = run(lxd_image_registry, absent)
    assert result["changed"] is True, result
    assert server.writes() == [("DELETE", REGISTRY, None)]
    assert result["image_registry"] is None and server.get(REGISTRY) is None

    del server.requests[:]
    result = run(lxd_image_registry, absent)
    assert result["changed"] is False, result
    assert server.writes() == []


def test_image_registry_of_a_cluster_has_the_protocol_lxd(lxd, run):
    result = run(lxd_image_registry, {"name": "dr", "config": {"cluster": "site-b", "source_project": "images"}}, check_mode=True)
    assert result["image_registry"]["protocol"] == "lxd"
    result = run(lxd_image_registry, {"name": "dr", "config": {"cluster": "site-b", "source_project": "images"}})
    assert result["changed"] is True, result
    assert result["image_registry"]["protocol"] == "lxd"


def test_image_registry_protocol_cannot_change(lxd, run):
    run(lxd_image_registry, {"name": "mirror", "config": {"url": URL}})
    del lxd.requests[:]
    result = run(lxd_image_registry, {"name": "mirror", "config": {"cluster": "site-b"}, "config_mode": "exact"})
    assert result["failed"] is True
    assert result["msg"] == "image registry protocol cannot change from simplestreams to lxd"
    assert lxd.writes() == []
    assert lxd.get(REGISTRY)["config"] == {"url": URL}


def test_builtin_image_registry_is_read_only(lxd, run):
    builtin = {"name": "ubuntu", "description": "Ubuntu images", "config": {"url": "https://cloud-images.ubuntu.com/releases"}}
    lxd.add(REGISTRIES + "/ubuntu", dict(builtin, protocol="simplestreams", builtin=True))

    # A task that names it as it is passes.
    result = run(lxd_image_registry, builtin)
    assert result["changed"] is False, result

    result = run(lxd_image_registry, dict(builtin, description="mine"))
    assert result["failed"] is True
    assert result["msg"] == "built-in image registry ubuntu cannot be changed"

    result = run(lxd_image_registry, {"name": "ubuntu", "state": "absent"})
    assert result["failed"] is True
    assert result["msg"] == "built-in image registry ubuntu cannot be deleted"
    assert lxd.writes() == []
    assert lxd.get(REGISTRIES + "/ubuntu")["description"] == "Ubuntu images"


# ----------------------------------------------------------------------
# lxd_replicator

REPLICATOR = "/1.0/replicators/dr"


def test_replicator_life_cycle_in_a_project(server, run):
    server.add("/1.0/projects/web", {"name": "web", "description": "", "config": {}})
    ident = {"name": "dr", "project": "web"}
    args = dict(ident, description="one", config={"cluster": "site-b", "schedule": "@daily", "user.team": "a"})
    body = {"name": "dr", "description": "one", "config": {"cluster": "site-b", "schedule": "@daily", "user.team": "a"}}

    result = run(lxd_replicator, args, check_mode=True)
    assert result["changed"] is True, result
    assert result["replicator"] == dict(body, project="web")
    assert server.writes() == []

    result = run(lxd_replicator, args, diff=True)
    assert result["changed"] is True, result
    assert server.writes() == [("POST", "/1.0/replicators?project=web", body)]
    assert result["replicator"]["config"]["cluster"] == "site-b"
    assert result["diff"] == {"before": {}, "after": {"description": "one", "config": body["config"]}}
    # The replicator is in the project of the task, not in the default project.
    assert server.get(REPLICATOR, "web") is not None and server.get(REPLICATOR) is None

    del server.requests[:]
    result = run(lxd_replicator, args)
    assert result["changed"] is False, result
    assert server.writes() == []

    # An exact config without the cluster keeps the cluster: a replicator cannot be without one.
    update = dict(ident, description="two", config={"schedule": "@hourly"}, config_mode="exact")
    result = run(lxd_replicator, update, check_mode=True)
    assert result["changed"] is True and server.writes() == []

    result = run(lxd_replicator, update, diff=True)
    assert result["changed"] is True, result
    assert server.writes() == [("PUT", REPLICATOR + "?project=web", {"description": "two", "config": {"cluster": "site-b", "schedule": "@hourly"}})]
    assert result["diff"]["after"] == {"description": "two", "config": {"cluster": "site-b", "schedule": "@hourly"}}
    assert result["replicator"]["config"] == {"cluster": "site-b", "schedule": "@hourly"}

    del server.requests[:]
    absent = dict(ident, state="absent")
    result = run(lxd_replicator, absent, check_mode=True)
    assert result["changed"] is True and server.writes() == []

    result = run(lxd_replicator, absent)
    assert result["changed"] is True, result
    assert server.writes() == [("DELETE", REPLICATOR + "?project=web", None)]
    assert result["replicator"] is None and server.get(REPLICATOR, "web") is None

    del server.requests[:]
    result = run(lxd_replicator, absent)
    assert result["changed"] is False, result
    assert server.writes() == []


@pytest.mark.parametrize("config", [None, {"schedule": "@daily"}, {"cluster": ""}], ids=["no-config", "no-cluster", "empty-cluster"])
def test_replicator_needs_a_cluster_on_create(lxd, run, config):
    result = run(lxd_replicator, {"name": "dr", "config": config})
    assert result["failed"] is True
    assert result["msg"] == "config.cluster is required to create a replicator"
    assert lxd.writes() == []


def test_replicator_in_a_project_that_does_not_exist_fails(lxd, run):
    result = run(lxd_replicator, {"name": "dr", "project": "pord", "config": {"cluster": "site-b"}})
    assert result["failed"] is True
    assert 'Project "pord" does not exist' in result["msg"]
    assert lxd.writes() == []


# ----------------------------------------------------------------------
# lxd_replicator_run

STATE = REPLICATOR + "/state?project=web"


@pytest.fixture
def replicator(web):
    web.add(REPLICATOR, {"name": "dr", "description": "", "config": {"cluster": "site-b"}}, "web")
    return web


def waits(lxd) -> list[str]:
    return [request[1] for request in lxd.requests if "/wait" in request[1]]


@pytest.mark.parametrize("mode", ["start", "restore"])
def test_replicator_run_starts_a_run_and_waits_for_it(replicator, run, mode):
    args = {"name": "dr", "project": "web", "mode": mode}
    result = run(lxd_replicator_run, args, check_mode=True)
    assert result["changed"] is True, result
    assert result["status"] == "Pending"
    assert replicator.writes() == [] and replicator.replicator_runs == []

    result = run(lxd_replicator_run, args)
    assert result["changed"] is True, result
    assert replicator.writes() == [("PUT", STATE, {"action": mode})]
    assert replicator.replicator_runs == [("web", "dr", mode)]
    assert result["operation"] == "run1"
    assert result["status"] == "Completed"
    assert len(waits(replicator)) == 1 and "/1.0/operations/run1/wait" in waits(replicator)[0]

    # Every run of the task is a new run of the replicator.
    result = run(lxd_replicator_run, args)
    assert result["changed"] is True, result
    assert replicator.replicator_runs == [("web", "dr", mode)] * 2


def test_replicator_run_without_wait_returns_the_operation(replicator, run):
    result = run(lxd_replicator_run, {"name": "dr", "project": "web", "wait": False})
    assert result["changed"] is True, result
    assert result["operation"] == "run1"
    assert replicator.replicator_runs == [("web", "dr", "start")]
    assert waits(replicator) == []


def test_replicator_run_starts_no_second_run(replicator, run):
    replicator.get(REPLICATOR, "web")["last_run_status"] = "Running"
    result = run(lxd_replicator_run, {"name": "dr", "project": "web"})
    assert result["changed"] is False, result
    assert result["status"] == "Running"
    assert any("has a run in progress" in str(w) for w in result["warnings"]), result
    assert replicator.writes() == [] and replicator.replicator_runs == []


def test_replicator_run_reports_the_errors_of_the_child_operations(replicator, run):
    replicator.replicator_errors["dr"] = ["instance c1: no space left", "instance c2: not found"]
    result = run(lxd_replicator_run, {"name": "dr", "project": "web"})
    assert result["failed"] is True
    # LXD names only "child operations failed" on the run. The module adds what each child says.
    assert result["msg"] == "LXD operation run1 failed: One or more child operations failed: instance c1: no space left; instance c2: not found"
    assert result["operation"] == "run1"
    assert ("GET", "/1.0/operations/run1?recursion=1", None) in replicator.requests


def test_replicator_run_of_a_missing_replicator_fails(web, run):
    result = run(lxd_replicator_run, {"name": "dr", "project": "web"})
    assert result["failed"] is True
    assert web.writes() == [] and web.replicator_runs == []


# ----------------------------------------------------------------------
# lxd_instance_metadata

INSTANCE = "/1.0/instances/c1"
METADATA = INSTANCE + "/metadata"
TEMPLATES = METADATA + "/templates"
HOSTNAME = {"path": "/etc/hostname", "when": ["create", "copy"], "template": "hostname.tpl"}
HOSTNAME_ENTRY = {"when": ["create", "copy"], "create_only": False, "template": "hostname.tpl", "properties": {}}
HOSTS_ENTRY = {"when": ["start"], "create_only": True, "template": "hosts.tpl", "properties": {"a": "1"}}
CONTENT = "{{ container.name }}\n"


def sha(text: str) -> str:
    return hashlib.sha256(text.encode()).hexdigest()


@pytest.fixture
def instance(lxd):
    lxd.add(INSTANCE, {"name": "c1", "type": "container", "status": "Stopped", "config": {}, "devices": {}, "profiles": ["default"]})
    lxd.add(
        METADATA, {"architecture": "x86_64", "creation_date": 1700000000, "expiry_date": 0, "properties": {"os": "ubuntu", "release": "noble"}, "templates": {}}
    )
    return lxd


def test_instance_metadata_properties(instance, run):
    args = {"instance": "c1", "properties": {"release": "plucky", "serial": 20261121, "os": None}}
    result = run(lxd_instance_metadata, args, check_mode=True, diff=True)
    assert result["changed"] is True, result
    assert result["diff"]["before"]["properties"] == {"os": "ubuntu", "release": "noble"}
    assert result["diff"]["after"]["properties"] == {"release": "plucky", "serial": "20261121"}
    assert instance.writes() == []

    result = run(lxd_instance_metadata, args)
    assert result["changed"] is True, result
    # Merge mode: a new value, a new key as text, and null removes a key. The PUT holds the whole metadata object.
    body = {"architecture": "x86_64", "creation_date": 1700000000, "expiry_date": 0, "properties": {"release": "plucky", "serial": "20261121"}, "templates": {}}
    assert instance.writes() == [("PUT", METADATA, body)]
    assert result["metadata"] == body

    del instance.requests[:]
    result = run(lxd_instance_metadata, args)
    assert result["changed"] is False, result
    assert instance.writes() == []

    # Exact mode removes the keys that the task does not name.
    result = run(lxd_instance_metadata, {"instance": "c1", "properties": {"release": "plucky"}, "properties_mode": "exact"})
    assert result["changed"] is True, result
    assert instance.writes()[0][2]["properties"] == {"release": "plucky"}

    # A task without properties and templates changes nothing.
    del instance.requests[:]
    result = run(lxd_instance_metadata, {"instance": "c1"})
    assert result["changed"] is False, result
    assert result["metadata"]["properties"] == {"release": "plucky"}
    assert instance.writes() == []


def test_instance_metadata_template_with_content(instance, run):
    args = {"instance": "c1", "templates": [dict(HOSTNAME, content=CONTENT)]}
    result = run(lxd_instance_metadata, args, check_mode=True, diff=True)
    assert result["changed"] is True, result
    assert result["diff"]["before"]["template_files"] == {}
    assert result["diff"]["after"]["template_files"] == {"hostname.tpl": sha(CONTENT)}
    assert instance.writes() == [] and instance.templates[("default", "c1")] == {}

    result = run(lxd_instance_metadata, args)
    assert result["changed"] is True, result
    # The file goes first: an entry that names a missing file would break the next copy of the instance.
    writes = instance.writes()
    assert [(method, target) for method, target, _body in writes] == [("POST", TEMPLATES + "?path=hostname.tpl"), ("PUT", METADATA)]
    assert writes[1][2]["templates"] == {"/etc/hostname": HOSTNAME_ENTRY}
    assert writes[1][2]["properties"] == {"os": "ubuntu", "release": "noble"}
    assert instance.templates[("default", "c1")] == {"hostname.tpl": CONTENT.encode()}
    assert result["metadata"]["templates"] == {"/etc/hostname": HOSTNAME_ENTRY}

    del instance.requests[:]
    result = run(lxd_instance_metadata, args, diff=True)
    assert result["changed"] is False, result
    assert instance.writes() == []
    assert result["diff"]["before"] == result["diff"]["after"]

    # Only the content differs: the module writes the file and leaves the metadata object.
    result = run(lxd_instance_metadata, {"instance": "c1", "templates": [dict(HOSTNAME, content="new\n")]}, diff=True)
    assert result["changed"] is True, result
    assert [(method, target) for method, target, _body in instance.writes()] == [("POST", TEMPLATES + "?path=hostname.tpl")]
    assert instance.templates[("default", "c1")]["hostname.tpl"] == b"new\n"
    assert result["diff"]["before"]["template_files"] == {"hostname.tpl": sha(CONTENT)}
    assert result["diff"]["after"]["template_files"] == {"hostname.tpl": sha("new\n")}

    # Without content the module uses the file that the instance has.
    del instance.requests[:]
    result = run(lxd_instance_metadata, {"instance": "c1", "templates": [dict(HOSTNAME, when=["start"])]})
    assert result["changed"] is True, result
    writes = instance.writes()
    assert [(method, target) for method, target, _body in writes] == [("PUT", METADATA)]
    assert writes[0][2]["templates"]["/etc/hostname"]["when"] == ["start"]
    assert instance.templates[("default", "c1")]["hostname.tpl"] == b"new\n"


def test_instance_metadata_template_without_a_file_and_without_content_fails(instance, run):
    result = run(lxd_instance_metadata, {"instance": "c1", "templates": [HOSTNAME]})
    assert result["failed"] is True
    assert result["msg"] == "template hostname.tpl has no file and no content"
    assert instance.writes() == []


def test_instance_metadata_exact_templates_removes_the_other_entries_and_files(instance, run):
    instance.get(METADATA)["templates"] = {"/etc/hostname": HOSTNAME_ENTRY, "/etc/hosts": HOSTS_ENTRY}
    instance.templates[("default", "c1")] = {"hostname.tpl": b"old\n", "hosts.tpl": b"hosts\n", "stray.tpl": b"x"}
    args = {"instance": "c1", "templates": [dict(HOSTNAME, content=CONTENT)], "templates_mode": "exact"}

    # Merge mode keeps the entry and the files that the task does not name.
    result = run(lxd_instance_metadata, dict(args, templates_mode="merge"), check_mode=True, diff=True)
    assert result["changed"] is True, result
    assert sorted(result["diff"]["after"]["templates"]) == ["/etc/hostname", "/etc/hosts"]
    assert sorted(result["diff"]["after"]["template_files"]) == ["hostname.tpl"]

    result = run(lxd_instance_metadata, args, check_mode=True, diff=True)
    assert result["changed"] is True, result
    assert result["diff"]["before"]["template_files"] == {"hostname.tpl": sha("old\n"), "hosts.tpl": "", "stray.tpl": ""}
    assert result["diff"]["after"]["template_files"] == {"hostname.tpl": sha(CONTENT)}
    assert instance.writes() == []

    result = run(lxd_instance_metadata, args)
    assert result["changed"] is True, result
    # Upload, then the metadata object, then the deletes of the files that no entry uses.
    assert [(method, target) for method, target, _body in instance.writes()] == [
        ("POST", TEMPLATES + "?path=hostname.tpl"),
        ("PUT", METADATA),
        ("DELETE", TEMPLATES + "?path=hosts.tpl"),
        ("DELETE", TEMPLATES + "?path=stray.tpl"),
    ]
    assert instance.get(METADATA)["templates"] == {"/etc/hostname": HOSTNAME_ENTRY}
    assert instance.templates[("default", "c1")] == {"hostname.tpl": CONTENT.encode()}

    del instance.requests[:]
    result = run(lxd_instance_metadata, args)
    assert result["changed"] is False, result
    assert instance.writes() == []


def test_instance_metadata_in_a_project(web, run):
    web.add(INSTANCE, {"name": "c1", "type": "container", "status": "Stopped", "config": {}, "devices": {}, "profiles": ["default"]}, "web")
    args = {"instance": "c1", "project": "web", "properties": {"os": "ubuntu"}, "templates": [dict(HOSTNAME, content=CONTENT)]}
    result = run(lxd_instance_metadata, args)
    assert result["changed"] is True, result
    assert [(method, target) for method, target, _body in web.writes()] == [
        ("POST", TEMPLATES + "?project=web&path=hostname.tpl"),
        ("PUT", METADATA + "?project=web"),
    ]
    assert web.get(METADATA, "web")["properties"] == {"os": "ubuntu"}
    assert web.templates[("web", "c1")] == {"hostname.tpl": CONTENT.encode()}


def test_instance_metadata_of_a_missing_instance_fails(lxd, run):
    result = run(lxd_instance_metadata, {"instance": "gone", "properties": {"os": "ubuntu"}})
    assert result["failed"] is True
    assert lxd.writes() == []
