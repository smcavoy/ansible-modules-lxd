#!/usr/bin/python
# Copyright (c) 2026, Sean McAvoy
# GNU General Public License v3.0+ (see LICENSES/GPL-3.0-or-later.txt or https://www.gnu.org/licenses/gpl-3.0.txt)
# SPDX-License-Identifier: GPL-3.0-or-later

from __future__ import annotations

DOCUMENTATION = r"""
module: lxd_network_acl
short_description: Manage LXD network ACLs
version_added: "0.1.0"
description:
  - Create, update, and delete LXD network ACLs, with their ingress and egress rules.
  - The module compares rule lists as sets. The order of the rules does not cause a change.
author:
  - Sean McAvoy (@smcavoy)
extends_documentation_fragment:
  - smcavoy.lxd._attributes
  - smcavoy.lxd._attributes.action_group
  - smcavoy.lxd._connection
  - smcavoy.lxd._project
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
      - The ACL name.
    type: str
    required: true
  state:
    description:
      - The wanted state of the ACL.
    type: str
    choices:
      present: The ACL exists.
      absent: The ACL does not exist.
    default: present
  description:
    description:
      - The ACL description.
      - If not set, the module does not manage the description.
    type: str
  ingress:
    description:
      - The rules for incoming traffic.
      - If not set, the module does not manage the ingress rules. V([]) removes all ingress rules.
      - Each rule takes the keys C(action), C(state), C(source), C(destination), C(protocol), C(source_port),
        C(destination_port), C(icmp_type), C(icmp_code), and C(description).
      - C(action) is required. It is V(allow), V(reject), or V(drop).
      - C(state) is V(enabled), V(disabled), or V(logged). The default is V(enabled).
      - The other keys are strings. Their default is an empty string.
    type: list
    elements: dict
  egress:
    description:
      - The rules for outgoing traffic. The rules are the same as for O(ingress).
      - If not set, the module does not manage the egress rules. V([]) removes all egress rules.
    type: list
    elements: dict
notes:
  - An ACL config takes only C(user.*) keys.
  - LXD does not delete an ACL that a network or a NIC uses. The module then fails with the LXD error.
seealso:
  - module: smcavoy.lxd.lxd_network
  - name: LXD network ACLs
    description: The LXD documentation about network ACLs.
    link: https://documentation.ubuntu.com/lxd/latest/howto/network_acls/
"""

EXAMPLES = r"""
- name: Allow HTTP and HTTPS in, and drop all other incoming traffic
  smcavoy.lxd.lxd_network_acl:
    name: web-in
    description: Allow HTTP in
    ingress:
      - action: allow
        protocol: tcp
        destination_port: "80,443"

- name: Remove all egress rules and keep the ingress rules
  smcavoy.lxd.lxd_network_acl:
    name: web-in
    egress: []

- name: Remove the ACL
  smcavoy.lxd.lxd_network_acl:
    name: web-in
    state: absent
"""

RETURN = r"""
acl:
  description:
    - The ACL after the change, as LXD returns it.
    - In check mode, the predicted ACL.
    - V(null) after a delete.
  returned: always
  type: dict
  sample:
    name: web-in
    description: Allow HTTP in
    ingress:
      - action: allow
        state: enabled
        protocol: tcp
        destination_port: "80,443"
        source: ""
        destination: ""
        source_port: ""
        icmp_type: ""
        icmp_code: ""
        description: ""
    egress: []
    config: {}
    used_by: []
"""

import json
import typing as t

from ansible_collections.smcavoy.lxd.plugins.module_utils._client import api_path
from ansible_collections.smcavoy.lxd.plugins.module_utils._config import trim_list
from ansible_collections.smcavoy.lxd.plugins.module_utils._module import LXDModule
from ansible_collections.smcavoy.lxd.plugins.module_utils._resource import create_config, plan_common

if t.TYPE_CHECKING:  # pragma: no cover
    from ansible_collections.smcavoy.lxd.plugins.module_utils._typing import ArgumentSpecMutT

FIELDS = ("description", "ingress", "egress", "config")
RULE_DEFAULTS = {
    "action": "",
    "state": "enabled",
    "source": "",
    "destination": "",
    "protocol": "",
    "source_port": "",
    "destination_port": "",
    "icmp_type": "",
    "icmp_code": "",
    "description": "",
}
ACTIONS = ("allow", "reject", "drop")
STATES = ("enabled", "disabled", "logged")
# LXD removes the spaces around each item of these lists before it stores a rule.
LIST_KEYS = ("source", "destination", "source_port", "destination_port")


