#!/usr/bin/python
# Copyright (c) 2026, Sean McAvoy
# GNU General Public License v3.0+ (see LICENSES/GPL-3.0-or-later.txt or https://www.gnu.org/licenses/gpl-3.0.txt)
# SPDX-License-Identifier: GPL-3.0-or-later

from __future__ import annotations

DOCUMENTATION = r"""
module: lxd_replicator
short_description: Manage LXD replicators
version_added: "0.1.0"
description:
  - Create, update, and delete replicators. A replicator copies the instances of a project to another cluster over a cluster link.
  - Use M(smcavoy.lxd.lxd_replicator_run) to start a run, and M(smcavoy.lxd.lxd_project) to set the replica modes of the projects.
author:
  - Sean McAvoy (@smcavoy)
extends_documentation_fragment:
  - smcavoy.lxd._attributes
  - smcavoy.lxd._attributes.action_group
  - smcavoy.lxd._connection
  - smcavoy.lxd._project
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
      - The replicator name.
    type: str
    required: true
  state:
    description:
      - The wanted state of the replicator.
    type: str
    choices:
      present: The replicator exists.
      absent: The replicator does not exist.
    default: present
  description:
    description:
      - The replicator description.
      - If not set, the module does not manage the description.
    type: str
  config:
    description:
      - The replicator config.
      - C(cluster) names the cluster link to the other cluster. It is required on create. The link must not be a public link.
      - C(schedule) is a cron expression, for example V(@daily) or V(0 6 * * *).
      - Other keys must start with C(user.).
      - A key with the value V(null) or an empty string is removed.
    type: dict
  config_mode:
    description:
      - How to treat config keys of the replicator that are not in O(config).
    type: str
    choices:
      merge: Keep them.
      exact: Remove them. The module always keeps C(cluster).
    default: merge
notes:
  - A project can have only one replicator for each cluster link.
  - A run needs the project in C(leader) mode here, and a project of the same name in C(standby) mode on the other cluster.
    The project in C(standby) mode needs the config key C(replica.cluster).
  - LXD promotes a project to C(leader) only when the project has a replicator.
seealso:
  - module: smcavoy.lxd.lxd_replicator_run
  - module: smcavoy.lxd.lxd_replicator_info
  - module: smcavoy.lxd.lxd_cluster_link
  - module: smcavoy.lxd.lxd_project
  - name: LXD replicators
    description: The LXD documentation about replicators.
    link: https://documentation.ubuntu.com/lxd/latest/howto/replicators_create/
"""

EXAMPLES = r"""
- name: Copy the project web to the cluster behind the link dr-site every day
  smcavoy.lxd.lxd_replicator:
    name: web-dr
    project: web
    config:
      cluster: dr-site
      schedule: "@daily"

- name: Stop the schedule and keep the replicator
  smcavoy.lxd.lxd_replicator:
    name: web-dr
    project: web
    config:
      schedule: null

- name: Remove the replicator
  smcavoy.lxd.lxd_replicator:
    name: web-dr
    project: web
    state: absent
"""

RETURN = r"""
replicator:
  description:
    - The replicator after the change, as LXD returns it.
    - In check mode, the predicted replicator.
    - V(null) after a delete.
  returned: always
  type: dict
  sample:
    name: web-dr
    project: web
    description: ""
    config:
      cluster: dr-site
      schedule: "@daily"
    last_run_at: "2026-11-07T06:00:00Z"
    last_run_status: Completed
    last_success_at: "2026-11-07T06:00:00Z"
"""

import typing as t

from ansible_collections.smcavoy.lxd.plugins.module_utils._client import api_path
from ansible_collections.smcavoy.lxd.plugins.module_utils._module import LXDModule
from ansible_collections.smcavoy.lxd.plugins.module_utils._resource import create_config, plan_common

if t.TYPE_CHECKING:  # pragma: no cover
    from ansible_collections.smcavoy.lxd.plugins.module_utils._typing import ArgumentSpecMutT

FIELDS = ("description", "config")
KEEP = ("cluster",)


class ReplicatorModule:
    """Manage one replicator."""

    def __init__(self, mod: LXDModule) -> None:
        self.mod = mod
        self.path = api_path("replicators", mod.params["name"])

    def read(self) -> tuple[dict[str, t.Any] | None, str | None]:
        """Read the replicator."""
        return self.mod.client.get_or_none(self.path, self.mod.query())

    def present(self) -> None:
        """Make sure that the replicator exists with the wanted settings."""
        params = self.mod.params
        current, etag = self.read()
        if current is None:
            config = create_config(self.mod)
            if not config.get("cluster"):
                self.mod.fail("config.cluster is required to create a replicator")
            body = {"name": params["name"], "description": params["description"] or "", "config": config}
            self.mod.write("POST", "/1.0/replicators", query=self.mod.query(), body=body)
            after = {key: body[key] for key in FIELDS}
            self.mod.exit(True, before={}, after=after, replicator=self.final(dict(body, project=params["project"] or "default")))
        plan = plan_common(self.mod, current, FIELDS, keep=KEEP)
        if not plan.is_changed:
            self.mod.exit(False, before=plan.before(), after=plan.after(), replicator=current)
        body = {"description": plan.new.get("description") or "", "config": plan.new.get("config") or {}}
        self.mod.write("PUT", self.path, query=self.mod.query(), body=body, etag=etag)
        self.mod.exit(True, before=plan.before(), after=plan.after(), replicator=self.final(dict(current, **plan.new)))

    def absent(self) -> None:
        """Make sure that the replicator does not exist."""
        current, _etag = self.read()
        if current is None:
            self.mod.exit(False, before={}, after={}, replicator=None)
        self.mod.write("DELETE", self.path, query=self.mod.query())
        self.mod.exit(True, before={key: current.get(key) for key in FIELDS}, after={}, replicator=None)

    def final(self, predicted: dict[str, t.Any]) -> dict[str, t.Any]:
        """Return the replicator from the server, or the prediction in check mode."""
        if self.mod.check_mode:
            return predicted
        replicator, _etag = self.read()
        return replicator or predicted


def get_argument_spec() -> ArgumentSpecMutT:
    """Return the argument spec of the module."""
    return {
        "name": {"type": "str", "required": True},
        "project": {"type": "str"},
        "state": {"type": "str", "default": "present", "choices": ["present", "absent"]},
        "description": {"type": "str"},
        "config": {"type": "dict"},
        "config_mode": {"type": "str", "default": "merge", "choices": ["merge", "exact"]},
    }


def main() -> None:
    """Run the module."""
    mod = LXDModule(get_argument_spec(), extensions=["replicators"])
    replicator = ReplicatorModule(mod)
    if mod.params["state"] == "present":
        mod.run(replicator.present)
    else:
        mod.run(replicator.absent)


if __name__ == "__main__":
    main()
