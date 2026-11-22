#!/usr/bin/python
# Copyright (c) 2026, Sean McAvoy
# GNU General Public License v3.0+ (see LICENSES/GPL-3.0-or-later.txt or https://www.gnu.org/licenses/gpl-3.0.txt)
# SPDX-License-Identifier: GPL-3.0-or-later

from __future__ import annotations

DOCUMENTATION = r"""
module: lxd_cluster_member
short_description: Manage LXD cluster members
version_added: "0.1.0"
description:
  - Manage the roles, groups, failure domain, description, and config of a cluster member.
  - Evacuate a member, restore it, or remove it from the cluster.
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
      - The member name.
    type: str
    required: true
  state:
    description:
      - The wanted state of the member.
    type: str
    choices:
      present: The member is in the cluster and not evacuated. The module restores an evacuated member.
      evacuated: The member is evacuated. Its instances move or stop, as O(evacuate_mode) says.
      absent: The member is not in the cluster.
    default: present
  roles:
    description:
      - The roles that users can set, V(control-plane) and V(ovn-chassis).
      - LXD assigns the database roles, such as V(database-voter) and V(database-leader). The module never adds or removes them.
      - If not set, the module does not manage the roles.
    type: list
    elements: str
  groups:
    description:
      - The cluster groups of the member.
      - If not set, the module does not manage the groups.
    type: list
    elements: str
  failure_domain:
    description:
      - The failure domain of the member.
      - If not set, the module does not manage the failure domain.
    type: str
  description:
    description:
      - The member description.
      - If not set, the module does not manage the description.
    type: str
  evacuate_mode:
    description:
      - With O(state=evacuated), how LXD moves the instances.
      - With V(auto), or if not set, LXD chooses for each instance. The module then sends no mode.
    type: str
    choices: ["auto", "live-migrate", "migrate", "stop"]
  restore_mode:
    description:
      - With O(state=present) on an evacuated member. V(skip) restores the status, but leaves the instances where they are.
    type: str
    choices: ["skip"]
  force:
    description:
      - With O(state=evacuated), skip the raft quorum check.
      - With O(state=absent), remove a member that does not answer.
    type: bool
    default: false
notes:
  - The module does not add members. Members join with C(lxd init) or C(lxd_cluster).
  - The module compares roles and groups as sets.
seealso:
  - module: smcavoy.lxd.lxd_cluster_group
  - module: smcavoy.lxd.lxd_cluster_member_info
"""

EXAMPLES = r"""
- name: Put a member into a failure domain and a group
  smcavoy.lxd.lxd_cluster_member:
    name: node2
    failure_domain: rack-b
    groups:
      - default
      - gpu-nodes

- name: Evacuate a member for maintenance
  smcavoy.lxd.lxd_cluster_member:
    name: node2
    state: evacuated
    evacuate_mode: migrate

- name: Restore the member
  smcavoy.lxd.lxd_cluster_member:
    name: node2
"""

RETURN = r"""
member:
  description:
    - The member after the change, as LXD returns it.
    - In check mode, the predicted member.
    - V(null) after a delete.
  returned: always
  type: dict
  sample:
    server_name: node2
    url: https://10.0.0.12:8443
    status: Evacuated
    message: Unavailable due to maintenance
    roles:
      - database-voter
    groups:
      - default
    failure_domain: default
    description: ""
    config: {}
"""

import typing as t

from ansible_collections.smcavoy.lxd.plugins.module_utils._client import api_path
from ansible_collections.smcavoy.lxd.plugins.module_utils._config import merge_config, normalize_config
from ansible_collections.smcavoy.lxd.plugins.module_utils._module import LXDModule

if t.TYPE_CHECKING:  # pragma: no cover
    from ansible_collections.smcavoy.lxd.plugins.module_utils._typing import ArgumentSpecMutT


def is_automatic(role: str) -> bool:
    """Return whether LXD assigns this role itself. A PUT keeps such a role when the body leaves it out.

    LXD 6.10.1 has C(database-voter), C(database-standby) and C(database-leader). Older servers have C(database) and C(database-client).
    """
    return role == "database" or role.startswith("database-")


