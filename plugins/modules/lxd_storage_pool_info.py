#!/usr/bin/python
# Copyright (c) 2026, Sean McAvoy
# GNU General Public License v3.0+ (see LICENSES/GPL-3.0-or-later.txt or https://www.gnu.org/licenses/gpl-3.0.txt)
# SPDX-License-Identifier: GPL-3.0-or-later

from __future__ import annotations

DOCUMENTATION = r"""
module: lxd_storage_pool_info
short_description: Read LXD storage pools
version_added: "0.1.0"
description:
  - Read all LXD storage pools, or one pool by name, optionally with space usage.
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
      - One pool. A missing pool gives an empty list.
    type: str
  include_resources:
    description:
      - Add the key C(resources) with the space and inode usage of each pool.
    type: bool
    default: false
  target:
    description:
      - On a cluster, read the member-specific keys and the resources of this member.
    type: str
seealso:
  - module: smcavoy.lxd.lxd_storage_pool
"""

EXAMPLES = r"""
- name: Read all pools with their usage
  smcavoy.lxd.lxd_storage_pool_info:
    include_resources: true
  register: result
"""

RETURN = r"""
storage_pools:
  description:
    - The pools. With O(include_resources=true), each pool has the key C(resources).
    - The module masks the passwords and tokens of the remote storage drivers in C(config).
  returned: always
  type: list
  elements: dict
  sample:
    - name: default
      driver: dir
      status: Created
      config:
        source: /var/snap/lxd/common/lxd/storage-pools/default
      resources:
        space:
          used: 1073741824
          total: 21474836480
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
        "include_resources": {"type": "bool", "default": False},
        "target": {"type": "str"},
    }


def main() -> None:
    """Run the module."""
    mod = LXDModule(get_argument_spec(), extensions=["storage"])
    # The passwords and tokens of the remote storage drivers.
    mod.hide_secrets(r"^((alletra|powerflex|powerstore)\.user\.password|pure\.api\.token)$")

    def read() -> None:
        params = mod.params
        query = {"target": params["target"]} if params["target"] else {}
        if params["name"]:
            pool, _etag = mod.client.get_or_none(api_path("storage-pools", params["name"]), query)
            pools = [pool] if pool else []
        else:
            items, _etag = mod.client.get("/1.0/storage-pools", dict(query, recursion=1))
            pools = list(items or [])
        if params["include_resources"]:
            for pool in pools:
                resources, _etag = mod.client.get_or_none(api_path("storage-pools", pool["name"], "resources"), query)
                pool["resources"] = resources
        mod.exit(False, storage_pools=pools)

    mod.run(read)


if __name__ == "__main__":
    main()
