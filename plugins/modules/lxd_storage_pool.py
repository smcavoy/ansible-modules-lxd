#!/usr/bin/python
# Copyright (c) 2026, Sean McAvoy
# GNU General Public License v3.0+ (see LICENSES/GPL-3.0-or-later.txt or https://www.gnu.org/licenses/gpl-3.0.txt)
# SPDX-License-Identifier: GPL-3.0-or-later

from __future__ import annotations

DOCUMENTATION = r"""
module: lxd_storage_pool
short_description: Manage LXD storage pools
version_added: "0.1.0"
description:
  - Create, update, and delete LXD storage pools for all drivers.
  - On a cluster, the module creates the pool with the pending-then-global flow, and it manages member-specific keys per member.
author:
  - Sean McAvoy (@smcavoy)
extends_documentation_fragment:
  - smcavoy.lxd._attributes
  - smcavoy.lxd._attributes.action_group
  - smcavoy.lxd._connection
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
      - The pool name.
    type: str
    required: true
  state:
    description:
      - The wanted state of the pool.
    type: str
    choices:
      present: The pool exists.
      absent: The pool does not exist.
    default: present
  driver:
    description:
      - The storage driver.
      - Required to create the pool. On an existing pool, the module warns and ignores a different value.
      - The module checks that the server offers the driver before it creates the pool.
    type: str
    choices: ["dir", "zfs", "btrfs", "lvm", "ceph", "cephfs", "cephobject", "powerflex", "pure", "powerstore", "alletra"]
  description:
    description:
      - The pool description.
      - If not set, the module does not manage the description.
    type: str
  member_config:
    description:
      - Member-specific config keys per cluster member, as a dictionary of member name to keys.
      - A member-specific key in O(config) is the default for all members. O(member_config) overrides it.
      - Only valid on a cluster.
    type: dict
notes:
  - Storage pools are global. They do not belong to a project.
  - Many driver keys apply only on create, for example C(source) and C(zfs.pool_name). LXD rejects a later change.
  - The module does not count keys that LXD fills in, such as C(source) or C(size), as a change, unless the task sets them.
  - A delete of a pool that LXD created destroys its data. For example, LXD destroys a ZFS pool that it made.
  - A cluster create that did not finish leaves the pool with the status C(Pending) or C(Errored). The module then fails.
    Find the cause, remove the pool with O(state=absent), and run the task again.
  - The module masks the secrets of the remote storage drivers in the diff and the result. The keys are C(alletra.user.password),
    C(powerflex.user.password), C(powerstore.user.password), and C(pure.api.token).
seealso:
  - module: smcavoy.lxd.lxd_storage_volume
  - name: LXD storage pools
    description: The LXD documentation about storage pools.
    link: https://documentation.ubuntu.com/lxd/latest/howto/storage_pools/
"""

EXAMPLES = r"""
- name: Create a dir pool
  smcavoy.lxd.lxd_storage_pool:
    name: data
    driver: dir

- name: Create a ZFS pool on a loop file of 20 GiB
  smcavoy.lxd.lxd_storage_pool:
    name: fast
    driver: zfs
    config:
      size: 20GiB

- name: Create a ZFS pool on a cluster, with one disk per member
  smcavoy.lxd.lxd_storage_pool:
    name: local
    driver: zfs
    member_config:
      node1:
        source: /dev/nvme1n1
      node2:
        source: /dev/nvme2n1

- name: Delete the pool
  smcavoy.lxd.lxd_storage_pool:
    name: data
    state: absent
"""

RETURN = r"""
storage_pool:
  description:
    - The pool after the change, as LXD returns it.
    - On a cluster, the key C(members) holds the member-specific keys of each member.
    - In check mode, the predicted pool.
    - V(null) after a delete.
  returned: always
  type: dict
  sample:
    name: data
    driver: dir
    status: Created
    description: ""
    config:
      source: /var/snap/lxd/common/lxd/storage-pools/data
    locations:
      - none
    used_by: []
"""

import typing as t

from ansible_collections.smcavoy.lxd.plugins.module_utils._client import api_path
from ansible_collections.smcavoy.lxd.plugins.module_utils._cluster import (
    local_keys,
    member_local_config,
    member_names,
    split_config,
    unfinished_create,
)
from ansible_collections.smcavoy.lxd.plugins.module_utils._config import merge_config, normalize_config
from ansible_collections.smcavoy.lxd.plugins.module_utils._module import LXDModule
from ansible_collections.smcavoy.lxd.plugins.module_utils._resource import Plan, warn_create_only

