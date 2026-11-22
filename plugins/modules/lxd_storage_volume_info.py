#!/usr/bin/python
# Copyright (c) 2026, Sean McAvoy
# GNU General Public License v3.0+ (see LICENSES/GPL-3.0-or-later.txt or https://www.gnu.org/licenses/gpl-3.0.txt)
# SPDX-License-Identifier: GPL-3.0-or-later

from __future__ import annotations

DOCUMENTATION = r"""
module: lxd_storage_volume_info
short_description: Read LXD storage volumes
version_added: "0.1.0"
description:
  - Read the storage volumes of one pool or of all pools, or one volume by name.
author:
  - Sean McAvoy (@smcavoy)
extends_documentation_fragment:
  - smcavoy.lxd._attributes
  - smcavoy.lxd._attributes.info_module
  - smcavoy.lxd._attributes.action_group
  - smcavoy.lxd._connection
  - smcavoy.lxd._project
options:
  pool:
    description:
      - One pool. If not set, the module reads the volumes of all pools.
    type: str
  name:
    description:
      - One volume. Needs O(pool). A missing volume gives an empty list.
    type: str
  type:
    description:
      - The volume type. With O(name), the default is V(custom). Without O(name), the module reads all types.
    type: str
    choices: ["custom", "container", "virtual-machine", "image"]
  filter:
    description:
      - An LXD filter expression, for example V(content_type eq block).
    type: str
  all_projects:
    description:
      - Read the volumes of all projects. Mutually exclusive with O(project).
    type: bool
    default: false
  include_state:
    description:
      - Add the key C(state) with the usage of each volume. This sends one more request per volume.
      - LXD has a state only for volumes of the types V(custom), V(container), and V(virtual-machine). For other volumes C(state) is null.
    type: bool
    default: false
  target:
    description:
      - On a cluster, the member of a volume on a local pool.
    type: str
seealso:
  - module: smcavoy.lxd.lxd_storage_volume
"""

EXAMPLES = r"""
- name: Read the custom volumes of a pool
  smcavoy.lxd.lxd_storage_volume_info:
    pool: default
    type: custom
  register: result
"""

RETURN = r"""
storage_volumes:
  description:
    - The volumes, each with the keys C(project) and C(pool).
  returned: always
  type: list
  elements: dict
  sample:
    - name: data
      pool: default
      project: default
      type: custom
      content_type: filesystem
      config:
        size: 10GiB
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
        "pool": {"type": "str"},
        "name": {"type": "str"},
        "type": {"type": "str", "choices": ["custom", "container", "virtual-machine", "image"]},
        "filter": {"type": "str"},
        "project": {"type": "str"},
        "all_projects": {"type": "bool", "default": False},
        "include_state": {"type": "bool", "default": False},
        "target": {"type": "str"},
    }


# The volume types that have a state in LXD 6.10.1 (lxd/storage_volumes_state.go).
STATE_TYPES = ("custom", "container", "virtual-machine")


def main() -> None:
    """Run the module."""
    mod = LXDModule(get_argument_spec(), required_by={"name": ["pool"]}, mutually_exclusive=[["name", "filter"]])

    def read() -> None:
        params = mod.params
        check_all_projects(mod, "storage_volumes_all_projects")
        extra = {"target": params["target"]}
        if params["name"]:
            vol_type = params["type"] or "custom"
            volumes = get_item(mod, api_path("storage-pools", params["pool"], "volumes", vol_type, params["name"]), **extra)
            for volume in volumes:
                volume.setdefault("pool", params["pool"])
        else:
            if params["filter"]:
                extra["filter"] = params["filter"]
            if params["pool"]:
                path = api_path("storage-pools", params["pool"], "volumes")
            else:
                missing = mod.client.missing_extensions(["storage_volumes_all"])
                if missing:
                    mod.fail("LXD server lacks the API extension storage_volumes_all, which a read of all pools needs")
                path = "/1.0/storage-volumes"
            volumes = list_items(mod, path, **extra)
            for volume in volumes:
                volume.setdefault("pool", params["pool"])
            if params["type"]:
                volumes = [vol for vol in volumes if vol.get("type") == params["type"]]
        if params["include_state"]:
            clustered = mod.client.is_clustered()
            for volume in volumes:
                if volume.get("type") not in STATE_TYPES:
                    # LXD answers 400 for the state of an image volume.
                    volume["state"] = None
                    continue
                # On a cluster, the member that holds a local volume answers for its state. A volume on remote storage
                # (for example Ceph) has no location; the member of the task then answers.
                location = volume.get("location") if clustered else None
                query = {"project": volume.get("project"), "target": location if location and location != "none" else params["target"]}
                state, _etag = mod.client.get_or_none(
                    api_path("storage-pools", volume["pool"], "volumes", volume["type"], volume["name"], "state"),
                    {key: value for key, value in query.items() if value},
                )
                volume["state"] = state
        mod.exit(False, storage_volumes=volumes)

    mod.run(read)


if __name__ == "__main__":
    main()
