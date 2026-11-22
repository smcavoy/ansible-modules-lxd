#!/usr/bin/python
# Copyright (c) 2026, Sean McAvoy
# GNU General Public License v3.0+ (see LICENSES/GPL-3.0-or-later.txt or https://www.gnu.org/licenses/gpl-3.0.txt)
# SPDX-License-Identifier: GPL-3.0-or-later

from __future__ import annotations

DOCUMENTATION = r"""
module: lxd_profile_info
short_description: Read LXD profiles
version_added: "0.1.0"
description:
  - Read the LXD profiles of a project, of all projects, or one profile by name.
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
      - One profile. A missing profile gives an empty list.
    type: str
  all_projects:
    description:
      - Read the profiles of all projects. Mutually exclusive with O(project) and O(name).
    type: bool
    default: false
seealso:
  - module: smcavoy.lxd.lxd_profile
"""

EXAMPLES = r"""
- name: Read all profiles of a project
  smcavoy.lxd.lxd_profile_info:
    project: web
  register: result

- name: Read one profile
  smcavoy.lxd.lxd_profile_info:
    name: default
  register: result
"""

RETURN = r"""
profiles:
  description:
    - The profiles, each with the key C(project).
  returned: always
  type: list
  elements: dict
  sample:
    - name: default
      project: default
      description: Default LXD profile
      config: {}
      devices:
        root:
          type: disk
          path: /
          pool: default
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
    }


def main() -> None:
    """Run the module."""
    mod = LXDModule(get_argument_spec(), mutually_exclusive=[["all_projects", "name"]])

    def read() -> None:
        check_all_projects(mod, "profiles_all_projects")
        if mod.params["name"]:
            profiles = get_item(mod, api_path("profiles", mod.params["name"]))
        else:
            profiles = list_items(mod, "/1.0/profiles")
        mod.exit(False, profiles=profiles)

    mod.run(read)


if __name__ == "__main__":
    main()
