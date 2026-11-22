#!/usr/bin/python
# Copyright (c) 2026, Sean McAvoy
# GNU General Public License v3.0+ (see LICENSES/GPL-3.0-or-later.txt or https://www.gnu.org/licenses/gpl-3.0.txt)
# SPDX-License-Identifier: GPL-3.0-or-later

from __future__ import annotations

DOCUMENTATION = r"""
module: lxd_instance_snapshot
short_description: Manage LXD instance snapshots
version_added: "0.1.0"
description:
  - Create, update, restore, and delete snapshots of LXD instances.
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
    support: partial
    details:
      - O(state=restored) restores the snapshot on every run and always reports a change.
options:
  instance:
    description:
      - The instance of the snapshot.
    type: str
    required: true
  name:
    description:
      - The snapshot name.
    type: str
    required: true
  state:
    description:
      - The wanted state of the snapshot.
    type: str
    choices:
      present: The snapshot exists.
      absent: The snapshot does not exist.
      restored: The module restores the instance from the snapshot. This state always reports a change.
    default: present
  stateful:
    description:
      - Save the running state of the instance in the snapshot. The instance needs C(migration.stateful).
      - With O(state=restored), restore the running state too.
      - The module uses it only when it creates the snapshot. On an existing snapshot, the module warns and ignores a different value.
    type: bool
    default: false
  expires_at:
    description:
      - The time when LXD deletes the snapshot, as an RFC 3339 time, for example V(2026-12-31T00:00:00Z).
      - An empty string means that the snapshot never expires.
      - If not set, the module does not manage the expiry.
    type: str
  disk_volumes_mode:
    description:
      - Which volumes the snapshot covers.
      - V(root) covers only the root volume. V(all-exclusive) also covers the custom volumes that only this instance uses.
      - LXD names each volume snapshot after the snapshot pattern of the volume, for example C(snap0).
        The description of the volume snapshot names the instance snapshot.
      - The module uses it only when it creates the snapshot.
    type: str
    choices: ["root", "all-exclusive"]
notes:
  - A restore replaces the state of the instance with the state of the snapshot. Changes since the snapshot are lost.
seealso:
  - module: smcavoy.lxd.lxd_instance
  - name: LXD instance snapshots
    description: The LXD documentation about instance snapshots.
    link: https://documentation.ubuntu.com/lxd/latest/howto/instances_backup/
"""

EXAMPLES = r"""
- name: Take a snapshot before an upgrade, and let it expire at the end of the year
  smcavoy.lxd.lxd_instance_snapshot:
    instance: web1
    name: before-upgrade
    expires_at: "2026-12-31T00:00:00Z"

- name: Restore the instance from the snapshot
  smcavoy.lxd.lxd_instance_snapshot:
    instance: web1
    name: before-upgrade
    state: restored

- name: Delete the snapshot
  smcavoy.lxd.lxd_instance_snapshot:
    instance: web1
    name: before-upgrade
    state: absent
"""

RETURN = r"""
snapshot:
  description:
    - The snapshot after the change, as LXD returns it.
    - In check mode, the predicted snapshot.
    - V(null) after a delete.
  returned: always
  type: dict
  sample:
    name: before-upgrade
    stateful: false
    created_at: "2026-11-03T10:00:00Z"
    expires_at: "0001-01-01T00:00:00Z"
    size: 2097152
    config:
      limits.cpu: "2"
"""

import datetime
import typing as t

from ansible_collections.smcavoy.lxd.plugins.module_utils._client import api_path
from ansible_collections.smcavoy.lxd.plugins.module_utils._module import LXDModule
from ansible_collections.smcavoy.lxd.plugins.module_utils._resource import warn_create_only
from ansible_collections.smcavoy.lxd.plugins.module_utils._time import format_time, parse_time

if t.TYPE_CHECKING:  # pragma: no cover
    from ansible_collections.smcavoy.lxd.plugins.module_utils._typing import ArgumentSpecMutT


