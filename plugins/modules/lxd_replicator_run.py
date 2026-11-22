#!/usr/bin/python
# Copyright (c) 2026, Sean McAvoy
# GNU General Public License v3.0+ (see LICENSES/GPL-3.0-or-later.txt or https://www.gnu.org/licenses/gpl-3.0.txt)
# SPDX-License-Identifier: GPL-3.0-or-later

from __future__ import annotations

DOCUMENTATION = r"""
module: lxd_replicator_run
short_description: Run an LXD replicator
version_added: "0.1.0"
description:
  - Start a replicator run now. The run copies the instances of the project to the other cluster, or copies them back with O(mode=restore).
  - This is an action module. It reports a change each time that it starts a run.
author:
  - Sean McAvoy (@smcavoy)
extends_documentation_fragment:
  - smcavoy.lxd._attributes
  - smcavoy.lxd._attributes.action_group
  - smcavoy.lxd._connection
  - smcavoy.lxd._project
attributes:
  check_mode:
    support: full
    details:
      - Check mode starts no run. It reports a change unless a run is in progress.
  diff_mode:
    support: none
  idempotent:
    support: none
    details:
      - Each run of the task starts a replicator run.
options:
  name:
    description:
      - The replicator.
    type: str
    required: true
  mode:
    description:
      - What the run does.
    type: str
    choices:
      start: Copy the instances of the project here to the project on the other cluster.
        The project here must be in C(leader) mode, and the project on the other cluster in C(standby) mode.
      restore: Copy the instances of the project on the other cluster back to the project here.
        The project here must be in C(standby) mode, and the project on the other cluster in C(leader) mode.
        All instances of the project here must be stopped.
    default: start
  wait:
    description:
      - Wait for the run to end. With V(false), the module returns after LXD starts the run.
    type: bool
    default: true
notes:
  - When a run is in progress, the module starts no run. It warns and reports no change.
  - A restore also creates the instances that exist only on the other cluster. It deletes no instance here.
  - A replicator cannot restore a project that Ceph RBD mirrors.
  - In LXD 6.10.1, a restore looks for the profiles of an instance in the project itself, also when the project has C(features.profiles=false).
    The restore then fails with C(Profile "default" not found). Give a replicated project its own profiles.
seealso:
  - module: smcavoy.lxd.lxd_replicator
  - module: smcavoy.lxd.lxd_replicator_info
  - module: smcavoy.lxd.lxd_project
"""

EXAMPLES = r"""
- name: Copy the project web to the other cluster now
  smcavoy.lxd.lxd_replicator_run:
    name: web-dr
    project: web

- name: After a failover, copy the instances back from the other cluster
  smcavoy.lxd.lxd_replicator_run:
    name: web-dr
    project: web
    mode: restore
"""

RETURN = r"""
status:
  description:
    - The status of the replicator after the run, or after the start with O(wait=false).
    - V(Pending), V(Running), V(Completed), or V(Failed).
  returned: always
  type: str
  sample: Completed
operation:
  description:
    - The ID of the LXD operation of the run.
  returned: when the module starts a run, and not in check mode
  type: str
  sample: 01a1a00a-6ae7-7412-8972-aea8529f209b
"""

import typing as t

from ansible_collections.smcavoy.lxd.plugins.module_utils._client import LXDClientError, api_path
from ansible_collections.smcavoy.lxd.plugins.module_utils._module import LXDModule

if t.TYPE_CHECKING:  # pragma: no cover
    from ansible_collections.smcavoy.lxd.plugins.module_utils._typing import ArgumentSpecMutT

RUNNING = "Running"


def child_errors(mod: LXDModule, operation: str) -> list[str]:
    """Return the errors of the child operations of a run. LXD reports only "One or more child operations failed" on the parent."""
    try:
        parent, _etag = mod.client.get(api_path("operations", operation), {"recursion": 1})
    except LXDClientError:
        return []
    children = (parent or {}).get("children") or []
    return [str(child.get("err")) for child in children if isinstance(child, dict) and child.get("err")]


def get_argument_spec() -> ArgumentSpecMutT:
    """Return the argument spec of the module."""
    return {
        "name": {"type": "str", "required": True},
        "project": {"type": "str"},
        "mode": {"type": "str", "default": "start", "choices": ["start", "restore"]},
        "wait": {"type": "bool", "default": True},
    }


def main() -> None:
    """Run the module."""
    mod = LXDModule(get_argument_spec(), extensions=["replicators"])

    def run() -> None:
        params = mod.params
        path = api_path("replicators", params["name"], "state")
        state, _etag = mod.client.get(path, mod.query())
        status = (state or {}).get("status") or ""
        if status == RUNNING:
            mod.warn(f"Replicator {params['name']} has a run in progress. The module started no run.")
            mod.exit(False, status=status)
        if mod.check_mode:
            mod.exit(True, status=status)
        resp = mod.client.request("PUT", path, query=mod.query(), body={"action": params["mode"]})
        operation = str(resp.envelope.get("operation") or "").rstrip("/").rsplit("/", 1)[-1]
        if params["wait"] and operation:
            try:
                mod.client.wait_operation(operation)
            except LXDClientError as exc:
                errors = child_errors(mod, operation)
                mod.fail(exc.message + ("" if not errors else ": " + "; ".join(errors)), operation=operation)
        state, _etag = mod.client.get(path, mod.query())
        mod.exit(True, status=(state or {}).get("status") or "", operation=operation)

    mod.run(run)


if __name__ == "__main__":
    main()
