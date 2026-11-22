#!/usr/bin/python
# Copyright (c) 2026, Sean McAvoy
# GNU General Public License v3.0+ (see LICENSES/GPL-3.0-or-later.txt or https://www.gnu.org/licenses/gpl-3.0.txt)
# SPDX-License-Identifier: GPL-3.0-or-later

from __future__ import annotations

DOCUMENTATION = r"""
module: lxd_auth_info
short_description: Read LXD access control
version_added: "0.1.0"
description:
  - Read the current identity, the identities, the authorization groups, the identity provider groups, and the permissions.
author:
  - Sean McAvoy (@smcavoy)
extends_documentation_fragment:
  - smcavoy.lxd._attributes
  - smcavoy.lxd._attributes.info_module
  - smcavoy.lxd._attributes.action_group
  - smcavoy.lxd._connection
options:
  gather:
    description:
      - The parts to read.
    type: list
    elements: str
    choices:
      current: The identity of this client, with its effective groups and permissions.
      identities: All identities.
      groups: All authorization groups.
      identity_provider_groups: All identity provider group mappings.
      permissions: The permissions, filtered by O(entity_type) and O(project).
    default: [current]
  identity_type:
    description:
      - Keep only identities with this authentication method.
    type: str
    choices: ["tls", "bearer", "oidc"]
  include_effective_groups:
    description:
      - Add the key C(effective_groups) to each identity. This sends one more request per identity.
    type: bool
    default: false
  entity_type:
    description:
      - With V(permissions) in O(gather), read only the permissions of this entity type, for example V(project).
    type: str
  project:
    description:
      - With V(permissions) in O(gather), read only the permissions in this project.
    type: str
seealso:
  - module: smcavoy.lxd.lxd_auth_group
  - module: smcavoy.lxd.lxd_auth_identity
"""

EXAMPLES = r"""
- name: Show who this client is
  smcavoy.lxd.lxd_auth_info:
  register: result

- name: List the TLS identities with their groups
  smcavoy.lxd.lxd_auth_info:
    gather: [identities]
    identity_type: tls
    include_effective_groups: true
  register: result
"""

RETURN = r"""
current:
  description:
    - The identity of this client, with C(effective_groups) and C(effective_permissions).
  returned: when O(gather) holds V(current)
  type: dict
  sample:
    authentication_method: tls
    type: Client certificate
    name: ci
    effective_groups: []
identities:
  description:
    - The identities.
  returned: when O(gather) holds V(identities)
  type: list
  elements: dict
groups:
  description:
    - The authorization groups.
  returned: when O(gather) holds V(groups)
  type: list
  elements: dict
identity_provider_groups:
  description:
    - The identity provider group mappings.
  returned: when O(gather) holds V(identity_provider_groups)
  type: list
  elements: dict
permissions:
  description:
    - The permissions. Each item has C(entity_type), C(url), C(entitlement), and C(groups).
  returned: when O(gather) holds V(permissions)
  type: list
  elements: dict
"""

import typing as t

from ansible_collections.smcavoy.lxd.plugins.module_utils._client import api_path
from ansible_collections.smcavoy.lxd.plugins.module_utils._module import LXDModule

if t.TYPE_CHECKING:  # pragma: no cover
    from ansible_collections.smcavoy.lxd.plugins.module_utils._typing import ArgumentSpecMutT

LISTS = {
    "groups": "/1.0/auth/groups",
    "identity_provider_groups": "/1.0/auth/identity-provider-groups",
}


def get_argument_spec() -> ArgumentSpecMutT:
    """Return the argument spec of the module."""
    return {
        "gather": {
            "type": "list",
            "elements": "str",
            "default": ["current"],
            "choices": ["current", "identities", "groups", "identity_provider_groups", "permissions"],
        },
        "identity_type": {"type": "str", "choices": ["tls", "bearer", "oidc"]},
        "include_effective_groups": {"type": "bool", "default": False},
        "entity_type": {"type": "str"},
        "project": {"type": "str"},
    }


def main() -> None:
    """Run the module."""
    mod = LXDModule(get_argument_spec(), extensions=["access_management"])

    def read() -> None:
        params = mod.params
        gather = params["gather"]
        result: dict[str, t.Any] = {}
        if "current" in gather:
            current, _etag = mod.client.get("/1.0/auth/identities/current")
            result["current"] = current
        if "identities" in gather:
            items, _etag = mod.client.get("/1.0/auth/identities", {"recursion": 1})
            identities = [item for item in items or [] if isinstance(item, dict)]
            if params["identity_type"]:
                identities = [item for item in identities if item.get("authentication_method") == params["identity_type"]]
            if params["include_effective_groups"]:
                if mod.client.missing_extensions(["access_management_identity_effective_groups"]):
                    mod.fail("LXD server lacks the API extension access_management_identity_effective_groups")
                for identity in identities:
                    path = api_path(
                        "auth", "identities", identity.get("authentication_method") or "", identity.get("id") or identity.get("name") or "", "state"
                    )
                    state, _etag = mod.client.get_or_none(path)
                    identity["effective_groups"] = (state or {}).get("effective_groups") or []
            result["identities"] = identities
        for part, path in LISTS.items():
            if part in gather:
                items, _etag = mod.client.get(path, {"recursion": 1})
                result[part] = list(items or [])
        if "permissions" in gather:
            query: dict[str, t.Any] = {"recursion": 1}
            if params["entity_type"]:
                query["entity-type"] = params["entity_type"]
            if params["project"]:
                query["project"] = params["project"]
            items, _etag = mod.client.get("/1.0/auth/permissions", query)
            result["permissions"] = list(items or [])
        mod.exit(False, **result)

    mod.run(read)


if __name__ == "__main__":
    main()
