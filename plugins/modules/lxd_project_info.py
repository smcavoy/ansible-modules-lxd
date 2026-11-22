#!/usr/bin/python
# Copyright (c) 2026, Sean McAvoy
# GNU General Public License v3.0+ (see LICENSES/GPL-3.0-or-later.txt or https://www.gnu.org/licenses/gpl-3.0.txt)
# SPDX-License-Identifier: GPL-3.0-or-later

from __future__ import annotations

DOCUMENTATION = r"""
module: lxd_project_info
short_description: Read LXD projects
version_added: "0.1.0"
description:
  - Read all LXD projects, or one project by name, optionally with usage and limits.
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
      - One project. A missing project gives an empty list.
    type: str
  include_state:
    description:
      - Add the key C(state) with the usage and limits of each project. This sends one more request per project.
      - LXD returns the fields of each resource as C(Limit) and C(Usage), with capital letters. A C(Limit) of V(-1) means no limit.
    type: bool
    default: false
seealso:
  - module: smcavoy.lxd.lxd_project
"""

EXAMPLES = r"""
- name: Read all projects with their usage
  smcavoy.lxd.lxd_project_info:
    include_state: true
  register: result
"""

RETURN = r"""
projects:
  description:
    - The projects. With O(include_state=true), each project has the key C(state).
  returned: always
  type: list
  elements: dict
  sample:
    - name: default
      description: Default LXD project
      config:
        features.images: "true"
      used_by: []
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
    mod = LXDModule(get_argument_spec(), extensions=["projects"])

    def read() -> None:
        if mod.params["name"]:
            project, _etag = mod.client.get_or_none(api_path("projects", mod.params["name"]))
            projects = [project] if project else []
        else:
            items, _etag = mod.client.get("/1.0/projects", {"recursion": 1})
            projects = list(items or [])
        if mod.params["include_state"]:
            missing = mod.client.missing_extensions(["project_usage"])
            if missing:
                mod.fail("LXD server lacks the API extension project_usage, which include_state needs")
            for project in projects:
                state, _etag = mod.client.get(api_path("projects", project["name"], "state"))
                project["state"] = state
        mod.exit(False, projects=projects)

    mod.run(read)


if __name__ == "__main__":
    main()
