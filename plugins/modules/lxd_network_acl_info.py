#!/usr/bin/python
# Copyright (c) 2026, Sean McAvoy
# GNU General Public License v3.0+ (see LICENSES/GPL-3.0-or-later.txt or https://www.gnu.org/licenses/gpl-3.0.txt)
# SPDX-License-Identifier: GPL-3.0-or-later

from __future__ import annotations

DOCUMENTATION = r"""
module: lxd_network_acl_info
short_description: Read LXD network ACLs
version_added: "0.1.0"
description:
  - Read the network ACLs of a project, of all projects, or one ACL by name.
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
      - One ACL. A missing ACL gives an empty list.
    type: str
  all_projects:
    description:
      - Read the ACLs of all projects. Mutually exclusive with O(project).
    type: bool
    default: false
  include_log:
    description:
      - Add the key C(log) with the ACL log as text. Needs O(name).
      - LXD writes this log only for OVN networks.
    type: bool
    default: false
seealso:
  - module: smcavoy.lxd.lxd_network_acl
"""

EXAMPLES = r"""
- name: Read all ACLs of a project
  smcavoy.lxd.lxd_network_acl_info:
    project: web
  register: result
"""

RETURN = r"""
acls:
  description:
    - The ACLs, each with the key C(project). With O(include_log=true), the ACL has the key C(log).
  returned: always
  type: list
  elements: dict
  sample:
    - name: web-in
      project: default
      description: Allow HTTP in
      ingress:
        - action: allow
          protocol: tcp
          destination_port: "80"
      egress: []
      config: {}
      used_by: []
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
        "include_log": {"type": "bool", "default": False},
    }


def main() -> None:
    """Run the module."""
    mod = LXDModule(get_argument_spec(), extensions=["network_acl"])

    def read() -> None:
        params = mod.params
        check_all_projects(mod, "networks_all_projects")
        if params["name"]:
            acls = get_item(mod, api_path("network-acls", params["name"]))
        else:
            acls = list_items(mod, "/1.0/network-acls")
        if params["include_log"]:
            if params["name"] is None:
                mod.fail("include_log needs name")
            for acl in acls:
                resp = mod.client.request("GET", api_path("network-acls", acl["name"], "log"), query=mod.query())
                acl["log"] = resp.body.decode("utf-8", errors="replace")
        mod.exit(False, acls=acls)

    mod.run(read)


if __name__ == "__main__":
    main()
