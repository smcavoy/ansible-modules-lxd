#!/usr/bin/python
# Copyright (c) 2026, Sean McAvoy
# GNU General Public License v3.0+ (see LICENSES/GPL-3.0-or-later.txt or https://www.gnu.org/licenses/gpl-3.0.txt)
# SPDX-License-Identifier: GPL-3.0-or-later

from __future__ import annotations

DOCUMENTATION = r"""
module: lxd_instance
short_description: Manage LXD containers and virtual machines
version_added: "0.1.0"
description:
  - Create, configure, start, stop, freeze, and delete LXD instances.
author:
  - Sean McAvoy (@smcavoy)
extends_documentation_fragment:
  - smcavoy.lxd._attributes
  - smcavoy.lxd._attributes.action_group
  - smcavoy.lxd._connection
  - smcavoy.lxd._project
  - smcavoy.lxd._config
  - smcavoy.lxd._config.devices
attributes:
  check_mode:
    support: full
  diff_mode:
    support: full
  idempotent:
    support: partial
    details:
      - O(state=restarted) restarts the instance on every run and always reports a change.
options:
  name:
    description:
      - The instance name.
    type: str
    required: true
  target:
    description:
      - The cluster member, or C(@<group>) for a cluster group, for a new instance.
      - The module uses it only when it creates the instance. On an existing instance, the module warns and ignores it.
      - Only valid on a cluster.
    type: str
  state:
    description:
      - The wanted state of the instance.
    type: str
    choices:
      present: The instance exists. The module does not change its run state.
      started: The instance exists and runs.
      stopped: The instance exists and does not run.
      frozen: The instance exists and is frozen.
      restarted: The instance exists and the module restarts it. This state always reports a change. The module unfreezes a frozen instance first.
      absent: The instance does not exist.
    default: started
  type:
    description:
      - The instance type.
      - The module uses it only when it creates the instance. On an existing instance, the module warns and ignores a different value.
      - If not set, the module creates a V(container).
    type: str
    choices: ["container", "virtual-machine"]
  source:
    description:
      - Where a new instance comes from.
      - The module uses it only when it creates the instance. On an existing instance, the module warns and ignores it.
      - Required when the instance does not exist and O(state) is not V(absent).
    type: dict
    suboptions:
      image:
        description:
          - An image alias or fingerprint.
        type: str
      image_registry:
        description:
          - The image registry of O(source.image). If not set, the module uses the local image store.
        type: str
      project:
        description:
          - The project of the source image or the source instance.
        type: str
      instance:
        description:
          - Copy this instance.
        type: str
      snapshot:
        description:
          - Copy this snapshot of O(source.instance).
        type: str
      instance_only:
        description:
          - Copy the instance without its snapshots.
        type: bool
        default: false
      empty:
        description:
          - Create an instance with an empty root disk.
        type: bool
        default: false
      backup_path:
        description:
          - Import the instance from this backup file, on the host where the module runs.
          - The backup file sets the type, the config, the devices, and the profiles. The module then applies O(config), O(devices),
            O(profiles), O(ephemeral), and O(description) like an update.
          - Make the file with M(smcavoy.lxd.lxd_instance_backup) and its C(dest) option, or with C(lxc export).
        type: path
      pool:
        description:
          - The storage pool for the imported instance. If not set, LXD uses the pool in the backup file.
        type: str
  profiles:
    description:
      - The profiles of the instance, in order.
      - An empty list means no profiles.
      - If not set, the module does not manage the profiles. A new instance then gets the V(default) profile.
    type: list
    elements: str
  ephemeral:
    description:
      - Delete the instance when it stops.
      - If not set, the module does not manage this setting.
    type: bool
  description:
    description:
      - The instance description.
      - If not set, the module does not manage the description.
    type: str
  instance_type:
    description:
      - A cloud instance type for a new instance, for example V(c2-m4).
      - The module uses it only when it creates the instance. On an existing instance, the module warns and ignores it.
    type: str
  force:
    description:
      - Force a stop when a clean stop does not finish in O(stop_timeout) seconds.
      - With O(state=absent), delete a running instance in one call.
    type: bool
    default: false
  stop_timeout:
    description:
      - Seconds for a clean stop.
    type: int
    default: 30
  allow_restart:
    description:
      - Restart the instance when LXD cannot apply a config change while the instance runs.
    type: bool
    default: false
  wait_for:
    description:
      - Conditions to wait for after the instance starts.
    type: list
    elements: dict
    suboptions:
      type:
        description:
          - The condition.
        type: str
        required: true
        choices:
          agent: The VM agent answers. Containers pass at once.
          ipv4: A NIC other than C(lo) has a global IPv4 address.
          ipv6: A NIC other than C(lo) has a global IPv6 address.
          ready: The guest sets the instance status to C(Ready).
          delay: O(wait_for[].seconds) seconds pass.
      nic:
        description:
          - For V(ipv4) and V(ipv6), the NIC to check. If not set, any NIC counts.
        type: str
      seconds:
        description:
          - For V(delay), the number of seconds.
        type: int
  wait_timeout:
    description:
      - Seconds for all O(wait_for) conditions together.
    type: int
    default: 300
notes:
  - LXD applies most changes to a running instance at once. For a VM, some keys need a restart.
    Without O(allow_restart=true), the module fails and names the key.
seealso:
  - module: smcavoy.lxd.lxd_profile
  - module: smcavoy.lxd.lxd_instance_file
  - name: LXD instances
    description: The LXD documentation about instances.
    link: https://documentation.ubuntu.com/lxd/latest/instances/
"""

