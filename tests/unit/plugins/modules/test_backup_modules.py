# Copyright (c) 2026, Sean McAvoy
# GNU General Public License v3.0+ (see LICENSES/GPL-3.0-or-later.txt or https://www.gnu.org/licenses/gpl-3.0.txt)
# SPDX-License-Identifier: GPL-3.0-or-later

"""lxd_instance_backup and lxd_storage_volume_backup against the in-memory LXD server."""

from __future__ import annotations

import os
import typing as t

import pytest

from ansible_collections.smcavoy.lxd.plugins.modules import lxd_instance_backup, lxd_storage_volume_backup


class Case(t.NamedTuple):
    module: t.Any
    parents: list[tuple[str, dict[str, t.Any]]]
    parent_path: str
    args: dict[str, t.Any]
    only_key: str


CASES = [
    Case(
        lxd_instance_backup,
        [("/1.0/instances/web", {"name": "web", "type": "container", "status": "Stopped", "config": {}, "devices": {}, "profiles": ["default"]})],
        "/1.0/instances/web",
        {"instance": "web"},
        "instance_only",
    ),
    Case(
        lxd_storage_volume_backup,
        [
            ("/1.0/storage-pools/p1", {"name": "p1", "driver": "dir", "config": {}}),
            ("/1.0/storage-pools/p1/volumes/custom/v1", {"name": "v1", "type": "custom", "config": {}}),
        ],
        "/1.0/storage-pools/p1/volumes/custom/v1",
        {"pool": "p1", "volume": "v1"},
        "volume_only",
    ),
]
IDS = ["instance", "volume"]


@pytest.fixture(params=[False, True], ids=["sync", "async"])
def server(request, lxd):
    lxd.async_writes = request.param
    return lxd


def add_parents(server, case):
    for path, obj in case.parents:
        server.add(path, obj)


@pytest.mark.parametrize("case", CASES, ids=IDS)
def test_create_download_and_delete(server, run, tmp_path, case):
    add_parents(server, case)
    dest = tmp_path / "b1.tar.gz"
    args = dict(case.args, name="b1", dest=str(dest))
    backup_path = case.parent_path + "/backups/b1"
    data = server.export_data(backup_path + "/export")

    result = run(case.module, args, check_mode=True)
    assert result["changed"] is True, result
    assert server.writes() == []
    assert not dest.exists()

    result = run(case.module, args)
    assert result["changed"] is True, result
    assert server.get(backup_path)[case.only_key] is False
    assert dest.read_bytes() == data
    assert result["size"] == len(data)
    assert [n for n in os.listdir(tmp_path) if n.startswith(".lxd-backup-")] == []

    # dest exists: no new download, no change.
    del server.requests[:]
    result = run(case.module, args)
    assert result["changed"] is False, result
    assert server.writes() == []
    assert not any(r[1].endswith("/export") for r in server.requests)

    dest.write_bytes(b"old")
    result = run(case.module, dict(args, force_download=True))
    assert result["changed"] is True, result
    assert dest.read_bytes() == data

    absent = dict(case.args, name="b1", state="absent")
    assert run(case.module, absent, check_mode=True)["changed"] is True
    assert server.get(backup_path) is not None
    assert run(case.module, absent)["changed"] is True
    assert server.get(backup_path) is None
    assert run(case.module, absent)["changed"] is False


@pytest.mark.parametrize("case", CASES, ids=IDS)
def test_only_option_and_expiry_go_to_the_server(lxd, run, case):
    add_parents(lxd, case)
    result = run(case.module, dict(case.args, name="b1", expires_at="2030-01-02T03:04:05Z", **{case.only_key: True}))
    assert result["changed"] is True, result
    stored = lxd.get(case.parent_path + "/backups/b1")
    assert stored[case.only_key] is True
    assert stored["expires_at"].startswith("2030-01-02T03:04:05")


@pytest.mark.parametrize("case", CASES, ids=IDS)
def test_parent_missing_fails(lxd, run, case):
    for path, obj in case.parents[:-1]:
        lxd.add(path, obj)
    result = run(case.module, dict(case.args, name="b1"))
    assert result.get("failed") is True, result
    assert "not found" in result["msg"]


@pytest.mark.parametrize("case", CASES, ids=IDS)
def test_dest_directory_missing_fails_before_any_write(lxd, run, tmp_path, case):
    add_parents(lxd, case)
    result = run(case.module, dict(case.args, name="b1", dest=str(tmp_path / "no" / "b1.tar.gz")))
    assert result.get("failed") is True, result
    assert "directory of dest does not exist" in result["msg"]
    assert lxd.writes() == []


@pytest.mark.parametrize("case", CASES, ids=IDS)
def test_bad_expiry_fails(lxd, run, case):
    add_parents(lxd, case)
    result = run(case.module, dict(case.args, name="b1", expires_at="next tuesday"))
    assert result.get("failed") is True, result
    assert "RFC 3339" in result["msg"]
