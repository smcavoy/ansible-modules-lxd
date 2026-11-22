#!/usr/bin/python
# Copyright (c) 2026, Sean McAvoy
# GNU General Public License v3.0+ (see LICENSES/GPL-3.0-or-later.txt or https://www.gnu.org/licenses/gpl-3.0.txt)
# SPDX-License-Identifier: GPL-3.0-or-later

from __future__ import annotations

DOCUMENTATION = r"""
module: lxd_network_load_balancer
short_description: Manage LXD OVN load balancers
version_added: "0.1.0"
description:
  - Create, update, and delete load balancers on OVN networks, with their backends and port rules.
  - Only V(ovn) networks support load balancers. The listen address must be in a range that the uplink network allows.
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
  listen_address:
    description:
      - The external IP address of the load balancer.
    type: str
    required: true
  state:
    description:
      - The wanted state of the load balancer.
    type: str
    choices:
      present: The load balancer exists.
      absent: The load balancer does not exist.
    default: present
  description:
    description:
      - The load balancer description.
      - If not set, the module does not manage the description.
    type: str
  config:
    description:
      - The load balancer config.
      - A key with the value V(null) or an empty string is removed.
    type: dict
  config_mode:
    description:
      - How to treat config keys of the load balancer that are not in O(config).
    type: str
    choices:
      merge: Keep them.
      exact: Remove them.
    default: merge
  backends:
    description:
      - The backends. The module compares them as a set.
      - An empty list means no backends. If not set, the module does not manage the backends.
    type: list
    elements: dict
    suboptions:
      name:
        description:
          - The backend name. Port rules refer to it.
        type: str
        required: true
      target_address:
        description:
          - The IP address of the backend.
        type: str
        required: true
      target_port:
        description:
          - The target port. If not set, the backend gets the listen port of each port rule.
        type: str
      description:
        description:
          - The backend description.
        type: str
  ports:
    description:
      - The port rules. The module compares them as a set.
      - An empty list means no port rules. If not set, the module does not manage the port rules.
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
      target_backend:
        description:
          - The names of the backends for this rule. The module compares them as a set.
        type: list
        elements: str
      target_pool:
        description:
          - A load balancer pool instead of O(ports[].target_backend). Needs the API extension C(network_load_balancer_pool).
        type: str
      description:
        description:
          - The rule description.
        type: str
notes:
  - LXD does not check C(If-Match) on a load balancer update. The module has no protection against a lost update.
seealso:
  - module: smcavoy.lxd.lxd_network
  - module: smcavoy.lxd.lxd_network_forward
"""

EXAMPLES = r"""
- name: Balance HTTP over two containers
  smcavoy.lxd.lxd_network_load_balancer:
    network: ovn1
    listen_address: 192.0.2.150
    description: Web pool
    backends:
      - name: web1
        target_address: 10.205.185.2
        target_port: "80"
      - name: web2
        target_address: 10.205.185.3
        target_port: "80"
    ports:
      - protocol: tcp
        listen_port: "80"
        target_backend: [web1, web2]
"""

RETURN = r"""
load_balancer:
  description:
    - The load balancer after the change, as LXD returns it.
    - In check mode, the predicted load balancer.
    - V(null) after a delete.
  returned: always
  type: dict
  sample:
    listen_address: 192.0.2.150
    description: Web pool
    config: {}
    backends:
      - name: web1
        target_address: 10.205.185.2
        target_port: "80"
        description: ""
    ports:
      - protocol: tcp
        listen_port: "80"
        target_backend:
          - web1
        description: ""
"""

import typing as t

from ansible_collections.smcavoy.lxd.plugins.module_utils._client import api_path
from ansible_collections.smcavoy.lxd.plugins.module_utils._config import canonical_ip, trim_list
from ansible_collections.smcavoy.lxd.plugins.module_utils._module import LXDModule
from ansible_collections.smcavoy.lxd.plugins.module_utils._resource import create_config, plan_common

if t.TYPE_CHECKING:  # pragma: no cover
    from ansible_collections.smcavoy.lxd.plugins.module_utils._typing import ArgumentSpecMutT

FIELDS = ("description", "config", "backends", "ports")


def normalize_backend(backend: t.Mapping[str, t.Any]) -> dict[str, str]:
    """Return a backend in the form that LXD stores."""
    return {
        "name": str(backend.get("name") or "").strip(),
        "target_address": canonical_ip(backend.get("target_address") or ""),
        "target_port": trim_list(backend.get("target_port") or ""),
        "description": str(backend.get("description") or "").strip(),
    }


def normalize_port(port: t.Mapping[str, t.Any]) -> dict[str, t.Any]:
    """Return a port rule in a stable form. The backend names are sorted. An empty pool is left out."""
    result: dict[str, t.Any] = {
        "protocol": str(port.get("protocol") or "").strip(),
        "listen_port": trim_list(port.get("listen_port") or ""),
        "target_backend": sorted(str(name) for name in port.get("target_backend") or []),
        "description": str(port.get("description") or "").strip(),
    }
    if port.get("target_pool"):
        result["target_pool"] = str(port["target_pool"])
    return result


def sorted_backends(backends: t.Iterable[t.Mapping[str, t.Any]] | None) -> list[dict[str, str]]:
    """Normalize the backends and sort them by name."""
    return sorted((normalize_backend(item) for item in backends or []), key=lambda item: item["name"])


