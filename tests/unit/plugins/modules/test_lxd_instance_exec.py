# Copyright (c) 2026, Sean McAvoy
# GNU General Public License v3.0+ (see LICENSES/GPL-3.0-or-later.txt or https://www.gnu.org/licenses/gpl-3.0.txt)
# SPDX-License-Identifier: GPL-3.0-or-later

"""lxd_instance_exec when the result of the command is unknown."""

from __future__ import annotations

import pytest

from ansible_collections.smcavoy.lxd.plugins.module_utils._client import LXDClient, LXDClientError
from ansible_collections.smcavoy.lxd.plugins.modules import lxd_instance_exec


@pytest.fixture
def lxd_web(lxd):
    lxd.add("/1.0/instances/web", {"name": "web", "type": "container", "status": "Running", "config": {}, "devices": {}, "profiles": ["default"]})
    return lxd


def fail_write_with(monkeypatch, error):
    def write(self, method, path, query=None, body=None, etag=None, headers=None, raw=None):
        raise error

    monkeypatch.setattr(LXDClient, "write", write)


def test_lost_operation_says_that_the_command_can_still_run(lxd_web, run, monkeypatch):
    # Seen live on LXD 6.10.1: a restart of LXD during the command loses the operation, and the command
    # runs to its end in the instance. "Run the task again" would run it twice.
    lost = "LXD does not know operation op1 any more (Operation not found)."
    fail_write_with(monkeypatch, LXDClientError(f"{lost} LXD restarted. Run the task again.", operation="op1", outcome_unknown=True, detail=lost))
    result = run(lxd_instance_exec, {"instance": "web", "command": ["sh", "-c", "sleep 60"]})
    assert result["failed"] is True
    assert result["changed"] is True
    assert result["msg"].startswith(lost)
    assert "The command can still run in the instance" in result["msg"]
    assert "Run the task again" not in result["msg"]


def test_a_failed_command_operation_is_not_an_unknown_outcome(lxd_web, run, monkeypatch):
    fail_write_with(monkeypatch, LXDClientError("LXD operation op1 failed: Command not found", operation="op1"))
    monkeypatch.setattr(lxd_instance_exec.ExecModule, "failed_outputs", lambda self, operation: {})
    result = run(lxd_instance_exec, {"instance": "web", "command": ["nope"], "ok_rc": [127]})
    assert result.get("failed") is not True, result
    assert result["rc"] == 127
