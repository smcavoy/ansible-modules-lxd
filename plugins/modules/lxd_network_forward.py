#!/usr/bin/python
# Copyright (c) 2026, Sean McAvoy
# GNU General Public License v3.0+ (see LICENSES/GPL-3.0-or-later.txt or https://www.gnu.org/licenses/gpl-3.0.txt)
# SPDX-License-Identifier: GPL-3.0-or-later

from __future__ import annotations

DOCUMENTATION = r"""
module: lxd_network_forward
short_description: Manage LXD network forwards
version_added: "0.1.0"
description:
  - Create, update, and delete network forwards that send traffic from a listen address to instances.
  - Only V(bridge) and V(ovn) networks support forwards.
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
  network:
    description:
      - The parent network.
    type: str
    required: true
  listen_address:
    description:
      - The external IP address of the forward.
      - The module refuses the unspecified address (V(0.0.0.0) or V(::)). LXD reads it as a request to allocate an address.
    type: str
    required: true
  target:
    description:
      - For a bridge on a cluster, the member that owns the forward.
      - Only valid on a cluster.
    type: str
  state:
    description:
      - The wanted state of the forward.
    type: str
    choices:
      present: The forward exists.
      absent: The forward does not exist.
    default: present
  description:
    description:
      - The forward description.
      - If not set, the module does not manage the description.
    type: str
  ports:
    description:
      - Port rules. The module compares them as a set.
      - An empty list means no port rules.
      - If not set, the module does not manage the port rules.
    type: list
    elements: dict
    suboptions:
      protocol:
        description:
          - The protocol.
        type: str
        required: true
        choices: ["tcp", "udp"]
      listen_port:
        description:
          - A port, a range, or a comma-separated list.
        type: str
        required: true
      target_address:
        description:
          - The target IP address.
        type: str
        required: true
      target_port:
        description:
          - The target port. If not set, LXD uses O(ports[].listen_port).
        type: str
      description:
        description:
          - The rule description.
        type: str
notes:
  - LXD 6.10.1 does not check C(If-Match) on a forward update. The module has no protection against a lost update.
seealso:
  - module: smcavoy.lxd.lxd_network
"""

EXAMPLES = r"""
- name: Forward port 8080 on the host address to a web container
  smcavoy.lxd.lxd_network_forward:
    network: lxdbr0
    listen_address: 192.0.2.10
    ports:
      - protocol: tcp
        listen_port: "8080"
        target_address: 10.99.0.20
        target_port: "80"

- name: Remove the forward
  smcavoy.lxd.lxd_network_forward:
    network: lxdbr0
    listen_address: 192.0.2.10
    state: absent
"""

RETURN = r"""
forward:
  description:
    - The forward after the change, as LXD returns it.
    - In check mode, the predicted forward.
    - V(null) after a delete.
  returned: always
  type: dict
  sample:
    listen_address: 192.0.2.10
    description: ""
    config: {}
    ports:
      - protocol: tcp
        listen_port: "8080"
        target_address: 10.99.0.20
        target_port: "80"
        description: ""
"""

import ipaddress
import typing as t

from ansible_collections.smcavoy.lxd.plugins.module_utils._client import api_path
from ansible_collections.smcavoy.lxd.plugins.module_utils._config import COMPUTED_KEYS, canonical_ip, trim_list
from ansible_collections.smcavoy.lxd.plugins.module_utils._module import LXDModule
from ansible_collections.smcavoy.lxd.plugins.module_utils._resource import create_config, plan_common

if t.TYPE_CHECKING:  # pragma: no cover
    from ansible_collections.smcavoy.lxd.plugins.module_utils._typing import ArgumentSpecMutT

FIELDS = ("description", "config", "ports")


def is_unspecified(address: t.Any) -> bool:
    """Tell whether a value is the unspecified address, C(0.0.0.0) or C(::) in any spelling."""
    try:
        return ipaddress.ip_address(str(address).strip()).is_unspecified
    except ValueError:
        return False


def normalize_port(port: t.Mapping[str, t.Any]) -> dict[str, str]:
    """Return a port rule in the form that LXD stores: no spaces in the port lists, and the canonical form of the address."""
    listen = trim_list(port.get("listen_port") or "")
    return {
        "protocol": str(port.get("protocol") or "").strip(),
        "listen_port": listen,
        "target_address": canonical_ip(port.get("target_address") or ""),
        "target_port": trim_list(port.get("target_port") or listen),
        "description": str(port.get("description") or "").strip(),
    }


def port_key(port: dict[str, str]) -> tuple[str, ...]:
    """Return a sort key for a port rule."""
    return (port["protocol"], port["listen_port"], port["target_address"], port["target_port"], port["description"])


def sorted_ports(ports: t.Iterable[t.Mapping[str, t.Any]] | None) -> list[dict[str, str]]:
    """Normalize and sort port rules, so that two lists compare as sets."""
    return sorted((normalize_port(port) for port in ports or []), key=port_key)


