#!/usr/bin/python
# Copyright (c) 2026, Sean McAvoy
# GNU General Public License v3.0+ (see LICENSES/GPL-3.0-or-later.txt or https://www.gnu.org/licenses/gpl-3.0.txt)
# SPDX-License-Identifier: GPL-3.0-or-later

from __future__ import annotations

DOCUMENTATION = r"""
module: lxd_warning_info
short_description: Read LXD warnings
version_added: "0.1.0"
description:
  - Read the warnings of the server and its projects, or one warning by UUID.
author:
  - Sean McAvoy (@smcavoy)
extends_documentation_fragment:
  - smcavoy.lxd._attributes
  - smcavoy.lxd._attributes.info_module
  - smcavoy.lxd._attributes.action_group
  - smcavoy.lxd._connection
  - smcavoy.lxd._project
options:
  uuid:
    description:
      - One warning. A missing warning gives an empty list.
    type: str
  all_projects:
    description:
      - Read the warnings of all projects and the server warnings.
      - A task that sets O(project) reads only the warnings of that project.
      - With V(false) and no O(project), the module reads the warnings of the project C(default).
    type: bool
    default: true
  status:
    description:
      - Keep only the warnings with one of these statuses.
    type: list
    elements: str
    choices: ["new", "acknowledged", "resolved"]
  severity:
    description:
      - Keep only the warnings with one of these severities.
    type: list
    elements: str
    choices: ["low", "moderate", "high"]
seealso:
  - module: smcavoy.lxd.lxd_warning
"""

EXAMPLES = r"""
- name: Read the new warnings with a high severity
  smcavoy.lxd.lxd_warning_info:
    status:
      - new
    severity:
      - high
  register: result
"""

RETURN = r"""
lxd_warnings:
  description:
    - The warnings, as LXD returns them.
    - The key is not C(warnings), because Ansible uses that key for the warnings of a task.
  returned: always
  type: list
  elements: dict
  sample:
    - uuid: e9f1b4a0-4a43-4c0f-9a6b-0b5f8a0c1d2e
      type: Couldn't find the CGroup memory swap accounting
      severity: low
      status: new
      count: 1
      location: none
      project: ""
      last_message: ""
"""

import typing as t

from ansible_collections.smcavoy.lxd.plugins.module_utils._client import api_path
from ansible_collections.smcavoy.lxd.plugins.module_utils._module import LXDModule

if t.TYPE_CHECKING:  # pragma: no cover
    from ansible_collections.smcavoy.lxd.plugins.module_utils._typing import ArgumentSpecMutT


def get_argument_spec() -> ArgumentSpecMutT:
    """Return the argument spec of the module."""
    return {
        "uuid": {"type": "str"},
        "project": {"type": "str"},
        "all_projects": {"type": "bool", "default": True},
        "status": {"type": "list", "elements": "str", "choices": ["new", "acknowledged", "resolved"]},
        "severity": {"type": "list", "elements": "str", "choices": ["low", "moderate", "high"]},
    }


def main() -> None:
    """Run the module."""
    mod = LXDModule(get_argument_spec(), extensions=["warnings"])

    def read() -> None:
        params = mod.params
        if params["uuid"]:
            item, _etag = mod.client.get_or_none(api_path("warnings", params["uuid"]))
            warnings = [item] if isinstance(item, dict) else []
        else:
            query: dict[str, t.Any] = {"recursion": 1}
            if params["project"]:
                query["project"] = params["project"]
            elif not params["all_projects"]:
                query["project"] = "default"
            items, _etag = mod.client.get("/1.0/warnings", query)
            warnings = [item for item in items or [] if isinstance(item, dict)]
        if params["status"]:
            warnings = [item for item in warnings if str(item.get("status") or "").lower() in params["status"]]
        if params["severity"]:
            warnings = [item for item in warnings if str(item.get("severity") or "").lower() in params["severity"]]
        mod.exit(False, lxd_warnings=warnings)

    mod.run(read)


if __name__ == "__main__":
    main()
