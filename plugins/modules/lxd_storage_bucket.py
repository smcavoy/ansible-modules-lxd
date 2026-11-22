#!/usr/bin/python
# Copyright (c) 2026, Sean McAvoy
# GNU General Public License v3.0+ (see LICENSES/GPL-3.0-or-later.txt or https://www.gnu.org/licenses/gpl-3.0.txt)
# SPDX-License-Identifier: GPL-3.0-or-later

from __future__ import annotations

DOCUMENTATION = r"""
module: lxd_storage_bucket
short_description: Manage LXD storage buckets
version_added: "0.1.0"
description:
  - Create, update, and delete S3 object storage buckets on a C(cephobject) storage pool.
  - LXD creates an C(admin) key with each bucket. The module returns its credentials only on the run that creates the bucket.
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
  name:
    description:
      - The bucket name. It follows the S3 naming rules.
    type: str
    required: true
  state:
    description:
      - The wanted state of the bucket.
    type: str
    choices:
      present: The bucket exists.
      absent: The bucket does not exist. LXD deletes its keys too.
    default: present
  description:
    description:
      - The bucket description.
      - If not set, the module does not manage the description.
    type: str
  config:
    description:
      - The bucket config, for example C(size) or C(user.*) keys.
      - A key with the value V(null) or an empty string is removed.
    type: dict
  config_mode:
    description:
      - How to treat config keys of the bucket that are not in O(config).
    type: str
    choices:
      merge: Keep them.
      exact: Remove them. The module keeps the C(volatile.*) keys.
    default: merge
notes:
  - The admin credentials are secrets. Use C(no_log=true) on the task that creates the bucket.
seealso:
  - module: smcavoy.lxd.lxd_storage_bucket_key
  - module: smcavoy.lxd.lxd_storage_pool
"""

EXAMPLES = r"""
- name: A bucket for backups
  smcavoy.lxd.lxd_storage_bucket:
    pool: objects
    name: backups
    config:
      size: 10GiB
  register: bucket
  no_log: true
"""

RETURN = r"""
bucket:
  description:
    - The bucket after the change, as LXD returns it, with C(s3_url).
    - In check mode, the predicted bucket.
    - V(null) after a delete.
  returned: always
  type: dict
  sample:
    name: backups
    description: ""
    s3_url: http://192.0.2.20/backups
    config:
      size: 10GiB
admin_credentials:
  description:
    - The credentials of the C(admin) key. Only on the run that creates the bucket. This is a secret.
  returned: when the module creates the bucket
  type: dict
  contains:
    access_key:
      description: The access key.
      type: str
    secret_key:
      description: The secret key.
      type: str
"""

import typing as t

from ansible_collections.smcavoy.lxd.plugins.module_utils._client import api_path
from ansible_collections.smcavoy.lxd.plugins.module_utils._config import COMPUTED_KEYS
from ansible_collections.smcavoy.lxd.plugins.module_utils._module import LXDModule
from ansible_collections.smcavoy.lxd.plugins.module_utils._resource import create_config, plan_common

if t.TYPE_CHECKING:  # pragma: no cover
    from ansible_collections.smcavoy.lxd.plugins.module_utils._typing import ArgumentSpecMutT

FIELDS = ("description", "config")


def credentials(meta: t.Any) -> dict[str, str] | None:
    """Return the admin credentials from the metadata of the create operation, or None."""
    if not isinstance(meta, dict):
        return None
    inner = meta.get("key")
    key: dict[str, t.Any] = inner if isinstance(inner, dict) else meta
    access = key.get("access-key") or key.get("access_key")
    secret = key.get("secret-key") or key.get("secret_key")
    if not access or not secret:
        return None
    return {"access_key": str(access), "secret_key": str(secret)}


class BucketModule:
    """Manage one storage bucket."""

    def __init__(self, mod: LXDModule) -> None:
        self.mod = mod
        params = mod.params
        self.collection = api_path("storage-pools", params["pool"], "buckets")
        self.path = api_path("storage-pools", params["pool"], "buckets", params["name"])

    def read(self) -> tuple[dict[str, t.Any] | None, str | None]:
        """Read the bucket."""
        return self.mod.client.get_or_none(self.path, self.mod.query())

    def present(self) -> None:
        """Make sure that the bucket exists with the wanted settings."""
        params = self.mod.params
        current, etag = self.read()
        if current is None:
            body = {"name": params["name"], "description": params["description"] or "", "config": create_config(self.mod)}
            meta = self.mod.write("POST", self.collection, query=self.mod.query(), body=body)
            after = {key: body[key] for key in FIELDS}
            result: dict[str, t.Any] = {}
            creds = credentials(meta)
            if creds:
                result["admin_credentials"] = creds
            self.mod.exit(True, before={}, after=after, bucket=self.final(body), **result)
        plan = plan_common(self.mod, current, FIELDS, COMPUTED_KEYS["storage_bucket"])
        if not plan.is_changed:
            self.mod.exit(False, before=plan.before(), after=plan.after(), bucket=current)
        body = {"description": plan.new.get("description") or "", "config": plan.new.get("config") or {}}
        self.mod.write("PUT", self.path, query=self.mod.query(), body=body, etag=etag)
        self.mod.exit(True, before=plan.before(), after=plan.after(), bucket=self.final(dict(current, **plan.new)))

    def absent(self) -> None:
        """Make sure that the bucket does not exist."""
        current, _etag = self.read()
        if current is None:
            self.mod.exit(False, before={}, after={}, bucket=None)
        self.mod.write("DELETE", self.path, query=self.mod.query())
        self.mod.exit(True, before={key: current.get(key) for key in FIELDS}, after={}, bucket=None)

    def final(self, predicted: dict[str, t.Any]) -> dict[str, t.Any]:
        """Return the bucket from the server, or the prediction in check mode."""
        if self.mod.check_mode:
            return predicted
        bucket, _etag = self.read()
        return bucket or predicted


def get_argument_spec() -> ArgumentSpecMutT:
    """Return the argument spec of the module."""
    return {
        "pool": {"type": "str", "required": True},
        "name": {"type": "str", "required": True},
        "project": {"type": "str"},
        "state": {"type": "str", "default": "present", "choices": ["present", "absent"]},
        "description": {"type": "str"},
        "config": {"type": "dict"},
        "config_mode": {"type": "str", "default": "merge", "choices": ["merge", "exact"]},
    }


def main() -> None:
    """Run the module."""
    mod = LXDModule(get_argument_spec(), extensions=["storage_buckets"])
    bucket = BucketModule(mod)
    if mod.params["state"] == "present":
        mod.run(bucket.present)
    else:
        mod.run(bucket.absent)


if __name__ == "__main__":
    main()
