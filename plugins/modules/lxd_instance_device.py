#!/usr/bin/python
# Copyright (c) 2026, Sean McAvoy
# GNU General Public License v3.0+ (see LICENSES/GPL-3.0-or-later.txt or https://www.gnu.org/licenses/gpl-3.0.txt)
# SPDX-License-Identifier: GPL-3.0-or-later

from __future__ import annotations

DOCUMENTATION = r"""
module: lxd_instance_device
short_description: Manage one device of an LXD instance
version_added: "0.1.0"
description:
  - Add, change, and remove one device of an instance, and leave all other devices and settings as they are.
  - Use it when other tasks or tools own the rest of the instance.
author:
  - Sean McAvoy (@smcavoy)
extends_documentation_fragment:
  - smcavoy.lxd._attributes
  - smcavoy.lxd._attributes.action_group
  - smcavoy.lxd._connection
  - smcavoy.lxd._project
attributes:
  check_mode:
    support: full
  diff_mode:
    support: full
  idempotent:
    support: full
options:
  instance:
    description:
      - The instance.
    type: str
    required: true
  name:
    description:
      - The device name.
    type: str
    required: true
  state:
    description:
      - The wanted state of the device.
    type: str
    choices:
      present: The instance has the device with O(properties).
      absent: The instance does not have the device.
    default: present
  properties:
    description:
      - The device properties, with C(type). The module converts each value to a string.
      - Required with O(state=present).
    type: dict
  allow_restart:
    description:
      - Restart the instance when LXD cannot add, change, or remove the device while the instance runs.
    type: bool
    default: false
notes:
  - A device with the same name in a profile does not count. An instance device overrides it, and the profile stays as it is.
seealso:
  - module: smcavoy.lxd.lxd_instance
"""

EXAMPLES = r"""
- name: Forward port 8080 on the host to port 80 in a container
  smcavoy.lxd.lxd_instance_device:
    instance: web1
    name: http
    properties:
      type: proxy
      listen: tcp:0.0.0.0:8080
      connect: tcp:127.0.0.1:80

- name: Remove the device
  smcavoy.lxd.lxd_instance_device:
    instance: web1
    name: http
    state: absent
"""

RETURN = r"""
instance:
  description:
    - The instance name.
  returned: always
  type: str
  sample: web1
device:
  description:
    - The device after the change. V(null) after a delete.
  returned: always
  type: dict
  sample:
    type: proxy
    listen: tcp:0.0.0.0:8080
    connect: tcp:127.0.0.1:80
restarted:
  description:
    - Whether the module restarted the instance to apply the change, because of O(allow_restart).
  returned: always
  type: bool
  sample: false
"""

import re
import typing as t

from ansible_collections.smcavoy.lxd.plugins.module_utils._client import LXDClientError, api_path
from ansible_collections.smcavoy.lxd.plugins.module_utils._config import normalize_device
from ansible_collections.smcavoy.lxd.plugins.module_utils._module import LXDModule

if t.TYPE_CHECKING:  # pragma: no cover
    from ansible_collections.smcavoy.lxd.plugins.module_utils._typing import ArgumentSpecMutT

# Wordings of LXD errors for a device that cannot change while the instance runs.
LIVE_ERROR_RE = re.compile(r"running|hot.?plug|live|while the instance", re.IGNORECASE)
# A frozen instance, and one that its guest marked as ready, also run.
RUN_STATUSES = ("Running", "Ready", "Frozen")
PUT_FIELDS = ("architecture", "config", "devices", "profiles", "ephemeral", "description")


class DeviceModule:
    """Manage one device of an LXD instance."""

    def __init__(self, mod: LXDModule) -> None:
        self.mod = mod
        self.instance: str = mod.params["instance"]
        self.name: str = mod.params["name"]
        self.path = api_path("instances", self.instance)
        self.restarted = False

    def read(self) -> tuple[dict[str, t.Any], str | None]:
        """Read the instance. Fail when it does not exist."""
        instance, etag = self.mod.client.get_or_none(self.path, self.mod.query())
        if instance is None:
            self.mod.fail(f"instance {self.instance} not found")
        return instance, etag

    def put(self, instance: dict[str, t.Any], devices: dict[str, t.Any], etag: str | None) -> None:
        """Write the instance back with the new devices. Restart it if LXD needs that and the task allows it."""
        body = {key: instance.get(key) for key in PUT_FIELDS}
        body["devices"] = devices
        body["ephemeral"] = bool(body["ephemeral"])
        if self.mod.check_mode:
            return
        try:
            self.mod.client.write("PUT", self.path, query=self.mod.query(), body=body, etag=etag)
        except LXDClientError as exc:
            if not (self.mod.params["allow_restart"] and instance.get("status") in RUN_STATUSES and LIVE_ERROR_RE.search(exc.message)):
                raise
            state_path = api_path("instances", self.instance, "state")
            self.mod.client.write("PUT", state_path, query=self.mod.query(), body={"action": "stop", "timeout": 60})
            fresh, fresh_etag = self.read()
            fresh_body = {key: fresh.get(key) for key in PUT_FIELDS}
            fresh_body["devices"] = devices
            fresh_body["ephemeral"] = bool(fresh_body["ephemeral"])
            self.mod.client.write("PUT", self.path, query=self.mod.query(), body=fresh_body, etag=fresh_etag)
            self.mod.client.write("PUT", state_path, query=self.mod.query(), body={"action": "start"})
            self.restarted = True

    def present(self) -> None:
        """Make sure that the instance has the device with the wanted properties."""
        params = self.mod.params
        if not params["properties"]:
            self.mod.fail("properties is required with state=present")
        if not params["properties"].get("type"):
            self.mod.fail("properties needs type")
        wanted = normalize_device(self.name, params["properties"])
        instance, etag = self.read()
        devices = dict(instance.get("devices") or {})
        current = devices.get(self.name)
        if current == wanted:
            self.mod.exit(False, before={"device": current}, after={"device": wanted}, instance=self.instance, device=current, restarted=False)
        devices[self.name] = wanted
        self.put(instance, devices, etag)
        self.mod.exit(True, before={"device": current or {}}, after={"device": wanted}, instance=self.instance, device=wanted, restarted=self.restarted)

    def absent(self) -> None:
        """Make sure that the instance does not have the device."""
        instance, etag = self.read()
        devices = dict(instance.get("devices") or {})
        current = devices.pop(self.name, None)
        if current is None:
            self.mod.exit(False, before={}, after={}, instance=self.instance, device=None, restarted=False)
        self.put(instance, devices, etag)
        self.mod.exit(True, before={"device": current}, after={}, instance=self.instance, device=None, restarted=self.restarted)


def get_argument_spec() -> ArgumentSpecMutT:
    """Return the argument spec of the module."""
    return {
        "instance": {"type": "str", "required": True},
        "name": {"type": "str", "required": True},
        "project": {"type": "str"},
        "state": {"type": "str", "default": "present", "choices": ["present", "absent"]},
        "properties": {"type": "dict"},
        "allow_restart": {"type": "bool", "default": False},
    }


def main() -> None:
    """Run the module."""
    mod = LXDModule(get_argument_spec(), extensions=["instances"])
    device = DeviceModule(mod)
    if mod.params["state"] == "present":
        mod.run(device.present)
    else:
        mod.run(device.absent)


if __name__ == "__main__":
    main()