class ForwardModule:
    """Manage one network forward."""

    def __init__(self, mod: LXDModule) -> None:
        self.mod = mod
        params = mod.params
        # LXD stores the canonical form of the address. The path of the forward must have that form too.
        params["listen_address"] = canonical_ip(params["listen_address"])
        self.check_addresses()
        self.collection = api_path("networks", params["network"], "forwards")
        self.path = api_path("networks", params["network"], "forwards", params["listen_address"])

    def check_addresses(self) -> None:
        """Refuse the unspecified address, and give C(config.target_address) the form that LXD stores."""
        params = self.mod.params
        if is_unspecified(params["listen_address"]):
            self.mod.fail(
                f"listen_address {params['listen_address']} is the unspecified address. LXD reads it as a request to allocate a listen address,"
                " so the forward gets another address than the task names (a bridge network refuses the request)."
                " Give the listen address itself."
            )
        config = params.get("config")
        if config and isinstance(config.get("target_address"), str):
            # LXD stores the canonical form (fd42::10 for FD42:0::0010). Without this, each run reports a change.
            config["target_address"] = canonical_ip(config["target_address"])
        targets = [("config.target_address", (config or {}).get("target_address"))]
        targets += [(f"ports[{index}].target_address", port.get("target_address")) for index, port in enumerate(params.get("ports") or [])]
        for option, address in targets:
            if is_unspecified(address):
                self.mod.fail(f"{option} {address} is the unspecified address. LXD refuses it as a target: it is not in the subnet of the network.")

    def query(self) -> dict[str, t.Any]:
        """Return the query string with O(project) and O(target)."""
        return self.mod.query(target=self.mod.params["target"])

    def read(self) -> tuple[dict[str, t.Any] | None, str | None]:
        """Read the forward."""
        return self.mod.client.get_or_none(self.path, self.query())

    def present(self) -> None:
        """Make sure that the forward exists with the wanted settings."""
        params = self.mod.params
        current, etag = self.read()
        if current is None:
            body = {
                "listen_address": params["listen_address"],
                "description": params["description"] or "",
                "config": create_config(self.mod),
                "ports": sorted_ports(params["ports"]),
            }
            self.mod.write("POST", self.collection, query=self.query(), body=body)
            after = {key: body[key] for key in FIELDS}
            self.mod.exit(True, before={}, after=after, forward=self.final(body))
        current = dict(current, ports=sorted_ports(current.get("ports")))
        plan = plan_common(self.mod, current, FIELDS, COMPUTED_KEYS["network_forward"])
        if params["ports"] is not None:
            plan.set("ports", sorted_ports(params["ports"]))
        if not plan.is_changed:
            self.mod.exit(False, before=plan.before(), after=plan.after(), forward=current)
        body = {
            "description": plan.new.get("description") or "",
            "config": plan.new.get("config") or {},
            "ports": plan.new.get("ports") or [],
        }
        self.mod.write("PUT", self.path, query=self.query(), body=body, etag=etag)
        self.mod.exit(True, before=plan.before(), after=plan.after(), forward=self.final(plan.new))

    def absent(self) -> None:
        """Make sure that the forward does not exist."""
        current, _etag = self.read()
        if current is None:
            self.mod.exit(False, before={}, after={}, forward=None)
        self.mod.write("DELETE", self.path, query=self.query())
        before = {key: current.get(key) for key in FIELDS}
        self.mod.exit(True, before=before, after={}, forward=None)

    def final(self, predicted: dict[str, t.Any]) -> dict[str, t.Any]:
        """Return the forward from the server, or the prediction in check mode."""
        if self.mod.check_mode:
            return predicted
        forward, _etag = self.read()
        return forward or predicted


def get_argument_spec() -> ArgumentSpecMutT:
    """Return the argument spec of the module."""
    return {
        "network": {"type": "str", "required": True},
        "listen_address": {"type": "str", "required": True},
        "project": {"type": "str"},
        "target": {"type": "str"},
        "state": {"type": "str", "default": "present", "choices": ["present", "absent"]},
        "description": {"type": "str"},
        "config": {"type": "dict"},
        "config_mode": {"type": "str", "default": "merge", "choices": ["merge", "exact"]},
        "ports": {
            "type": "list",
            "elements": "dict",
            "options": {
                "protocol": {"type": "str", "required": True, "choices": ["tcp", "udp"]},
                "listen_port": {"type": "str", "required": True},
                "target_address": {"type": "str", "required": True},
                "target_port": {"type": "str"},
                "description": {"type": "str"},
            },
        },
    }


def main() -> None:
    """Run the module."""
    mod = LXDModule(get_argument_spec(), extensions=["network_forward"])
    mod.check_target()
    forward = ForwardModule(mod)
    if mod.params["state"] == "present":
        mod.run(forward.present)
    else:
        mod.run(forward.absent)


if __name__ == "__main__":
    main()
