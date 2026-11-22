#!/usr/bin/python
# Copyright (c) 2026, Sean McAvoy
# GNU General Public License v3.0+ (see LICENSES/GPL-3.0-or-later.txt or https://www.gnu.org/licenses/gpl-3.0.txt)
# SPDX-License-Identifier: GPL-3.0-or-later

from __future__ import annotations

DOCUMENTATION = r"""
module: lxd_image_registry_info
short_description: Read LXD image registries
version_added: "0.1.0"
description:
  - Read all image registries, or one registry by name, optionally with the images that it offers.
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
      - One registry. A missing registry gives an empty list.
    type: str
  include_images:
    description:
      - Add the key C(images) with the images that the registry offers. Needs O(name).
      - LXD contacts the registry for this list.
    type: bool
    default: false
  image_filter:
    description:
      - "Keep only images whose fields match, for example V({'properties.os': 'Alpine', 'type': 'container'})."
      - A key with dots reads a nested field. The module filters on the client.
    type: dict
seealso:
  - module: smcavoy.lxd.lxd_image_registry
"""

EXAMPLES = r"""
- name: Find the Alpine container images of the images registry
  smcavoy.lxd.lxd_image_registry_info:
    name: images
    include_images: true
    image_filter:
      properties.os: Alpine
      type: container
  register: result
"""

RETURN = r"""
image_registries:
  description:
    - The registries. With O(include_images=true), the registry has the key C(images).
  returned: always
  type: list
  elements: dict
  sample:
    - name: images
      protocol: simplestreams
      builtin: true
      public: true
      config:
        url: https://images.lxd.canonical.com
"""

import typing as t

from ansible_collections.smcavoy.lxd.plugins.module_utils._client import api_path
from ansible_collections.smcavoy.lxd.plugins.module_utils._module import LXDModule

if t.TYPE_CHECKING:  # pragma: no cover
    from ansible_collections.smcavoy.lxd.plugins.module_utils._typing import ArgumentSpecMutT


def field(item: t.Any, path: str) -> t.Any:
    """Return a nested field, for example C(properties.os). Try the whole key first, because some keys hold dots."""
    if isinstance(item, dict) and path in item:
        return item[path]
    head, sep, rest = path.partition(".")
    if not sep or not isinstance(item, dict):
        return None
    return field(item.get(head), rest)


def matches(image: dict[str, t.Any], wanted: dict[str, t.Any]) -> bool:
    """Return whether every filter field of an image has the wanted value."""
    return all(str(field(image, key)) == str(value) for key, value in wanted.items())


def get_argument_spec() -> ArgumentSpecMutT:
    """Return the argument spec of the module."""
    return {
        "name": {"type": "str"},
        "include_images": {"type": "bool", "default": False},
        "image_filter": {"type": "dict"},
    }


def main() -> None:
    """Run the module."""
    mod = LXDModule(get_argument_spec(), extensions=["image_registries"])

    def read() -> None:
        params = mod.params
        if params["include_images"] and not params["name"]:
            mod.fail("include_images needs name")
        if params["name"]:
            registry, _etag = mod.client.get_or_none(api_path("image-registries", params["name"]))
            registries = [registry] if registry else []
        else:
            items, _etag = mod.client.get("/1.0/image-registries", {"recursion": 1})
            registries = list(items or [])
        if params["include_images"]:
            for registry in registries:
                images, _etag = mod.client.get(api_path("image-registries", registry["name"], "images"), {"recursion": 1})
                images = [image for image in images or [] if isinstance(image, dict)]
                if params["image_filter"]:
                    images = [image for image in images if matches(image, params["image_filter"])]
                registry["images"] = images
        mod.exit(False, image_registries=registries)

    mod.run(read)


if __name__ == "__main__":
    main()
