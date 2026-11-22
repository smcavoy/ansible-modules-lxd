#!/usr/bin/python
# Copyright (c) 2026, Sean McAvoy
# GNU General Public License v3.0+ (see LICENSES/GPL-3.0-or-later.txt or https://www.gnu.org/licenses/gpl-3.0.txt)
# SPDX-License-Identifier: GPL-3.0-or-later

from __future__ import annotations

DOCUMENTATION = r"""
module: lxd_network_zone_record
short_description: Manage records in LXD network zones
version_added: "0.1.0"
description:
  - Create, update, and delete DNS records in a network zone.
  - The module compares the entries as a set. Their order does not cause a change.
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
  zone:
    description:
      - The zone of the record.
    type: str
    required: true
  name:
    description:
      - The record name inside the zone, for example V(www).
    type: str
    required: true
  state:
    description:
      - The wanted state of the record.
    type: str
    choices:
      present: The record exists.
      absent: The record does not exist.
    default: present
  description:
    description:
      - The record description.
      - If not set, the module does not manage the description.
    type: str
  entries:
    description:
      - The DNS entries of the record.
      - If not set, the module does not manage the entries. V([]) removes all entries.
    type: list
    elements: dict
    suboptions:
      type:
        description:
          - The DNS type, for example V(A), V(AAAA), V(CNAME), or V(TXT).
        type: str
        required: true
      value:
        description:
          - The value of the entry.
        type: str
        required: true
      ttl:
        description:
          - The time to live in seconds. V(0) means the default of the zone.
        type: int
        default: 0
notes:
  - The record config takes only C(user.*) keys.
seealso:
  - module: smcavoy.lxd.lxd_network_zone
"""

EXAMPLES = r"""
- name: Point www to two addresses
  smcavoy.lxd.lxd_network_zone_record:
    zone: lxd.example.net
    name: www
    entries:
      - type: A
        value: 192.0.2.10
      - type: A
        value: 192.0.2.11
        ttl: 300
"""

RETURN = r"""
record:
  description:
    - The record after the change, as LXD returns it.
    - In check mode, the predicted record.
    - V(null) after a delete.
  returned: always
  type: dict
  sample:
    name: www
    description: ""
    entries:
      - type: A
        value: 192.0.2.10
    config: {}
"""

import json
import typing as t

from ansible_collections.smcavoy.lxd.plugins.module_utils._client import api_path
from ansible_collections.smcavoy.lxd.plugins.module_utils._module import LXDModule
from ansible_collections.smcavoy.lxd.plugins.module_utils._resource import create_config, plan_common

if t.TYPE_CHECKING:  # pragma: no cover
    from ansible_collections.smcavoy.lxd.plugins.module_utils._typing import ArgumentSpecMutT

FIELDS = ("description", "entries", "config")


def normalize_entries(entries: list[t.Any] | None) -> list[dict[str, t.Any]]:
    """Return the entries in a stable order, with ttl 0 when LXD leaves it out."""
    result = [{"type": str(item.get("type") or "").upper(), "value": str(item.get("value") or ""), "ttl": int(item.get("ttl") or 0)} for item in entries or []]
    return sorted(result, key=lambda item: json.dumps(item, sort_keys=True))


class ZoneRecordModule:
    """Manage one record in an LXD network zone."""

    def __init__(self, mod: LXDModule) -> None:
        self.mod = mod
        self.zone: str = mod.params["zone"]
        self.name: str = mod.params["name"]
        self.zone_path = api_path("network-zones", self.zone)
        self.path = api_path("network-zones", self.zone, "records", self.name)

    def read(self) -> tuple[dict[str, t.Any] | None, str | None]:
        """Read the record."""
        return self.mod.client.get_or_none(self.path, self.mod.query())

    def view(self, record: dict[str, t.Any]) -> dict[str, t.Any]:
        """Return the managed fields in a stable form."""
        return {
            "description": record.get("description") or "",
            "entries": normalize_entries(record.get("entries")),
            "config": dict(record.get("config") or {}),
        }

    def present(self) -> None:
        """Make sure that the record exists with the wanted entries."""
        params = self.mod.params
        current, etag = self.read()
        if current is None:
            zone, _etag = self.mod.client.get_or_none(self.zone_path, self.mod.query())
            if zone is None:
                self.mod.fail(f"network zone {self.zone} not found")
            body = {
                "name": self.name,
                "description": params["description"] or "",
                "entries": normalize_entries(params["entries"]),
                "config": create_config(self.mod),
            }
            self.mod.write("POST", f"{self.zone_path}/records", query=self.mod.query(), body=body)
            self.mod.exit(True, before={}, after=self.view(body), record=self.final(body))
        plan = plan_common(self.mod, current, FIELDS)
        if params["entries"] is not None:
            wanted = normalize_entries(params["entries"])
            if wanted != normalize_entries(current.get("entries")):
                plan.set("entries", wanted)
        before, after = self.view(plan.current), self.view(plan.new)
        if not plan.is_changed:
            self.mod.exit(False, before=before, after=after, record=current)
        body = {key: after[key] for key in FIELDS}
        self.mod.write("PUT", self.path, query=self.mod.query(), body=body, etag=etag)
        self.mod.exit(True, before=before, after=after, record=self.final(dict(current, **body)))

    def absent(self) -> None:
        """Make sure that the record does not exist."""
        current, _etag = self.read()
        if current is None:
            self.mod.exit(False, before={}, after={}, record=None)
        self.mod.write("DELETE", self.path, query=self.mod.query())
        self.mod.exit(True, before=self.view(current), after={}, record=None)

    def final(self, predicted: dict[str, t.Any]) -> dict[str, t.Any]:
        """Return the record from the server, or the prediction in check mode."""
        if self.mod.check_mode:
            return predicted
        record, _etag = self.read()
        return record or predicted


def get_argument_spec() -> ArgumentSpecMutT:
    """Return the argument spec of the module."""
    return {
        "zone": {"type": "str", "required": True},
        "name": {"type": "str", "required": True},
        "project": {"type": "str"},
        "state": {"type": "str", "default": "present", "choices": ["present", "absent"]},
        "description": {"type": "str"},
        "entries": {
            "type": "list",
            "elements": "dict",
            "options": {
                "type": {"type": "str", "required": True},
                "value": {"type": "str", "required": True},
                "ttl": {"type": "int", "default": 0},
            },
        },
        "config": {"type": "dict"},
        "config_mode": {"type": "str", "default": "merge", "choices": ["merge", "exact"]},
    }


def main() -> None:
    """Run the module."""
    mod = LXDModule(get_argument_spec(), extensions=["network_dns_records"])
    record = ZoneRecordModule(mod)
    if mod.params["state"] == "present":
        mod.run(record.present)
    else:
        mod.run(record.absent)


if __name__ == "__main__":
    main()
