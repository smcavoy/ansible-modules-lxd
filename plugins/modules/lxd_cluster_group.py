#!/usr/bin/python
# Copyright (c) 2026, Sean McAvoy
# GNU General Public License v3.0+ (see LICENSES/GPL-3.0-or-later.txt or https://www.gnu.org/licenses/gpl-3.0.txt)
# SPDX-License-Identifier: GPL-3.0-or-later

from __future__ import annotations

DOCUMENTATION = r"""
module: lxd_cluster_group
short_description: Manage LXD cluster groups
version_added: "0.1.0"
description:
  - Create, update, and delete cluster groups and their members.
  - Instances and projects can target a group, for example with C(target=@gpu-nodes).
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
      absent: The group does not exist. The module removes its members first. A group that is in use fails the task, and the module changes nothing.
    default: present
  description:
    description:
      - The group description.
      - If not set, the module does not manage the description.
    type: str
  members:
    description:
      - The cluster members of the group.
      - If not set, the module does not manage the members.
    type: list
    elements: str
  members_mode:
    description:
      - How to treat members of the group that are not in O(members).
    type: str
    choices:
      exact: Remove them.
      merge: Keep them.
    default: exact
notes:
  - The module needs a cluster.
  - The module compares the members as a set. Their order does not cause a change.
  - LXD adds each new cluster member to the group V(default). The V(default) group cannot be deleted.
  - LXD does not delete a group that is in use, for example by a project with C(restricted.cluster.groups) or by an instance that was
    placed with C(target=@group). The key C(used_by) of the group lists the users.
seealso:
  - module: smcavoy.lxd.lxd_cluster_member
"""

EXAMPLES = r"""
- name: Put two members into a group
  smcavoy.lxd.lxd_cluster_group:
    name: gpu-nodes
    description: Members with GPUs
    members:
      - node2
      - node3

- name: Remove the group
  smcavoy.lxd.lxd_cluster_group:
    name: gpu-nodes
    state: absent
"""

RETURN = r"""
group:
  description:
    - The group after the change, as LXD returns it.
    - In check mode, the predicted group.
    - V(null) after a delete.
  returned: always
  type: dict
  sample:
    name: gpu-nodes
    description: Members with GPUs
    members:
      - node2
    used_by: []
"""

import typing as t

from ansible_collections.smcavoy.lxd.plugins.module_utils._client import api_path
from ansible_collections.smcavoy.lxd.plugins.module_utils._module import LXDModule

if t.TYPE_CHECKING:  # pragma: no cover
    from ansible_collections.smcavoy.lxd.plugins.module_utils._typing import ArgumentSpecMutT


class ClusterGroupModule:
    """Manage one LXD cluster group."""

    def __init__(self, mod: LXDModule) -> None:
        self.mod = mod
        self.name: str = mod.params["name"]
        self.path = api_path("cluster", "groups", self.name)
        if not mod.client.is_clustered():
            mod.fail("This server is not clustered")

    def read(self) -> tuple[dict[str, t.Any] | None, str | None]:
        """Read the group."""
        return self.mod.client.get_or_none(self.path)

    @staticmethod
    def view(group: dict[str, t.Any]) -> dict[str, t.Any]:
        """Return the managed fields in a stable form."""
        return {"description": group.get("description") or "", "members": sorted(group.get("members") or [])}

    def wanted(self, current: dict[str, t.Any]) -> dict[str, t.Any]:
        """Return the managed fields after the task."""
        params = self.mod.params
        new = self.view(current)
        if params["description"] is not None:
            new["description"] = params["description"]
        if params["members"] is not None:
            members = set(params["members"])
            if params["members_mode"] == "merge":
                members |= set(new["members"])
            new["members"] = sorted(members)
        return new

    def present(self) -> None:
        """Make sure that the group exists with the wanted fields."""
        current, etag = self.read()
        if current is None:
            after = self.wanted({})
            body = dict(after, name=self.name)
            self.mod.write("POST", "/1.0/cluster/groups", body=body)
            self.mod.exit(True, before={}, after=after, group=self.final(dict(body, used_by=[])))
        before, after = self.view(current), self.wanted(current)
        if before == after:
            self.mod.exit(False, before=before, after=after, group=current)
        self.mod.write("PUT", self.path, body=after, etag=etag)
        self.mod.exit(True, before=before, after=after, group=self.final(dict(current, **after)))

    def absent(self) -> None:
        """Make sure that the group does not exist. Remove its members first."""
        current, etag = self.read()
        if current is None:
            self.mod.exit(False, before={}, after={}, group=None)
        before = self.view(current)
        # LXD refuses to delete a group that is in use ("Cluster group is currently in use"). So the module does not empty it either.
        used_by = sorted(current.get("used_by") or [])
        if used_by:
            self.mod.fail(
                f"The cluster group {self.name} is in use and LXD cannot delete it. The module did not change it. "
                f"Remove these users of the group first: {', '.join(used_by)}",
                group=current,
            )
        # LXD refuses to delete the default group. Emptying it first would only give a less clear error.
        if before["members"] and self.name != "default":
            self.mod.write("PUT", self.path, body={"description": before["description"], "members": []}, etag=etag)
        self.mod.write("DELETE", self.path)
        self.mod.exit(True, before=before, after={}, group=None)

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
        "members": {"type": "list", "elements": "str"},
        "members_mode": {"type": "str", "default": "exact", "choices": ["exact", "merge"]},
    }


def main() -> None:
    """Run the module."""
    mod = LXDModule(get_argument_spec(), extensions=["clustering_groups"])
    group = ClusterGroupModule(mod)
    if mod.params["state"] == "present":
        mod.run(group.present)
    else:
        mod.run(group.absent)


if __name__ == "__main__":
    main()
