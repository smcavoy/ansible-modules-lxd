#!/usr/bin/python
# Copyright (c) 2026, Sean McAvoy
# GNU General Public License v3.0+ (see LICENSES/GPL-3.0-or-later.txt or https://www.gnu.org/licenses/gpl-3.0.txt)
# SPDX-License-Identifier: GPL-3.0-or-later

from __future__ import annotations

DOCUMENTATION = r"""
module: lxd_instance_rebuild
short_description: Rebuild the root disk of an LXD instance
version_added: "0.1.0"
description:
  - Replace the root disk of an instance with a fresh image, or with an empty disk. The instance keeps its name, config, devices, and snapshots.
  - This is an action module. It reports a change each time that it rebuilds.
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
    details:
      - Check mode does not rebuild. It reports a change.
  diff_mode:
    support: none
  idempotent:
    support: none
    details:
      - Each run of the task rebuilds the instance.
options:
  instance:
    description:
      - The instance.
    type: str
    required: true
  source:
    description:
      - The new root disk.
    type: dict
    required: true
    suboptions:
      image:
        description:
          - An image alias or fingerprint. Mutually exclusive with O(source.empty).
        type: str
      image_registry:
        description:
          - The image registry of O(source.image). If not set, LXD uses the local image store.
        type: str
      empty:
        description:
          - With V(true), use an empty root disk. Mutually exclusive with O(source.image).
        type: bool
  force:
    description:
      - Stop a running instance before the rebuild. Without it, the module fails on a running instance.
    type: bool
    default: false
  start:
    description:
      - Start the instance after the rebuild.
      - If not set, the module starts the instance when it ran before the rebuild.
    type: bool
  stop_timeout:
    description:
      - Seconds to wait for a clean stop before the module forces the stop.
    type: int
    default: 30
seealso:
  - module: smcavoy.lxd.lxd_instance
"""

EXAMPLES = r"""
- name: Give web1 a fresh root disk from the image debian/13, and start it again
  smcavoy.lxd.lxd_instance_rebuild:
    instance: web1
    source:
      image: debian/13
      image_registry: images
    force: true
"""

RETURN = r"""
instance:
  description:
    - The instance after the rebuild, as LXD returns it.
    - In check mode, the instance before the rebuild.
  returned: always
  type: dict
  sample:
    name: web1
    status: Running
    config:
      volatile.base_image: 32cc6e69adc37342567a7be18e82d6e62f4f5c01b9ca419dcd94e5ea37f3c0b8
"""

import re
import typing as t

from ansible_collections.smcavoy.lxd.plugins.module_utils._client import LXDClientError, api_path
from ansible_collections.smcavoy.lxd.plugins.module_utils._module import LXDModule

if t.TYPE_CHECKING:  # pragma: no cover
    from ansible_collections.smcavoy.lxd.plugins.module_utils._typing import ArgumentSpecMutT

FINGERPRINT_RE = re.compile(r"^[0-9a-f]{12,64}$")


class RebuildModule:
    """Rebuild one instance."""

    def __init__(self, mod: LXDModule) -> None:
        self.mod = mod
        self.name = mod.params["instance"]
        self.path = api_path("instances", self.name)

    def source_body(self) -> dict[str, t.Any]:
        """Build the C(source) of the rebuild request."""
        source = self.mod.params["source"]
        if source.get("empty"):
            return {"type": "none"}
        image = source.get("image")
        if not image:
            self.mod.fail("source needs image or empty")
        key = "alias"
        if FINGERPRINT_RE.match(image) and (source.get("image_registry") or not self.local_alias(image)):
            # A name of hex characters can be an alias too. A local alias of that name wins.
            key = "fingerprint"
        body: dict[str, t.Any] = {"type": "image", key: image}
        if source.get("image_registry"):
            body["image_registry"] = source["image_registry"]
        return body

    def local_alias(self, name: str) -> bool:
        """Return whether the local image store has an alias of that name."""
        alias, _etag = self.mod.client.get_or_none(api_path("images", "aliases", name), self.mod.query())
        return alias is not None

    def set_state(self, action: str, force: bool = False) -> None:
        """Send one state action and wait for it."""
        body = {"action": action, "timeout": self.mod.params["stop_timeout"], "force": force}
        self.mod.write("PUT", f"{self.path}/state", query=self.mod.query(), body=body)

    def run(self) -> None:
        """Rebuild the instance."""
        params = self.mod.params
        current, _etag = self.mod.client.get_or_none(self.path, self.mod.query())
        if current is None:
            self.mod.fail(f"instance {self.name} not found")
        # A frozen instance, and one that its guest marked as ready, also run.
        running = current.get("status") in ("Running", "Ready", "Frozen")
        if running and not params["force"]:
            self.mod.fail(f"instance {self.name} runs. Set force to stop it before the rebuild.")
        body = {"source": self.source_body()}
        if self.mod.check_mode:
            self.mod.exit(True, instance=current)
        if running:
            try:
                self.set_state("stop")
            except LXDClientError:
                self.set_state("stop", force=True)
        self.mod.write("POST", f"{self.path}/rebuild", query=self.mod.query(), body=body)
        start = running if params["start"] is None else params["start"]
        if start:
            self.set_state("start")
        instance, _etag = self.mod.client.get(self.path, self.mod.query())
        self.mod.exit(True, instance=instance)


def get_argument_spec() -> ArgumentSpecMutT:
    """Return the argument spec of the module."""
    return {
        "instance": {"type": "str", "required": True},
        "project": {"type": "str"},
        "source": {
            "type": "dict",
            "required": True,
            "options": {
                "image": {"type": "str"},
                "image_registry": {"type": "str"},
                "empty": {"type": "bool"},
            },
            "mutually_exclusive": [["image", "empty"]],
            "required_by": {"image_registry": "image"},
        },
        "force": {"type": "bool", "default": False},
        "start": {"type": "bool"},
        "stop_timeout": {"type": "int", "default": 30},
    }


def main() -> None:
    """Run the module."""
    mod = LXDModule(get_argument_spec(), extensions=["instances_rebuild"])
    if mod.params["source"].get("image_registry"):
        missing = mod.client.missing_extensions(["image_registries"])
        if missing:
            mod.fail("LXD server lacks the API extension image_registries, which source.image_registry needs")
    mod.run(RebuildModule(mod).run)


if __name__ == "__main__":
    main()
