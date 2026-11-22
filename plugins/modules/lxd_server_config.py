#!/usr/bin/python
# Copyright (c) 2026, Sean McAvoy
# GNU General Public License v3.0+ (see LICENSES/GPL-3.0-or-later.txt or https://www.gnu.org/licenses/gpl-3.0.txt)
# SPDX-License-Identifier: GPL-3.0-or-later

from __future__ import annotations

DOCUMENTATION = r"""
module: lxd_server_config
short_description: Manage the LXD server config
version_added: "0.1.0"
description:
  - Manage the server config keys of a standalone LXD server or a cluster.
  - On a cluster, the module manages member-specific keys per member, for example C(core.https_address).
author:
  - Sean McAvoy (@smcavoy)
extends_documentation_fragment:
  - smcavoy.lxd._attributes
  - smcavoy.lxd._attributes.action_group
  - smcavoy.lxd._connection
attributes:
  check_mode:
    support: full
  diff_mode:
    support: full
  idempotent:
    support: full
options:
  config:
    description:
      - The server config keys.
      - The module converts each value to a string. V(true) becomes C("true"), and V(6) becomes C("6").
      - A value of V(null) or an empty string removes the key.
      - If not set, the module does not manage the config.
    type: dict
  config_mode:
    description:
      - How to treat config keys that are on the server but not in O(config).
      - V(exact) never removes C(core.https_address), C(cluster.https_address), or C(volatile.*) keys.
        A removal of an address can end the connection of the task itself.
    type: str
    choices:
      merge: Keep them.
      exact: Remove them. Use this with care, because it also removes keys that other tools set.
    default: merge
  member_config:
    description:
      - Member-specific config keys per cluster member, as a dictionary of member name to keys.
      - A member-specific key in O(config) is the default for all members. O(member_config) overrides it.
      - Only valid on a cluster.
    type: dict
notes:
  - The module masks the values of C(loki.auth.password), C(oidc.client.secret), and C(network.ovn.client_key) in the diff and the result.
  - The module masks the password in the URL of C(core.proxy_http) and C(core.proxy_https) in the diff and the result, for example
    C(http://user:********@proxy:3128). The user, the host, and the port stay. The module compares the real values.
  - A change of C(core.https_address) can end the connection that the task uses. The module warns before it sends such a change.
  - LXD does not store a key at its default value. A task that sets a key to its default, for example C(images.auto_update_interval=6),
    reports a change on every run. Set such a key to V(null) instead.
seealso:
  - name: LXD server configuration
    description: The LXD documentation about the server config keys.
    link: https://documentation.ubuntu.com/lxd/latest/server/
"""

EXAMPLES = r"""
- name: Set the image update interval and a user key
  smcavoy.lxd.lxd_server_config:
    config:
      images.auto_update_interval: 6
      user.owner: platform-team

- name: Give each cluster member its own metrics address
  smcavoy.lxd.lxd_server_config:
    member_config:
      node1:
        core.metrics_address: 10.0.0.11:9100
      node2:
        core.metrics_address: 10.0.0.12:9100
"""

RETURN = r"""
config:
  description:
    - The global server config after the change, with secret values masked.
    - On a standalone server, it holds all keys.
    - In check mode, the predicted config.
  returned: always
  type: dict
  sample:
    core.https_address: "[::]:8443"
    images.auto_update_interval: "6"
    oidc.client.secret: "********"
members:
  description:
    - On a cluster, the member-specific keys of each member, with secret values masked.
  returned: on a cluster
  type: dict
  sample:
    node1:
      core.metrics_address: 10.0.0.11:9100
"""

import typing as t

from ansible_collections.smcavoy.lxd.plugins.module_utils._cluster import (
    local_keys,
    member_local_config,
    member_names,
    split_config,
)
from ansible_collections.smcavoy.lxd.plugins.module_utils._config import (
    URL_SECRET_KEYS,
    mask_url_password,
    merge_config,
    normalize_config,
    url_password,
)
from ansible_collections.smcavoy.lxd.plugins.module_utils._module import LXDModule

if t.TYPE_CHECKING:  # pragma: no cover
    from ansible_collections.smcavoy.lxd.plugins.module_utils._typing import ArgumentSpecMutT

SECRET_KEYS = ("loki.auth.password", "oidc.client.secret", "network.ovn.client_key")
MASK = "********"
COMPUTED = ("volatile.*",)
PROTECTED = ("core.https_address", "cluster.https_address")


def put_body(current: dict[str, t.Any], new: dict[str, t.Any]) -> dict[str, t.Any]:
    """Return the config for a PUT /1.0. LXD keeps keys that the body leaves out, so a removed key goes in with an empty value."""
    body = dict(new)
    for key in current:
        if key not in new:
            body[key] = ""
    return {"config": body}


def mask(config: dict[str, t.Any] | None) -> dict[str, t.Any]:
    """Return a copy of a config with the secret values masked, and the password in a proxy URL."""
    result: dict[str, t.Any] = {}
    for key, value in (config or {}).items():
        if key in SECRET_KEYS and value not in (None, ""):
            value = MASK
        elif key in URL_SECRET_KEYS:
            value = mask_url_password(value)
        result[key] = value
    return result


