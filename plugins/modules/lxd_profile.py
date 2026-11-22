#!/usr/bin/python
# Copyright (c) 2026, Sean McAvoy
# GNU General Public License v3.0+ (see LICENSES/GPL-3.0-or-later.txt or https://www.gnu.org/licenses/gpl-3.0.txt)
# SPDX-License-Identifier: GPL-3.0-or-later

from __future__ import annotations

DOCUMENTATION = r"""
module: lxd_profile
short_description: Manage LXD profiles
version_added: "0.1.0"
description:
  - Create, update, and delete LXD profiles, with their config, devices, and description.
  - LXD applies a profile change to every instance that uses the profile.
author:
  - Sean McAvoy (@smcavoy)
extends_documentation_fragment:
  - smcavoy.lxd._attributes
  - smcavoy.lxd._attributes.action_group
  - smcavoy.lxd._connection
  - smcavoy.lxd._project
  - smcavoy.lxd._config
  - smcavoy.lxd._config.devices
attributes:
  check_mode:
    support: full
  diff_mode:
    support: full
  idempotent:
    support: full
options:
  name:
    description:
      - The profile name.
    type: str
    required: true
  state:
    description:
      - The wanted state of the profile.
    type: str
    choices:
      present: The profile exists.
      absent: The profile does not exist.
    default: present
  description:
    description:
      - The profile description.
      - If not set, the module does not manage the description.
    type: str
notes:
  - LXD saves a profile change even when the change fails on some instances.
    The module then fails with the LXD error and reports RV(ignore:changed=true).
seealso:
  - module: smcavoy.lxd.lxd_instance
  - name: LXD profiles
    description: The LXD documentation about profiles.
    link: https://documentation.ubuntu.com/lxd/latest/profiles/
"""

EXAMPLES = r"""
- name: Create a profile with a CPU limit and a NIC
  smcavoy.lxd.lxd_profile:
    name: web
    config:
      limits.cpu: 2
    devices:
      eth0:
        type: nic
        network: lxdbr0
        name: eth0

- name: Remove the profile
  smcavoy.lxd.lxd_profile:
    name: web
    state: absent
"""

RETURN = r"""
profile:
  description:
    - The profile after the change, as LXD returns it.
    - In check mode, the predicted profile.
    - V(null) after a delete.
  returned: always
  type: dict
  sample:
    name: web
    project: default
    description: ""
    config:
      limits.cpu: "2"
    devices:
      eth0:
        type: nic
        network: lxdbr0
        name: eth0
    used_by: []
"""

import typing as t

from ansible_collections.smcavoy.lxd.plugins.module_utils._client import LXDClientError, api_path
from ansible_collections.smcavoy.lxd.plugins.module_utils._config import COMPUTED_KEYS, normalize_device
from ansible_collections.smcavoy.lxd.plugins.module_utils._module import LXDModule
from ansible_collections.smcavoy.lxd.plugins.module_utils._resource import create_config, plan_common

if t.TYPE_CHECKING:  # pragma: no cover
    from ansible_collections.smcavoy.lxd.plugins.module_utils._typing import ArgumentSpecMutT

FIELDS = ("description", "config", "devices")


class ProfileModule:
    """Manage one LXD profile."""

    def __init__(self, mod: LXDModule) -> None:
        self.mod = mod
        self.name: str = mod.params["name"]
        self.path = api_path("profiles", self.name)

    def read(self) -> tuple[dict[str, t.Any] | None, str | None]:
        """Read the profile."""
        return self.mod.client.get_or_none(self.path, self.mod.query())

    def present(self) -> None:
        """Make sure that the profile exists with the wanted settings."""
        params = self.mod.params
        current, etag = self.read()
        if current is None:
            devices = {name: normalize_device(name, props) for name, props in (params["devices"] or {}).items() if props is not None}
            body = {
                "name": self.name,
                "description": params["description"] or "",
                "config": create_config(self.mod),
                "devices": devices,
            }
            self.mod.write("POST", "/1.0/profiles", query=self.mod.query(), body=body)
            after = {key: body[key] for key in FIELDS}
            self.mod.exit(True, before={}, after=after, profile=self.final(dict(body, used_by=[])))
        plan = plan_common(self.mod, current, FIELDS, COMPUTED_KEYS["profile"])
        if not plan.is_changed:
            self.mod.exit(False, before=plan.before(), after=plan.after(), profile=current)
        body = {
            "description": plan.new.get("description") or "",
            "config": plan.new.get("config") or {},
            "devices": plan.new.get("devices") or {},
        }
        try:
            self.mod.write("PUT", self.path, query=self.mod.query(), body=body, etag=etag)
        except LXDClientError as exc:
            if "instances failed updating" in exc.message:
                self.mod.fail(exc.message, changed=True)
            raise
        self.mod.exit(True, before=plan.before(), after=plan.after(), profile=self.final(plan.new))

    def absent(self) -> None:
        """Make sure that the profile does not exist."""
        current, _etag = self.read()
        if current is None:
            self.mod.exit(False, before={}, after={}, profile=None)
        self.mod.write("DELETE", self.path, query=self.mod.query())
        before = {key: current.get(key) for key in FIELDS}
        self.mod.exit(True, before=before, after={}, profile=None)

    def final(self, predicted: dict[str, t.Any]) -> dict[str, t.Any]:
        """Return the profile from the server, or the prediction in check mode."""
        if self.mod.check_mode:
            return predicted
        profile, _etag = self.read()
        return profile or predicted


def get_argument_spec() -> ArgumentSpecMutT:
    """Return the argument spec of the module."""
    return {
        "name": {"type": "str", "required": True},
        "project": {"type": "str"},
        "state": {"type": "str", "default": "present", "choices": ["present", "absent"]},
        "description": {"type": "str"},
        "config": {"type": "dict"},
        "config_mode": {"type": "str", "default": "merge", "choices": ["merge", "exact"]},
        "devices": {"type": "dict"},
        "devices_mode": {"type": "str", "default": "merge", "choices": ["merge", "exact"]},
    }


def main() -> None:
    """Run the module."""
    mod = LXDModule(get_argument_spec())
    profile = ProfileModule(mod)
    if mod.params["state"] == "present":
        mod.run(profile.present)
    else:
        mod.run(profile.absent)


if __name__ == "__main__":
    main()
