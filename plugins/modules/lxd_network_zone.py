#!/usr/bin/python
# Copyright (c) 2026, Sean McAvoy
# GNU General Public License v3.0+ (see LICENSES/GPL-3.0-or-later.txt or https://www.gnu.org/licenses/gpl-3.0.txt)
# SPDX-License-Identifier: GPL-3.0-or-later

from __future__ import annotations

DOCUMENTATION = r"""
module: lxd_network_zone
short_description: Manage LXD network zones
version_added: "0.1.0"
description:
  - Create, update, and delete DNS zones that LXD serves for its networks.
  - A network uses a zone with its keys C(dns.zone.forward) and C(dns.zone.reverse.*).
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
      - The zone name, for example V(lxd.example.net).
    type: str
    required: true
  state:
    description:
      - The wanted state of the zone.
    type: str
    choices:
      present: The zone exists.
      absent: The zone does not exist.
    default: present
  description:
    description:
      - The zone description.
      - If not set, the module does not manage the description.
    type: str
notes:
  - The config keys are C(dns.nameservers), C(network.nat), C(peers.<name>.address), C(peers.<name>.key), and C(user.*).
  - C(peers.<name>.key) holds a TSIG secret. The module masks it in the diff and the result.
  - The server serves zones on C(core.dns_address).
seealso:
  - module: smcavoy.lxd.lxd_network_zone_record
  - module: smcavoy.lxd.lxd_network
"""

EXAMPLES = r"""
- name: Create a zone with a transfer peer
  smcavoy.lxd.lxd_network_zone:
    name: lxd.example.net
    config:
      dns.nameservers: ns1.example.net
      peers.ns1.address: 192.0.2.53
      peers.ns1.key: "{{ tsig_secret }}"
"""

RETURN = r"""
zone:
  description:
    - The zone after the change, as LXD returns it, with the peer keys masked.
    - In check mode, the predicted zone.
    - V(null) after a delete.
  returned: always
  type: dict
  sample:
    name: lxd.example.net
    description: ""
    config:
      dns.nameservers: ns1.example.net
      peers.ns1.key: "********"
    used_by: []
"""

import re
import typing as t

from ansible_collections.smcavoy.lxd.plugins.module_utils._client import api_path
from ansible_collections.smcavoy.lxd.plugins.module_utils._module import LXDModule
from ansible_collections.smcavoy.lxd.plugins.module_utils._resource import create_config, plan_common

if t.TYPE_CHECKING:  # pragma: no cover
    from ansible_collections.smcavoy.lxd.plugins.module_utils._typing import ArgumentSpecMutT

FIELDS = ("description", "config")
SECRET_KEY_RE = re.compile(r"^peers\.[^.]+\.key$")
MASK = "********"


def mask(zone: dict[str, t.Any] | None) -> dict[str, t.Any] | None:
    """Return a copy of a zone, or a diff part, with the peer keys masked."""
    if zone is None:
        return None
    result = dict(zone)
    if isinstance(result.get("config"), dict):
        result["config"] = {key: (MASK if SECRET_KEY_RE.match(key) and value else value) for key, value in result["config"].items()}
    return result


class NetworkZoneModule:
    """Manage one LXD network zone."""

    def __init__(self, mod: LXDModule) -> None:
        self.mod = mod
        self.name: str = mod.params["name"]
        self.path = api_path("network-zones", self.name)
        # Ansible then masks the TSIG secrets everywhere in the output, also in invocation.module_args.
        for key, value in (mod.params["config"] or {}).items():
            if SECRET_KEY_RE.match(str(key)) and value:
                mod.module.no_log_values.add(str(value))

    def read(self) -> tuple[dict[str, t.Any] | None, str | None]:
        """Read the zone."""
        return self.mod.client.get_or_none(self.path, self.mod.query())

    def present(self) -> None:
        """Make sure that the zone exists with the wanted settings."""
        params = self.mod.params
        current, etag = self.read()
        if current is None:
            body = {"name": self.name, "description": params["description"] or "", "config": create_config(self.mod)}
            self.mod.write("POST", "/1.0/network-zones", query=self.mod.query(), body=body)
            after = mask({key: body[key] for key in FIELDS})
            self.mod.exit(True, before={}, after=after, zone=mask(self.final(dict(body, used_by=[]))))
        plan = plan_common(self.mod, current, FIELDS)
        if not plan.is_changed:
            self.mod.exit(False, before=mask(plan.before()), after=mask(plan.after()), zone=mask(current))
        body = {"description": plan.new.get("description") or "", "config": plan.new.get("config") or {}}
        self.mod.write("PUT", self.path, query=self.mod.query(), body=body, etag=etag)
        self.mod.exit(True, before=mask(plan.before()), after=mask(plan.after()), zone=mask(self.final(plan.new)))

    def absent(self) -> None:
        """Make sure that the zone does not exist."""
        current, _etag = self.read()
        if current is None:
            self.mod.exit(False, before={}, after={}, zone=None)
        self.mod.write("DELETE", self.path, query=self.mod.query())
        self.mod.exit(True, before=mask({key: current.get(key) for key in FIELDS}), after={}, zone=None)

    def final(self, predicted: dict[str, t.Any]) -> dict[str, t.Any]:
        """Return the zone from the server, or the prediction in check mode."""
        if self.mod.check_mode:
            return predicted
        zone, _etag = self.read()
        return zone or predicted


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
    mod = LXDModule(get_argument_spec(), extensions=["network_dns"])
    zone = NetworkZoneModule(mod)
    if mod.params["state"] == "present":
        mod.run(zone.present)
    else:
        mod.run(zone.absent)


if __name__ == "__main__":
    main()