EXAMPLES = r"""
- name: Run an Alpine container from the local image store
  smcavoy.lxd.lxd_instance:
    name: web1
    source:
      image: alpine/3.22
    config:
      limits.cpu: 2
    wait_for:
      - type: ipv4

- name: Run an Ubuntu VM from the ubuntu image registry
  smcavoy.lxd.lxd_instance:
    name: vm1
    type: virtual-machine
    source:
      image: "26.04"
      image_registry: ubuntu
    wait_for:
      - type: agent

- name: Stop the container
  smcavoy.lxd.lxd_instance:
    name: web1
    state: stopped

- name: Delete the container, also when it runs
  smcavoy.lxd.lxd_instance:
    name: web1
    state: absent
    force: true
"""

RETURN = r"""
instance:
  description:
    - The instance after the change and after O(wait_for), as LXD returns it with C(recursion=1).
    - In check mode, the predicted instance.
    - V(null) after a delete.
  returned: always
  type: dict
  sample:
    name: web1
    type: container
    status: Running
    profiles:
      - default
    config:
      limits.cpu: "2"
    devices: {}
    ephemeral: false
addresses:
  description:
    - The global addresses of each NIC, from the instance state.
  returned: always
  type: dict
  sample:
    eth0:
      - 10.99.0.12
restarted:
  description:
    - Whether the module restarted the instance to apply a change, because of O(allow_restart).
  returned: always
  type: bool
  sample: false
"""

import os
import re
import time
import typing as t

from ansible_collections.smcavoy.lxd.plugins.module_utils._client import LXDClientError, api_path
from ansible_collections.smcavoy.lxd.plugins.module_utils._config import (
    COMPUTED_KEYS,
    is_computed,
    normalize_device,
)
from ansible_collections.smcavoy.lxd.plugins.module_utils._module import LXDModule
from ansible_collections.smcavoy.lxd.plugins.module_utils._resource import (
    create_config,
    plan_common,
    warn_create_only,
)

if t.TYPE_CHECKING:  # pragma: no cover
    from ansible_collections.smcavoy.lxd.plugins.module_utils._typing import ArgumentSpecMutT

FIELDS = ("description", "config", "devices", "profiles", "ephemeral", "status")
FINGERPRINT_RE = re.compile(r"^[0-9a-f]{12,64}$")
LIVE_UPDATE_RE = re.compile(r"(?:Key \"([^\"]+)\" cannot be updated when VM is running|Cannot update key \"([^\"]+)\")")
RUN_STATUS = {"Running": "started", "Ready": "started", "Stopped": "stopped", "Frozen": "frozen"}


def instance_addresses(state: dict[str, t.Any] | None) -> dict[str, list[str]]:
    """Return the global addresses of each NIC from an instance state."""
    result: dict[str, list[str]] = {}
    for nic, data in ((state or {}).get("network") or {}).items():
        if nic == "lo":
            continue
        result[nic] = [addr.get("address") for addr in (data or {}).get("addresses") or [] if addr.get("scope") == "global" and addr.get("address")]
    return result


def address_families(state: dict[str, t.Any] | None, nic: str | None) -> set[str]:
    """Return the address families with a global address, on one NIC or on any NIC."""
    families: set[str] = set()
    for name, data in ((state or {}).get("network") or {}).items():
        if name == "lo" or (nic and name != nic):
            continue
        for addr in (data or {}).get("addresses") or []:
            if addr.get("scope") == "global":
                families.add(addr.get("family") or "")
    return families


