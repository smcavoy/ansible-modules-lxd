#!/usr/bin/python
# Copyright (c) 2026, Sean McAvoy
# GNU General Public License v3.0+ (see LICENSES/GPL-3.0-or-later.txt or https://www.gnu.org/licenses/gpl-3.0.txt)
# SPDX-License-Identifier: GPL-3.0-or-later

from __future__ import annotations

DOCUMENTATION = r"""
module: lxd_network_allocation_info
short_description: Read the addresses that LXD networks use
version_added: "0.1.0"
description:
  - Read the addresses that networks, instances, forwards, and load balancers use, in one project or in all projects.
author:
  - Sean McAvoy (@smcavoy)
extends_documentation_fragment:
  - smcavoy.lxd._attributes
  - smcavoy.lxd._attributes.info_module
  - smcavoy.lxd._attributes.action_group
  - smcavoy.lxd._connection
  - smcavoy.lxd._project
options:
  all_projects:
    description:
      - Read the allocations of all projects. Mutually exclusive with O(project).
    type: bool
    default: false
  network:
    description:
      - Keep only the allocations on this network. A missing network gives an empty list.
    type: str
  type:
    description:
      - Keep only the allocations of this type.
    type: str
    choices: ["network", "uplink", "instance", "network-forward", "network-load-balancer"]
seealso:
  - module: smcavoy.lxd.lxd_network_info
"""

EXAMPLES = r"""
- name: Read the instance addresses on lxdbr0
  smcavoy.lxd.lxd_network_allocation_info:
    network: lxdbr0
    type: instance
  register: result

- name: Print the addresses
  ansible.builtin.debug:
    msg: "{{ result.allocations | map(attribute='addresses') | list }}"
"""

RETURN = r"""
allocations:
  description:
    - The allocations, as LXD returns them.
  returned: always
  type: list
  elements: dict
  sample:
    - addresses: 10.99.0.12/32
      used_by: /1.0/instances/c1
      type: instance
      nat: false
      hwaddr: 00:16:3e:aa:bb:cc
      network: lxdbr0
"""

import typing as t

from ansible_collections.smcavoy.lxd.plugins.module_utils._info import check_all_projects
from ansible_collections.smcavoy.lxd.plugins.module_utils._module import LXDModule

if t.TYPE_CHECKING:  # pragma: no cover
    from ansible_collections.smcavoy.lxd.plugins.module_utils._typing import ArgumentSpecMutT


def get_argument_spec() -> ArgumentSpecMutT:
    """Return the argument spec of the module."""
    return {
        "project": {"type": "str"},
        "all_projects": {"type": "bool", "default": False},
        "network": {"type": "str"},
        "type": {"type": "str", "choices": ["network", "uplink", "instance", "network-forward", "network-load-balancer"]},
    }


def main() -> None:
    """Run the module."""
    mod = LXDModule(get_argument_spec(), extensions=["network_allocations"])

    def read() -> None:
        params = mod.params
        check_all_projects(mod, None)
        query = mod.query()
        if params["all_projects"]:
            query["all-projects"] = "true"
        items, _etag = mod.client.get("/1.0/network-allocations", query)
        allocations = [item for item in items or [] if isinstance(item, dict)]
        if params["network"]:
            allocations = [item for item in allocations if item.get("network") == params["network"]]
        if params["type"]:
            allocations = [item for item in allocations if item.get("type") == params["type"]]
        mod.exit(False, allocations=allocations)

    mod.run(read)


if __name__ == "__main__":
    main()
