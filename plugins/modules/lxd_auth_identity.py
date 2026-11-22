#!/usr/bin/python
# Copyright (c) 2026, Sean McAvoy
# GNU General Public License v3.0+ (see LICENSES/GPL-3.0-or-later.txt or https://www.gnu.org/licenses/gpl-3.0.txt)
# SPDX-License-Identifier: GPL-3.0-or-later

from __future__ import annotations

DOCUMENTATION = r"""
module: lxd_auth_identity
short_description: Manage LXD TLS, bearer, and OIDC identities
version_added: "0.1.0"
description:
  - Create, update, and delete identities, and set their groups.
  - OIDC identities exist only after a login. The module can set their groups or delete them, but not create them.
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
  type:
    description:
      - The authentication method of the identity.
    type: str
    required: true
    choices: ["tls", "bearer", "oidc"]
  name:
    description:
      - The identity name. For V(oidc), the email address or the identifier.
    type: str
    required: true
  state:
    description:
      - The wanted state of the identity.
    type: str
    choices:
      present: The identity exists.
      absent: The identity does not exist.
    default: present
  groups:
    description:
      - The authorization groups of the identity. The module compares them as a set.
      - If not set, the module does not manage the groups.
    type: list
    elements: str
  certificate:
    description:
      - For O(type=tls), the PEM client certificate.
      - The module compares it by its SHA-256 fingerprint.
      - Mutually exclusive with O(pending).
    type: str
  pending:
    description:
      - For O(type=tls), create a pending identity and return a join token.
      - The module uses it only when it creates the identity.
      - Mutually exclusive with O(certificate).
    type: bool
    default: false
  bearer_type:
    description:
      - For O(type=bearer), the kind of bearer identity.
      - The module uses it only when it creates the identity.
    type: str
    choices:
      client: A client of the main API.
      devlxd: A client of the guest API C(/dev/lxd).
    default: client
seealso:
  - module: smcavoy.lxd.lxd_auth_group
"""

EXAMPLES = r"""
- name: Trust a client certificate and put it in a group
  smcavoy.lxd.lxd_auth_identity:
    type: tls
    name: alice
    certificate: "{{ lookup('ansible.builtin.file', 'alice.crt') }}"
    groups:
      - web-operators

- name: Create a pending TLS identity and keep the join token
  smcavoy.lxd.lxd_auth_identity:
    type: tls
    name: bob
    pending: true
  register: bob_identity

- name: Remove the identity
  smcavoy.lxd.lxd_auth_identity:
    type: tls
    name: alice
    state: absent
"""

RETURN = r"""
identity:
  description:
    - The identity after the change, as LXD returns it.
    - In check mode, the predicted identity.
    - V(null) after a delete.
  returned: always
  type: dict
  sample:
    type: Client certificate
    authentication_method: tls
    id: 0ab1c2d3e4f5
    name: alice
    groups:
      - web-operators
join_token:
  description:
    - The join token of a new pending TLS identity. Only on the run that creates it.
  returned: when O(pending=true) creates the identity
  type: str
  sample: eyJjbGllbnRfbmFtZSI6...
"""

import base64
import hashlib
import json
import ssl
import typing as t

from ansible_collections.smcavoy.lxd.plugins.module_utils._client import api_path
from ansible_collections.smcavoy.lxd.plugins.module_utils._module import LXDModule
from ansible_collections.smcavoy.lxd.plugins.module_utils._resource import Plan, warn_create_only

if t.TYPE_CHECKING:  # pragma: no cover
    from ansible_collections.smcavoy.lxd.plugins.module_utils._typing import ArgumentSpecMutT

FIELDS = ("groups", "fingerprint")
BEARER_TYPES = {"client": "Client token bearer", "devlxd": "DevLXD token bearer"}


def fingerprint(pem: str | None) -> str | None:
    """Return the SHA-256 fingerprint of a PEM certificate."""
    if not pem:
        return None
    try:
        der = ssl.PEM_cert_to_DER_cert(pem.strip() + "\n")
    except ValueError as exc:
        raise ValueError("certificate is not a valid PEM certificate") from exc
    return hashlib.sha256(der).hexdigest()


def encode_token(token: t.Any) -> str | None:
    """Encode a token object as LXD does: Base64 of its JSON."""
    if not token:
        return None
    if isinstance(token, str):
        return token
    return base64.b64encode(json.dumps(token, separators=(",", ":")).encode("utf-8")).decode("ascii")


