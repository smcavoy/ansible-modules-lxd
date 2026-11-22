#!/usr/bin/python
# Copyright (c) 2026, Sean McAvoy
# GNU General Public License v3.0+ (see LICENSES/GPL-3.0-or-later.txt or https://www.gnu.org/licenses/gpl-3.0.txt)
# SPDX-License-Identifier: GPL-3.0-or-later

from __future__ import annotations

DOCUMENTATION = r"""
module: lxd_replicator_info
short_description: Read LXD replicators
version_added: "0.1.0"
description:
  - Read all replicators of a project, or one replicator by name, with their last run.
author:
  - Sean McAvoy (@smcavoy)
extends_documentation_fragment:
  - smcavoy.lxd._attributes
  - smcavoy.lxd._attributes.info_module
  - smcavoy.lxd._attributes.action_group
  - smcavoy.lxd._connection
  - smcavoy.lxd._project
options:
  name:
    description:
      - One replicator. A missing replicator gives an empty list.
    type: str
  all_projects:
    description:
      - Read the replicators of all projects. Mutually exclusive with O(project) and O(name).
    type: bool
    default: false
  include_state:
    description:
      - Add the key C(state) with the current C(status) of each replicator. This costs one more request per replicator.
      - The status is V(Pending) before the first run, then V(Running), V(Completed), or V(Failed).
    type: bool
    default: false
seealso:
  - module: smcavoy.lxd.lxd_replicator
  - module: smcavoy.lxd.lxd_replicator_run
"""

EXAMPLES = r"""
- name: Read the replicators of the project web with their status
  smcavoy.lxd.lxd_replicator_info:
    project: web
    include_state: true
  register: result

- name: Fail when the last run failed
  ansible.builtin.assert:
    that: result.replicators | selectattr('last_run_status', 'eq', 'Failed') | list == []
"""

RETURN = r"""
replicators:
  description:
    - The replicators, as LXD returns them.
  returned: always
  type: list
  elements: dict
  sample:
    - name: web-dr
      project: web
      description: ""
      config:
        cluster: dr-site
        schedule: "@daily"
      last_run_at: "2026-11-07T06:00:00Z"
      last_run_status: Completed
      last_success_at: "2026-11-07T06:00:00Z"
      state:
        status: Completed
"""

import typing as t

from ansible_collections.smcavoy.lxd.plugins.module_utils._client import api_path
from ansible_collections.smcavoy.lxd.plugins.module_utils._info import check_all_projects, get_item, list_items
from ansible_collections.smcavoy.lxd.plugins.module_utils._module import LXDModule

if t.TYPE_CHECKING:  # pragma: no cover
    from ansible_collections.smcavoy.lxd.plugins.module_utils._typing import ArgumentSpecMutT


def get_argument_spec() -> ArgumentSpecMutT:
    """Return the argument spec of the module."""
    return {
        "name": {"type": "str"},
        "project": {"type": "str"},
        "all_projects": {"type": "bool", "default": False},
        "include_state": {"type": "bool", "default": False},
    }


def main() -> None:
    """Run the module."""
    mod = LXDModule(get_argument_spec(), extensions=["replicators"], mutually_exclusive=[["name", "all_projects"]])

    def read() -> None:
        params = mod.params
        check_all_projects(mod, None)
        if params["name"]:
            replicators = get_item(mod, api_path("replicators", params["name"]))
        else:
            replicators = list_items(mod, "/1.0/replicators")
        if params["include_state"]:
            for replicator in replicators:
                state, _etag = mod.client.get(api_path("replicators", replicator["name"], "state"), {"project": replicator["project"]})
                replicator["state"] = state
        mod.exit(False, replicators=replicators)

    mod.run(read)


if __name__ == "__main__":
    main()
