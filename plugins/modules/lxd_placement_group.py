#!/usr/bin/python
# Copyright (c) 2026, Sean McAvoy
# GNU General Public License v3.0+ (see LICENSES/GPL-3.0-or-later.txt or https://www.gnu.org/licenses/gpl-3.0.txt)
# SPDX-License-Identifier: GPL-3.0-or-later

from __future__ import annotations

DOCUMENTATION = r"""
module: lxd_placement_group
short_description: Manage LXD placement groups
version_added: "0.1.0"
description:
  - Create, update, and delete placement groups on a cluster. A placement group spreads its instances over the members, or keeps them together.
  - An instance joins a group through its config key C(placement.group).
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
      - The group name.
    type: str
    required: true
  state:
    description:
      - The wanted state of the group.
    type: str
    choices:
      present: The group exists.
      absent: The group does not exist. LXD refuses to delete a group that an instance uses.
    default: present
  description:
    description:
      - The group description.
      - If not set, the module does not manage the description.
    type: str
  policy:
    description:
      - V(spread) puts the instances on different members. V(compact) puts them on the same member.
      - Required to create a group. The module sends it as the config key C(policy).
    type: str
    choices: ["spread", "compact"]
  rigor:
    description:
      - V(strict) refuses an instance when LXD cannot follow the policy. V(permissive) places it anyway.
      - Required to create a group. The module sends it as the config key C(rigor).
    type: str
    choices: ["strict", "permissive"]
  config:
    description:
      - Other config keys of the group. They must start with C(user.).
      - A key with the value V(null) or an empty string is removed.
    type: dict
  config_mode:
    description:
      - How to treat config keys of the group that are not in O(config).
    type: str
    choices:
      merge: Keep them.
      exact: Remove them. The module always keeps C(policy) and C(rigor).
    default: merge
notes:
  - Placement groups need a cluster.
seealso:
  - module: smcavoy.lxd.lxd_instance
  - module: smcavoy.lxd.lxd_cluster_group
"""

EXAMPLES = r"""
- name: Spread the web servers over the members
  smcavoy.lxd.lxd_placement_group:
    name: web-spread
    policy: spread
    rigor: strict

- name: Put an instance into the group
  smcavoy.lxd.lxd_instance:
    name: web1
    source:
      image: debian/13
      image_registry: images
    config:
      placement.group: web-spread
"""

RETURN = r"""
placement_group:
  description:
    - The group after the change, as LXD returns it.
    - In check mode, the predicted group.
    - V(null) after a delete.
  returned: always
  type: dict
  sample:
    name: web-spread
    project: default
    description: ""
    config:
      policy: spread
      rigor: strict
    used_by: []
"""

import typing as t

from ansible_collections.smcavoy.lxd.plugins.module_utils._client import api_path
from ansible_collections.smcavoy.lxd.plugins.module_utils._config import normalize_config
from ansible_collections.smcavoy.lxd.plugins.module_utils._module import LXDModule
from ansible_collections.smcavoy.lxd.plugins.module_utils._resource import create_config, plan_common

if t.TYPE_CHECKING:  # pragma: no cover
    from ansible_collections.smcavoy.lxd.plugins.module_utils._typing import ArgumentSpecMutT

FIELDS = ("description", "config")
KEEP = ("policy", "rigor")


class PlacementGroupModule:
    """Manage one placement group."""

    def __init__(self, mod: LXDModule) -> None:
        self.mod = mod
        self.path = api_path("placement-groups", mod.params["name"])
        params = mod.params
        for key in ("policy", "rigor"):
            if params["config"] and key in params["config"]:
                mod.fail(f"set {key} with the option {key}, not in config")
        if params["policy"] or params["rigor"]:
            config = dict(normalize_config(params["config"]) or {})
            for key in ("policy", "rigor"):
                if params[key]:
                    config[key] = params[key]
            params["config"] = config

    def read(self) -> tuple[dict[str, t.Any] | None, str | None]:
        """Read the group."""
        return self.mod.client.get_or_none(self.path, self.mod.query())

    def present(self) -> None:
        """Make sure that the group exists with the wanted settings."""
        params = self.mod.params
        current, etag = self.read()
        if current is None:
            if not (params["policy"] and params["rigor"]):
                self.mod.fail("policy and rigor are required to create a placement group")
            body = {"name": params["name"], "description": params["description"] or "", "config": create_config(self.mod)}
            self.mod.write("POST", "/1.0/placement-groups", query=self.mod.query(), body=body)
            after = {key: body[key] for key in FIELDS}
            predicted = dict(body, project=params["project"] or "default", used_by=[])
            self.mod.exit(True, before={}, after=after, placement_group=self.final(predicted))
        plan = plan_common(self.mod, current, FIELDS, keep=KEEP)
        if not plan.is_changed:
            self.mod.exit(False, before=plan.before(), after=plan.after(), placement_group=current)
        body = {"description": plan.new.get("description") or "", "config": plan.new.get("config") or {}}
        self.mod.write("PUT", self.path, query=self.mod.query(), body=body, etag=etag)
        self.mod.exit(True, before=plan.before(), after=plan.after(), placement_group=self.final(dict(current, **plan.new)))

    def absent(self) -> None:
        """Make sure that the group does not exist."""
        current, _etag = self.read()
        if current is None:
            self.mod.exit(False, before={}, after={}, placement_group=None)
        self.mod.write("DELETE", self.path, query=self.mod.query())
        self.mod.exit(True, before={key: current.get(key) for key in FIELDS}, after={}, placement_group=None)

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
        "project": {"type": "str"},
        "state": {"type": "str", "default": "present", "choices": ["present", "absent"]},
        "description": {"type": "str"},
        "policy": {"type": "str", "choices": ["spread", "compact"]},
        "rigor": {"type": "str", "choices": ["strict", "permissive"]},
        "config": {"type": "dict"},
        "config_mode": {"type": "str", "default": "merge", "choices": ["merge", "exact"]},
    }


def main() -> None:
    """Run the module."""
    mod = LXDModule(get_argument_spec(), extensions=["instance_placement_groups"])
    group = PlacementGroupModule(mod)
    if mod.params["state"] == "present":
        mod.run(group.present)
    else:
        mod.run(group.absent)


if __name__ == "__main__":
    main()
