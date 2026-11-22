# Copyright (c) 2026, Sean McAvoy
# GNU General Public License v3.0+ (see LICENSES/GPL-3.0-or-later.txt or https://www.gnu.org/licenses/gpl-3.0.txt)
# SPDX-License-Identifier: GPL-3.0-or-later

# Note that this module util is **PRIVATE** to the collection. It can have breaking changes at any time.
# Do not use this from other collections or standalone plugins/modules!

"""Member-specific config keys and the pending-then-global create flow."""

from __future__ import annotations

import typing as t
from collections.abc import Mapping

from ansible_collections.smcavoy.lxd.plugins.module_utils._config import ConfigValueError

if t.TYPE_CHECKING:  # pragma: no cover
    from ansible_collections.smcavoy.lxd.plugins.module_utils._client import LXDClient

_SCOPES_ATTR = "_lxd_local_key_cache"


def local_keys(client: LXDClient, entity: str) -> set[str]:
    """Return the member-specific keys of an entity, for example C(network-bridge) or C(storage-zfs)."""
    cache: dict[str, set[str]] | None = getattr(client, _SCOPES_ATTR, None)
    if cache is None:
        meta, _etag = client.get("/1.0/metadata/configuration")
        cache = {}
        for name, sections in ((meta or {}).get("configs") or {}).items():
            keys: set[str] = set()
            for section in (sections or {}).values():
                for item in (section or {}).get("keys") or []:
                    for key, info in item.items():
                        if (info or {}).get("scope") == "local":
                            keys.add(key)
            cache[name] = keys
        setattr(client, _SCOPES_ATTR, cache)
    return set(cache.get(entity, set()))


def split_config(config: Mapping[str, t.Any], local: set[str]) -> tuple[dict[str, t.Any], dict[str, t.Any]]:
    """Split a config into global keys and member-specific keys."""
    global_part = {key: value for key, value in config.items() if key not in local}
    local_part = {key: value for key, value in config.items() if key in local}
    return global_part, local_part


UNFINISHED_STATUSES = ("Pending", "Errored")


def unfinished_create(kind: str, name: str, obj: Mapping[str, t.Any]) -> str | None:
    """Return a failure message when a cluster create of the object did not finish, or None.

    A create on a cluster first makes the object on each member (status C(Pending)), then on the whole cluster. When
    the second step fails, the status is C(Errored). When it never runs, the status stays C(Pending). LXD cannot use
    the object in both cases.
    """
    status = obj.get("status")
    if status not in UNFINISHED_STATUSES:
        return None
    members = ", ".join(obj.get("locations") or []) or "none"
    return (
        f"The {kind} {name} has the status {status}: its cluster create did not finish, and LXD cannot use it "
        f"(members: {members}). Find the cause, remove the {kind} with state=absent, and run the task again."
    )


def member_names(client: LXDClient) -> list[str]:
    """Return the names of the cluster members."""
    urls, _etag = client.get("/1.0/cluster/members")
    return sorted(url.rstrip("/").rsplit("/", 1)[-1] for url in urls or [])


def member_local_config(
    members: list[str],
    default_local: Mapping[str, t.Any],
    member_config: Mapping[str, Mapping[str, t.Any]] | None,
) -> dict[str, dict[str, t.Any]]:
    """Return the member-specific keys for each member: the defaults, then the per-member values.

    Raise ConfigValueError when O(member_config) names a member that the cluster does not have.
    """
    unknown = sorted(set(member_config or {}) - set(members))
    if unknown:
        raise ConfigValueError(f"member_config names members that the cluster does not have: {', '.join(unknown)}. Members: {', '.join(members)}")
    result: dict[str, dict[str, t.Any]] = {}
    for member in members:
        values = dict(default_local)
        values.update((member_config or {}).get(member) or {})
        result[member] = values
    return result