class InstanceModule:
    """Manage one LXD instance."""

    def __init__(self, mod: LXDModule) -> None:
        self.mod = mod
        self.name: str = mod.params["name"]
        self.path = api_path("instances", self.name)
        self.restarted = False
        self.diff_before: dict[str, t.Any] = {}
        self.diff_after: dict[str, t.Any] = {}

    # ------------------------------------------------------------------
    # Reads

    def read(self) -> tuple[dict[str, t.Any] | None, str | None]:
        """Read the instance with its state."""
        return self.mod.client.get_or_none(self.path, self.mod.query(recursion=1))

    def read_state(self) -> dict[str, t.Any]:
        """Read the runtime state of the instance."""
        state, _etag = self.mod.client.get(api_path("instances", self.name, "state"), self.mod.query())
        return state or {}

    # ------------------------------------------------------------------
    # Steps

    def source_body(self) -> dict[str, t.Any]:
        """Build the C(source) of the create request."""
        source = self.mod.params["source"] or {}
        if source.get("empty"):
            return {"type": "none"}
        if source.get("instance"):
            body: dict[str, t.Any] = {
                "type": "copy",
                "source": source["instance"] + ("/" + source["snapshot"] if source.get("snapshot") else ""),
                "instance_only": bool(source.get("instance_only")),
            }
        elif source.get("image"):
            image = source["image"]
            body = {"type": "image"}
            body["fingerprint" if FINGERPRINT_RE.match(image) else "alias"] = image
            if source.get("image_registry"):
                body["image_registry"] = source["image_registry"]
        else:
            self.mod.fail(f"source needs image, instance, or empty to create instance {self.name}")
        if source.get("project"):
            body["project"] = source["project"]
        return body

    def import_backup(self) -> dict[str, t.Any]:
        """Import the instance from a backup file, then apply the managed fields. Return the predicted or the real instance."""
        params = self.mod.params
        source = params["source"]
        path = source["backup_path"]
        if not os.path.isfile(path):
            self.mod.fail(f"backup_path does not exist: {path}")
        needed = ["container_backup", "backup_override_name"] + (["container_backup_override_pool"] if source.get("pool") else [])
        missing = self.mod.client.missing_extensions(needed)
        if missing:
            self.mod.fail(f"LXD server lacks the API extensions: {', '.join(missing)}")
        if self.mod.check_mode:
            return {
                "name": self.name,
                "type": params["type"] or "container",
                "config": params["config"] or {},
                "devices": params["devices"] or {},
                "profiles": params["profiles"] if params["profiles"] is not None else ["default"],
                "description": params["description"] or "",
                "status": "Stopped",
            }
        headers = {"X-LXD-name": self.name, "Content-Length": str(os.path.getsize(path))}
        if source.get("pool"):
            headers["X-LXD-pool"] = source["pool"]
        with open(path, "rb") as stream:
            self.mod.client.write("POST", "/1.0/instances", query=self.mod.query(target=params["target"]), raw=stream, headers=headers)
        current, etag = self.read()
        if current is None:
            self.mod.fail(f"LXD did not create instance {self.name} from {path}")
        instance, _changed = self.update(current, etag)
        self.diff_before = {}
        return instance

    def create(self) -> dict[str, t.Any]:
        """Create the instance. Return the predicted or the real instance."""
        params = self.mod.params
        if not params["source"]:
            self.mod.fail(f"source is required to create instance {self.name}")
        if params["source"].get("backup_path"):
            return self.import_backup()
        devices = {name: normalize_device(name, props) for name, props in (params["devices"] or {}).items() if props is not None}
        body: dict[str, t.Any] = {
            "name": self.name,
            "type": params["type"] or "container",
            "source": self.source_body(),
            "config": create_config(self.mod),
            "devices": devices,
            "description": params["description"] or "",
            "start": False,
        }
        if params["profiles"] is not None:
            body["profiles"] = params["profiles"]
        if params["ephemeral"] is not None:
            body["ephemeral"] = params["ephemeral"]
        if params["instance_type"]:
            body["instance_type"] = params["instance_type"]
        self.mod.write("POST", "/1.0/instances", query=self.mod.query(target=params["target"]), body=body)
        if self.mod.check_mode:
            predicted = dict(body, status="Stopped", profiles=body.get("profiles", ["default"]))
            predicted.pop("source")
            predicted.pop("start")
            return predicted
        instance, _etag = self.read()
        return instance or {}

    def update(self, current: dict[str, t.Any], etag: str | None) -> tuple[dict[str, t.Any], bool]:
        """Apply config, devices, profiles, and other fields. Return the new instance and whether it changed."""
        params = self.mod.params
        plan = plan_common(self.mod, current, FIELDS, COMPUTED_KEYS["instance"])
        if params["profiles"] is not None:
            plan.set("profiles", list(params["profiles"]))
        if params["ephemeral"] is not None:
            plan.set("ephemeral", params["ephemeral"])
        self.diff_before = clean(plan.before())
        if not plan.is_changed:
            self.diff_after = clean(plan.after())
            return current, False
        body = {
            "architecture": current.get("architecture"),
            "config": plan.new.get("config") or {},
            "devices": plan.new.get("devices") or {},
            "profiles": plan.new.get("profiles") or [],
            "ephemeral": bool(plan.new.get("ephemeral")),
            "description": plan.new.get("description") or "",
        }
        self.diff_after = clean(plan.after())
        if self.mod.check_mode:
            return plan.new, True
        try:
            self.mod.client.write("PUT", self.path, query=self.mod.query(), body=body, etag=etag)
        except LXDClientError as exc:
            match = LIVE_UPDATE_RE.search(exc.message)
            if not match:
                raise
            key = match.group(1) or match.group(2)
            if not params["allow_restart"]:
                self.mod.fail(f"LXD cannot apply {key} while the instance runs. Set allow_restart.")
            self.set_state("stop", force=params["force"])
            fresh, fresh_etag = self.read()
            self.mod.client.write("PUT", self.path, query=self.mod.query(), body=body, etag=fresh_etag)
            self.set_state("start")
            self.restarted = True
        instance, _etag = self.read()
        return instance or plan.new, True

    def set_state(self, action: str, force: bool = False) -> None:
        """Send one state action and wait for it."""
        body: dict[str, t.Any] = {"action": action, "timeout": self.mod.params["stop_timeout"], "force": force}
        self.mod.write("PUT", api_path("instances", self.name, "state"), query=self.mod.query(), body=body)

    def stop(self) -> None:
        """Stop the instance cleanly, then by force if O(force) is set."""
        try:
            self.set_state("stop")
        except LXDClientError as exc:
            if not self.mod.params["force"]:
                self.mod.fail(
                    f"instance {self.name} did not stop in {self.mod.params['stop_timeout']} seconds. Set force to force the stop. LXD said: {exc.message}"
                )
            self.set_state("stop", force=True)

    def reach_state(self, status: str) -> tuple[str, bool]:
        """Move the instance to the wanted run state. Return the new status and whether it changed."""
        wanted = self.mod.params["state"]
        have = RUN_STATUS.get(status, "stopped")
        if wanted == "present":
            return status, False
        if wanted == "restarted":
            if have == "frozen":
                # LXD 6.10.1 refuses the restart of a frozen instance ("Instance is not running"), unless it is forced.
                # After the unfreeze, the restart is a clean one.
                self.set_state("unfreeze")
            self.set_state("start" if have == "stopped" else "restart")
            return "Running", True
        if wanted == have:
            return status, False
        if wanted == "started":
            self.set_state("unfreeze" if have == "frozen" else "start")
            return "Running", True
        if wanted == "stopped":
            self.stop()
            return "Stopped", True
        if have == "stopped":
            self.set_state("start")
        self.set_state("freeze")
        return "Frozen", True

    def wait(self) -> None:
        """Wait for the O(wait_for) conditions."""
        conditions = self.mod.params["wait_for"] or []
        if not conditions or self.mod.check_mode or self.mod.params["state"] not in ("started", "restarted"):
            return
        deadline = time.monotonic() + self.mod.params["wait_timeout"]
        for cond in conditions:
            kind = cond["type"]
            if kind == "delay":
                time.sleep(max(0, cond.get("seconds") or 0))
                continue
            while not self.condition_met(kind, cond.get("nic")):
                if time.monotonic() >= deadline:
                    self.mod.fail(f"instance {self.name} did not reach {kind} in {self.mod.params['wait_timeout']} seconds")
                time.sleep(2)

    def condition_met(self, kind: str, nic: str | None) -> bool:
        """Check one wait condition."""
        try:
            state = self.read_state()
        except LXDClientError:
            return False
        if kind == "agent":
            instance, _etag = self.read()
            if (instance or {}).get("type") != "virtual-machine":
                return True
            processes = state.get("processes")
            return processes is not None and processes >= 0
        if kind == "ready":
            return state.get("status") == "Ready"
        family = "inet" if kind == "ipv4" else "inet6"
        return family in address_families(state, nic)

    # ------------------------------------------------------------------
    # States

    def present(self) -> None:
        """Make sure that the instance exists in the wanted run state."""
        current, etag = self.read()
        changed = False
        before_status: str | None = None
        if current is None:
            current = self.create()
            changed = True
            self.diff_after = clean({key: current.get(key) for key in FIELDS})
        else:
            before_status = current.get("status")
            warn_create_only(
                self.mod,
                current,
                {
                    "type": current.get("type"),
                    "source": None,
                    "instance_type": None,
                    "target": current.get("location"),
                },
            )
            current, changed = self.update(current, etag)
        status, state_changed = self.reach_state(current.get("status") or "Stopped")
        if before_status is not None:
            self.diff_before["status"] = before_status
        self.diff_after["status"] = status
        changed = changed or state_changed
        self.wait()
        instance: dict[str, t.Any] | None = current
        if not self.mod.check_mode:
            instance, _etag = self.read()
        else:
            instance = dict(current, status=status)
        self.mod.exit(
            changed,
            before=self.diff_before,
            after=self.diff_after,
            instance=instance,
            addresses=instance_addresses((instance or {}).get("state")),
            restarted=self.restarted,
        )

    def absent(self) -> None:
        """Make sure that the instance does not exist."""
        current, _etag = self.read()
        if current is None:
            self.mod.exit(False, before={}, after={}, instance=None, addresses={}, restarted=False)
        running = current.get("status") in ("Running", "Ready", "Frozen")
        if running and self.mod.params["force"]:
            self.mod.write("DELETE", self.path, query=self.mod.query(force="true"))
        else:
            if running:
                self.stop()
            self.mod.write("DELETE", self.path, query=self.mod.query())
        before = clean({key: current.get(key) for key in FIELDS})
        self.mod.exit(True, before=before, after={}, instance=None, addresses={}, restarted=False)


