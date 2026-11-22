#!/usr/bin/python
# Copyright (c) 2026, Sean McAvoy
# GNU General Public License v3.0+ (see LICENSES/GPL-3.0-or-later.txt or https://www.gnu.org/licenses/gpl-3.0.txt)
# SPDX-License-Identifier: GPL-3.0-or-later

from __future__ import annotations

DOCUMENTATION = r"""
module: lxd_storage_volume
short_description: Manage LXD custom storage volumes
version_added: "0.1.0"
description:
  - Create, update, copy, import, and delete custom storage volumes.
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
  pool:
    description:
      - The storage pool.
    type: str
    required: true
  name:
    description:
      - The volume name.
    type: str
    required: true
  target:
    description:
      - The cluster member for a volume on a local pool.
      - The module uses it only when it creates the volume.
      - Only valid on a cluster.
    type: str
  state:
    description:
      - The wanted state of the volume.
    type: str
    choices:
      present: The volume exists.
      absent: The volume does not exist.
    default: present
  content_type:
    description:
      - The content type of a new volume.
      - The module uses it only when it creates the volume. On an existing volume, the module warns and ignores a different value.
      - If not set, LXD creates a V(filesystem) volume.
    type: str
    choices: ["filesystem", "block", "iso"]
  description:
    description:
      - The volume description.
      - If not set, the module does not manage the description.
    type: str
  source:
    description:
      - Where the data of a new volume comes from. Without it, the module creates an empty volume.
      - The module uses it only when it creates the volume. On an existing volume, the module warns and ignores it.
    type: dict
    suboptions:
      volume:
        description:
          - Copy this volume.
        type: str
      pool:
        description:
          - The pool of O(source.volume). If not set, the module uses O(pool).
        type: str
      project:
        description:
          - The project of O(source.volume).
        type: str
      snapshot:
        description:
          - Copy this snapshot of O(source.volume).
        type: str
      volume_only:
        description:
          - Copy the volume without its snapshots.
        type: bool
        default: false
      iso_path:
        description:
          - Import this ISO file from the controller.
        type: path
      tarball_path:
        description:
          - Import this tarball from the controller.
        type: path
      backup_path:
        description:
          - Import this volume backup file from the controller.
        type: path
seealso:
  - module: smcavoy.lxd.lxd_instance
  - name: LXD storage volumes
    description: The LXD documentation about storage volumes.
    link: https://documentation.ubuntu.com/lxd/latest/explanation/storage/#storage-volumes
"""

EXAMPLES = r"""
- name: Create a 5 GiB volume for web content
  smcavoy.lxd.lxd_storage_volume:
    pool: default
    name: www
    config:
      size: 5GiB

- name: Copy the volume
  smcavoy.lxd.lxd_storage_volume:
    pool: default
    name: www-copy
    source:
      volume: www

- name: Delete the copy
  smcavoy.lxd.lxd_storage_volume:
    pool: default
    name: www-copy
    state: absent
"""

RETURN = r"""
storage_volume:
  description:
    - The volume after the change, as LXD returns it.
    - In check mode, the predicted volume.
    - V(null) after a delete.
  returned: always
  type: dict
  sample:
    name: www
    type: custom
    content_type: filesystem
    description: ""
    config:
      size: 5GiB
    used_by: []
"""

import os
import typing as t

from ansible_collections.smcavoy.lxd.plugins.module_utils._client import api_path
from ansible_collections.smcavoy.lxd.plugins.module_utils._config import COMPUTED_KEYS
from ansible_collections.smcavoy.lxd.plugins.module_utils._module import LXDModule
from ansible_collections.smcavoy.lxd.plugins.module_utils._resource import (
    create_config,
    plan_common,
    warn_create_only,
)

if t.TYPE_CHECKING:  # pragma: no cover
    from ansible_collections.smcavoy.lxd.plugins.module_utils._typing import ArgumentSpecMutT

FIELDS = ("description", "config")
FILE_SOURCES = {"iso_path": "iso", "tarball_path": "tar", "backup_path": None}


