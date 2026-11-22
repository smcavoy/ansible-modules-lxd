# Copyright (c) 2026, Sean McAvoy
# GNU General Public License v3.0+ (see LICENSES/GPL-3.0-or-later.txt or https://www.gnu.org/licenses/gpl-3.0.txt)
# SPDX-License-Identifier: GPL-3.0-or-later

"""lxd_instance against the in-memory LXD server: create, run states, idempotence, check mode, delete."""

from __future__ import annotations

import typing as t

import pytest

from ansible_collections.smcavoy.lxd.plugins.modules import lxd_instance

PATH = "/1.0/instances/web"
IMAGE = {"image": "alpine/3.22"}


def create(lxd, status="Stopped", **extra):
    inst: dict[str, t.Any] = {"name": "web", "type": "container", "description": "", "config": {}, "devices": {}, "profiles": ["default"]}
    inst.update(ephemeral=False, status=status, location="none", used_by=[], **extra)
    lxd.add(PATH, inst)


@pytest.mark.parametrize("async_writes", [False, True], ids=["sync", "async"])
def test_create_started_then_no_change(lxd, run, async_writes):
    lxd.async_writes = async_writes
    result = run(lxd_instance, {"name": "web", "source": IMAGE})
    assert result["changed"] is True, result
    assert lxd.get(PATH)["status"] == "Running"
    del lxd.requests[:]
    result = run(lxd_instance, {"name": "web", "source": IMAGE})
    assert result["changed"] is False, result
    assert lxd.writes() == []


def test_check_mode_create_sends_nothing(lxd, run):
    result = run(lxd_instance, {"name": "web", "source": IMAGE}, check_mode=True)
    assert result["changed"] is True
    assert lxd.writes() == []
    assert lxd.get(PATH) is None


def test_create_without_source_fails(lxd, run):
    result = run(lxd_instance, {"name": "web"})
    assert result["failed"] is True
    assert "source" in result["msg"]


@pytest.mark.parametrize(
    ("before", "state", "after", "changed"),
    [
        ("Stopped", "started", "Running", True),
        ("Running", "started", "Running", False),
        ("Running", "stopped", "Stopped", True),
        ("Stopped", "stopped", "Stopped", False),
        ("Running", "frozen", "Frozen", True),
        ("Stopped", "frozen", "Frozen", True),
        ("Frozen", "started", "Running", True),
        ("Frozen", "present", "Frozen", False),
        ("Stopped", "present", "Stopped", False),
    ],
)
def test_run_states(lxd, run, before, state, after, changed):
    create(lxd, status=before)
    result = run(lxd_instance, {"name": "web", "state": state})
    assert result["changed"] is changed, result
    assert lxd.get(PATH)["status"] == after


def test_restarted_always_changes(lxd, run):
    create(lxd, status="Running")
    for _round in range(2):
        result = run(lxd_instance, {"name": "web", "state": "restarted"})
        assert result["changed"] is True
    assert lxd.get(PATH)["restarts"] == 2


def test_check_mode_state_change_sends_nothing(lxd, run):
    create(lxd, status="Running")
    result = run(lxd_instance, {"name": "web", "state": "stopped"}, check_mode=True)
    assert result["changed"] is True
    assert lxd.writes() == []
    assert lxd.get(PATH)["status"] == "Running"


def test_a_stuck_instance_needs_force_to_stop(lxd, run):
    create(lxd, status="Running")
    lxd.stuck.add("web")
    result = run(lxd_instance, {"name": "web", "state": "stopped"})
    assert result["failed"] is True
    assert "Set force" in result["msg"]
    assert lxd.get(PATH)["status"] == "Running"
    result = run(lxd_instance, {"name": "web", "state": "stopped", "force": True})
    assert result["changed"] is True
    assert lxd.get(PATH)["status"] == "Stopped"


def test_config_change_is_applied_and_shown_in_the_diff(lxd, run):
    create(lxd, status="Running")
    result = run(lxd_instance, {"name": "web", "config": {"limits.cpu": 2}}, diff=True)
    assert result["changed"] is True, result
    assert lxd.get(PATH)["config"]["limits.cpu"] == "2"
    assert result["diff"]["after"]["config"]["limits.cpu"] == "2"
    result = run(lxd_instance, {"name": "web", "config": {"limits.cpu": 2}})
    assert result["changed"] is False, result


def test_absent_stops_a_running_instance_first(lxd, run):
    create(lxd, status="Running")
    result = run(lxd_instance, {"name": "web", "state": "absent"})
    assert result["changed"] is True
    assert lxd.get(PATH) is None
    methods = [(m, target.split("?")[0]) for m, target, _b in lxd.writes()]
    assert ("PUT", PATH + "/state") in methods
    assert methods[-1] == ("DELETE", PATH)


def test_absent_with_force_deletes_at_once(lxd, run):
    create(lxd, status="Running")
    lxd.stuck.add("web")
    result = run(lxd_instance, {"name": "web", "state": "absent", "force": True})
    assert result["changed"] is True
    assert lxd.get(PATH) is None
    assert [m for m, _t, _b in lxd.writes()] == ["DELETE"]


def test_absent_twice(lxd, run):
    create(lxd)
    assert run(lxd_instance, {"name": "web", "state": "absent"})["changed"] is True
    assert run(lxd_instance, {"name": "web", "state": "absent"})["changed"] is False


def test_absent_in_a_project_that_does_not_exist_fails(lxd, run):
    result = run(lxd_instance, {"name": "web", "project": "pord", "state": "absent"})
    assert result["failed"] is True
    assert 'Project "pord" does not exist' in result["msg"]


def test_instances_in_two_projects_are_apart(lxd, run):
    lxd.add("/1.0/projects/blue", {"name": "blue", "config": {}, "description": "", "used_by": []})
    run(lxd_instance, {"name": "web", "source": IMAGE, "state": "stopped"})
    result = run(lxd_instance, {"name": "web", "source": IMAGE, "project": "blue", "state": "stopped"})
    assert result["changed"] is True
    assert lxd.get(PATH) is not None
    assert lxd.get(PATH, "blue") is not None
