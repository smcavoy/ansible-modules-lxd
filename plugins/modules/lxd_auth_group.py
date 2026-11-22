#!/usr/bin/python
# Copyright (c) 2026, Sean McAvoy
# GNU General Public License v3.0+ (see LICENSES/GPL-3.0-or-later.txt or https://www.gnu.org/licenses/gpl-3.0.txt)
# SPDX-License-Identifier: GPL-3.0-or-later

from __future__ import annotations

DOCUMENTATION = r"""
module: lxd_auth_group
short_description: Manage LXD authorization groups
version_added: "0.1.0"
description:
  - Create, update, and delete authorization groups with their permissions.
  - The module does not manage group members. Use M(smcavoy.lxd.lxd_auth_identity) to set the groups of an identity.
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
      - The group name.
    type: str
    required: true
  state:
    description:
      - The wanted state of the group.
    type: str
    choices:
      present: The group exists.
      absent: The group does not exist.
    default: present
  description:
    description:
      - The group description.
      - If not set, the module does not manage the description.
    type: str
  permissions:
    description:
      - Permissions of the group. The module compares them as a set.
      - If not set, the module does not manage the permissions.
    type: list
    elements: dict
    suboptions:
      entity_type:
        description:
          - The entity type, for example V(project), V(instance), or V(server).
        type: str
        required: true
      url:
        description:
          - The API URL of the entity, for example V(/1.0/projects/web).
        type: str
        required: true
      entitlement:
        description:
          - The entitlement, for example V(operator) or V(viewer).
        type: str
        required: true
  permissions_mode:
    description:
      - How to treat permissions that are on the server but not in O(permissions).
    type: str
    choices:
      exact: Remove them.
      merge: Keep them.
    default: exact
seealso:
  - module: smcavoy.lxd.lxd_auth_identity
  - name: LXD access control
    description: The LXD documentation about fine-grained authorization.
    link: https://documentation.ubuntu.com/lxd/latest/explanation/authorization/
"""

EXAMPLES = r"""
- name: Let a group operate the web project
  smcavoy.lxd.lxd_auth_group:
    name: web-operators
    description: Operators of the web project
    permissions:
      - entity_type: project
        url: /1.0/projects/web
        entitlement: operator

- name: Remove the group
  smcavoy.lxd.lxd_auth_group:
    name: web-operators
    state: absent
"""

RETURN = r"""
auth_group:
  description:
    - The group after the change, as LXD returns it.
    - In check mode, the predicted group.
    - V(null) after a delete.
  returned: always
  type: dict
  sample:
    name: web-operators
    description: Operators of the web project
    permissions:
      - entity_type: project
        url: /1.0/projects/web
        entitlement: operator
    identities: {}
    identity_provider_groups: []
"""

import typing as t
from urllib.parse import parse_qsl, urlencode, urlsplit

from ansible_collections.smcavoy.lxd.plugins.module_utils._client import api_path
from ansible_collections.smcavoy.lxd.plugins.module_utils._module import LXDModule
from ansible_collections.smcavoy.lxd.plugins.module_utils._resource import Plan

if t.TYPE_CHECKING:  # pragma: no cover
    from ansible_collections.smcavoy.lxd.plugins.module_utils._typing import ArgumentSpecMutT

FIELDS = ("description", "permissions")


def normalize_url(url: str) -> str:
    """Return an entity URL in one form: without C(project=default), and with the query in a fixed order.

    LXD takes C(/1.0/instances/c1) as an instance of the default project, and returns C(/1.0/instances/c1?project=default).
    Without one form for both, each run sees a difference.
    """
    parts = urlsplit(url)
    query = sorted((key, value) for key, value in parse_qsl(parts.query, keep_blank_values=True) if (key, value) != ("project", "default"))
    return parts.path + ("?" + urlencode(query) if query else "")


def normalize_permissions(items: t.Iterable[t.Mapping[str, t.Any]] | None) -> list[dict[str, str]]:
    """Return permissions as a sorted list without duplicates, each URL in the form of L(normalize_url)."""
    unique = {(str(item["entity_type"]), normalize_url(str(item["url"])), str(item["entitlement"])) for item in items or [] if item is not None}
    return [{"entity_type": e, "url": u, "entitlement": n} for e, u, n in sorted(unique)]


class AuthGroupModule:
    """Manage one authorization group."""

    def __init__(self, mod: LXDModule) -> None:
        self.mod = mod
        self.name: str = mod.params["name"]
        self.path = api_path("auth", "groups", self.name)

    def read(self) -> tuple[dict[str, t.Any] | None, str | None]:
        """Read the group."""
        return self.mod.client.get_or_none(self.path)

    def present(self) -> None:
        """Make sure that the group exists with the wanted settings."""
        params = self.mod.params
        current, etag = self.read()
        if current is None:
            body = {
                "name": self.name,
                "description": params["description"] or "",
                "permissions": normalize_permissions(params["permissions"]),
            }
            self.mod.write("POST", api_path("auth", "groups"), body=body)
            after = {key: body[key] for key in FIELDS}
            self.mod.exit(True, before={}, after=after, auth_group=self.final(dict(body, identities={})))
        server = current
        current = dict(current, permissions=normalize_permissions(current.get("permissions")))
        plan = Plan(current, FIELDS)
        if params["description"] is not None:
            plan.set("description", params["description"])
        if params["permissions"] is not None:
            wanted = normalize_permissions(params["permissions"])
            if params["permissions_mode"] == "merge":
                wanted = normalize_permissions(current["permissions"] + wanted)
            plan.set("permissions", wanted)
        if not plan.is_changed:
            self.mod.exit(False, before=plan.before(), after=plan.after(), auth_group=server)
        body = {"description": plan.new.get("description") or "", "permissions": plan.new.get("permissions") or []}
        self.mod.write("PUT", self.path, body=body, etag=etag)
        self.mod.exit(True, before=plan.before(), after=plan.after(), auth_group=self.final(plan.new))

    def absent(self) -> None:
        """Make sure that the group does not exist."""
        current, _etag = self.read()
        if current is None:
            self.mod.exit(False, before={}, after={}, auth_group=None)
        self.mod.write("DELETE", self.path)
        before = {"description": current.get("description"), "permissions": normalize_permissions(current.get("permissions"))}
        self.mod.exit(True, before=before, after={}, auth_group=None)

    def final(self, predicted: dict[str, t.Any]) -> dict[str, t.Any]:
        """Return the group from the server, or the prediction in check mode."""
        if self.mod.check_mode:
            return predicted
        group, _etag = self.read()
        return group or predicted


def get_argument_spec() -> ArgumentSpecMutT:
    """Return the argument spec of the module."""
    return {
        "name": {"type": "str", "required": True},
        "state": {"type": "str", "default": "present", "choices": ["present", "absent"]},
        "description": {"type": "str"},
        "permissions": {
            "type": "list",
            "elements": "dict",
            "options": {
                "entity_type": {"type": "str", "required": True},
                "url": {"type": "str", "required": True},
                "entitlement": {"type": "str", "required": True},
            },
        },
        "permissions_mode": {"type": "str", "default": "exact", "choices": ["exact", "merge"]},
    }


def main() -> None:
    """Run the module."""
    mod = LXDModule(get_argument_spec(), extensions=["access_management"])
    group = AuthGroupModule(mod)
    if mod.params["state"] == "present":
        mod.run(group.present)
    else:
        mod.run(group.absent)


if __name__ == "__main__":
    main()
