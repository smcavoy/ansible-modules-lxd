#!/usr/bin/python
# Copyright (c) 2026, Sean McAvoy
# GNU General Public License v3.0+ (see LICENSES/GPL-3.0-or-later.txt or https://www.gnu.org/licenses/gpl-3.0.txt)
# SPDX-License-Identifier: GPL-3.0-or-later

from __future__ import annotations

DOCUMENTATION = r"""
module: lxd_image_registry
short_description: Manage LXD image registries
version_added: "0.1.0"
description:
  - Create, update, and delete the image registries that instances and images use as sources.
  - LXD infers the protocol from the config. C(url) gives a simplestreams registry.
    C(cluster) with C(source_project) gives an LXD registry over a cluster link.
author:
  - Sean McAvoy (@smcavoy)
extends_documentation_fragment:
  - smcavoy.lxd._attributes
  - smcavoy.lxd._attributes.action_group
  - smcavoy.lxd._connection
  - smcavoy.lxd._config
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
      - The registry name.
    type: str
    required: true
  state:
    description:
      - The wanted state of the registry.
    type: str
    choices:
      present: The registry exists.
      absent: The registry does not exist.
    default: present
  description:
    description:
      - The registry description.
      - If not set, the module does not manage the description.
    type: str
notes:
  - Image registries are global. They do not belong to a project.
  - The built-in registries, such as V(images) and V(ubuntu), cannot change. The module fails on a change to them.
  - The protocol of a registry cannot change. The module fails when the config asks for the other protocol.
  - A C(url) cannot hold a user name or a password.
seealso:
  - module: smcavoy.lxd.lxd_image
  - name: LXD image registries
    description: The LXD documentation about remote image servers and registries.
    link: https://documentation.ubuntu.com/lxd/latest/image-handling/
"""

EXAMPLES = r"""
- name: Add a local simplestreams mirror
  smcavoy.lxd.lxd_image_registry:
    name: mirror
    description: Local mirror
    config:
      url: https://images.example.net

- name: Use the images of a project on a linked cluster
  smcavoy.lxd.lxd_image_registry:
    name: dc2-golden
    config:
      cluster: dc2
      source_project: golden

- name: Remove the mirror
  smcavoy.lxd.lxd_image_registry:
    name: mirror
    state: absent
"""

RETURN = r"""
image_registry:
  description:
    - The registry after the change, as LXD returns it.
    - In check mode, the predicted registry.
    - V(null) after a delete.
  returned: always
  type: dict
  sample:
    name: mirror
    description: Local mirror
    protocol: simplestreams
    public: true
    builtin: false
    config:
      url: https://images.example.net
"""

import typing as t

from ansible_collections.smcavoy.lxd.plugins.module_utils._client import api_path
from ansible_collections.smcavoy.lxd.plugins.module_utils._module import LXDModule
from ansible_collections.smcavoy.lxd.plugins.module_utils._resource import create_config, plan_common

if t.TYPE_CHECKING:  # pragma: no cover
    from ansible_collections.smcavoy.lxd.plugins.module_utils._typing import ArgumentSpecMutT

FIELDS = ("description", "config")


def protocol_of(config: t.Mapping[str, t.Any]) -> str | None:
    """Return the protocol that LXD infers from a config, or None when it cannot tell."""
    if config.get("url") and not config.get("cluster"):
        return "simplestreams"
    if config.get("cluster") and not config.get("url"):
        return "lxd"
    return None


class ImageRegistryModule:
    """Manage one LXD image registry."""

    def __init__(self, mod: LXDModule) -> None:
        self.mod = mod
        self.name: str = mod.params["name"]
        self.path = api_path("image-registries", self.name)

    def read(self) -> tuple[dict[str, t.Any] | None, str | None]:
        """Read the registry."""
        return self.mod.client.get_or_none(self.path)

    def present(self) -> None:
        """Make sure that the registry exists with the wanted settings."""
        params = self.mod.params
        current, etag = self.read()
        if current is None:
            body = {"name": self.name, "description": params["description"] or "", "config": create_config(self.mod)}
            self.mod.write("POST", "/1.0/image-registries", body=body)
            after = {key: body[key] for key in FIELDS}
            predicted = dict(body, protocol=protocol_of(create_config(self.mod)), builtin=False)
            self.mod.exit(True, before={}, after=after, image_registry=self.final(predicted))
        plan = plan_common(self.mod, current, FIELDS)
        if not plan.is_changed:
            self.mod.exit(False, before=plan.before(), after=plan.after(), image_registry=current)
        if current.get("builtin"):
            self.mod.fail(f"built-in image registry {self.name} cannot be changed")
        old_protocol = current.get("protocol")
        new_protocol = protocol_of(plan.new.get("config") or {})
        if new_protocol and old_protocol and new_protocol != old_protocol:
            self.mod.fail(f"image registry protocol cannot change from {old_protocol} to {new_protocol}")
        body = {"description": plan.new.get("description") or "", "config": plan.new.get("config") or {}}
        self.mod.write("PUT", self.path, body=body, etag=etag)
        self.mod.exit(True, before=plan.before(), after=plan.after(), image_registry=self.final(plan.new))

    def absent(self) -> None:
        """Make sure that the registry does not exist."""
        current, _etag = self.read()
        if current is None:
            self.mod.exit(False, before={}, after={}, image_registry=None)
        if current.get("builtin"):
            self.mod.fail(f"built-in image registry {self.name} cannot be deleted")
        self.mod.write("DELETE", self.path)
        self.mod.exit(True, before={key: current.get(key) for key in FIELDS}, after={}, image_registry=None)

    def final(self, predicted: dict[str, t.Any]) -> dict[str, t.Any]:
        """Return the registry from the server, or the prediction in check mode."""
        if self.mod.check_mode:
            return predicted
        registry, _etag = self.read()
        return registry or predicted


def get_argument_spec() -> ArgumentSpecMutT:
    """Return the argument spec of the module."""
    return {
        "name": {"type": "str", "required": True},
        "state": {"type": "str", "default": "present", "choices": ["present", "absent"]},
        "description": {"type": "str"},
        "config": {"type": "dict"},
        "config_mode": {"type": "str", "default": "merge", "choices": ["merge", "exact"]},
    }


def main() -> None:
    """Run the module."""
    mod = LXDModule(get_argument_spec(), extensions=["image_registries"])
    registry = ImageRegistryModule(mod)
    if mod.params["state"] == "present":
        mod.run(registry.present)
    else:
        mod.run(registry.absent)


if __name__ == "__main__":
    main()
