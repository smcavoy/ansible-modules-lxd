# Copyright (c) 2026, Sean McAvoy
# GNU General Public License v3.0+ (see LICENSES/GPL-3.0-or-later.txt or https://www.gnu.org/licenses/gpl-3.0.txt)
# SPDX-License-Identifier: GPL-3.0-or-later

# Note that this module util is **PRIVATE** to the collection. It can have breaking changes at any time.
# Do not use this from other collections or standalone plugins/modules!

"""Shared read steps for the info modules."""

from __future__ import annotations

import typing as t

if t.TYPE_CHECKING:  # pragma: no cover
    from ansible_collections.smcavoy.lxd.plugins.module_utils._module import LXDModule


def check_all_projects(mod: LXDModule, extension: str | None) -> None:
    """Fail when O(all_projects) goes with O(project), or the server lacks the extension for it."""
    if not mod.params.get("all_projects"):
        return
    if mod.params.get("project"):
        mod.fail("all_projects and project are mutually exclusive")
    if extension:
        missing = mod.client.missing_extensions([extension])
        if missing:
            mod.fail(f"LXD server lacks the API extension {extension}, which all_projects needs")


def with_project(mod: LXDModule, item: dict[str, t.Any]) -> dict[str, t.Any]:
    """Return a copy of an object with the key C(project). LXD leaves it out for some objects."""
    result = dict(item)
    result.setdefault("project", mod.params.get("project") or "default")
    return result


def list_items(mod: LXDModule, path: str, recursion: int = 1, **extra: t.Any) -> list[dict[str, t.Any]]:
    """Return all objects of a collection, each with C(project)."""
    query = mod.query(**extra)
    if mod.params.get("all_projects"):
        query.pop("project", None)
        query["all-projects"] = "true"
    query["recursion"] = recursion
    items, _etag = mod.client.get(path, query)
    return [with_project(mod, item) for item in items or [] if isinstance(item, dict)]


def get_item(mod: LXDModule, path: str, **extra: t.Any) -> list[dict[str, t.Any]]:
    """Return a list with one object, or an empty list when it does not exist."""
    item, _etag = mod.client.get_or_none(path, mod.query(**extra))
    return [with_project(mod, item)] if isinstance(item, dict) else []
