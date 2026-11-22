#!/usr/bin/python
# Copyright (c) 2026, Sean McAvoy
# GNU General Public License v3.0+ (see LICENSES/GPL-3.0-or-later.txt or https://www.gnu.org/licenses/gpl-3.0.txt)
# SPDX-License-Identifier: GPL-3.0-or-later

from __future__ import annotations

DOCUMENTATION = r"""
module: lxd_storage_volume_snapshot
short_description: Manage snapshots of LXD custom storage volumes
version_added: "0.1.0"
description:
  - Create, update, restore, and delete snapshots of custom storage volumes.
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
  pool:
    description:
      - The storage pool of the volume.
    type: str
    required: true
  volume:
    description:
      - The custom volume.
    type: str
    required: true
  name:
    description:
      - The snapshot name.
    type: str
    required: true
  target:
    description:
      - On a cluster, the member of a volume on a local pool.
    type: str
  state:
    description:
      - The wanted state of the snapshot.
    type: str
    choices:
      present: The snapshot exists.
      absent: The snapshot does not exist.
      restored: The module restores the volume from the snapshot. This state always reports a change.
    default: present
  description:
    description:
      - The snapshot description.
      - If not set, the module does not manage the description.
    type: str
  expires_at:
    description:
      - The time when LXD deletes the snapshot, as an RFC 3339 time.
      - An empty string means that the snapshot never expires.
      - If not set, the module does not manage the expiry.
    type: str
notes:
  - A restore replaces the content of the volume. Most drivers cannot restore a volume that a running instance uses.
seealso:
  - module: smcavoy.lxd.lxd_storage_volume
"""

EXAMPLES = r"""
- name: Take a snapshot of a volume that expires in a week
  smcavoy.lxd.lxd_storage_volume_snapshot:
    pool: default
    volume: data
    name: before-upgrade
    expires_at: "2026-11-13T00:00:00Z"

- name: Restore the volume from the snapshot
  smcavoy.lxd.lxd_storage_volume_snapshot:
    pool: default
    volume: data
    name: before-upgrade
    state: restored
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
    description: ""
    content_type: filesystem
    created_at: "2026-11-03T10:00:00Z"
    expires_at: "2026-11-10T10:00:00Z"
    config:
      size: 5GiB
"""

import datetime
import typing as t

from ansible_collections.smcavoy.lxd.plugins.module_utils._client import api_path
from ansible_collections.smcavoy.lxd.plugins.module_utils._module import LXDModule
from ansible_collections.smcavoy.lxd.plugins.module_utils._time import format_time, parse_time

if t.TYPE_CHECKING:  # pragma: no cover
    from ansible_collections.smcavoy.lxd.plugins.module_utils._typing import ArgumentSpecMutT


class VolumeSnapshotModule:
    """Manage one snapshot of a custom storage volume."""

    def __init__(self, mod: LXDModule) -> None:
        self.mod = mod
        params = mod.params
        self.volume: str = params["volume"]
        self.name: str = params["name"]
        self.volume_path = api_path("storage-pools", params["pool"], "volumes", "custom", self.volume)
        self.path = api_path("storage-pools", params["pool"], "volumes", "custom", self.volume, "snapshots", self.name)
        self.expires: datetime.datetime | None = None
        if params["expires_at"] is not None:
            try:
                self.expires = parse_time(params["expires_at"])
            except ValueError:
                mod.fail("expires_at must be an RFC 3339 time")

    def query(self) -> dict[str, t.Any]:
        """Return the query, with the cluster member."""
        return self.mod.query(target=self.mod.params["target"])

    def read(self) -> tuple[dict[str, t.Any] | None, str | None]:
        """Read the snapshot."""
        return self.mod.client.get_or_none(self.path, self.query())

    def view(self, snapshot: dict[str, t.Any]) -> dict[str, t.Any]:
        """Return the managed fields in a stable form."""
        try:
            expires: str | None = format_time(parse_time(snapshot.get("expires_at")))
        except ValueError:
            expires = snapshot.get("expires_at")
        return {"description": snapshot.get("description") or "", "expires_at": expires}

    def present(self) -> None:
        """Make sure that the snapshot exists with the wanted fields."""
        params = self.mod.params
        current, etag = self.read()
        if current is None:
            volume, _etag = self.mod.client.get_or_none(self.volume_path, self.query())
            if volume is None:
                self.mod.fail(f"storage volume {self.volume} not found in pool {params['pool']}")
            body: dict[str, t.Any] = {"name": self.name, "description": params["description"] or ""}
            if params["expires_at"] is not None:
                # An empty expires_at goes as the zero time. Without the field, LXD uses snapshots.expiry of the volume.
                body["expires_at"] = format_time(self.expires)
            self.mod.write("POST", f"{self.volume_path}/snapshots", query=self.query(), body=body)
            after = {"description": body["description"], "expires_at": format_time(self.expires)}
            self.mod.exit(True, before={}, after=after, snapshot=self.final(dict(after, name=self.name)))
        before = self.view(current)
        after = dict(before)
        if params["description"] is not None:
            after["description"] = params["description"]
        if params["expires_at"] is not None:
            after["expires_at"] = format_time(self.expires)
        if after == before:
            self.mod.exit(False, before=before, after=after, snapshot=current)
        self.mod.write("PUT", self.path, query=self.query(), body=after, etag=etag)
        self.mod.exit(True, before=before, after=after, snapshot=self.final(dict(current, **after)))

    def restored(self) -> None:
        """Restore the volume from the snapshot."""
        current, _etag = self.read()
        if current is None:
            self.mod.fail(f"snapshot {self.name} of volume {self.volume} not found")
        volume, etag = self.mod.client.get(self.volume_path, self.query())
        body = {"config": (volume or {}).get("config") or {}, "description": (volume or {}).get("description") or "", "restore": self.name}
        self.mod.write("PUT", self.volume_path, query=self.query(), body=body, etag=etag)
        self.mod.exit(True, before={}, after={}, snapshot=current)

    def absent(self) -> None:
        """Make sure that the snapshot does not exist."""
        current, _etag = self.read()
        if current is None:
            self.mod.exit(False, before={}, after={}, snapshot=None)
        self.mod.write("DELETE", self.path, query=self.query())
        self.mod.exit(True, before=self.view(current), after={}, snapshot=None)

    def final(self, predicted: dict[str, t.Any]) -> dict[str, t.Any]:
        """Return the snapshot from the server, or the prediction in check mode."""
        if self.mod.check_mode:
            return predicted
        snapshot, _etag = self.read()
        return snapshot or predicted


def get_argument_spec() -> ArgumentSpecMutT:
    """Return the argument spec of the module."""
    return {
        "pool": {"type": "str", "required": True},
        "volume": {"type": "str", "required": True},
        "name": {"type": "str", "required": True},
        "project": {"type": "str"},
        "target": {"type": "str"},
        "state": {"type": "str", "default": "present", "choices": ["present", "absent", "restored"]},
        "description": {"type": "str"},
        "expires_at": {"type": "str"},
    }


def main() -> None:
    """Run the module."""
    mod = LXDModule(get_argument_spec(), extensions=["storage_api_volume_snapshots"])
    mod.check_target()
    snapshot = VolumeSnapshotModule(mod)
    state = mod.params["state"]
    if state == "present":
        mod.run(snapshot.present)
    elif state == "restored":
        mod.run(snapshot.restored)
    else:
        mod.run(snapshot.absent)


if __name__ == "__main__":
    main()
