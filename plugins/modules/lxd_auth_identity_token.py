#!/usr/bin/python
# Copyright (c) 2026, Sean McAvoy
# GNU General Public License v3.0+ (see LICENSES/GPL-3.0-or-later.txt or https://www.gnu.org/licenses/gpl-3.0.txt)
# SPDX-License-Identifier: GPL-3.0-or-later

from __future__ import annotations

DOCUMENTATION = r"""
module: lxd_auth_identity_token
short_description: Issue and revoke tokens of LXD bearer identities
version_added: "0.1.0"
description:
  - Issue a token for a bearer identity, or revoke its token.
  - Create the identity first with M(smcavoy.lxd.lxd_auth_identity).
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
    support: none
  idempotent:
    support: full
    details:
      - A second run does not issue a new token while the identity has one, unless O(force=true).
options:
  name:
    description:
      - The name or the ID of the bearer identity.
    type: str
    required: true
  state:
    description:
      - The wanted state of the token.
    type: str
    choices:
      present: The identity has a token that is not expired. The module issues one if it has none, or if its token is expired.
      absent: The identity has no token. The module revokes it.
    default: present
  expiry:
    description:
      - The lifetime of a new token, for example V(24H) or V(30d). LXD takes the units S, M, H, d, w, m, and y. If not set, the server default applies.
    type: str
  force:
    description:
      - Issue a new token even when the identity has one. The new token replaces the old one.
    type: bool
    default: false
notes:
  - The token is a secret. It appears only in the result of the run that issues it. Use C(no_log=true) on the task.
seealso:
  - module: smcavoy.lxd.lxd_auth_identity
"""

EXAMPLES = r"""
- name: Issue a token for the bearer identity ci
  smcavoy.lxd.lxd_auth_identity_token:
    name: ci
    expiry: 30d
  register: ci_token
  no_log: true

- name: Revoke the token
  smcavoy.lxd.lxd_auth_identity_token:
    name: ci
    state: absent
"""

RETURN = r"""
token:
  description:
    - The new token. Only when the module issues one. This is a secret.
  returned: when the module issues a token
  type: str
  sample: eyJhbGciOiJFUzM4NCIs...
identity:
  description:
    - The identity after the change.
  returned: always
  type: dict
  sample:
    name: ci
    type: Client token bearer
    expires_at: "2026-12-06T10:00:00Z"
"""

import datetime
import typing as t

from ansible_collections.smcavoy.lxd.plugins.module_utils._client import api_path
from ansible_collections.smcavoy.lxd.plugins.module_utils._module import LXDModule
from ansible_collections.smcavoy.lxd.plugins.module_utils._time import parse_time

if t.TYPE_CHECKING:  # pragma: no cover
    from ansible_collections.smcavoy.lxd.plugins.module_utils._typing import ArgumentSpecMutT

PENDING = "(pending)"


class IdentityTokenModule:
    """Issue or revoke the token of one bearer identity."""

    def __init__(self, mod: LXDModule) -> None:
        self.mod = mod
        self.name: str = mod.params["name"]
        self.path = api_path("auth", "identities", "bearer", self.name)

    def read(self) -> dict[str, t.Any]:
        """Read the identity. Fail when it does not exist."""
        identity, _etag = self.mod.client.get_or_none(self.path)
        if identity is None:
            self.mod.fail(f"bearer identity {self.name} not found")
        return identity

    @staticmethod
    def expired(identity: dict[str, t.Any]) -> bool:
        """Return whether the token of the identity is past its expiry time. A token without a time never expires."""
        try:
            expires = parse_time(identity.get("expires_at"))
        except ValueError:
            return False
        return expires is not None and expires <= datetime.datetime.now(datetime.timezone.utc)

    def present(self) -> None:
        """Issue a token when the identity has none or an expired one, or with force."""
        identity = self.read()
        has_token = not str(identity.get("type") or "").endswith(PENDING)
        if has_token and self.expired(identity):
            # LXD keeps the type of the identity when its token expires. Such a token opens nothing, so the module issues a new one.
            has_token = False
        if has_token and not self.mod.params["force"]:
            self.mod.exit(False, identity=identity)
        if self.mod.check_mode:
            self.mod.exit(True, identity=identity)
        body = {"expiry": self.mod.params["expiry"] or ""}
        resp = self.mod.client.request("POST", f"{self.path}/token", body=body)
        token = (resp.envelope.get("metadata") or {}).get("token")
        if not token:
            self.mod.fail("LXD did not return a token")
        self.mod.exit(True, token=token, identity=self.read())

    def absent(self) -> None:
        """Revoke the token of the identity."""
        identity = self.read()
        if str(identity.get("type") or "").endswith(PENDING):
            self.mod.exit(False, identity=identity)
        if self.mod.check_mode:
            self.mod.exit(True, identity=identity)
        self.mod.client.request("DELETE", f"{self.path}/token")
        self.mod.exit(True, identity=self.read())


def get_argument_spec() -> ArgumentSpecMutT:
    """Return the argument spec of the module."""
    return {
        "name": {"type": "str", "required": True},
        "state": {"type": "str", "default": "present", "choices": ["present", "absent"]},
        "expiry": {"type": "str"},
        "force": {"type": "bool", "default": False},
    }


def main() -> None:
    """Run the module."""
    mod = LXDModule(get_argument_spec(), extensions=["auth_bearer"])
    token = IdentityTokenModule(mod)
    if mod.params["state"] == "present":
        mod.run(token.present)
    else:
        mod.run(token.absent)


if __name__ == "__main__":
    main()