class ServerConfigModule:
    """Manage the LXD server config."""

    def __init__(self, mod: LXDModule) -> None:
        self.mod = mod
        # Ansible then masks the secret values everywhere in the output, also in invocation.module_args.
        configs = [mod.params["config"] or {}] + list((mod.params["member_config"] or {}).values())
        for config in configs:
            for key in SECRET_KEYS:
                if isinstance(config, dict) and config.get(key) not in (None, ""):
                    mod.module.no_log_values.add(str(config[key]))
            for key in URL_SECRET_KEYS:
                password = url_password(config.get(key)) if isinstance(config, dict) else None
                if password:
                    mod.module.no_log_values.add(password)
        self.clustered = mod.client.is_clustered()
        self.local = local_keys(mod.client, "server") if self.clustered else set()

    def read(self, target: str | None = None) -> tuple[dict[str, t.Any], str | None]:
        """Read the server config, or the view of one member."""
        server, etag = self.mod.client.get("/1.0", {"target": target} if target else None)
        return dict((server or {}).get("config") or {}), etag

    def warn_address(self, before: dict[str, t.Any], after: dict[str, t.Any], where: str = "") -> None:
        """Warn when the task changes the HTTPS address."""
        if before.get("core.https_address") != after.get("core.https_address"):
            self.mod.warn(f"core.https_address changes{where}. This can end the connection that the task uses.")

    def run(self) -> None:
        """Compare and update the config."""
        params = self.mod.params
        if params["member_config"] and not self.clustered:
            self.mod.fail("member_config is only valid on a clustered server")
        if self.clustered:
            self.run_cluster()
        current, etag = self.read()
        new, changed = merge_config(current, normalize_config(params["config"]), params["config_mode"], COMPUTED, keep=PROTECTED)
        before, after = mask(current), mask(new)
        if not changed:
            self.mod.exit(False, before={"config": before}, after={"config": after}, config=before)
        self.warn_address(current, new)
        self.mod.write("PUT", "/1.0", body=put_body(current, new), etag=etag)
        self.mod.exit(True, before={"config": before}, after={"config": after}, config=self.final(new))

    def run_cluster(self) -> t.NoReturn:
        """Compare and update the global keys and the member-specific keys of each member."""
        params = self.mod.params
        desired = normalize_config(params["config"])
        desired_global, desired_local = split_config(desired or {}, self.local)
        answer, answer_etag = self.read()
        current_global, answer_local = split_config(answer, self.local)
        new_global, global_changes = merge_config(
            current_global,
            desired_global if desired is not None else None,
            params["config_mode"],
            COMPUTED,
            keep=sorted(set(PROTECTED) | self.local),
        )
        members = member_names(self.mod.client)
        wanted = member_local_config(members, desired_local, params["member_config"])
        before_members: dict[str, t.Any] = {}
        after_members: dict[str, t.Any] = {}
        updates: dict[str, tuple[dict[str, t.Any], str | None]] = {}
        for member in members:
            view, member_etag = self.read(target=member)
            _unused, server_local = split_config(view, self.local)
            new_local, changes = merge_config(server_local, normalize_config(wanted[member]), "merge")
            before_members[member] = mask(server_local)
            after_members[member] = mask(new_local)
            if changes:
                self.warn_address(server_local, new_local, f" on member {member}")
                updates[member] = (put_body(dict(current_global, **server_local), dict(new_global, **new_local)), member_etag)
        before = {"config": mask(current_global), "members": before_members}
        after = {"config": mask(new_global), "members": after_members}
        if not global_changes and not updates:
            self.mod.exit(False, before=before, after=after, config=mask(current_global), members=before_members)
        # LXD applies the full body of a PUT /1.0 to the global keys too, so every body holds the new global keys.
        if global_changes and not updates:
            self.mod.write("PUT", "/1.0", body=put_body(answer, dict(new_global, **answer_local)), etag=answer_etag)
        for member, (body, member_etag) in updates.items():
            self.mod.write("PUT", "/1.0", query={"target": member}, body=body, etag=member_etag)
        if self.mod.check_mode:
            self.mod.exit(True, before=before, after=after, config=mask(new_global), members=after_members)
        final_global, _etag = self.read()
        final_members = {member: mask(split_config(self.read(target=member)[0], self.local)[1]) for member in members}
        self.mod.exit(True, before=before, after=after, config=mask(split_config(final_global, self.local)[0]), members=final_members)

    def final(self, predicted: dict[str, t.Any]) -> dict[str, t.Any]:
        """Return the masked config from the server, or the prediction in check mode."""
        if self.mod.check_mode:
            return mask(predicted)
        config, _etag = self.read()
        return mask(config)


def get_argument_spec() -> ArgumentSpecMutT:
    """Return the argument spec of the module."""
    return {
        "config": {"type": "dict"},
        "config_mode": {"type": "str", "default": "merge", "choices": ["merge", "exact"]},
        "member_config": {"type": "dict"},
    }


def main() -> None:
    """Run the module."""
    mod = LXDModule(get_argument_spec())
    server = ServerConfigModule(mod)
    mod.run(server.run)


if __name__ == "__main__":
    main()