class SnapshotModule:
    """Manage one LXD instance snapshot."""

    def __init__(self, mod: LXDModule) -> None:
        self.mod = mod
        self.instance: str = mod.params["instance"]
        self.name: str = mod.params["name"]
        self.instance_path = api_path("instances", self.instance)
        self.path = api_path("instances", self.instance, "snapshots", self.name)
        self.expires: datetime.datetime | None = None
        if mod.params["expires_at"] is not None:
            try:
                self.expires = parse_time(mod.params["expires_at"])
            except ValueError:
                mod.fail("expires_at must be an RFC 3339 time")

    def read(self) -> tuple[dict[str, t.Any] | None, str | None]:
        """Read the snapshot."""
        return self.mod.client.get_or_none(self.path, self.mod.query())

    def instance_exists(self) -> bool:
        """Return whether the instance exists."""
        instance, _etag = self.mod.client.get_or_none(self.instance_path, self.mod.query())
        return instance is not None

    def wanted_expiry(self) -> str:
        """Return the task expiry in the form LXD returns."""
        return format_time(self.expires)

    def present(self) -> None:
        """Make sure that the snapshot exists with the wanted expiry."""
        params = self.mod.params
        current, etag = self.read()
        if current is None:
            self.create()
        warn_create_only(self.mod, current, {"stateful": current.get("stateful")})
        before = {"expires_at": current.get("expires_at")}
        if params["expires_at"] is None:
            self.mod.exit(False, before=before, after=before, snapshot=current)
        try:
            server = parse_time(current.get("expires_at"))
        except ValueError:
            server = None
        if server == self.expires:
            self.mod.exit(False, before=before, after=before, snapshot=current)
        after = {"expires_at": self.wanted_expiry()}
        self.mod.write("PUT", self.path, query=self.mod.query(), body=after, etag=etag)
        self.mod.exit(True, before=before, after=after, snapshot=self.final(dict(current, **after)))

    def create(self) -> t.NoReturn:
        """Create the snapshot."""
        params = self.mod.params
        if not self.instance_exists():
            self.mod.fail(f"instance {self.instance} not found")
        body: dict[str, t.Any] = {"name": self.name, "stateful": params["stateful"]}
        extensions = []
        if params["expires_at"] is not None:
            # An empty expires_at goes as the zero time. Without the field, LXD uses snapshots.expiry of the instance.
            body["expires_at"] = self.wanted_expiry()
            extensions.append("snapshot_expiry_creation")
        if params["disk_volumes_mode"]:
            body["disk_volumes_mode"] = params["disk_volumes_mode"]
            extensions.append("instance_snapshots_multi_volume")
        missing = self.mod.client.missing_extensions(extensions)
        if missing:
            self.mod.fail(f"LXD server lacks the API extensions: {', '.join(missing)}")
        self.mod.write("POST", f"{self.instance_path}/snapshots", query=self.mod.query(), body=body)
        after = {"expires_at": self.wanted_expiry()}
        predicted = {"name": self.name, "stateful": params["stateful"], "expires_at": self.wanted_expiry(), "config": {}}
        self.mod.exit(True, before={}, after=after, snapshot=self.final(predicted))

    def restored(self) -> None:
        """Restore the instance from the snapshot."""
        current, _etag = self.read()
        if current is None:
            self.mod.fail(f"snapshot {self.name} of instance {self.instance} not found")
        body = {"restore": self.name, "stateful": self.mod.params["stateful"]}
        self.mod.write("PUT", self.instance_path, query=self.mod.query(), body=body)
        self.mod.exit(True, before={}, after={}, snapshot=current)

    def absent(self) -> None:
        """Make sure that the snapshot does not exist."""
        current, _etag = self.read()
        if current is None:
            self.mod.exit(False, before={}, after={}, snapshot=None)
        self.mod.write("DELETE", self.path, query=self.mod.query())
        self.mod.exit(True, before={"expires_at": current.get("expires_at")}, after={}, snapshot=None)

    def final(self, predicted: dict[str, t.Any]) -> dict[str, t.Any]:
        """Return the snapshot from the server, or the prediction in check mode."""
        if self.mod.check_mode:
            return predicted
        snapshot, _etag = self.read()
        return snapshot or predicted


def get_argument_spec() -> ArgumentSpecMutT:
    """Return the argument spec of the module."""
    return {
        "instance": {"type": "str", "required": True},
        "name": {"type": "str", "required": True},
        "project": {"type": "str"},
        "state": {"type": "str", "default": "present", "choices": ["present", "absent", "restored"]},
        "stateful": {"type": "bool", "default": False},
        "expires_at": {"type": "str"},
        "disk_volumes_mode": {"type": "str", "choices": ["root", "all-exclusive"]},
    }


def main() -> None:
    """Run the module."""
    mod = LXDModule(get_argument_spec(), extensions=["instances"])
    snapshot = SnapshotModule(mod)
    state = mod.params["state"]
    if state == "present":
        mod.run(snapshot.present)
    elif state == "restored":
        mod.run(snapshot.restored)
    else:
        mod.run(snapshot.absent)


if __name__ == "__main__":
    main()