def sorted_ports(ports: t.Iterable[t.Mapping[str, t.Any]] | None) -> list[dict[str, t.Any]]:
    """Normalize the port rules and sort them, so that two lists compare as sets."""
    normalized = [normalize_port(item) for item in ports or []]
    return sorted(normalized, key=lambda item: (item["protocol"], item["listen_port"], ",".join(item["target_backend"]), item.get("target_pool", "")))


class LoadBalancerModule:
    """Manage one OVN load balancer."""

    def __init__(self, mod: LXDModule) -> None:
        self.mod = mod
        params = mod.params
        # LXD stores the canonical form of the address. The path of the load balancer must have that form too.
        params["listen_address"] = canonical_ip(params["listen_address"])
        self.collection = api_path("networks", params["network"], "load-balancers")
        self.path = api_path("networks", params["network"], "load-balancers", params["listen_address"])
        self.check_ports()

    def check_ports(self) -> None:
        """Fail early on a port rule that names an unknown backend, or that has both a backend and a pool."""
        params = self.mod.params
        names = {item["name"] for item in params["backends"] or []}
        for index, port in enumerate(params["ports"] or []):
            if port.get("target_backend") and port.get("target_pool"):
                self.mod.fail(f"port {index} takes target_backend or target_pool, not both")
            if params["backends"] is None:
                continue
            for name in port.get("target_backend") or []:
                if name not in names:
                    self.mod.fail(f"port {index} names an unknown backend {name}")
        if any(port.get("target_pool") for port in params["ports"] or []):
            missing = self.mod.client.missing_extensions(["network_load_balancer_pool"])
            if missing:
                self.mod.fail(f"LXD server lacks the API extensions: {', '.join(missing)}")

    def read(self) -> tuple[dict[str, t.Any] | None, str | None]:
        """Read the load balancer."""
        return self.mod.client.get_or_none(self.path, self.mod.query())

    def present(self) -> None:
        """Make sure that the load balancer exists with the wanted settings."""
        params = self.mod.params
        current, etag = self.read()
        if current is None:
            body = {
                "listen_address": params["listen_address"],
                "description": params["description"] or "",
                "config": create_config(self.mod),
                "backends": sorted_backends(params["backends"]),
                "ports": sorted_ports(params["ports"]),
            }
            self.mod.write("POST", self.collection, query=self.mod.query(), body=body)
            after = {key: body[key] for key in FIELDS}
            self.mod.exit(True, before={}, after=after, load_balancer=self.final(body))
        current = dict(current, backends=sorted_backends(current.get("backends")), ports=sorted_ports(current.get("ports")))
        plan = plan_common(self.mod, current, FIELDS)
        if params["backends"] is not None:
            plan.set("backends", sorted_backends(params["backends"]))
        if params["ports"] is not None:
            plan.set("ports", sorted_ports(params["ports"]))
        if not plan.is_changed:
            self.mod.exit(False, before=plan.before(), after=plan.after(), load_balancer=current)
        body = {
            "description": plan.new.get("description") or "",
            "config": plan.new.get("config") or {},
            "backends": plan.new.get("backends") or [],
            "ports": plan.new.get("ports") or [],
        }
        self.mod.write("PUT", self.path, query=self.mod.query(), body=body, etag=etag)
        self.mod.exit(True, before=plan.before(), after=plan.after(), load_balancer=self.final(plan.new))

    def absent(self) -> None:
        """Make sure that the load balancer does not exist."""
        current, _etag = self.read()
        if current is None:
            self.mod.exit(False, before={}, after={}, load_balancer=None)
        self.mod.write("DELETE", self.path, query=self.mod.query())
        self.mod.exit(True, before={key: current.get(key) for key in FIELDS}, after={}, load_balancer=None)

    def final(self, predicted: dict[str, t.Any]) -> dict[str, t.Any]:
        """Return the load balancer from the server, or the prediction in check mode."""
        if self.mod.check_mode:
            return predicted
        balancer, _etag = self.read()
        return balancer or predicted


def get_argument_spec() -> ArgumentSpecMutT:
    """Return the argument spec of the module."""
    return {
        "network": {"type": "str", "required": True},
        "listen_address": {"type": "str", "required": True},
        "project": {"type": "str"},
        "state": {"type": "str", "default": "present", "choices": ["present", "absent"]},
        "description": {"type": "str"},
        "config": {"type": "dict"},
        "config_mode": {"type": "str", "default": "merge", "choices": ["merge", "exact"]},
        "backends": {
            "type": "list",
            "elements": "dict",
            "options": {
                "name": {"type": "str", "required": True},
                "target_address": {"type": "str", "required": True},
                "target_port": {"type": "str"},
                "description": {"type": "str"},
            },
        },
        "ports": {
            "type": "list",
            "elements": "dict",
            "options": {
                "protocol": {"type": "str", "required": True, "choices": ["tcp", "udp"]},
                "listen_port": {"type": "str", "required": True},
                "target_backend": {"type": "list", "elements": "str"},
                "target_pool": {"type": "str"},
                "description": {"type": "str"},
            },
        },
    }


def main() -> None:
    """Run the module."""
    mod = LXDModule(get_argument_spec(), extensions=["network_load_balancer"])
    balancer = LoadBalancerModule(mod)
    if mod.params["state"] == "present":
        mod.run(balancer.present)
    else:
        mod.run(balancer.absent)


if __name__ == "__main__":
    main()
