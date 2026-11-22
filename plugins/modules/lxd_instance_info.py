#!/usr/bin/python
# Copyright (c) 2026, Sean McAvoy
# GNU General Public License v3.0+ (see LICENSES/GPL-3.0-or-later.txt or https://www.gnu.org/licenses/gpl-3.0.txt)
# SPDX-License-Identifier: GPL-3.0-or-later

from __future__ import annotations

DOCUMENTATION = r"""
module: lxd_instance_info
short_description: Read LXD instances
version_added: "0.1.0"
description:
  - Read LXD instances with their config, run state, and addresses.
  - Read one instance by name, the instances of a project or of all projects, or the instances that match a filter.
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
      - One instance. A missing instance gives an empty list.
      - With O(all_projects=true), the instances of this name in all projects.
    type: str
  all_projects:
    description:
      - Read the instances of all projects. Mutually exclusive with O(project).
      - With O(name), the module reads the list of all projects with a filter on the name, because LXD has no request for one instance
        in all projects.
    type: bool
    default: false
  filter:
    description:
      - An LXD filter expression, for example V(status eq Running). Mutually exclusive with O(name).
    type: str
  include_state:
    description:
      - Add the key C(state) with the run state, the addresses, and the usage. With V(false), the read is faster.
    type: bool
    default: true
  include_snapshots:
    description:
      - Add the key C(snapshots).
    type: bool
    default: false
seealso:
  - module: smcavoy.lxd.lxd_instance
"""

EXAMPLES = r"""
- name: Read the running instances
  smcavoy.lxd.lxd_instance_info:
    filter: status eq Running
  register: result

- name: Print the IPv4 addresses of eth0
  ansible.builtin.debug:
    msg: "{{ item.name }}: {{ item.state.network.eth0.addresses | selectattr('family', 'eq', 'inet') | map(attribute='address') | list }}"
  loop: "{{ result.instances }}"
"""

RETURN = r"""
instances:
  description:
    - The instances, each with the key C(project).
    - With O(include_state=true), each instance has the key C(state). With O(include_snapshots=true), the key C(snapshots).
  returned: always
  type: list
  elements: dict
  sample:
    - name: web1
      project: default
      type: container
      status: Running
      config:
        limits.cpu: "2"
      state:
        status: Running
        network:
          eth0:
            addresses:
              - family: inet
                address: 10.99.0.23
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
        "filter": {"type": "str"},
        "include_state": {"type": "bool", "default": True},
        "include_snapshots": {"type": "bool", "default": False},
    }


def main() -> None:
    """Run the module."""
    mod = LXDModule(get_argument_spec(), extensions=["instances"], mutually_exclusive=[["name", "filter"]])

    def read() -> None:
        params = mod.params
        check_all_projects(mod, "instance_all_projects")
        full = params["include_state"] or params["include_snapshots"]
        if params["name"] and params["all_projects"]:
            # LXD answers GET /1.0/instances/<name>?all-projects=true with HTTP 400, so read the list with a filter.
            if mod.client.missing_extensions(["api_filtering"]):
                mod.fail("LXD server lacks the API extension api_filtering, which name with all_projects needs")
            found = list_items(mod, "/1.0/instances", recursion=2 if full else 1, filter=f"name eq {params['name']}")
            # The filter of LXD ignores the case of the value.
            instances = [instance for instance in found if instance.get("name") == params["name"]]
        elif params["name"]:
            instances = get_item(mod, api_path("instances", params["name"]), recursion=1 if full else None)
        else:
            extra = {}
            if params["filter"]:
                missing = mod.client.missing_extensions(["api_filtering"])
                if missing:
                    mod.fail("LXD server lacks the API extension api_filtering, which filter needs")
                extra["filter"] = params["filter"]
            instances = list_items(mod, "/1.0/instances", recursion=2 if full else 1, **extra)
        for instance in instances:
            if not params["include_state"]:
                instance.pop("state", None)
            if not params["include_snapshots"]:
                instance.pop("snapshots", None)
            instance.pop("backups", None)
        mod.exit(False, instances=instances)

    mod.run(read)


if __name__ == "__main__":
    main()
