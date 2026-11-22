#!/usr/bin/python
# Copyright (c) 2026, Sean McAvoy
# GNU General Public License v3.0+ (see LICENSES/GPL-3.0-or-later.txt or https://www.gnu.org/licenses/gpl-3.0.txt)
# SPDX-License-Identifier: GPL-3.0-or-later

from __future__ import annotations

DOCUMENTATION = r"""
module: lxd_cluster_link_info
short_description: Read LXD cluster links
version_added: "0.1.0"
description:
  - Read all cluster links of a cluster, or one link by name, optionally with the status of the members of the other cluster.
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
      - One link. A missing link gives an empty list.
    type: str
  include_state:
    description:
      - Add the key C(state) with the address and the status of each member of the other cluster.
      - A pending link has no state. Its C(state) is then V(null).
    type: bool
    default: false
seealso:
  - module: smcavoy.lxd.lxd_cluster_link
"""

EXAMPLES = r"""
- name: Read all links with the status of the other members
  smcavoy.lxd.lxd_cluster_link_info:
    include_state: true
  register: links
"""

RETURN = r"""
links:
  description:
    - The links, as LXD returns them.
  returned: always
  type: list
  elements: dict
  sample:
    - name: dr-site
      type: bidirectional
      description: ""
      config:
        volatile.addresses: 10.250.0.41:8443
      used_by: []
      state:
        cluster_link_members:
          - server_name: dr-ab12-1
            address: 10.250.0.41:8443
            status: Active
"""

import typing as t

from ansible_collections.smcavoy.lxd.plugins.module_utils._client import LXDClientError, api_path
from ansible_collections.smcavoy.lxd.plugins.module_utils._module import LXDModule

if t.TYPE_CHECKING:  # pragma: no cover
    from ansible_collections.smcavoy.lxd.plugins.module_utils._typing import ArgumentSpecMutT


def get_argument_spec() -> ArgumentSpecMutT:
    """Return the argument spec of the module."""
    return {
        "name": {"type": "str"},
        "include_state": {"type": "bool", "default": False},
    }


def main() -> None:
    """Run the module."""
    mod = LXDModule(get_argument_spec(), extensions=["cluster_links"])

    def read() -> None:
        params = mod.params
        if params["name"]:
            link, _etag = mod.client.get_or_none(api_path("cluster", "links", params["name"]))
            links = [link] if isinstance(link, dict) else []
        else:
            items, _etag = mod.client.get("/1.0/cluster/links", {"recursion": 1})
            links = [item for item in items or [] if isinstance(item, dict)]
        if params["include_state"]:
            for link in links:
                try:
                    state, _etag = mod.client.get(api_path("cluster", "links", link["name"], "state"))
                except LXDClientError:
                    # A pending link has no member addresses yet. LXD then answers with an error.
                    state = None
                link["state"] = state
        mod.exit(False, links=links)

    mod.run(read)


if __name__ == "__main__":
    main()