class ClusterMemberModule:
    """Manage one LXD cluster member."""

    def __init__(self, mod: LXDModule) -> None:
        self.mod = mod
        self.name: str = mod.params["name"]
        self.path = api_path("cluster", "members", self.name)
        if not mod.client.is_clustered():
            mod.fail("This server is not clustered")
        for role in mod.params["roles"] or []:
            if is_automatic(role):
                mod.fail(f"role {role} is assigned by LXD and cannot be set")

    def read(self) -> tuple[dict[str, t.Any] | None, str | None]:
        """Read the member."""
        return self.mod.client.get_or_none(self.path)

    @staticmethod
    def view(member: dict[str, t.Any]) -> dict[str, t.Any]:
        """Return the managed fields in a stable form, without the automatic roles."""
        return {
            "roles": sorted(role for role in member.get("roles") or [] if not is_automatic(role)),
            "groups": sorted(member.get("groups") or []),
            "failure_domain": member.get("failure_domain") or "",
            "description": member.get("description") or "",
            "config": dict(member.get("config") or {}),
        }

    def wanted(self, current: dict[str, t.Any]) -> dict[str, t.Any]:
        """Return the managed fields after the task."""
        params = self.mod.params
        new = self.view(current)
        if params["roles"] is not None:
            new["roles"] = sorted(set(params["roles"]))
        if params["groups"] is not None:
            new["groups"] = sorted(set(params["groups"]))
        for key in ("failure_domain", "description"):
            if params[key] is not None:
                new[key] = params[key]
        config, _changed = merge_config(new["config"], normalize_config(params["config"]), params["config_mode"])
        new["config"] = config
        return new

    def set_state(self, action: str, mode: str | None) -> None:
        """Evacuate or restore the member."""
        body: dict[str, t.Any] = {"action": action}
        if mode and mode != "auto":
            # LXD 6.10.1 has no mode with the name auto. Without a mode, LXD chooses for each instance.
            body["mode"] = mode
        if action == "evacuate" and self.mod.params["force"]:
            body["force"] = True
        self.mod.write("POST", f"{self.path}/state", body=body)

    def present(self, evacuated: bool) -> None:
        """Make sure that the member has the wanted fields and status."""
        params = self.mod.params
        current, etag = self.read()
        if current is None:
            self.mod.fail(f"cluster member {self.name} not found")
        before, after = self.view(current), self.wanted(current)
        is_evacuated = current.get("status") == "Evacuated"
        before["status"] = current.get("status")
        after["status"] = "Evacuated" if evacuated else ("Online" if is_evacuated else current.get("status"))
        fields_changed = {key: value for key, value in after.items() if key != "status"} != {key: value for key, value in before.items() if key != "status"}
        state_action = None
        if evacuated and not is_evacuated:
            state_action = ("evacuate", params["evacuate_mode"])
        elif not evacuated and is_evacuated:
            state_action = ("restore", params["restore_mode"])
        if not fields_changed and state_action is None:
            self.mod.exit(False, before=before, after=after, member=current)
        if fields_changed:
            body = {key: after[key] for key in ("roles", "groups", "failure_domain", "description", "config")}
            self.mod.write("PUT", self.path, body=body, etag=etag)
        if state_action:
            self.set_state(*state_action)
        self.mod.exit(True, before=before, after=after, member=self.final(dict(current, **after)))

    def absent(self) -> None:
        """Remove the member from the cluster."""
        current, _etag = self.read()
        if current is None:
            self.mod.exit(False, before={}, after={}, member=None)
        query = {"force": 1} if self.mod.params["force"] else None
        self.mod.write("DELETE", self.path, query=query)
        self.mod.exit(True, before=self.view(current), after={}, member=None)

    def final(self, predicted: dict[str, t.Any]) -> dict[str, t.Any]:
        """Return the member from the server, or the prediction in check mode."""
        if self.mod.check_mode:
            return predicted
        member, _etag = self.read()
        return member or predicted


def get_argument_spec() -> ArgumentSpecMutT:
    """Return the argument spec of the module."""
    return {
        "name": {"type": "str", "required": True},
        "state": {"type": "str", "default": "present", "choices": ["present", "evacuated", "absent"]},
        "roles": {"type": "list", "elements": "str"},
        "groups": {"type": "list", "elements": "str"},
        "failure_domain": {"type": "str"},
        "description": {"type": "str"},
        "config": {"type": "dict"},
        "config_mode": {"type": "str", "default": "merge", "choices": ["merge", "exact"]},
        "evacuate_mode": {"type": "str", "choices": ["auto", "live-migrate", "migrate", "stop"]},
        "restore_mode": {"type": "str", "choices": ["skip"]},
        "force": {"type": "bool", "default": False},
    }


def main() -> None:
    """Run the module."""
    mod = LXDModule(get_argument_spec(), extensions=["clustering_roles", "clustering_failure_domains", "clustering_groups"])
    member = ClusterMemberModule(mod)
    state = mod.params["state"]
    if state == "absent":
        mod.run(member.absent)
    else:
        mod.run(lambda: member.present(evacuated=state == "evacuated"))


if __name__ == "__main__":
    main()
