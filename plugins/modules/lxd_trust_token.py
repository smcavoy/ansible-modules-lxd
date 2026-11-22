#!/usr/bin/python
# Copyright (c) 2026, Sean McAvoy
# GNU General Public License v3.0+ (see LICENSES/GPL-3.0-or-later.txt or https://www.gnu.org/licenses/gpl-3.0.txt)
# SPDX-License-Identifier: GPL-3.0-or-later

from __future__ import annotations

DOCUMENTATION = r"""
module: lxd_trust_token
short_description: Issue and revoke LXD trust tokens
version_added: "0.1.0"
description:
  - Issue a trust token that a new client uses once to add its certificate to the LXD trust store.
  - Revoke the open tokens of a client name.
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
      - A second run does not issue a new token while one is open for the name, unless O(force=true).
options:
  name:
    description:
      - The client name in the token. The new trust entry gets this name.
    type: str
    required: true
  state:
    description:
      - The wanted state of the tokens for O(name).
    type: str
    choices:
      present: A token is open for O(name). The module issues one if none is open.
      absent: No token is open for O(name). The module revokes the open tokens.
    default: present
  restricted:
    description:
      - The new certificate is restricted to O(projects).
    type: bool
    default: false
  projects:
    description:
      - The projects of a restricted certificate.
    type: list
    elements: str
  force:
    description:
      - Issue a new token even when one is open.
    type: bool
    default: false
notes:
  - The token is a secret. It appears only in the result of the run that issues it. Use C(no_log=true) on the task.
  - A client uses the token with C(lxc remote add) or with a C(POST /1.0/certificates) that holds C(trust_token).
seealso:
  - module: smcavoy.lxd.lxd_trust_certificate
"""

EXAMPLES = r"""
- name: Issue a token for a new workstation
  smcavoy.lxd.lxd_trust_token:
    name: laptop
  register: trust
  no_log: true
"""

RETURN = r"""
token:
  description:
    - The trust token. Only when the module issues one. This is a secret.
  returned: when the module issues a token
  type: str
  sample: eyJjbGllbnRfbmFtZSI6ImxhcHRvcCIsLi4u
expires_at:
  description:
    - The expiry of the new token.
  returned: when the module issues a token
  type: str
  sample: "2026-11-06T13:00:00Z"
operation:
  description:
    - The ID of the operation that holds the token.
  returned: when the module issues a token
  type: str
  sample: 01a1a00a-6ae7-7412-8972-aea8529f209b
revoked:
  description:
    - The IDs of the token operations that the module revoked.
  returned: when O(state=absent) revokes tokens
  type: list
  elements: str
"""

import base64
import json
import typing as t

from ansible_collections.smcavoy.lxd.plugins.module_utils._client import api_path
from ansible_collections.smcavoy.lxd.plugins.module_utils._module import LXDModule

if t.TYPE_CHECKING:  # pragma: no cover
    from ansible_collections.smcavoy.lxd.plugins.module_utils._typing import ArgumentSpecMutT


def encode_token(meta: dict[str, t.Any]) -> str:
    """Build the trust token from the operation metadata, as the lxc client does: base64 of a JSON object."""
    token = {
        "client_name": (meta.get("request") or {}).get("name"),
        "fingerprint": meta.get("fingerprint"),
        "addresses": meta.get("addresses") or [],
        "secret": meta.get("secret"),
        "expires_at": meta.get("expiresAt"),
    }
    return base64.b64encode(json.dumps(token, separators=(",", ":")).encode()).decode()


class TrustTokenModule:
    """Issue or revoke the trust tokens of one client name."""

    def __init__(self, mod: LXDModule) -> None:
        self.mod = mod
        self.name: str = mod.params["name"]
        if mod.params["projects"] and not mod.params["restricted"]:
            mod.fail("projects needs restricted=true")

    def open_tokens(self) -> list[dict[str, t.Any]]:
        """Return the running trust token operations for this name."""
        ops, _etag = self.mod.client.get("/1.0/operations", {"recursion": 1})
        running = ((ops or {}).get("running") or []) if isinstance(ops, dict) else []
        return [op for op in running if op.get("class") == "token" and ((op.get("metadata") or {}).get("request") or {}).get("name") == self.name]

    def present(self) -> None:
        """Issue a token unless one is open."""
        params = self.mod.params
        if self.open_tokens() and not params["force"]:
            self.mod.exit(False, msg=f"a trust token for {self.name} is already open")
        if self.mod.check_mode:
            self.mod.exit(True)
        body: dict[str, t.Any] = {"name": self.name, "type": "client", "token": True, "restricted": params["restricted"]}
        if params["restricted"]:
            body["projects"] = params["projects"] or []
        # The token operation runs until a client uses it or it expires, so the module does not wait for it.
        resp = self.mod.client.request("POST", "/1.0/certificates", body=body)
        operation = resp.envelope.get("metadata") or {}
        meta = operation.get("metadata") or {}
        self.mod.exit(True, token=encode_token(meta), expires_at=meta.get("expiresAt"), operation=operation.get("id"))

    def absent(self) -> None:
        """Revoke the open tokens of this name."""
        tokens = self.open_tokens()
        if not tokens:
            self.mod.exit(False)
        if not self.mod.check_mode:
            for op in tokens:
                self.mod.client.request("DELETE", api_path("operations", op["id"]))
        self.mod.exit(True, revoked=[op["id"] for op in tokens])


def get_argument_spec() -> ArgumentSpecMutT:
    """Return the argument spec of the module."""
    return {
        "name": {"type": "str", "required": True},
        "state": {"type": "str", "default": "present", "choices": ["present", "absent"]},
        "restricted": {"type": "bool", "default": False},
        "projects": {"type": "list", "elements": "str"},
        "force": {"type": "bool", "default": False},
    }


def main() -> None:
    """Run the module."""
    mod = LXDModule(get_argument_spec(), extensions=["certificate_token"])
    token = TrustTokenModule(mod)
    if mod.params["state"] == "present":
        mod.run(token.present)
    else:
        mod.run(token.absent)


if __name__ == "__main__":
    main()
