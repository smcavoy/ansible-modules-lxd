#!/usr/bin/python
# Copyright (c) 2026, Sean McAvoy
# GNU General Public License v3.0+ (see LICENSES/GPL-3.0-or-later.txt or https://www.gnu.org/licenses/gpl-3.0.txt)
# SPDX-License-Identifier: GPL-3.0-or-later

from __future__ import annotations

DOCUMENTATION = r"""
module: lxd_image_alias
short_description: Manage LXD image aliases
version_added: "0.1.0"
description:
  - Create, update, and delete LXD image aliases, apart from the images that they point to.
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
  name:
    description:
      - The alias name. It can hold C(/), for example C(test/alpine).
    type: str
    required: true
  state:
    description:
      - The wanted state of the alias.
    type: str
    choices:
      present: The alias exists and points to O(target).
      absent: The alias does not exist. The image stays.
    default: present
  target:
    description:
      - The fingerprint of the image. A unique prefix of the fingerprint is allowed.
      - Required with O(state=present).
    type: str
  description:
    description:
      - The alias description.
      - If not set, the module does not manage the description.
    type: str
seealso:
  - name: LXD images
    description: The LXD documentation about images and aliases.
    link: https://documentation.ubuntu.com/lxd/latest/image-handling/
"""

EXAMPLES = r"""
- name: Point an alias to an image
  smcavoy.lxd.lxd_image_alias:
    name: base/alpine
    target: 32cc6e69adc3
    description: Pinned Alpine

- name: Remove the alias and keep the image
  smcavoy.lxd.lxd_image_alias:
    name: base/alpine
    state: absent
"""

RETURN = r"""
alias:
  description:
    - The alias after the change, as LXD returns it.
    - In check mode, the predicted alias.
    - V(null) after a delete.
  returned: always
  type: dict
  sample:
    name: base/alpine
    target: 32cc6e69adc37342567a7be18e82d6e62f4f5c01b9ca419dcd94e5ea37f3c0b8
    type: container
    description: Pinned Alpine
"""

import typing as t

from ansible_collections.smcavoy.lxd.plugins.module_utils._client import api_path
from ansible_collections.smcavoy.lxd.plugins.module_utils._module import LXDModule

if t.TYPE_CHECKING:  # pragma: no cover
    from ansible_collections.smcavoy.lxd.plugins.module_utils._typing import ArgumentSpecMutT


class ImageAliasModule:
    """Manage one LXD image alias."""

    def __init__(self, mod: LXDModule) -> None:
        self.mod = mod
        self.name: str = mod.params["name"]
        self.path = api_path("images", "aliases", self.name)

    def read(self) -> tuple[dict[str, t.Any] | None, str | None]:
        """Read the alias."""
        return self.mod.client.get_or_none(self.path, self.mod.query())

    def image(self, target: str) -> dict[str, t.Any]:
        """Return the image of a fingerprint or a fingerprint prefix. Fail when it does not exist."""
        image, _etag = self.mod.client.get_or_none(api_path("images", target), self.mod.query())
        if image is None:
            self.mod.fail(f"image {target} not found")
        return image

    def present(self) -> None:
        """Make sure that the alias exists and points to the target."""
        params = self.mod.params
        image = self.image(params["target"])
        fingerprint = image["fingerprint"]
        current, etag = self.read()
        if current is None:
            body = {"name": self.name, "target": fingerprint, "description": params["description"] or ""}
            self.mod.write("POST", "/1.0/images/aliases", query=self.mod.query(), body=body)
            after = {"target": fingerprint, "description": body["description"]}
            self.mod.exit(True, before={}, after=after, alias=self.final(dict(body, type=image.get("type"))))
        before = {"target": current.get("target"), "description": current.get("description")}
        after = {"target": fingerprint, "description": current.get("description")}
        if params["description"] is not None:
            after["description"] = params["description"]
        if after == before:
            self.mod.exit(False, before=before, after=after, alias=current)
        self.mod.write("PUT", self.path, query=self.mod.query(), body=after, etag=etag)
        self.mod.exit(True, before=before, after=after, alias=self.final(dict(current, type=image.get("type"), **after)))

    def absent(self) -> None:
        """Make sure that the alias does not exist. The image stays."""
        current, _etag = self.read()
        if current is None:
            self.mod.exit(False, before={}, after={}, alias=None)
        self.mod.write("DELETE", self.path, query=self.mod.query())
        before = {"target": current.get("target"), "description": current.get("description")}
        self.mod.exit(True, before=before, after={}, alias=None)

    def final(self, predicted: dict[str, t.Any]) -> dict[str, t.Any]:
        """Return the alias from the server, or the prediction in check mode."""
        if self.mod.check_mode:
            return predicted
        alias, _etag = self.read()
        return alias or predicted


def get_argument_spec() -> ArgumentSpecMutT:
    """Return the argument spec of the module."""
    return {
        "name": {"type": "str", "required": True},
        "project": {"type": "str"},
        "state": {"type": "str", "default": "present", "choices": ["present", "absent"]},
        "target": {"type": "str"},
        "description": {"type": "str"},
    }


def main() -> None:
    """Run the module."""
    mod = LXDModule(get_argument_spec(), required_if=[["state", "present", ["target"]]])
    alias = ImageAliasModule(mod)
    if mod.params["state"] == "present":
        mod.run(alias.present)
    else:
        mod.run(alias.absent)


if __name__ == "__main__":
    main()
