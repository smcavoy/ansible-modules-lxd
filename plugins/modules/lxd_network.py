#!/usr/bin/python
# Copyright (c) 2026, Sean McAvoy
# GNU General Public License v3.0+ (see LICENSES/GPL-3.0-or-later.txt or https://www.gnu.org/licenses/gpl-3.0.txt)
# SPDX-License-Identifier: GPL-3.0-or-later

from __future__ import annotations

DOCUMENTATION = r"""
module: lxd_network
short_description: Manage LXD networks
version_added: "0.1.0"
description:
  - Create, update, and delete managed LXD networks of type V(bridge), V(macvlan), V(sriov), V(ovn), and V(physical).
  - On a cluster, the module creates the network with the pending-then-global flow, and it manages member-specific keys per member.
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
      - The network name. A bridge name has at most 15 characters.
    type: str
    required: true
  state:
    description:
      - The wanted state of the network.
    type: str
    choices:
      present: The network exists.
      absent: The network does not exist.
    default: present
  type:
    description:
      - The network type.
      - The module uses it only when it creates the network. On an existing network, the module warns and ignores a different value.
      - Only V(ovn) networks can live in a project other than V(default).
      - If not set, the module creates a V(bridge).
    type: str
    choices: ["bridge", "macvlan", "sriov", "ovn", "physical"]
  description:
    description:
      - The network description.
      - If not set, the module does not manage the description.
    type: str
  member_config:
    description:
      - Member-specific config keys per cluster member, as a dictionary of member name to keys.
      - A member-specific key in O(config) is the default for all members. O(member_config) overrides it.
      - Only valid on a cluster.
    type: dict
notes:
  - A task value V(auto) for C(ipv4.address) or C(ipv6.address) equals any address on the server.
  - LXD gives a new OVN network an IPv6 address also when the uplink has no IPv6. LXD then refuses every later update of the network.
    On such an uplink, create the OVN network with C(ipv6.address=none).
  - C(bgp.peers.<name>.password) holds a secret. The module masks it in the diff and the result.
  - A cluster create that did not finish leaves the network with the status C(Pending) or C(Errored). The module then fails.
    Find the cause, remove the network with O(state=absent), and run the task again.
seealso:
  - module: smcavoy.lxd.lxd_network_forward
  - name: LXD networks
    description: The LXD documentation about networks.
    link: https://documentation.ubuntu.com/lxd/latest/networks/
"""

EXAMPLES = r"""
- name: Create a bridge with NAT
  smcavoy.lxd.lxd_network:
    name: br-web
    config:
      ipv4.address: 10.123.0.1/24
      ipv4.nat: true
      ipv6.address: none

- name: Create a bridge on a cluster with one external interface per member
  smcavoy.lxd.lxd_network:
    name: br-ext
    config:
      ipv4.address: auto
    member_config:
      node1:
        bridge.external_interfaces: enp5s0
      node2:
        bridge.external_interfaces: enp6s0

- name: Delete the bridge
  smcavoy.lxd.lxd_network:
    name: br-web
    state: absent
"""

RETURN = r"""
network:
  description:
    - The network after the change, as LXD returns it.
    - On a cluster, the key C(members) holds the member-specific keys of each member.
    - In check mode, the predicted network.
    - V(null) after a delete.
  returned: always
  type: dict
  sample:
    name: br-web
    type: bridge
    managed: true
    status: Created
    description: ""
    config:
      ipv4.address: 10.123.0.1/24
      ipv4.nat: "true"
      ipv6.address: none
    used_by: []
"""

import typing as t

from ansible_collections.smcavoy.lxd.plugins.module_utils._client import api_path
from ansible_collections.smcavoy.lxd.plugins.module_utils._cluster import (
    local_keys,
    member_local_config,
    member_names,
    split_config,
    unfinished_create,
)
from ansible_collections.smcavoy.lxd.plugins.module_utils._config import (
    COMPUTED_KEYS,
    merge_config,
    normalize_config,
)
from ansible_collections.smcavoy.lxd.plugins.module_utils._module import LXDModule
from ansible_collections.smcavoy.lxd.plugins.module_utils._resource import Plan, warn_create_only