class IdentityModule:
    """Manage one identity."""

    def __init__(self, mod: LXDModule) -> None:
        self.mod = mod
        self.kind: str = mod.params["type"]
        self.name: str = mod.params["name"]
        self.path = api_path("auth", "identities", self.kind, self.name)
        try:
            self.wanted_fingerprint = fingerprint(mod.params["certificate"])
        except ValueError as exc:
            mod.fail(str(exc))

    def read(self) -> tuple[dict[str, t.Any] | None, str | None]:
        """Read the identity."""
        identity, etag = self.mod.client.get_or_none(self.path)
        if identity is not None:
            identity = dict(identity, fingerprint=fingerprint(identity.get("tls_certificate")))
        return identity, etag

    def present(self) -> None:
        """Make sure that the identity exists with the wanted settings."""
        params = self.mod.params
        current, etag = self.read()
        if current is None:
            self.create()
        warn_create_only(self.mod, current, {"pending": False if not params["pending"] else None})
        plan = Plan(dict(current, groups=sorted(current.get("groups") or [])), FIELDS)
        if params["groups"] is not None:
            plan.set("groups", sorted(set(params["groups"])))
        if self.wanted_fingerprint and self.kind == "tls":
            plan.set("fingerprint", self.wanted_fingerprint)
        if not plan.is_changed:
            self.mod.exit(False, before=plan.before(), after=plan.after(), identity=self.clean(current))
        body: dict[str, t.Any] = {"groups": plan.new.get("groups") or []}
        if "fingerprint" in plan.changed:
            body["tls_certificate"] = params["certificate"]
        self.mod.write("PUT", self.path, body=body, etag=etag)
        self.mod.exit(True, before=plan.before(), after=plan.after(), identity=self.final(plan.new))

    def create(self) -> t.NoReturn:
        """Create the identity."""
        params = self.mod.params
        groups = sorted(set(params["groups"] or []))
        token: t.Any = None
        if self.kind == "oidc":
            self.mod.fail("OIDC identities exist only after a login")
        if self.kind == "tls":
            if not params["certificate"] and not params["pending"]:
                self.mod.fail("certificate or pending is required to create a TLS identity")
            body: dict[str, t.Any] = {"name": self.name, "groups": groups}
            if params["pending"]:
                body["token"] = True
            else:
                body["certificate"] = params["certificate"]
            token = self.mod.write("POST", api_path("auth", "identities", "tls"), body=body)
        else:
            body = {"name": self.name, "type": BEARER_TYPES[params["bearer_type"]], "groups": groups}
            self.mod.write("POST", api_path("auth", "identities", "bearer"), body=body)
        after = {"groups": groups, "fingerprint": self.wanted_fingerprint}
        predicted = {"name": self.name, "authentication_method": self.kind, "groups": groups}
        result: dict[str, t.Any] = {"identity": self.final(predicted)}
        if params["pending"] and self.kind == "tls" and not self.mod.check_mode:
            result["join_token"] = encode_token(token)
        self.mod.exit(True, before={}, after=after, **result)

    def absent(self) -> None:
        """Make sure that the identity does not exist."""
        current, _etag = self.read()
        if current is None:
            self.mod.exit(False, before={}, after={}, identity=None)
        self.mod.write("DELETE", self.path)
        before = {"groups": sorted(current.get("groups") or []), "fingerprint": current.get("fingerprint")}
        self.mod.exit(True, before=before, after={}, identity=None)

    @staticmethod
    def clean(identity: dict[str, t.Any]) -> dict[str, t.Any]:
        """Remove the helper key C(fingerprint) when the server sent no certificate."""
        result = dict(identity)
        if result.get("fingerprint") is None:
            result.pop("fingerprint", None)
        return result

    def final(self, predicted: dict[str, t.Any]) -> dict[str, t.Any]:
        """Return the identity from the server, or the prediction in check mode."""
        if self.mod.check_mode:
            return predicted
        identity, _etag = self.read()
        return self.clean(identity or predicted)


def get_argument_spec() -> ArgumentSpecMutT:
    """Return the argument spec of the module."""
    return {
        "type": {"type": "str", "required": True, "choices": ["tls", "bearer", "oidc"]},
        "name": {"type": "str", "required": True},
        "state": {"type": "str", "default": "present", "choices": ["present", "absent"]},
        "groups": {"type": "list", "elements": "str"},
        "certificate": {"type": "str"},
        "pending": {"type": "bool", "default": False},
        "bearer_type": {"type": "str", "default": "client", "choices": ["client", "devlxd"]},
    }


def main() -> None:
    """Run the module."""
    mod = LXDModule(get_argument_spec(), mutually_exclusive=[["certificate", "pending"]])
    extensions = {"tls": ["access_management_tls"], "bearer": ["auth_bearer"], "oidc": ["access_management"]}
    missing = mod.client.missing_extensions(extensions[mod.params["type"]])
    if missing:
        mod.fail(f"LXD server lacks the API extensions: {', '.join(missing)}")
    identity = IdentityModule(mod)
    if mod.params["state"] == "present":
        mod.run(identity.present)
    else:
        mod.run(identity.absent)


if __name__ == "__main__":
    main()
