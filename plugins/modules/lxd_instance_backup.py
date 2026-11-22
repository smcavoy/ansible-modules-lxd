#!/usr/bin/python
# Copyright (c) 2026, Sean McAvoy
# GNU General Public License v3.0+ (see LICENSES/GPL-3.0-or-later.txt or https://www.gnu.org/licenses/gpl-3.0.txt)
# SPDX-License-Identifier: GPL-3.0-or-later

from __future__ import annotations

DOCUMENTATION = r"""
module: lxd_instance_backup
short_description: Manage LXD instance backups
version_added: "0.1.0"
description:
  - Create and delete instance backups on the LXD server, and download a backup to a file.
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
  instance:
    description:
      - The instance.
    type: str
    required: true
  name:
    description:
      - The backup name.
    type: str
    required: true
  state:
    description:
      - The wanted state of the backup.
    type: str
    choices:
      present: The backup exists on the server.
      absent: The backup does not exist on the server. The module does not delete O(dest).
    default: present
  expires_at:
    description:
      - The time when LXD deletes the backup, as an RFC 3339 time.
      - The module uses this option and the next three only when it creates the backup.
    type: str
  instance_only:
    description:
      - Leave out the snapshots of the instance.
    type: bool
    default: false
  optimized_storage:
    description:
      - Use the format of the storage driver. The backup then restores only to a pool with the same driver.
    type: bool
    default: false
  compression_algorithm:
    description:
      - The compression, for example V(gzip), V(zstd), or V(none).
    type: str
  dest:
    description:
      - A file to download the backup to, on the host where the module runs.
      - That is the controller with a local connection or with C(delegate_to=localhost).
      - The module does not download again when the file exists, unless O(force_download=true).
    type: path
  force_download:
    description:
      - Download the backup even when O(dest) exists.
    type: bool
    default: false
notes:
  - The module reads the backup into memory before it writes O(dest).
seealso:
  - module: smcavoy.lxd.lxd_instance_snapshot
"""

EXAMPLES = r"""
- name: Back up an instance and download the backup to the controller
  smcavoy.lxd.lxd_instance_backup:
    instance: web1
    name: nightly
    compression_algorithm: zstd
    dest: /srv/backups/web1-nightly.tar.zst
  delegate_to: localhost
"""

RETURN = r"""
backup:
  description:
    - The backup, as LXD returns it. V(null) after a delete.
  returned: always
  type: dict
  sample:
    name: nightly
    created_at: "2026-11-03T02:00:00Z"
    expires_at: "2026-11-10T02:00:00Z"
    instance_only: false
    optimized_storage: false
dest:
  description:
    - The downloaded file.
  returned: when O(dest) is set
  type: str
  sample: /srv/backups/web1-nightly.tar.zst
size:
  description:
    - The size of the downloaded file in bytes.
  returned: when the module downloads the backup
  type: int
  sample: 104857600
"""

import typing as t

from ansible_collections.smcavoy.lxd.plugins.module_utils._backup import Backup, backup_argument_spec
from ansible_collections.smcavoy.lxd.plugins.module_utils._client import api_path
from ansible_collections.smcavoy.lxd.plugins.module_utils._module import LXDModule

if t.TYPE_CHECKING:  # pragma: no cover
    from ansible_collections.smcavoy.lxd.plugins.module_utils._typing import ArgumentSpecMutT


def get_argument_spec() -> ArgumentSpecMutT:
    """Return the argument spec of the module."""
    spec: ArgumentSpecMutT = {"instance": {"type": "str", "required": True}, "instance_only": {"type": "bool", "default": False}}
    spec.update(backup_argument_spec())
    return spec


def main() -> None:
    """Run the module."""
    mod = LXDModule(get_argument_spec(), extensions=["container_backup"])
    instance = mod.params["instance"]
    backup = Backup(mod, api_path("instances", instance), "instance_only", f"instance {instance}", mod.query())
    if mod.params["state"] == "present":
        mod.run(backup.present)
    else:
        mod.run(backup.absent)


if __name__ == "__main__":
    main()
