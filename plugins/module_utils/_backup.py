# Copyright (c) 2026, Sean McAvoy
# GNU General Public License v3.0+ (see LICENSES/GPL-3.0-or-later.txt or https://www.gnu.org/licenses/gpl-3.0.txt)
# SPDX-License-Identifier: GPL-3.0-or-later

"""Shared code of the backup modules for instances and custom volumes."""

from __future__ import annotations

import os
import tempfile
import typing as t

from ansible_collections.smcavoy.lxd.plugins.module_utils._resource import warn_create_only
from ansible_collections.smcavoy.lxd.plugins.module_utils._time import format_time, parse_time

if t.TYPE_CHECKING:  # pragma: no cover
    from ansible_collections.smcavoy.lxd.plugins.module_utils._module import LXDModule


def backup_argument_spec() -> dict[str, t.Any]:
    """Return the options that every backup module has."""
    return {
        "name": {"type": "str", "required": True},
        "project": {"type": "str"},
        "state": {"type": "str", "default": "present", "choices": ["present", "absent"]},
        "expires_at": {"type": "str"},
        "optimized_storage": {"type": "bool", "default": False},
        "compression_algorithm": {"type": "str"},
        "dest": {"type": "path"},
        "force_download": {"type": "bool", "default": False},
    }


class Backup:
    """Manage one backup of an LXD instance or custom volume.

    O(parent_path) is the API path of the instance or volume. O(only_key) is C(instance_only) or C(volume_only).
    O(label) names the parent in error messages, for example C(instance web1).
    """

    def __init__(self, mod: LXDModule, parent_path: str, only_key: str, label: str, query: dict[str, t.Any]) -> None:
        self.mod = mod
        params = mod.params
        self.name: str = params["name"]
        self.parent_path = parent_path
        self.path = f"{parent_path}/backups/{self.name}"
        self.only_key = only_key
        self.label = label
        self.query = query
        self.expires = None
        if params["expires_at"]:
            try:
                self.expires = parse_time(params["expires_at"])
            except ValueError:
                mod.fail("expires_at must be an RFC 3339 time")
        if params["dest"]:
            directory = os.path.dirname(os.path.abspath(params["dest"]))
            if not os.path.isdir(directory):
                mod.fail(f"directory of dest does not exist: {directory}")

    def read(self) -> tuple[dict[str, t.Any] | None, str | None]:
        """Read the backup."""
        return self.mod.client.get_or_none(self.path, self.query)

    def download(self) -> int:
        """Download the backup to a temporary file next to dest, then move it into place. Return the size."""
        dest = self.mod.params["dest"]
        # The backup streams to disk in chunks. A large VM backup does not have to fit in memory.
        handle, temp = tempfile.mkstemp(dir=os.path.dirname(os.path.abspath(dest)), prefix=".lxd-backup-")
        try:
            with os.fdopen(handle, "wb") as out:
                resp = self.mod.client.download_to(f"{self.path}/export", out, self.query)
            os.replace(temp, dest)
        except OSError as exc:
            if os.path.exists(temp):
                os.unlink(temp)
            self.mod.fail(f"cannot write {dest}: {exc}")
        except BaseException:
            if os.path.exists(temp):
                os.unlink(temp)
            raise
        return resp.size

    def present(self) -> None:
        """Make sure that the backup exists, and download it when dest needs it."""
        params = self.mod.params
        current, _etag = self.read()
        changed = False
        before: dict[str, t.Any] = {}
        if current is None:
            parent, _etag = self.mod.client.get_or_none(self.parent_path, self.query)
            if parent is None:
                self.mod.fail(f"{self.label} not found")
            body: dict[str, t.Any] = {
                "name": self.name,
                self.only_key: params[self.only_key],
                "optimized_storage": params["optimized_storage"],
            }
            if self.expires is not None:
                body["expires_at"] = format_time(self.expires)
            if params["compression_algorithm"]:
                body["compression_algorithm"] = params["compression_algorithm"]
            self.mod.write("POST", f"{self.parent_path}/backups", query=self.query, body=body)
            changed = True
            current = body if self.mod.check_mode else (self.read()[0] or body)
        else:
            before = {"name": self.name}
            warn_create_only(
                self.mod,
                current,
                {self.only_key: current.get(self.only_key), "optimized_storage": current.get("optimized_storage")},
            )
        result: dict[str, t.Any] = {"backup": current}
        after: dict[str, t.Any] = {"name": self.name}
        dest = params["dest"]
        if dest:
            result["dest"] = dest
            after["dest"] = dest
            if params["force_download"] or not os.path.exists(dest):
                changed = True
                if not self.mod.check_mode:
                    result["size"] = self.download()
            elif before:
                before["dest"] = dest
        self.mod.exit(changed, before=before, after=after, **result)

    def absent(self) -> None:
        """Make sure that the backup does not exist on the server."""
        current, _etag = self.read()
        if current is None:
            self.mod.exit(False, before={}, after={}, backup=None)
        self.mod.write("DELETE", self.path, query=self.query)
        self.mod.exit(True, before={"name": self.name}, after={}, backup=None)