if t.TYPE_CHECKING:  # pragma: no cover
    from ansible_collections.smcavoy.lxd.plugins.module_utils._typing import ArgumentSpecMutT

FIELDS = ("description", "config", "members")
# The password of a BGP peer. The module masks it in the result and the diff.
SECRET_KEYS = r"^bgp\.peers\.[^.]+\.password$"
AUTO_KEYS = ("ipv4.address", "ipv6.address")


class NetworkModule:
    """Manage one LXD network."""

    def __init__(self, mod: LXDModule) -> None:
        self.mod = mod
        self.name: str = mod.params["name"]
        self.path = api_path("networks", self.name)
        self.clustered = mod.client.is_clustered()

    def read(self, target: str | None = None) -> tuple[dict[str, t.Any] | None, str | None]:
        """Read the network, or the view of one member."""
        return self.mod.client.get_or_none(self.path, self.mod.query(target=target))

    def desired_config(self, current: dict[str, t.Any] | None) -> dict[str, str | None] | None:
        """Return the task config, with V(auto) addresses dropped when the server has an address."""
        config = normalize_config(self.mod.params["config"])
        if config is None or current is None:
            return config
        server = current.get("config") or {}
        for key in AUTO_KEYS:
            if config.get(key) == "auto" and server.get(key) not in (None, "", "none"):
                del config[key]
        return config

    def local(self, net_type: str) -> set[str]:
        """Return the member-specific keys for this network type, on a cluster only."""
        if not self.clustered:
            return set()
        return local_keys(self.mod.client, f"network-{net_type}")

    def present(self) -> None:
        """Make sure that the network exists with the wanted settings."""
        params = self.mod.params
        if params["member_config"] and not self.clustered:
            self.mod.fail("member_config is only valid on a clustered server")
        current, etag = self.read()
        if current is None:
            self.create()
        unfinished = unfinished_create("network", self.name, current)
        if unfinished:
            self.mod.fail(unfinished)
        warn_create_only(self.mod, current, {"type": current.get("type")})
        local = self.local(current.get("type") or "bridge")
        desired = self.desired_config(current)
        desired_global, desired_local = split_config(desired or {}, local)
        current_global, _unused = split_config(current.get("config") or {}, local)
        plan = Plan(dict(current, config=current_global), FIELDS)
        if params["description"] is not None:
            plan.set("description", params["description"])
        new_global, global_changes = merge_config(
            current_global,
            desired_global if desired is not None else None,
            params["config_mode"],
            COMPUTED_KEYS["network"],
            keep=sorted(local),
        )
        if global_changes:
            plan.new["config"] = new_global
            plan.changed.append("config")
        member_updates = self.plan_members(desired_local, plan)
        if not plan.is_changed:
            self.mod.exit(False, before=plan.before(), after=plan.after(), network=self.with_members(current))
        if set(plan.changed) & {"description", "config"}:
            body = {"description": plan.new.get("description") or "", "config": plan.new.get("config") or {}}
            self.mod.write("PUT", self.path, query=self.mod.query(), body=body, etag=etag)
        for member, new_local in member_updates.items():
            # LXD replaces the whole config on a PUT with a target, the global keys too. So the body is the member view
            # with the new member-specific keys, as lxc sends it. The view is read now, after the global PUT.
            view, member_etag = self.read(target=member)
            member_global, _unused = split_config((view or {}).get("config") or {}, local)
            member_body = {"description": (view or {}).get("description") or "", "config": dict(member_global, **new_local)}
            self.mod.write("PUT", self.path, query=self.mod.query(target=member), body=member_body, etag=member_etag)
        self.mod.exit(True, before=plan.before(), after=plan.after(), network=self.final(plan.new))

    def plan_members(self, desired_local: dict[str, t.Any], plan: Plan) -> dict[str, dict[str, t.Any]]:
        """Compare the member-specific keys of each member. Return the new member-specific keys of each member that changes."""
        updates: dict[str, dict[str, t.Any]] = {}
        if not self.clustered:
            return updates
        params = self.mod.params
        members = member_names(self.mod.client)
        wanted = member_local_config(members, desired_local, params["member_config"])
        before: dict[str, t.Any] = {}
        after: dict[str, t.Any] = {}
        local = self.local(plan.current.get("type") or "bridge")
        for member in members:
            view, _etag = self.read(target=member)
            _unused, server_local = split_config((view or {}).get("config") or {}, local)
            new_local, changes = merge_config(server_local, normalize_config(wanted[member]), "merge")
            before[member] = server_local
            after[member] = new_local
            if changes:
                updates[member] = new_local
        plan.current["members"] = before
        plan.new["members"] = after
        if updates:
            plan.changed.append("members")
        return updates

    def create(self) -> t.NoReturn:
        """Create the network, with the pending-then-global flow on a cluster."""
        params = self.mod.params
        net_type = params["type"] or "bridge"
        config = {key: value for key, value in (self.desired_config(None) or {}).items() if value not in (None, "")}
        description = params["description"] or ""
        after: dict[str, t.Any] = {"description": description, "config": config}
        # An OVN network has no member-specific setup. LXD creates it on the whole cluster in one step.
        if self.clustered and net_type != "ovn":
            local = self.local(net_type)
            global_part, local_part = split_config(config, local)
            members = member_names(self.mod.client)
            wanted = member_local_config(members, local_part, params["member_config"])
            for member in members:
                member_body = {"name": self.name, "type": net_type, "config": normalize_config(wanted[member]) or {}}
                self.mod.write("POST", "/1.0/networks", query=self.mod.query(target=member), body=member_body)
            body = {"name": self.name, "type": net_type, "description": description, "config": global_part}
            after = {"description": description, "config": global_part, "members": wanted}
        else:
            body = {"name": self.name, "type": net_type, "description": description, "config": config}
        self.mod.write("POST", "/1.0/networks", query=self.mod.query(), body=body)
        predicted: dict[str, t.Any] = dict(body, managed=True, status="Created", used_by=[])
        self.mod.exit(True, before={}, after=after, network=self.final(predicted))

    def absent(self) -> None:
        """Make sure that the network does not exist."""
        current, _etag = self.read()
        if current is None:
            self.mod.exit(False, before={}, after={}, network=None)
        self.mod.write("DELETE", self.path, query=self.mod.query())
        before = {"description": current.get("description"), "config": current.get("config")}
        self.mod.exit(True, before=before, after={}, network=None)

    def with_members(self, network: dict[str, t.Any]) -> dict[str, t.Any]:
        """Add the member-specific keys of each member on a cluster."""
        if not self.clustered:
            return network
        local = self.local(network.get("type") or "bridge")
        members: dict[str, t.Any] = {}
        for member in member_names(self.mod.client):
            view, _etag = self.read(target=member)
            members[member] = split_config((view or {}).get("config") or {}, local)[1]
        return dict(network, members=members)

    def final(self, predicted: dict[str, t.Any]) -> dict[str, t.Any]:
        """Return the network from the server, or the prediction in check mode."""
        if self.mod.check_mode:
            return predicted
        network, _etag = self.read()
        return self.with_members(network or predicted)


def get_argument_spec() -> ArgumentSpecMutT:
    """Return the argument spec of the module."""
    return {
        "name": {"type": "str", "required": True},
        "project": {"type": "str"},
        "state": {"type": "str", "default": "present", "choices": ["present", "absent"]},
        "type": {"type": "str", "choices": ["bridge", "macvlan", "sriov", "ovn", "physical"]},
        "description": {"type": "str"},
        "config": {"type": "dict"},
        "config_mode": {"type": "str", "default": "merge", "choices": ["merge", "exact"]},
        "member_config": {"type": "dict"},
    }


def main() -> None:
    """Run the module."""
    mod = LXDModule(get_argument_spec(), extensions=["network"])
    mod.hide_secrets(SECRET_KEYS)
    network = NetworkModule(mod)
    if mod.params["state"] == "present":
        mod.run(network.present)
    else:
        mod.run(network.absent)


if __name__ == "__main__":
    main()
