# Copyright (c) 2026, Sean McAvoy
# GNU General Public License v3.0+ (see LICENSES/GPL-3.0-or-later.txt or https://www.gnu.org/licenses/gpl-3.0.txt)
# SPDX-License-Identifier: GPL-3.0-or-later

# Note that this module util is **PRIVATE** to the collection. It can have breaking changes at any time.
# Do not use this from other collections or standalone plugins/modules!

"""Compare and merge LXD config maps and device maps."""

from __future__ import annotations

import fnmatch
import ipaddress
import re
import typing as t
from collections.abc import Mapping, Sequence

# Computed keys per resource, from section 5.6 of the module plan.
COMPUTED_KEYS: dict[str, tuple[str, ...]] = {
    "instance": ("volatile.*", "image.*"),
    "network": ("volatile.*", "bridge.mtu", "ipv4.address", "ipv4.nat", "ipv6.address", "ipv6.nat"),
    "profile": (),
    "project": ("features.images", "features.profiles", "features.storage.volumes", "features.storage.buckets"),
    "storage_volume": ("volatile.*", "block.filesystem", "block.mount_options"),
    "network_forward": (),
    "cluster_link": ("volatile.*",),
    "storage_bucket": ("volatile.*",),
}


# Server config keys whose value is a URL that can hold a password, for example http://user:secret@proxy:3128.
URL_SECRET_KEYS = ("core.proxy_http", "core.proxy_https")
URL_MASK = "********"
# The scheme and the user of a URL, then its password. The user information ends at the last "@" of the authority.
_URL_PASSWORD_RE = re.compile(r"^([A-Za-z][A-Za-z0-9+.-]*://[^/?#:@]*):([^/?#]*)@")


def url_password(value: t.Any) -> str | None:
    """Return the password in the user information of a URL, or None when it has none."""
    match = _URL_PASSWORD_RE.match(value) if isinstance(value, str) else None
    return match.group(2) or None if match else None


def mask_url_password(value: t.Any) -> t.Any:
    """Return a URL with its password masked. The user, the host, and the port stay. Any other value stays as it is."""
    if url_password(value) is None:
        return value
    return _URL_PASSWORD_RE.sub(lambda match: f"{match.group(1)}:{URL_MASK}@", value, count=1)


class ConfigValueError(ValueError):
    """A config value that LXD cannot take."""


def to_lxd_value(key: str, value: t.Any) -> str | None:
    """Convert one task value to the string form that LXD stores. C(None) stays C(None)."""
    if value is None:
        return None
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, (int, float)):
        return str(value)
    if isinstance(value, str):
        return value
    if isinstance(value, (Mapping, Sequence)):
        raise ConfigValueError(f"config value for {key} must be a string, a number, or a boolean")
    return str(value)


def normalize_config(config: Mapping[str, t.Any] | None) -> dict[str, str | None] | None:
    """Convert every value of a task config to its LXD string form."""
    if config is None:
        return None
    return {str(key): to_lxd_value(str(key), value) for key, value in config.items()}


def is_computed(key: str, patterns: Sequence[str]) -> bool:
    """Return whether a key matches one of the computed key patterns."""
    return any(fnmatch.fnmatchcase(key, pattern) for pattern in patterns)


def merge_config(
    current: Mapping[str, str] | None,
    desired: Mapping[str, str | None] | None,
    mode: str = "merge",
    computed: Sequence[str] = (),
    keep: Sequence[str] = (),
) -> tuple[dict[str, str], list[str]]:
    """Return the new config and the sorted list of keys that change.

    A value of C(None) or an empty string removes the key.
    In C(exact) mode, keys that are not in O(desired) go away, except computed keys and keys in O(keep).
    """
    base = dict(current or {})
    if desired is None:
        return base, []
    new = dict(base)
    changed: set[str] = set()
    for key, value in desired.items():
        if value is None or value == "":
            if key in new:
                del new[key]
                changed.add(key)
        elif new.get(key) != value:
            new[key] = value
            changed.add(key)
    if mode == "exact":
        for key in list(new):
            if key not in desired and not is_computed(key, computed) and key not in keep:
                del new[key]
                changed.add(key)
    return new, sorted(changed)


def normalize_device(name: str, props: Mapping[str, t.Any]) -> dict[str, str]:
    """Convert every property of a device to a string. The device needs C(type)."""
    if "type" not in props or props["type"] in (None, ""):
        raise ConfigValueError(f"device {name} needs a type")
    result: dict[str, str] = {}
    for key, value in props.items():
        converted = to_lxd_value(f"{name}.{key}", value)
        if converted is not None and converted != "":
            result[str(key)] = converted
    return result


def merge_devices(
    current: Mapping[str, Mapping[str, str]] | None,
    desired: Mapping[str, Mapping[str, t.Any] | None] | None,
    mode: str = "merge",
) -> tuple[dict[str, dict[str, str]], list[str]]:
    """Return the new devices and the sorted list of device names that change.

    A device value of C(None) removes the device. A device changes as a whole.
    """
    base = {name: dict(props) for name, props in (current or {}).items()}
    if desired is None:
        return base, []
    new = dict(base)
    changed: set[str] = set()
    for name, props in desired.items():
        if props is None:
            if name in new:
                del new[name]
                changed.add(name)
            continue
        device = normalize_device(name, props)
        if new.get(name) != device:
            new[name] = device
            changed.add(name)
    if mode == "exact":
        for name in list(new):
            if name not in desired:
                del new[name]
                changed.add(name)
    return new, sorted(changed)


def pick(obj: Mapping[str, t.Any] | None, keys: Sequence[str]) -> dict[str, t.Any]:
    """Return a new dictionary with only the given keys of O(obj)."""
    if not obj:
        return {}
    return {key: obj[key] for key in keys if key in obj}


def trim_list(text: t.Any) -> str:
    """Return a comma-separated list without the spaces around its items, as LXD stores it."""
    return ",".join(item.strip() for item in str("" if text is None else text).split(","))


def canonical_ip(text: t.Any) -> str:
    """Return an IP address in the form that LXD stores (for example lower case for IPv6). Other text stays, trimmed."""
    value = str("" if text is None else text).strip()
    try:
        return str(ipaddress.ip_address(value))
    except ValueError:
        return value
