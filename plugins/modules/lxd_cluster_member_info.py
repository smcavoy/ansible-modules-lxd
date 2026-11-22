#!/usr/bin/python
# Copyright (c) 2026, Sean McAvoy
# GNU General Public License v3.0+ (see LICENSES/GPL-3.0-or-later.txt or https://www.gnu.org/licenses/gpl-3.0.txt)
# SPDX-License-Identifier: GPL-3.0-or-later

from __future__ import annotations

DOCUMENTATION = r"""
module: lxd_cluster_member_info
short_description: Read LXD cluster members
version_added: "0.1.0"
description:
  - Read all cluster members, or one member by name, optionally with system info and pool usage.
  - On a standalone server, the module returns an empty list and RV(clustered=false).
author:
  - Sean McAvoy (@smcavoy)
extends_documentation_fragment:
  - smcavoy.lxd._attributes
  - smcavoy.lxd._attributes.info_module
  - smcavoy.lxd._attributes.action_group
  - smcavoy.lxd._connection
options:
  name:
    description:
      - One member. A missing member gives an empty list.
    type: str
  include_state:
    description:
      - Add the key C(state) with the system info and the pool usage of each member.
    type: bool
    default: false
seealso:
  - module: smcavoy.lxd.lxd_cluster_member
"""

EXAMPLES = r"""
- name: Read the members with their state
  smcavoy.lxd.lxd_cluster_member_info:
    include_state: true
  register: result

- name: Print the members that are not online
  ansible.builtin.debug:
    msg: "{{ result.members | rejectattr('status', 'eq', 'Online') | map(attribute='server_name') | list }}"
"""

RETURN = r"""
clustered:
  description:
    - Whether the server is part of a cluster.
  returned: always
  type: bool
  sample: true
members:
  description:
    - The members. With O(include_state=true), each member has the key C(state).
  returned: always
  type: list
  elements: dict
  sample:
    - server_name: node1
      url: https://10.0.0.11:8443
      status: Online
      roles:
        - database-leader
        - database
      groups:
        - default
"""

import typing as t

from ansible_collections.smcavoy.lxd.plugins.module_utils._client import api_path
from ansible_collections.smcavoy.lxd.plugins.module_utils._module import LXDModule

if t.TYPE_CHECKING:  # pragma: no cover
    from ansible_collections.smcavoy.lxd.plugins.module_utils._typing import ArgumentSpecMutT


def get_argument_spec() -> ArgumentSpecMutT:
    """Return the argument spec of the module."""
    return {
        "name": {"type": "str"},
        "include_state": {"type": "bool", "default": False},
    }


def main() -> None:
    """Run the module."""
    mod = LXDModule(get_argument_spec())

    def read() -> None:
        params = mod.params
        if not mod.client.is_clustered():
            mod.exit(False, clustered=False, members=[])
        if params["name"]:
            member, _etag = mod.client.get_or_none(api_path("cluster", "members", params["name"]))
            members = [member] if member else []
        else:
            items, _etag = mod.client.get("/1.0/cluster/members", {"recursion": 1})
            members = list(items or [])
        if params["include_state"]:
            if mod.client.missing_extensions(["cluster_member_state"]):
                mod.fail("LXD server lacks the API extension cluster_member_state, which include_state needs")
            for member in members:
                state, _etag = mod.client.get_or_none(api_path("cluster", "members", member["server_name"], "state"))
                member["state"] = state
        mod.exit(False, clustered=True, members=members)

    mod.run(read)


if __name__ == "__main__":
    main()
