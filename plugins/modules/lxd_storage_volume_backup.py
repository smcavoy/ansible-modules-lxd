#!/usr/bin/python
# Copyright (c) 2026, Sean McAvoy
# GNU General Public License v3.0+ (see LICENSES/GPL-3.0-or-later.txt or https://www.gnu.org/licenses/gpl-3.0.txt)
# SPDX-License-Identifier: GPL-3.0-or-later

from __future__ import annotations

DOCUMENTATION = r"""
module: lxd_storage_volume_backup
short_description: Manage backups of LXD custom storage volumes
version_added: "0.1.0"
description:
  - Create and delete backups of custom storage volumes on the LXD server, and download a backup to a file.
  - Import a backup file as a new volume with M(smcavoy.lxd.lxd_storage_volume) and its C(source.backup_path) option.
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
      - The storage pool of the volume.
    type: str
    required: true
  volume:
    description:
      - The custom volume.
    type: str
    required: true
  target:
    description:
      - The cluster member of the volume, for a pool that is local to each member.
    type: str
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
  volume_only:
    description:
      - Leave out the snapshots of the volume.
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
  - The module writes the backup to O(dest) in chunks. The backup does not have to fit in memory.
  - The module does not compare the size of O(dest) with the backup. LXD does not give the size or a checksum of a backup.
seealso:
  - module: smcavoy.lxd.lxd_storage_volume
  - module: smcavoy.lxd.lxd_storage_volume_snapshot
  - module: smcavoy.lxd.lxd_instance_backup
"""

EXAMPLES = r"""
- name: Back up a volume and download the backup to the controller
  smcavoy.lxd.lxd_storage_volume_backup:
    pool: default
    volume: data
    name: nightly
    dest: /srv/backups/data-nightly.tar.gz
  delegate_to: localhost

- name: Import the backup as a new volume
  smcavoy.lxd.lxd_storage_volume:
    pool: default
    name: data-restored
    source:
      backup_path: /srv/backups/data-nightly.tar.gz
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
    volume_only: false
    optimized_storage: false
dest:
  description:
    - The downloaded file.
  returned: when O(dest) is set
  type: str
  sample: /srv/backups/data-nightly.tar.gz
size:
  description:
    - The size of the downloaded file in bytes.
  returned: when the module downloads the backup
  type: int
  sample: 52428800
"""

import typing as t

from ansible_collections.smcavoy.lxd.plugins.module_utils._backup import Backup, backup_argument_spec
from ansible_collections.smcavoy.lxd.plugins.module_utils._client import api_path
from ansible_collections.smcavoy.lxd.plugins.module_utils._module import LXDModule

if t.TYPE_CHECKING:  # pragma: no cover
    from ansible_collections.smcavoy.lxd.plugins.module_utils._typing import ArgumentSpecMutT


def get_argument_spec() -> ArgumentSpecMutT:
    """Return the argument spec of the module."""
    spec: ArgumentSpecMutT = {
        "pool": {"type": "str", "required": True},
        "volume": {"type": "str", "required": True},
        "target": {"type": "str"},
        "volume_only": {"type": "bool", "default": False},
    }
    spec.update(backup_argument_spec())
    return spec


def main() -> None:
    """Run the module."""
    mod = LXDModule(get_argument_spec(), extensions=["custom_volume_backup"])
    mod.check_target()
    params = mod.params
    parent = api_path("storage-pools", params["pool"], "volumes", "custom", params["volume"])
    label = f"volume {params['volume']} in pool {params['pool']}"
    backup = Backup(mod, parent, "volume_only", label, mod.query(target=params["target"]))
    if params["state"] == "present":
        mod.run(backup.present)
    else:
        mod.run(backup.absent)


if __name__ == "__main__":
    main()
