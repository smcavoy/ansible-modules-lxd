#!/usr/bin/python
# Copyright (c) 2026, Sean McAvoy
# GNU General Public License v3.0+ (see LICENSES/GPL-3.0-or-later.txt or https://www.gnu.org/licenses/gpl-3.0.txt)
# SPDX-License-Identifier: GPL-3.0-or-later

from __future__ import annotations

DOCUMENTATION = r"""
module: lxd_network_info
short_description: Read LXD networks
version_added: "0.1.0"
description:
  - Read the LXD networks of a project, of all projects, or one network by name.
  - Optionally add the runtime state and the DHCP leases.
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
      - One network. A missing network gives an empty list.
    type: str
  all_projects:
    description:
      - Read the networks of all projects. Mutually exclusive with O(project).
    type: bool
    default: false
  managed_only:
    description:
      - Leave out the host interfaces that LXD does not manage.
    type: bool
    default: true
  include_state:
    description:
      - Add the key C(state) with the runtime state of each network.
    type: bool
    default: false
  include_leases:
    description:
      - Add the key C(leases) with the DHCP leases of each managed V(bridge) or V(ovn) network.
    type: bool
    default: false
  target:
    description:
      - On a cluster, read the state and the leases of this member.
    type: str
seealso:
  - module: smcavoy.lxd.lxd_network
"""

EXAMPLES = r"""
- name: Read a bridge with its state and leases
  smcavoy.lxd.lxd_network_info:
    name: lxdbr0
    include_state: true
    include_leases: true
  register: result
"""

RETURN = r"""
networks:
  description:
    - The networks, each with the key C(project). The module masks the values of C(bgp.peers.<name>.password).
    - With O(include_state=true), each network has the key C(state). With O(include_leases=true), managed bridges have C(leases).
  returned: always
  type: list
  elements: dict
  sample:
    - name: lxdbr0
      project: default
      type: bridge
      managed: true
      status: Created
      config:
        ipv4.address: 10.99.0.1/24
      state:
        state: up
      leases:
        - hostname: web1
          address: 10.99.0.23
          type: dynamic
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
        "managed_only": {"type": "bool", "default": True},
        "include_state": {"type": "bool", "default": False},
        "include_leases": {"type": "bool", "default": False},
        "target": {"type": "str"},
    }


def main() -> None:
    """Run the module."""
    mod = LXDModule(get_argument_spec(), extensions=["network"])
    # The password of a BGP peer.
    mod.hide_secrets(r"^bgp\.peers\.[^.]+\.password$")

    def read() -> None:
        params = mod.params
        check_all_projects(mod, "networks_all_projects")
        if params["name"]:
            networks = get_item(mod, api_path("networks", params["name"]))
        else:
            networks = list_items(mod, "/1.0/networks")
        if params["managed_only"]:
            networks = [net for net in networks if net.get("managed")]
        for net in networks:
            query = {"target": params["target"]} if params["target"] else {}
            if net.get("project"):
                query["project"] = net["project"]
            if params["include_state"]:
                state, _etag = mod.client.get_or_none(api_path("networks", net["name"], "state"), query)
                net["state"] = state
            if params["include_leases"] and net.get("managed") and net.get("type") in ("bridge", "ovn"):
                leases, _etag = mod.client.get_or_none(api_path("networks", net["name"], "leases"), query)
                net["leases"] = leases or []
        mod.exit(False, networks=networks)

    mod.run(read)


if __name__ == "__main__":
    main()
