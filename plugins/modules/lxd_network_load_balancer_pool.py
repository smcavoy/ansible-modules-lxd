#!/usr/bin/python
# Copyright (c) 2026, Sean McAvoy
# GNU General Public License v3.0+ (see LICENSES/GPL-3.0-or-later.txt or https://www.gnu.org/licenses/gpl-3.0.txt)
# SPDX-License-Identifier: GPL-3.0-or-later

from __future__ import annotations

DOCUMENTATION = r"""
module: lxd_network_load_balancer_pool
short_description: Manage LXD OVN load balancer pools
version_added: "0.1.0"
description:
  - Create, update, and delete pools of instances that OVN load balancer ports can target, with health checks.
  - A port of M(smcavoy.lxd.lxd_network_load_balancer) uses a pool with C(target_pool).
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
  network:
    description:
      - The OVN network.
    type: str
    required: true
  name:
    description:
      - The pool name.
    type: str
    required: true
  state:
    description:
      - The wanted state of the pool.
    type: str
    choices:
      present: The pool exists.
      absent: The pool does not exist.
    default: present
  description:
    description:
      - The pool description.
      - If not set, the module does not manage the description.
    type: str
  config:
    description:
      - The pool config, for example C(target_port), C(protocol), C(healthcheck), and C(healthcheck.interval).
      - LXD needs C(target_port) to create the pool.
      - A key with the value V(null) or an empty string is removed.
    type: dict
  config_mode:
    description:
      - How to treat config keys of the pool that are not in O(config).
    type: str
    choices:
      merge: Keep them.
      exact: Remove them.
    default: merge
  instances:
    description:
      - The instances of the pool. The module compares them as a set by name.
      - An empty list means no instances. If not set, the module does not manage the instances.
    type: list
    elements: dict
    suboptions:
      name:
        description:
          - The instance name.
        type: str
        required: true
      target_port:
        description:
          - A target port for this instance instead of C(config.target_port).
        type: str
notes:
  - LXD does not check C(If-Match) on a pool update. The module has no protection against a lost update.
seealso:
  - module: smcavoy.lxd.lxd_network_load_balancer
"""

EXAMPLES = r"""
- name: A pool of two web containers with health checks
  smcavoy.lxd.lxd_network_load_balancer_pool:
    network: ovn1
    name: web
    config:
      target_port: "80"
      healthcheck: "true"
    instances:
      - name: web1
      - name: web2
"""

RETURN = r"""
load_balancer_pool:
  description:
    - The pool after the change, as LXD returns it, with C(state) from the state endpoint when LXD gives it.
    - In check mode, the predicted pool.
    - V(null) after a delete.
  returned: always
  type: dict
  sample:
    name: web
    description: ""
    config:
      target_port: "80"
    instances:
      - name: web1
        target_port: ""
    used_by: []
"""

import typing as t

from ansible_collections.smcavoy.lxd.plugins.module_utils._client import LXDClientError, api_path
from ansible_collections.smcavoy.lxd.plugins.module_utils._module import LXDModule
from ansible_collections.smcavoy.lxd.plugins.module_utils._resource import create_config, plan_common

if t.TYPE_CHECKING:  # pragma: no cover
    from ansible_collections.smcavoy.lxd.plugins.module_utils._typing import ArgumentSpecMutT

FIELDS = ("description", "config", "instances")


def sorted_instances(instances: t.Iterable[t.Mapping[str, t.Any]] | None) -> list[dict[str, str]]:
    """Normalize the instances and sort them by name."""
    items = [{"name": str(item.get("name") or ""), "target_port": str(item.get("target_port") or "")} for item in instances or []]
    return sorted(items, key=lambda item: item["name"])


class PoolModule:
    """Manage one OVN load balancer pool."""

    def __init__(self, mod: LXDModule) -> None:
        self.mod = mod
        params = mod.params
        self.collection = api_path("networks", params["network"], "load-balancer-pools")
        self.path = api_path("networks", params["network"], "load-balancer-pools", params["name"])

    def read(self) -> tuple[dict[str, t.Any] | None, str | None]:
        """Read the pool."""
        return self.mod.client.get_or_none(self.path, self.mod.query())

    def with_state(self, pool: dict[str, t.Any]) -> dict[str, t.Any]:
        """Add the target state of the pool. Keep the pool as it is when LXD gives no state."""
        if self.mod.check_mode:
            return pool
        try:
            state, _etag = self.mod.client.get(f"{self.path}/state", self.mod.query())
        except LXDClientError:
            return pool
        return dict(pool, state=state)

    def present(self) -> None:
        """Make sure that the pool exists with the wanted settings."""
        params = self.mod.params
        current, etag = self.read()
        if current is None:
            config = create_config(self.mod)
            if not config.get("target_port"):
                self.mod.fail("config.target_port is required on create")
            body = {
                "name": params["name"],
                "description": params["description"] or "",
                "config": config,
                "instances": sorted_instances(params["instances"]),
            }
            self.mod.write("POST", self.collection, query=self.mod.query(), body=body)
            after = {key: body[key] for key in FIELDS}
            self.mod.exit(True, before={}, after=after, load_balancer_pool=self.with_state(self.final(dict(body, used_by=[]))))
        current = dict(current, instances=sorted_instances(current.get("instances")))
        plan = plan_common(self.mod, current, FIELDS)
        if params["instances"] is not None:
            plan.set("instances", sorted_instances(params["instances"]))
        if not plan.is_changed:
            self.mod.exit(False, before=plan.before(), after=plan.after(), load_balancer_pool=self.with_state(current))
        body = {
            "description": plan.new.get("description") or "",
            "config": plan.new.get("config") or {},
            "instances": plan.new.get("instances") or [],
        }
        self.mod.write("PUT", self.path, query=self.mod.query(), body=body, etag=etag)
        self.mod.exit(True, before=plan.before(), after=plan.after(), load_balancer_pool=self.with_state(self.final(plan.new)))

    def absent(self) -> None:
        """Make sure that the pool does not exist."""
        current, _etag = self.read()
        if current is None:
            self.mod.exit(False, before={}, after={}, load_balancer_pool=None)
        self.mod.write("DELETE", self.path, query=self.mod.query())
        self.mod.exit(True, before={key: current.get(key) for key in FIELDS}, after={}, load_balancer_pool=None)

    def final(self, predicted: dict[str, t.Any]) -> dict[str, t.Any]:
        """Return the pool from the server, or the prediction in check mode."""
        if self.mod.check_mode:
            return predicted
        pool, _etag = self.read()
        return pool or predicted


def get_argument_spec() -> ArgumentSpecMutT:
    """Return the argument spec of the module."""
    return {
        "network": {"type": "str", "required": True},
        "name": {"type": "str", "required": True},
        "project": {"type": "str"},
        "state": {"type": "str", "default": "present", "choices": ["present", "absent"]},
        "description": {"type": "str"},
        "config": {"type": "dict"},
        "config_mode": {"type": "str", "default": "merge", "choices": ["merge", "exact"]},
        "instances": {
            "type": "list",
            "elements": "dict",
            "options": {
                "name": {"type": "str", "required": True},
                "target_port": {"type": "str"},
            },
        },
    }


def main() -> None:
    """Run the module."""
    mod = LXDModule(get_argument_spec(), extensions=["network_load_balancer_pool"])
    pool = PoolModule(mod)
    if mod.params["state"] == "present":
        mod.run(pool.present)
    else:
        mod.run(pool.absent)


if __name__ == "__main__":
    main()
