#!/usr/bin/python
# Copyright (c) 2026, Sean McAvoy
# GNU General Public License v3.0+ (see LICENSES/GPL-3.0-or-later.txt or https://www.gnu.org/licenses/gpl-3.0.txt)
# SPDX-License-Identifier: GPL-3.0-or-later

from __future__ import annotations

DOCUMENTATION = r"""
module: lxd_storage_bucket_key
short_description: Manage access keys of LXD storage buckets
version_added: "0.1.0"
description:
  - Create, update, and delete access keys of a storage bucket.
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
  pool:
    description:
      - The C(cephobject) storage pool.
    type: str
    required: true
  bucket:
    description:
      - The bucket.
    type: str
    required: true
  name:
    description:
      - The key name.
    type: str
    required: true
  state:
    description:
      - The wanted state of the key.
    type: str
    choices:
      present: The key exists.
      absent: The key does not exist.
    default: present
  description:
    description:
      - The key description.
      - If not set, the module does not manage the description.
    type: str
  role:
    description:
      - The role of the key.
    type: str
    choices: ["admin", "read-only"]
    default: read-only
  access_key:
    description:
      - A fixed access key. If not set, LXD makes one on create, and the module does not manage it.
    type: str
  secret_key:
    description:
      - A fixed secret key. If not set, LXD makes one on create, and the module does not manage it.
    type: str
notes:
  - The module never shows the secret key in the diff. A change shows as V(changed).
seealso:
  - module: smcavoy.lxd.lxd_storage_bucket
"""

EXAMPLES = r"""
- name: A read-only key for a backup reader
  smcavoy.lxd.lxd_storage_bucket_key:
    pool: objects
    bucket: backups
    name: reader
  register: reader
  no_log: true
"""

RETURN = r"""
key:
  description:
    - The key after the change, with C(secret_key) masked.
    - In check mode, the predicted key.
    - V(null) after a delete.
  returned: always
  type: dict
  sample:
    name: reader
    description: ""
    role: read-only
    access-key: AKIAEXAMPLE2
    secret-key: "********"
secret_key:
  description:
    - The secret key. Only on the run that creates the key or changes its secret key. This is a secret.
  returned: when the module creates the key or changes its secret key
  type: str
access_key:
  description:
    - The access key of the key.
  returned: when O(state=present)
  type: str
"""

import typing as t

from ansible_collections.smcavoy.lxd.plugins.module_utils._client import api_path
from ansible_collections.smcavoy.lxd.plugins.module_utils._module import LXDModule

if t.TYPE_CHECKING:  # pragma: no cover
    from ansible_collections.smcavoy.lxd.plugins.module_utils._typing import ArgumentSpecMutT

MASK = "********"


def field(item: t.Mapping[str, t.Any], name: str) -> str:
    """Read a key field. The API uses dashes, for example C(access-key)."""
    return str(item.get(name.replace("_", "-")) or item.get(name) or "")


def masked(key: dict[str, t.Any] | None) -> dict[str, t.Any] | None:
    """Return a copy of a key with the secret masked."""
    if key is None:
        return None
    result = dict(key)
    for name in ("secret-key", "secret_key"):
        if result.get(name):
            result[name] = MASK
    return result


class BucketKeyModule:
    """Manage one access key of a storage bucket."""

    def __init__(self, mod: LXDModule) -> None:
        self.mod = mod
        params = mod.params
        self.bucket_path = api_path("storage-pools", params["pool"], "buckets", params["bucket"])
        self.path = api_path("storage-pools", params["pool"], "buckets", params["bucket"], "keys", params["name"])
        if params["secret_key"]:
            mod.module.no_log_values.add(params["secret_key"])

    def read(self) -> tuple[dict[str, t.Any] | None, str | None]:
        """Read the key."""
        return self.mod.client.get_or_none(self.path, self.mod.query())

    def view(self, key: t.Mapping[str, t.Any]) -> dict[str, str]:
        """Return the managed fields for the diff, without the secret."""
        return {"description": field(key, "description"), "role": field(key, "role"), "access_key": field(key, "access_key")}

    def present(self) -> None:
        """Make sure that the key exists with the wanted settings."""
        params = self.mod.params
        current, etag = self.read()
        if current is None:
            bucket, _etag = self.mod.client.get_or_none(self.bucket_path, self.mod.query())
            if bucket is None:
                self.mod.fail(f"bucket {params['bucket']} not found in pool {params['pool']}")
            body: dict[str, t.Any] = {"name": params["name"], "description": params["description"] or "", "role": params["role"]}
            if params["access_key"]:
                body["access-key"] = params["access_key"]
            if params["secret_key"]:
                body["secret-key"] = params["secret_key"]
            after = self.view(body)
            if self.mod.check_mode:
                self.mod.exit(True, before={}, after=after, key=masked(body))
            self.mod.client.write("POST", f"{self.bucket_path}/keys", query=self.mod.query(), body=body)
            key, _etag = self.read()
            key = key or body
            self.mod.exit(True, before={}, after=self.view(key), key=masked(key), access_key=field(key, "access_key"), secret_key=field(key, "secret_key"))
        before = self.view(current)
        after = dict(before)
        if params["description"] is not None:
            after["description"] = params["description"]
        after["role"] = params["role"]
        if params["access_key"]:
            after["access_key"] = params["access_key"]
        secret_changed = bool(params["secret_key"]) and params["secret_key"] != field(current, "secret_key")
        if after == before and not secret_changed:
            self.mod.exit(False, before=before, after=after, key=masked(current), access_key=field(current, "access_key"))
        body = {
            "description": after["description"],
            "role": after["role"],
            "access-key": after["access_key"],
            "secret-key": params["secret_key"] or field(current, "secret_key"),
        }
        diff_after = dict(after, secret_key="changed") if secret_changed else after
        if self.mod.check_mode:
            self.mod.exit(True, before=before, after=diff_after, key=masked(dict(current, **body)), access_key=after["access_key"])
        self.mod.client.write("PUT", self.path, query=self.mod.query(), body=body, etag=etag)
        key, _etag = self.read()
        key = key or dict(current, **body)
        result: dict[str, t.Any] = {"access_key": field(key, "access_key")}
        if secret_changed:
            result["secret_key"] = field(key, "secret_key")
        self.mod.exit(True, before=before, after=diff_after, key=masked(key), **result)

    def absent(self) -> None:
        """Make sure that the key does not exist."""
        current, _etag = self.read()
        if current is None:
            self.mod.exit(False, before={}, after={}, key=None)
        self.mod.write("DELETE", self.path, query=self.mod.query())
        self.mod.exit(True, before=self.view(current), after={}, key=None)


def get_argument_spec() -> ArgumentSpecMutT:
    """Return the argument spec of the module."""
    return {
        "pool": {"type": "str", "required": True},
        "bucket": {"type": "str", "required": True},
        "name": {"type": "str", "required": True},
        "project": {"type": "str"},
        "state": {"type": "str", "default": "present", "choices": ["present", "absent"]},
        "description": {"type": "str"},
        "role": {"type": "str", "default": "read-only", "choices": ["admin", "read-only"]},
        "access_key": {"type": "str", "no_log": False},
        "secret_key": {"type": "str", "no_log": True},
    }


def main() -> None:
    """Run the module."""
    mod = LXDModule(get_argument_spec(), extensions=["storage_buckets"])
    key = BucketKeyModule(mod)
    if mod.params["state"] == "present":
        mod.run(key.present)
    else:
        mod.run(key.absent)


if __name__ == "__main__":
    main()
