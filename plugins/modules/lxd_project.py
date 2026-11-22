#!/usr/bin/python
# Copyright (c) 2026, Sean McAvoy
# GNU General Public License v3.0+ (see LICENSES/GPL-3.0-or-later.txt or https://www.gnu.org/licenses/gpl-3.0.txt)
# SPDX-License-Identifier: GPL-3.0-or-later

from __future__ import annotations

DOCUMENTATION = r"""
module: lxd_project
short_description: Manage LXD projects
version_added: "0.1.0"
description:
  - Create, update, and delete LXD projects, with their config, description, and replica mode.
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
      - The project name.
    type: str
    required: true
  state:
    description:
      - The wanted state of the project.
    type: str
    choices:
      present: The project exists.
      absent: The project does not exist.
    default: present
  description:
    description:
      - The project description.
      - If not set, the module does not manage the description.
    type: str
  default_storage_pool:
    description:
      - A storage pool for the root disk of the new default profile.
      - The module uses it only when it creates the project. On an existing project, the module warns and ignores it.
    type: str
  default_network:
    description:
      - A network for the NIC of the new default profile.
      - The module uses it only when it creates the project. On an existing project, the module warns and ignores it.
    type: str
  replica_mode:
    description:
      - The replica mode of the project. Use an empty string to clear it.
      - If not set, the module does not manage the replica mode.
    type: str
    choices: ["leader", "standby", ""]
  force_delete:
    description:
      - With O(state=absent), delete the project and every object in it.
    type: bool
    default: false
notes:
  - LXD sets C(features.images), C(features.profiles), C(features.storage.volumes), and C(features.storage.buckets) to V(true)
    when the create request does not hold them. With O(config_mode=exact), the module keeps these keys.
seealso:
  - module: smcavoy.lxd.lxd_profile
  - name: LXD projects
    description: The LXD documentation about projects.
    link: https://documentation.ubuntu.com/lxd/latest/projects/
"""

EXAMPLES = r"""
- name: Create a project for web servers
  smcavoy.lxd.lxd_project:
    name: web
    description: Web servers
    config:
      features.networks: false
      limits.instances: 10

- name: Delete a project and everything in it
  smcavoy.lxd.lxd_project:
    name: web
    state: absent
    force_delete: true
"""

RETURN = r"""
project:
  description:
    - The project after the change, as LXD returns it.
    - In check mode, the predicted project.
    - V(null) after a delete.
  returned: always
  type: dict
  sample:
    name: web
    description: Web servers
    config:
      features.images: "true"
      limits.instances: "10"
    used_by: []
"""

import typing as t

from ansible_collections.smcavoy.lxd.plugins.module_utils._client import LXDClientError, api_path
from ansible_collections.smcavoy.lxd.plugins.module_utils._config import COMPUTED_KEYS
from ansible_collections.smcavoy.lxd.plugins.module_utils._module import LXDModule
from ansible_collections.smcavoy.lxd.plugins.module_utils._resource import (
    create_config,
    plan_common,
    warn_create_only,
)

if t.TYPE_CHECKING:  # pragma: no cover
    from ansible_collections.smcavoy.lxd.plugins.module_utils._typing import ArgumentSpecMutT

FIELDS = ("description", "config", "replica_mode")


class ProjectModule:
    """Manage one LXD project."""

    def __init__(self, mod: LXDModule) -> None:
        self.mod = mod
        self.name: str = mod.params["name"]
        self.path = api_path("projects", self.name)

    def read(self) -> tuple[dict[str, t.Any] | None, str | None]:
        """Read the project."""
        return self.mod.client.get_or_none(self.path)

    def present(self) -> None:
        """Make sure that the project exists with the wanted settings."""
        params = self.mod.params
        current, etag = self.read()
        if current is None:
            body: dict[str, t.Any] = {
                "name": self.name,
                "description": params["description"] or "",
                "config": create_config(self.mod),
            }
            if params["default_storage_pool"]:
                body["storage"] = params["default_storage_pool"]
            if params["default_network"]:
                body["network"] = params["default_network"]
            self.mod.write("POST", "/1.0/projects", body=body)
            if params["replica_mode"]:
                self.mod.write("PUT", api_path("projects", self.name, "state"), body={"replica_mode": params["replica_mode"]})
            after = {"description": body["description"], "config": body["config"], "replica_mode": params["replica_mode"] or ""}
            project = self.final(dict(body, replica_mode=after["replica_mode"], used_by=[]))
            self.mod.exit(True, before={}, after=after, project=project)
        warn_create_only(self.mod, current, {"default_storage_pool": None, "default_network": None})
        plan = plan_common(self.mod, current, FIELDS, COMPUTED_KEYS["project"])
        replica_changed = params["replica_mode"] is not None and (current.get("replica_mode") or "") != params["replica_mode"]
        if replica_changed:
            plan.set("replica_mode", params["replica_mode"])
        if not plan.is_changed:
            self.mod.exit(False, before=plan.before(), after=plan.after(), project=current)
        if set(plan.changed) - {"replica_mode"}:
            body = {"description": plan.new.get("description") or "", "config": plan.new.get("config") or {}}
            self.mod.write("PUT", self.path, body=body, etag=etag)
        if replica_changed:
            self.mod.write("PUT", api_path("projects", self.name, "state"), body={"replica_mode": params["replica_mode"]})
        self.mod.exit(True, before=plan.before(), after=plan.after(), project=self.final(plan.new))

    def absent(self) -> None:
        """Make sure that the project does not exist."""
        current, _etag = self.read()
        if current is None:
            self.mod.exit(False, before={}, after={}, project=None)
        if self.name == "default":
            self.mod.fail("The default project cannot be deleted")
        query = {"force": "true"} if self.mod.params["force_delete"] else None
        try:
            self.mod.write("DELETE", self.path, query=query)
        except LXDClientError as exc:
            if "Only empty projects" in exc.message:
                self.mod.fail(f"{exc.message}. Set force_delete to delete its contents.")
            raise
        before = {key: current.get(key) for key in FIELDS}
        self.mod.exit(True, before=before, after={}, project=None)

    def final(self, predicted: dict[str, t.Any]) -> dict[str, t.Any]:
        """Return the project from the server, or the prediction in check mode."""
        if self.mod.check_mode:
            return predicted
        project, _etag = self.read()
        return project or predicted


def get_argument_spec() -> ArgumentSpecMutT:
    """Return the argument spec of the module."""
    return {
        "name": {"type": "str", "required": True},
        "state": {"type": "str", "default": "present", "choices": ["present", "absent"]},
        "description": {"type": "str"},
        "config": {"type": "dict"},
        "config_mode": {"type": "str", "default": "merge", "choices": ["merge", "exact"]},
        "default_storage_pool": {"type": "str"},
        "default_network": {"type": "str"},
        "replica_mode": {"type": "str", "choices": ["leader", "standby", ""]},
        "force_delete": {"type": "bool", "default": False},
    }


def main() -> None:
    """Run the module."""
    mod = LXDModule(get_argument_spec(), extensions=["projects"])
    params = mod.params
    if params["replica_mode"] is not None:
        missing = mod.client.missing_extensions(["project_replica_mode"])
        if missing:
            mod.fail(f"LXD server lacks the API extensions: {', '.join(missing)}")
    project = ProjectModule(mod)
    if params["state"] == "present":
        mod.run(project.present)
    else:
        mod.run(project.absent)


if __name__ == "__main__":
    main()
