#!/usr/bin/python
# Copyright (c) 2026, Sean McAvoy
# GNU General Public License v3.0+ (see LICENSES/GPL-3.0-or-later.txt or https://www.gnu.org/licenses/gpl-3.0.txt)
# SPDX-License-Identifier: GPL-3.0-or-later

from __future__ import annotations

DOCUMENTATION = r"""
module: lxd_auth_identity_provider_group
short_description: Map identity provider groups to LXD groups
version_added: "0.1.0"
description:
  - Create, update, and delete the mapping from a group of the OIDC identity provider to LXD authorization groups.
author:
  - Sean McAvoy (@smcavoy)
extends_documentation_fragment:
  - smcavoy.lxd._attributes
  - smcavoy.lxd._attributes.action_group
  - smcavoy.lxd._connection
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
      - The group name in the claim of the identity provider.
    type: str
    required: true
  state:
    description:
      - The wanted state of the mapping.
    type: str
    choices:
      present: The mapping exists.
      absent: The mapping does not exist.
    default: present
  groups:
    description:
      - The LXD authorization groups that members of the provider group get.
      - If not set, the module does not manage the groups.
    type: list
    elements: str
notes:
  - The module compares O(groups) as a set.
  - A mapping needs no identity provider. Only a login through it needs one.
seealso:
  - module: smcavoy.lxd.lxd_auth_group
"""

EXAMPLES = r"""
- name: Give the provider group lxd-admins the LXD group admins
  smcavoy.lxd.lxd_auth_identity_provider_group:
    name: lxd-admins
    groups:
      - admins
"""

RETURN = r"""
identity_provider_group:
  description:
    - The mapping after the change, as LXD returns it.
    - In check mode, the predicted mapping.
    - V(null) after a delete.
  returned: always
  type: dict
  sample:
    name: lxd-admins
    groups:
      - admins
"""

import typing as t

from ansible_collections.smcavoy.lxd.plugins.module_utils._client import api_path
from ansible_collections.smcavoy.lxd.plugins.module_utils._module import LXDModule

if t.TYPE_CHECKING:  # pragma: no cover
    from ansible_collections.smcavoy.lxd.plugins.module_utils._typing import ArgumentSpecMutT


class ProviderGroupModule:
    """Manage one identity provider group mapping."""

    def __init__(self, mod: LXDModule) -> None:
        self.mod = mod
        self.name: str = mod.params["name"]
        self.path = api_path("auth", "identity-provider-groups", self.name)

    def read(self) -> tuple[dict[str, t.Any] | None, str | None]:
        """Read the mapping."""
        return self.mod.client.get_or_none(self.path)

    def present(self) -> None:
        """Make sure that the mapping exists with the wanted groups."""
        groups = self.mod.params["groups"]
        current, etag = self.read()
        if current is None:
            after = {"groups": sorted(set(groups or []))}
            self.mod.write("POST", "/1.0/auth/identity-provider-groups", body={"name": self.name, "groups": after["groups"]})
            self.mod.exit(True, before={}, after=after, identity_provider_group=self.final(dict(after, name=self.name)))
        before = {"groups": sorted(current.get("groups") or [])}
        after = {"groups": sorted(set(groups))} if groups is not None else dict(before)
        if before == after:
            self.mod.exit(False, before=before, after=after, identity_provider_group=current)
        self.mod.write("PUT", self.path, body=after, etag=etag)
        self.mod.exit(True, before=before, after=after, identity_provider_group=self.final(dict(current, **after)))

    def absent(self) -> None:
        """Make sure that the mapping does not exist."""
        current, _etag = self.read()
        if current is None:
            self.mod.exit(False, before={}, after={}, identity_provider_group=None)
        self.mod.write("DELETE", self.path)
        self.mod.exit(True, before={"groups": sorted(current.get("groups") or [])}, after={}, identity_provider_group=None)

    def final(self, predicted: dict[str, t.Any]) -> dict[str, t.Any]:
        """Return the mapping from the server, or the prediction in check mode."""
        if self.mod.check_mode:
            return predicted
        mapping, _etag = self.read()
        return mapping or predicted


def get_argument_spec() -> ArgumentSpecMutT:
    """Return the argument spec of the module."""
    return {
        "name": {"type": "str", "required": True},
        "state": {"type": "str", "default": "present", "choices": ["present", "absent"]},
        "groups": {"type": "list", "elements": "str"},
    }


def main() -> None:
    """Run the module."""
    mod = LXDModule(get_argument_spec(), extensions=["access_management"])
    mapping = ProviderGroupModule(mod)
    if mod.params["state"] == "present":
        mod.run(mapping.present)
    else:
        mod.run(mapping.absent)


if __name__ == "__main__":
    main()
