#!/usr/bin/python
# Copyright (c) 2026, Sean McAvoy
# GNU General Public License v3.0+ (see LICENSES/GPL-3.0-or-later.txt or https://www.gnu.org/licenses/gpl-3.0.txt)
# SPDX-License-Identifier: GPL-3.0-or-later

from __future__ import annotations

DOCUMENTATION = r"""
module: lxd_network_peer
short_description: Manage peers between LXD OVN networks
version_added: "0.1.0"
description:
  - Create, update, and delete a peer from one OVN network to another OVN network.
  - A peer stays V(Pending) until the other network has a peer back to this network. Then both peers are V(Created).
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
      - The local OVN network.
    type: str
    required: true
  name:
    description:
      - The peer name.
    type: str
    required: true
  state:
    description:
      - The wanted state of the peer.
    type: str
    choices:
      present: The peer exists.
      absent: The peer does not exist.
    default: present
  target_network:
    description:
      - The other OVN network. Required to create the peer.
      - The module uses it only when it creates the peer. On an existing peer, the module warns and ignores a different value.
    type: str
  target_project:
    description:
      - The project of the other network. If not set, LXD uses the project of the local network.
      - The module uses it only when it creates the peer.
    type: str
  description:
    description:
      - The peer description.
      - If not set, the module does not manage the description.
    type: str
  config:
    description:
      - The peer config. Only C(user.*) keys.
      - A key with the value V(null) or an empty string is removed.
    type: dict
  config_mode:
    description:
      - How to treat config keys of the peer that are not in O(config).
    type: str
    choices:
      merge: Keep them.
      exact: Remove them.
    default: merge
notes:
  - The module does not wait for the V(Created) status. It returns the status in RV(peer).
seealso:
  - module: smcavoy.lxd.lxd_network
"""

EXAMPLES = r"""
- name: Peer ovn1 with ovn2
  smcavoy.lxd.lxd_network_peer:
    network: ovn1
    name: to-ovn2
    target_network: ovn2

- name: Peer ovn2 back with ovn1
  smcavoy.lxd.lxd_network_peer:
    network: ovn2
    name: to-ovn1
    target_network: ovn1
"""

RETURN = r"""
peer:
  description:
    - The peer after the change, as LXD returns it.
    - In check mode, the predicted peer.
    - V(null) after a delete.
  returned: always
  type: dict
  sample:
    name: to-ovn2
    description: ""
    target_project: default
    target_network: ovn2
    status: Created
    config: {}
    used_by: []
"""

import typing as t

from ansible_collections.smcavoy.lxd.plugins.module_utils._client import api_path
from ansible_collections.smcavoy.lxd.plugins.module_utils._module import LXDModule
from ansible_collections.smcavoy.lxd.plugins.module_utils._resource import create_config, plan_common, warn_create_only

if t.TYPE_CHECKING:  # pragma: no cover
    from ansible_collections.smcavoy.lxd.plugins.module_utils._typing import ArgumentSpecMutT

FIELDS = ("description", "config")


class PeerModule:
    """Manage one peer of an OVN network."""

    def __init__(self, mod: LXDModule) -> None:
        self.mod = mod
        params = mod.params
        self.collection = api_path("networks", params["network"], "peers")
        self.path = api_path("networks", params["network"], "peers", params["name"])
        for key in params["config"] or {}:
            if not str(key).startswith("user."):
                mod.fail(f"config key {key} is not a user.* key")

    def read(self) -> tuple[dict[str, t.Any] | None, str | None]:
        """Read the peer."""
        return self.mod.client.get_or_none(self.path, self.mod.query())

    def present(self) -> None:
        """Make sure that the peer exists with the wanted settings."""
        params = self.mod.params
        current, etag = self.read()
        if current is None:
            if not params["target_network"]:
                self.mod.fail(f"target_network is required to create peer {params['name']}")
            body: dict[str, t.Any] = {
                "name": params["name"],
                "target_network": params["target_network"],
                "description": params["description"] or "",
                "config": create_config(self.mod),
            }
            if params["target_project"]:
                body["target_project"] = params["target_project"]
            self.mod.write("POST", self.collection, query=self.mod.query(), body=body)
            after = {key: body[key] for key in FIELDS}
            predicted = dict(body, status="Pending", used_by=[])
            self.mod.exit(True, before={}, after=after, peer=self.final(predicted))
        warn_create_only(
            self.mod,
            current,
            {"target_network": current.get("target_network"), "target_project": current.get("target_project")},
        )
        plan = plan_common(self.mod, current, FIELDS)
        if not plan.is_changed:
            self.mod.exit(False, before=plan.before(), after=plan.after(), peer=current)
        body = {"description": plan.new.get("description") or "", "config": plan.new.get("config") or {}}
        self.mod.write("PUT", self.path, query=self.mod.query(), body=body, etag=etag)
        self.mod.exit(True, before=plan.before(), after=plan.after(), peer=self.final(dict(current, **plan.new)))

    def absent(self) -> None:
        """Make sure that the peer does not exist."""
        current, _etag = self.read()
        if current is None:
            self.mod.exit(False, before={}, after={}, peer=None)
        self.mod.write("DELETE", self.path, query=self.mod.query())
        self.mod.exit(True, before={key: current.get(key) for key in FIELDS}, after={}, peer=None)

    def final(self, predicted: dict[str, t.Any]) -> dict[str, t.Any]:
        """Return the peer from the server, or the prediction in check mode."""
        if self.mod.check_mode:
            return predicted
        peer, _etag = self.read()
        return peer or predicted


def get_argument_spec() -> ArgumentSpecMutT:
    """Return the argument spec of the module."""
    return {
        "network": {"type": "str", "required": True},
        "name": {"type": "str", "required": True},
        "project": {"type": "str"},
        "state": {"type": "str", "default": "present", "choices": ["present", "absent"]},
        "target_network": {"type": "str"},
        "target_project": {"type": "str"},
        "description": {"type": "str"},
        "config": {"type": "dict"},
        "config_mode": {"type": "str", "default": "merge", "choices": ["merge", "exact"]},
    }


def main() -> None:
    """Run the module."""
    mod = LXDModule(get_argument_spec(), extensions=["network_peer"])
    peer = PeerModule(mod)
    if mod.params["state"] == "present":
        mod.run(peer.present)
    else:
        mod.run(peer.absent)


if __name__ == "__main__":
    main()
