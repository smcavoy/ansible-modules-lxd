#!/usr/bin/python
# Copyright (c) 2026, Sean McAvoy
# GNU General Public License v3.0+ (see LICENSES/GPL-3.0-or-later.txt or https://www.gnu.org/licenses/gpl-3.0.txt)
# SPDX-License-Identifier: GPL-3.0-or-later

from __future__ import annotations

DOCUMENTATION = r"""
module: lxd_image_info
short_description: Read LXD images
version_added: "0.1.0"
description:
  - Read the LXD images of a project or of all projects, by fingerprint, by alias, or with a filter.
author:
  - Sean McAvoy (@smcavoy)
extends_documentation_fragment:
  - smcavoy.lxd._attributes
  - smcavoy.lxd._attributes.info_module
  - smcavoy.lxd._attributes.action_group
  - smcavoy.lxd._connection
  - smcavoy.lxd._project
options:
  fingerprint:
    description:
      - One image, by its fingerprint or a unique prefix of it. A missing image gives an empty list.
    type: str
  alias:
    description:
      - One image, by an alias. A missing alias gives an empty list.
    type: str
  filter:
    description:
      - An LXD filter expression, for example V(properties.os eq Alpine).
    type: str
  all_projects:
    description:
      - Read the images of all projects. Mutually exclusive with O(project).
    type: bool
    default: false
seealso:
  - module: smcavoy.lxd.lxd_image
"""

EXAMPLES = r"""
- name: Find the Alpine images
  smcavoy.lxd.lxd_image_info:
    filter: properties.os eq Alpine
  register: result

- name: Read the image of an alias
  smcavoy.lxd.lxd_image_info:
    alias: base/alpine
  register: result
"""

RETURN = r"""
images:
  description:
    - The images, each with the key C(project).
  returned: always
  type: list
  elements: dict
  sample:
    - fingerprint: 32cc6e69adc37342567a7be18e82d6e62f4f5c01b9ca419dcd94e5ea37f3c0b8
      project: default
      type: container
      aliases:
        - name: base/alpine
          description: ""
      properties:
        os: Alpine
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
        "fingerprint": {"type": "str"},
        "alias": {"type": "str"},
        "filter": {"type": "str"},
        "project": {"type": "str"},
        "all_projects": {"type": "bool", "default": False},
    }


def main() -> None:
    """Run the module."""
    mod = LXDModule(get_argument_spec(), mutually_exclusive=[["fingerprint", "alias", "filter"]])

    def read() -> None:
        params = mod.params
        check_all_projects(mod, "images_all_projects")
        if params["filter"]:
            missing = mod.client.missing_extensions(["api_filtering"])
            if missing:
                mod.fail("LXD server lacks the API extension api_filtering, which filter needs")
        fingerprint = params["fingerprint"]
        if params["alias"]:
            alias, _etag = mod.client.get_or_none(api_path("images", "aliases", params["alias"]), mod.query())
            if alias is None:
                mod.exit(False, images=[])
            fingerprint = alias["target"]
        if fingerprint:
            images = get_item(mod, api_path("images", fingerprint))
        elif params["filter"]:
            images = list_items(mod, "/1.0/images", filter=params["filter"])
        else:
            images = list_items(mod, "/1.0/images")
        mod.exit(False, images=images)

    mod.run(read)


if __name__ == "__main__":
    main()