if t.TYPE_CHECKING:  # pragma: no cover
    from ansible_collections.smcavoy.lxd.plugins.module_utils._typing import ArgumentSpecMutT

FIELDS = ("description", "config", "members")
DRIVERS = ["dir", "zfs", "btrfs", "lvm", "ceph", "cephfs", "cephobject", "powerflex", "pure", "powerstore", "alletra"]

# Keys that LXD fills in. They count only when the task sets them. Section 5.6 of the module plan.
COMPUTED_BY_DRIVER: dict[str, tuple[str, ...]] = {
    "dir": ("source", "volatile.*"),
    "zfs": ("source", "size", "zfs.pool_name", "volatile.*"),
    "lvm": ("source", "size", "lvm.vg_name", "lvm.thinpool_name", "volatile.*"),
    "btrfs": ("source", "size", "volatile.*"),
    "ceph": ("ceph.cluster_name", "ceph.user.name", "ceph.osd.pg_num", "ceph.osd.pool_name", "ceph.osd.pool_size", "source", "volatile.*"),
    "cephfs": ("cephfs.cluster_name", "cephfs.user.name", "cephfs.path", "source", "volatile.*"),
}

# The passwords and tokens of the remote storage drivers. The module masks them in the result and the diff.
SECRET_KEYS = r"^((alletra|powerflex|powerstore)\.user\.password|pure\.api\.token)$"