def normalize_rules(mod: LXDModule, direction: str, rules: list[t.Any]) -> list[dict[str, str]]:
    """Fill each rule with the defaults. Fail on a rule without an action, or with an unknown key or value."""
    result = []
    for number, rule in enumerate(rules, start=1):
        if not isinstance(rule, dict):
            mod.fail(f"rule {number} in {direction} is not a dictionary")
        unknown = sorted(set(rule) - set(RULE_DEFAULTS))
        if unknown:
            mod.fail(f"rule {number} in {direction} has unknown keys: {', '.join(unknown)}")
        filled = dict(RULE_DEFAULTS)
        for key, value in rule.items():
            # The same form as LXD stores, so that a second run sees no difference.
            filled[key] = trim_list(value) if key in LIST_KEYS else ("" if value is None else str(value).strip())
        if not filled["action"]:
            mod.fail(f"rule {number} in {direction} needs an action")
        if filled["action"] not in ACTIONS:
            mod.fail(f"rule {number} in {direction} has the action {filled['action']}, not one of {', '.join(ACTIONS)}")
        if filled["state"] not in STATES:
            mod.fail(f"rule {number} in {direction} has the state {filled['state']}, not one of {', '.join(STATES)}")
        result.append(filled)
    return result


def rule_set(rules: list[t.Any] | None) -> list[str]:
    """Return a sorted form of a rule list, for a compare that ignores order."""
    filled = [dict(RULE_DEFAULTS, **{k: ("" if v is None else str(v)) for k, v in rule.items()}) for rule in rules or []]
    return sorted(json.dumps(rule, sort_keys=True) for rule in filled)


def sorted_rules(rules: list[t.Any] | None) -> list[dict[str, t.Any]]:
    """Return a rule list in a stable order, for the diff."""
    return [json.loads(item) for item in rule_set(rules)]


class NetworkAclModule:
    """Manage one LXD network ACL."""

    def __init__(self, mod: LXDModule) -> None:
        self.mod = mod
        self.name: str = mod.params["name"]
        self.path = api_path("network-acls", self.name)
        self.rules = {
            direction: (None if mod.params[direction] is None else normalize_rules(mod, direction, mod.params[direction]))
            for direction in ("ingress", "egress")
        }

    def read(self) -> tuple[dict[str, t.Any] | None, str | None]:
        """Read the ACL."""
        return self.mod.client.get_or_none(self.path, self.mod.query())

    def diff_view(self, acl: dict[str, t.Any]) -> dict[str, t.Any]:
        """Return the managed fields with sorted rule lists."""
        view = {key: acl.get(key) for key in FIELDS}
        for direction in ("ingress", "egress"):
            view[direction] = sorted_rules(acl.get(direction))
        return view

    def present(self) -> None:
        """Make sure that the ACL exists with the wanted settings."""
        params = self.mod.params
        current, etag = self.read()
        if current is None:
            body = {
                "name": self.name,
                "description": params["description"] or "",
                "config": create_config(self.mod),
                "ingress": self.rules["ingress"] or [],
                "egress": self.rules["egress"] or [],
            }
            self.mod.write("POST", "/1.0/network-acls", query=self.mod.query(), body=body)
            self.mod.exit(True, before={}, after=self.diff_view(body), acl=self.final(dict(body, used_by=[])))
        plan = plan_common(self.mod, current, FIELDS)
        for direction in ("ingress", "egress"):
            wanted = self.rules[direction]
            if wanted is not None and rule_set(wanted) != rule_set(current.get(direction)):
                plan.set(direction, wanted)
        before, after = self.diff_view(plan.current), self.diff_view(plan.new)
        if not plan.is_changed:
            self.mod.exit(False, before=before, after=after, acl=current)
        body = {
            "description": plan.new.get("description") or "",
            "config": plan.new.get("config") or {},
            "ingress": plan.new.get("ingress") or [],
            "egress": plan.new.get("egress") or [],
        }
        self.mod.write("PUT", self.path, query=self.mod.query(), body=body, etag=etag)
        self.mod.exit(True, before=before, after=after, acl=self.final(plan.new))

    def absent(self) -> None:
        """Make sure that the ACL does not exist."""
        current, _etag = self.read()
        if current is None:
            self.mod.exit(False, before={}, after={}, acl=None)
        self.mod.write("DELETE", self.path, query=self.mod.query())
        self.mod.exit(True, before=self.diff_view(current), after={}, acl=None)

    def final(self, predicted: dict[str, t.Any]) -> dict[str, t.Any]:
        """Return the ACL from the server, or the prediction in check mode."""
        if self.mod.check_mode:
            return predicted
        acl, _etag = self.read()
        return acl or predicted


def get_argument_spec() -> ArgumentSpecMutT:
    """Return the argument spec of the module."""
    return {
        "name": {"type": "str", "required": True},
        "project": {"type": "str"},
        "state": {"type": "str", "default": "present", "choices": ["present", "absent"]},
        "description": {"type": "str"},
        "ingress": {"type": "list", "elements": "dict"},
        "egress": {"type": "list", "elements": "dict"},
        "config": {"type": "dict"},
        "config_mode": {"type": "str", "default": "merge", "choices": ["merge", "exact"]},
    }


def main() -> None:
    """Run the module."""
    mod = LXDModule(get_argument_spec(), extensions=["network_acl"])
    acl = NetworkAclModule(mod)
    if mod.params["state"] == "present":
        mod.run(acl.present)
    else:
        mod.run(acl.absent)


if __name__ == "__main__":
    main()
