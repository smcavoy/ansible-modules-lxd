#!/usr/bin/python
# Copyright (c) 2026, Sean McAvoy
# GNU General Public License v3.0+ (see LICENSES/GPL-3.0-or-later.txt or https://www.gnu.org/licenses/gpl-3.0.txt)
# SPDX-License-Identifier: GPL-3.0-or-later

from __future__ import annotations

DOCUMENTATION = r"""
module: lxd_warning
short_description: Acknowledge or delete LXD warnings
version_added: "0.1.0"
description:
  - Set the status of a warning to C(acknowledged) or back to C(new), or delete the warning.
  - A module cannot create a warning. Only LXD creates warnings.
author:
  - Sean McAvoy (@smcavoy)
extends_documentation_fragment:
  - smcavoy.lxd._attributes
  - smcavoy.lxd._attributes.action_group
  - smcavoy.lxd._connection
attributes:
  check_mode:
    support: full
  diff_mode:
    support: full
  idempotent:
    support: full
options:
  uuid:
    description:
      - The warning UUID. Use M(smcavoy.lxd.lxd_warning_info) to find it.
    type: str
    required: true
  state:
    description:
      - The wanted state of the warning.
    type: str
    choices:
      present: The warning exists. The module fails when it does not exist.
      absent: The warning does not exist. LXD makes a new warning when the cause comes back.
    default: present
  status:
    description:
      - The wanted status of the warning.
      - If not set, the module does not manage the status.
      - LXD sets the status C(resolved) itself. The module cannot set it.
    type: str
    choices: ["new", "acknowledged"]
seealso:
  - module: smcavoy.lxd.lxd_warning_info
"""

EXAMPLES = r"""
- name: Read the new warnings
  smcavoy.lxd.lxd_warning_info:
    status:
      - new
  register: result

- name: Acknowledge them
  smcavoy.lxd.lxd_warning:
    uuid: "{{ item.uuid }}"
    status: acknowledged
  loop: "{{ result.lxd_warnings }}"
"""

RETURN = r"""
warning:
  description:
    - The warning after the change, as LXD returns it.
    - In check mode, the predicted warning.
    - V(null) after a delete.
  returned: always
  type: dict
  sample:
    uuid: e9f1b4a0-4a43-4c0f-9a6b-0b5f8a0c1d2e
    type: Couldn't find the CGroup memory swap accounting
    severity: low
    status: acknowledged
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
        "uuid": {"type": "str", "required": True},
        "state": {"type": "str", "default": "present", "choices": ["present", "absent"]},
        "status": {"type": "str", "choices": ["new", "acknowledged"]},
    }


def main() -> None:
    """Run the module."""
    mod = LXDModule(get_argument_spec(), extensions=["warnings"])
    params = mod.params
    path = api_path("warnings", params["uuid"])

    def present() -> None:
        current, _etag = mod.client.get_or_none(path)
        if current is None:
            mod.fail(f"warning {params['uuid']} not found")
        before = {"status": current.get("status")}
        if params["status"] is None or current.get("status") == params["status"]:
            mod.exit(False, before=before, after=before, warning=current)
        mod.write("PUT", path, body={"status": params["status"]})
        after = {"status": params["status"]}
        warning = dict(current, status=params["status"])
        if not mod.check_mode:
            warning = mod.client.get_or_none(path)[0] or warning
        mod.exit(True, before=before, after=after, warning=warning)

    def absent() -> None:
        current, _etag = mod.client.get_or_none(path)
        if current is None:
            mod.exit(False, before={}, after={}, warning=None)
        mod.write("DELETE", path)
        mod.exit(True, before={"status": current.get("status")}, after={}, warning=None)

    mod.run(present if params["state"] == "present" else absent)


if __name__ == "__main__":
    main()