class StoragePoolModule:
    """Manage one LXD storage pool."""

    def __init__(self, mod: LXDModule) -> None:
        self.mod = mod
        self.name: str = mod.params["name"]
        self.path = api_path("storage-pools", self.name)
        self.clustered = mod.client.is_clustered()

    def read(self, target: str | None = None) -> tuple[dict[str, t.Any] | None, str | None]:
        """Read the pool, or the view of one member."""
        return self.mod.client.get_or_none(self.path, self.mod.query(target=target))

    def local(self, driver: str) -> set[str]:
        """Return the member-specific keys for this driver, on a cluster only."""
        if not self.clustered:
            return set()
        return local_keys(self.mod.client, f"storage-{driver}")

    def computed(self, driver: str) -> tuple[str, ...]:
        """Return the keys that LXD fills in for this driver."""
        return COMPUTED_BY_DRIVER.get(driver, ("source", "volatile.*"))

    def present(self) -> None:
        """Make sure that the pool exists with the wanted settings."""
        params = self.mod.params
        if params["member_config"] and not self.clustered:
            self.mod.fail("member_config is only valid on a clustered server")
        current, etag = self.read()
        if current is None:
            self.create()
        unfinished = unfinished_create("storage pool", self.name, current)
        if unfinished:
            self.mod.fail(unfinished)
        warn_create_only(self.mod, current, {"driver": current.get("driver")})
        driver = current.get("driver") or "dir"
        local = self.local(driver)
        desired = normalize_config(params["config"])
        desired_global, desired_local = split_config(desired or {}, local)
        current_global, _unused = split_config(current.get("config") or {}, local)
        plan = Plan(dict(current, config=current_global), FIELDS)
        if params["description"] is not None:
            plan.set("description", params["description"])
        new_global, global_changes = merge_config(
            current_global,
            desired_global if desired is not None else None,
            params["config_mode"],
            self.computed(driver),
            keep=sorted(local),
        )
        if global_changes:
            plan.new["config"] = new_global
            plan.changed.append("config")
        member_updates = self.plan_members(driver, desired_local, plan)
        if not plan.is_changed:
            self.mod.exit(False, before=plan.before(), after=plan.after(), storage_pool=self.with_members(current))
        if set(plan.changed) & {"description", "config"}:
            body = {"description": plan.new.get("description") or "", "config": plan.new.get("config") or {}}
            self.mod.write("PUT", self.path, body=body, etag=etag)
        for member, new_local in member_updates.items():
            # LXD replaces the whole config on a PUT with a target, the global keys too. So the body is the member view
            # with the new member-specific keys, as lxc sends it. The view is read now, after the global PUT.
            view, member_etag = self.read(target=member)
            member_global, _unused = split_config((view or {}).get("config") or {}, local)
            member_body = {"description": (view or {}).get("description") or "", "config": dict(member_global, **new_local)}
            self.mod.write("PUT", self.path, query={"target": member}, body=member_body, etag=member_etag)
        self.mod.exit(True, before=plan.before(), after=plan.after(), storage_pool=self.final(plan.new))

    def plan_members(self, driver: str, desired_local: dict[str, t.Any], plan: Plan) -> dict[str, dict[str, t.Any]]:
        """Compare the member-specific keys of each member. Return the new member-specific keys of each member that changes."""
        updates: dict[str, dict[str, t.Any]] = {}
        if not self.clustered:
            return updates
        members = member_names(self.mod.client)
        wanted = member_local_config(members, desired_local, self.mod.params["member_config"])
        local = self.local(driver)
        before: dict[str, t.Any] = {}
        after: dict[str, t.Any] = {}
        for member in members:
            view, _etag = self.read(target=member)
            _unused, server_local = split_config((view or {}).get("config") or {}, local)
            new_local, changes = merge_config(server_local, normalize_config(wanted[member]), "merge")
            before[member] = server_local
            after[member] = new_local
            if changes:
                updates[member] = new_local
        plan.current["members"] = before
        plan.new["members"] = after
        if updates:
            plan.changed.append("members")
        return updates

    def check_driver(self, driver: str) -> None:
        """Fail early when the server does not offer the driver."""
        server, _etag = self.mod.client.get("/1.0")
        offered = [item.get("Name") for item in ((server or {}).get("environment") or {}).get("storage_supported_drivers") or []]
        if offered and driver not in offered:
            self.mod.fail(f"Storage driver {driver} is not available. Available: {', '.join(sorted(name for name in offered if name))}")

    def create(self) -> t.NoReturn:
        """Create the pool, with the pending-then-global flow on a cluster."""
        params = self.mod.params
        driver = params["driver"]
        if not driver:
            self.mod.fail("driver is required to create the storage pool")
        self.check_driver(driver)
        config = {key: value for key, value in (normalize_config(params["config"]) or {}).items() if value not in (None, "")}
        description = params["description"] or ""
        after: dict[str, t.Any] = {"description": description, "config": config}
        if self.clustered:
            global_part, local_part = split_config(config, self.local(driver))
            members = member_names(self.mod.client)
            wanted = member_local_config(members, local_part, params["member_config"])
            for member in members:
                member_body = {"name": self.name, "driver": driver, "config": normalize_config(wanted[member]) or {}}
                self.mod.write("POST", "/1.0/storage-pools", query={"target": member}, body=member_body)
            body = {"name": self.name, "driver": driver, "description": description, "config": global_part}
            after = {"description": description, "config": global_part, "members": wanted}
        else:
            body = {"name": self.name, "driver": driver, "description": description, "config": config}
        self.mod.write("POST", "/1.0/storage-pools", body=body)
        predicted: dict[str, t.Any] = dict(body, status="Created", used_by=[])
        self.mod.exit(True, before={}, after=after, storage_pool=self.final(predicted))

    def absent(self) -> None:
        """Make sure that the pool does not exist."""
        current, _etag = self.read()
        if current is None:
            self.mod.exit(False, before={}, after={}, storage_pool=None)
        self.mod.write("DELETE", self.path)
        before = {"description": current.get("description"), "config": current.get("config")}
        self.mod.exit(True, before=before, after={}, storage_pool=None)

    def with_members(self, pool: dict[str, t.Any]) -> dict[str, t.Any]:
        """Add the member-specific keys of each member on a cluster."""
        if not self.clustered:
            return pool
        local = self.local(pool.get("driver") or "dir")
        members: dict[str, t.Any] = {}
        for member in member_names(self.mod.client):
            view, _etag = self.read(target=member)
            members[member] = split_config((view or {}).get("config") or {}, local)[1]
        return dict(pool, members=members)

    def final(self, predicted: dict[str, t.Any]) -> dict[str, t.Any]:
        """Return the pool from the server, or the prediction in check mode."""
        if self.mod.check_mode:
            return predicted
        pool, _etag = self.read()
        return self.with_members(pool or predicted)


def get_argument_spec() -> ArgumentSpecMutT:
    """Return the argument spec of the module."""
    return {
        "name": {"type": "str", "required": True},
        "state": {"type": "str", "default": "present", "choices": ["present", "absent"]},
        "driver": {"type": "str", "choices": DRIVERS},
        "description": {"type": "str"},
        "config": {"type": "dict"},
        "config_mode": {"type": "str", "default": "merge", "choices": ["merge", "exact"]},
        "member_config": {"type": "dict"},
    }


def main() -> None:
    """Run the module."""
    mod = LXDModule(get_argument_spec(), extensions=["storage"])
    mod.hide_secrets(SECRET_KEYS)
    pool = StoragePoolModule(mod)
    if mod.params["state"] == "present":
        mod.run(pool.present)
    else:
        mod.run(pool.absent)


if __name__ == "__main__":
    main()
