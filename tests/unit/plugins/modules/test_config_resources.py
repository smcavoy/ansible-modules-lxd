# Copyright (c) 2026, Sean McAvoy
# GNU General Public License v3.0+ (see LICENSES/GPL-3.0-or-later.txt or https://www.gnu.org/licenses/gpl-3.0.txt)
# SPDX-License-Identifier: GPL-3.0-or-later

"""The life cycle of the modules that manage one object with a description and a config.

Each module runs through main() against the in-memory LXD server: check mode, create, a second run,
an update with a diff, delete, and a second delete.
"""

from __future__ import annotations

import typing as t

import pytest

from ansible_collections.smcavoy.lxd.plugins.modules import (
    lxd_network,
    lxd_network_acl,
    lxd_network_zone,
    lxd_profile,
    lxd_project,
    lxd_storage_pool,
)

CASES: list[tuple[t.Any, str, dict[str, t.Any], dict[str, t.Any], dict[str, t.Any]]] = [
    # module, path of the object, create args, update args, expected config after the update
    (lxd_project, "/1.0/projects/web", {"name": "web", "description": "one"}, {"config": {"limits.instances": 5}}, {"limits.instances": "5"}),
    (lxd_profile, "/1.0/profiles/web", {"name": "web", "description": "one"}, {"config": {"limits.cpu": 2}}, {"limits.cpu": "2"}),
    (lxd_network, "/1.0/networks/webbr", {"name": "webbr", "description": "one"}, {"config": {"ipv6.address": "none"}}, {"ipv6.address": "none"}),
    (lxd_network_acl, "/1.0/network-acls/web", {"name": "web", "description": "one"}, {"config": {"user.team": "a"}}, {"user.team": "a"}),
    (lxd_network_zone, "/1.0/network-zones/web.example", {"name": "web.example", "description": "one"}, {"config": {"user.team": "a"}}, {"user.team": "a"}),
    (lxd_storage_pool, "/1.0/storage-pools/web", {"name": "web", "driver": "dir", "description": "one"}, {"config": {"user.team": "a"}}, {"user.team": "a"}),
]
IDS = [case[0].__name__.rsplit(".", 1)[-1] for case in CASES]


@pytest.fixture(params=[False, True], ids=["sync", "async"])
def server(request, lxd):
    lxd.async_writes = request.param
    return lxd


@pytest.mark.parametrize(("module", "path", "create", "update", "config"), CASES, ids=IDS)
def test_life_cycle(server, run, module, path, create, update, config):
    result = run(module, create, check_mode=True)
    assert result["changed"] is True
    assert server.writes() == []
    assert server.get(path) is None

    result = run(module, create)
    assert result["changed"] is True, result
    assert server.get(path)["description"] == "one"

    del server.requests[:]
    result = run(module, create)
    assert result["changed"] is False, result
    assert server.writes() == []

    result = run(module, dict(create, **update), diff=True)
    assert result["changed"] is True, result
    for key, value in config.items():
        assert server.get(path)["config"][key] == value
    assert result["diff"]["before"] != result["diff"]["after"]

    del server.requests[:]
    result = run(module, dict(create, **update))
    assert result["changed"] is False, result
    assert server.writes() == []

    absent = {"name": create["name"], "state": "absent"}
    result = run(module, absent, check_mode=True)
    assert result["changed"] is True
    assert server.get(path) is not None

    result = run(module, absent)
    assert result["changed"] is True
    assert server.get(path) is None

    result = run(module, absent)
    assert result["changed"] is False


@pytest.mark.parametrize(("module", "path", "create", "update", "config"), CASES, ids=IDS)
def test_create_converges_when_another_writer_was_first(lxd, run, module, path, create, update, config):
    # The object appears between the read and the create.
    original = lxd.on_post
    raced: list[bool] = []

    def post_after_another_writer(path_, query, project, body, headers):
        if not raced:
            raced.append(True)
            original(path_, query, project, dict(body, description="other"), headers)
        return original(path_, query, project, body, headers)

    lxd.on_post = post_after_another_writer
    result = run(module, create)
    assert result.get("failed") is not True, result
    assert lxd.get(path)["description"] == "one"


def test_storage_pool_refuses_a_driver_that_the_server_does_not_offer(lxd, run):
    # Case S3 of the integration target cannot reach this check on a server that offers every driver, as LXD 6.10 does.
    lxd.server_info["environment"]["storage_supported_drivers"] = [{"Name": "dir"}, {"Name": "btrfs"}]
    result = run(lxd_storage_pool, {"name": "web", "driver": "zfs"})
    assert result["failed"] is True
    assert result["msg"] == "Storage driver zfs is not available. Available: btrfs, dir"
    assert lxd.get("/1.0/storage-pools/web") is None
    assert lxd.writes() == []

    result = run(lxd_storage_pool, {"name": "web", "driver": "btrfs"})
    assert result["changed"] is True, result
    assert lxd.get("/1.0/storage-pools/web")["driver"] == "btrfs"