class VolumeModule:
    """Manage one custom storage volume."""

    def __init__(self, mod: LXDModule) -> None:
        self.mod = mod
        self.pool: str = mod.params["pool"]
        self.name: str = mod.params["name"]
        self.path = api_path("storage-pools", self.pool, "volumes", "custom", self.name)
        self.collection = api_path("storage-pools", self.pool, "volumes", "custom")

    def read(self) -> tuple[dict[str, t.Any] | None, str | None]:
        """Read the volume."""
        return self.mod.client.get_or_none(self.path, self.mod.query(target=self.mod.params["target"]))

    def computed(self) -> list[str]:
        """Return the computed keys, plus the keys that the pool fills from its C(volume.*) keys."""
        keys = list(COMPUTED_KEYS["storage_volume"])
        pool, _etag = self.mod.client.get_or_none(api_path("storage-pools", self.pool))
        task_config = self.mod.params["config"] or {}
        for key in (pool or {}).get("config") or {}:
            short = key[len("volume.") :]
            if key.startswith("volume.") and short not in task_config:
                keys.append(short)
        return keys

    def present(self) -> None:
        """Make sure that the volume exists with the wanted settings."""
        params = self.mod.params
        current, etag = self.read()
        if current is None:
            self.create()
        warn_create_only(
            self.mod,
            current,
            {"content_type": current.get("content_type"), "source": None, "target": current.get("location")},
        )
        plan = plan_common(self.mod, current, FIELDS, self.computed())
        if not plan.is_changed:
            self.mod.exit(False, before=plan.before(), after=plan.after(), storage_volume=current)
        body = {"description": plan.new.get("description") or "", "config": plan.new.get("config") or {}}
        self.mod.write("PUT", self.path, query=self.mod.query(target=params["target"]), body=body, etag=etag)
        self.mod.exit(True, before=plan.before(), after=plan.after(), storage_volume=self.final(plan.new))

    def create(self) -> t.NoReturn:
        """Create the volume from its source."""
        params = self.mod.params
        source = params["source"] or {}
        query = self.mod.query(target=params["target"])
        file_option = next((key for key in FILE_SOURCES if source.get(key)), None)
        body: dict[str, t.Any] = {
            "name": self.name,
            "type": "custom",
            "description": params["description"] or "",
            "config": create_config(self.mod),
        }
        if params["content_type"]:
            body["content_type"] = params["content_type"]
        if file_option:
            self.upload(source[file_option], FILE_SOURCES[file_option], query)
            current, etag = self.read() if not self.mod.check_mode else (None, None)
            if current is not None:
                plan = plan_common(self.mod, current, FIELDS, self.computed())
                if plan.is_changed:
                    put = {"description": plan.new.get("description") or "", "config": plan.new.get("config") or {}}
                    self.mod.write("PUT", self.path, query=query, body=put, etag=etag)
        else:
            if source.get("volume"):
                name = source["volume"] + ("/" + source["snapshot"] if source.get("snapshot") else "")
                body["source"] = {
                    "type": "copy",
                    "name": name,
                    "pool": source.get("pool") or self.pool,
                    "volume_only": bool(source.get("volume_only")),
                }
                if source.get("project"):
                    body["source"]["project"] = source["project"]
            self.mod.write("POST", self.collection, query=query, body=body)
        after = {"description": body["description"], "config": body["config"]}
        predicted = dict(body, content_type=params["content_type"] or "filesystem", used_by=[])
        predicted.pop("source", None)
        self.mod.exit(True, before={}, after=after, storage_volume=self.final(predicted))

    def upload(self, path: str, kind: str | None, query: dict[str, t.Any]) -> None:
        """Stream a file from the controller as a new volume."""
        if not os.path.isfile(path):
            self.mod.fail(f"source file {path} not found")
        if self.mod.check_mode:
            return
        headers = {"X-LXD-name": self.name, "Content-Length": str(os.path.getsize(path))}
        if kind:
            headers["X-LXD-type"] = kind
        with open(path, "rb") as stream:
            self.mod.client.write("POST", self.collection, query=query, raw=stream, headers=headers)

    def absent(self) -> None:
        """Make sure that the volume does not exist."""
        current, _etag = self.read()
        if current is None:
            self.mod.exit(False, before={}, after={}, storage_volume=None)
        self.mod.write("DELETE", self.path, query=self.mod.query(target=self.mod.params["target"]))
        before = {key: current.get(key) for key in FIELDS}
        self.mod.exit(True, before=before, after={}, storage_volume=None)

    def final(self, predicted: dict[str, t.Any]) -> dict[str, t.Any]:
        """Return the volume from the server, or the prediction in check mode."""
        if self.mod.check_mode:
            return predicted
        volume, _etag = self.read()
        return volume or predicted


def get_argument_spec() -> ArgumentSpecMutT:
    """Return the argument spec of the module."""
    return {
        "pool": {"type": "str", "required": True},
        "name": {"type": "str", "required": True},
        "project": {"type": "str"},
        "target": {"type": "str"},
        "state": {"type": "str", "default": "present", "choices": ["present", "absent"]},
        "content_type": {"type": "str", "choices": ["filesystem", "block", "iso"]},
        "description": {"type": "str"},
        "config": {"type": "dict"},
        "config_mode": {"type": "str", "default": "merge", "choices": ["merge", "exact"]},
        "source": {
            "type": "dict",
            "options": {
                "volume": {"type": "str"},
                "pool": {"type": "str"},
                "project": {"type": "str"},
                "snapshot": {"type": "str"},
                "volume_only": {"type": "bool", "default": False},
                "iso_path": {"type": "path"},
                "tarball_path": {"type": "path"},
                "backup_path": {"type": "path"},
            },
            "mutually_exclusive": [["volume", "iso_path", "tarball_path", "backup_path"]],
            "required_by": {"snapshot": "volume"},
        },
    }


def main() -> None:
    """Run the module."""
    mod = LXDModule(get_argument_spec(), extensions=["storage_api_local_volume_handling"])
    mod.check_target()
    volume = VolumeModule(mod)
    if mod.params["state"] == "present":
        mod.run(volume.present)
    else:
        mod.run(volume.absent)


if __name__ == "__main__":
    main()