def clean(fields: dict[str, t.Any]) -> dict[str, t.Any]:
    """Remove computed config keys from a diff part."""
    result = dict(fields)
    if isinstance(result.get("config"), dict):
        result["config"] = {key: value for key, value in result["config"].items() if not is_computed(key, COMPUTED_KEYS["instance"])}
    return result


def get_argument_spec() -> ArgumentSpecMutT:
    """Return the argument spec of the module."""
    return {
        "name": {"type": "str", "required": True},
        "project": {"type": "str"},
        "target": {"type": "str"},
        "state": {
            "type": "str",
            "default": "started",
            "choices": ["present", "started", "stopped", "frozen", "restarted", "absent"],
        },
        "type": {"type": "str", "choices": ["container", "virtual-machine"]},
        "source": {
            "type": "dict",
            "options": {
                "image": {"type": "str"},
                "image_registry": {"type": "str"},
                "project": {"type": "str"},
                "instance": {"type": "str"},
                "snapshot": {"type": "str"},
                "instance_only": {"type": "bool", "default": False},
                "empty": {"type": "bool", "default": False},
                "backup_path": {"type": "path"},
                "pool": {"type": "str"},
            },
            "mutually_exclusive": [["image", "instance", "empty", "backup_path"]],
            "required_by": {"snapshot": "instance", "image_registry": "image", "pool": "backup_path"},
        },
        "profiles": {"type": "list", "elements": "str"},
        "config": {"type": "dict"},
        "config_mode": {"type": "str", "default": "merge", "choices": ["merge", "exact"]},
        "devices": {"type": "dict"},
        "devices_mode": {"type": "str", "default": "merge", "choices": ["merge", "exact"]},
        "ephemeral": {"type": "bool"},
        "description": {"type": "str"},
        "instance_type": {"type": "str"},
        "force": {"type": "bool", "default": False},
        "stop_timeout": {"type": "int", "default": 30},
        "allow_restart": {"type": "bool", "default": False},
        "wait_for": {
            "type": "list",
            "elements": "dict",
            "options": {
                "type": {"type": "str", "required": True, "choices": ["agent", "ipv4", "ipv6", "ready", "delay"]},
                "nic": {"type": "str"},
                "seconds": {"type": "int"},
            },
        },
        "wait_timeout": {"type": "int", "default": 300},
    }


def main() -> None:
    """Run the module."""
    mod = LXDModule(get_argument_spec(), extensions=["instances"])
    mod.check_target()
    if mod.params["source"] and mod.params["source"].get("image_registry"):
        missing = mod.client.missing_extensions(["image_registries"])
        if missing:
            mod.fail(f"LXD server lacks the API extensions: {', '.join(missing)}")
    instance = InstanceModule(mod)
    if mod.params["state"] == "absent":
        mod.run(instance.absent)
    else:
        mod.run(instance.present)


if __name__ == "__main__":
    main()
