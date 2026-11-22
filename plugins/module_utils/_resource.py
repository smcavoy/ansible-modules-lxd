# Copyright (c) 2026, Sean McAvoy
# GNU General Public License v3.0+ (see LICENSES/GPL-3.0-or-later.txt or https://www.gnu.org/licenses/gpl-3.0.txt)
# SPDX-License-Identifier: GPL-3.0-or-later

# Note that this module util is **PRIVATE** to the collection. It can have breaking changes at any time.
# Do not use this from other collections or standalone plugins/modules!

"""Shared read, compare, and write steps for LXD objects with config and description."""

from __future__ import annotations

import copy
import typing as t
from collections.abc import Mapping, Sequence

from ansible_collections.smcavoy.lxd.plugins.module_utils._config import (
    merge_config,
    merge_devices,
    normalize_config,
    pick,
)

if t.TYPE_CHECKING:  # pragma: no cover
    from ansible_collections.smcavoy.lxd.plugins.module_utils._module import LXDModule


class Plan:
    """The result of a compare: the new object, the changed fields, and the diff parts."""

    def __init__(self, current: Mapping[str, t.Any], fields: Sequence[str]) -> None:
        self.current = copy.deepcopy(dict(current))
        self.new = copy.deepcopy(dict(current))
        self.fields = list(fields)
        self.changed: list[str] = []

    @property
    def is_changed(self) -> bool:
        """Return whether any field changes."""
        return bool(self.changed)

    def set(self, field: str, value: t.Any) -> None:
        """Set a field of the new object. Record a change if it differs."""
        if self.new.get(field) != value:
            self.new[field] = value
            if field not in self.changed:
                self.changed.append(field)

    def before(self) -> dict[str, t.Any]:
        """Return the managed fields before the change."""
        return pick(self.current, self.fields)

    def after(self) -> dict[str, t.Any]:
        """Return the managed fields after the change."""
        return pick(self.new, self.fields)


def plan_common(
    mod: LXDModule,
    current: Mapping[str, t.Any],
    fields: Sequence[str],
    computed: Sequence[str] = (),
    keep: Sequence[str] = (),
) -> Plan:
    """Compare O(description), O(config), and O(devices) of a task with the current object."""
    plan = Plan(current, fields)
    params = mod.params
    if "description" in params and params["description"] is not None:
        plan.set("description", params["description"])
    if "config" in params:
        new_config, changed = merge_config(
            current.get("config") or {},
            normalize_config(params["config"]),
            params.get("config_mode") or "merge",
            computed,
            keep,
        )
        if changed:
            plan.new["config"] = new_config
            plan.changed.append("config")
    if "devices" in params:
        new_devices, changed = merge_devices(
            current.get("devices") or {},
            params["devices"],
            params.get("devices_mode") or "merge",
        )
        if changed:
            plan.new["devices"] = new_devices
            plan.changed.append("devices")
    return plan


def create_config(mod: LXDModule) -> dict[str, str]:
    """Return the config of a task for a create, without removed keys."""
    config = normalize_config(mod.params.get("config")) or {}
    return {key: value for key, value in config.items() if value not in (None, "")}


def warn_create_only(mod: LXDModule, current: Mapping[str, t.Any], options: Mapping[str, t.Any]) -> None:
    """Warn about create-only options that differ on an existing object. This is rule R10."""
    for option, server_value in options.items():
        value = mod.params.get(option)
        if value is None:
            continue
        if server_value is not None and value == server_value:
            continue
        mod.warn(f"{option} applies only on create. The existing object keeps its value.")
