#!/usr/bin/python
# Copyright (c) 2026, Sean McAvoy
# GNU General Public License v3.0+ (see LICENSES/GPL-3.0-or-later.txt or https://www.gnu.org/licenses/gpl-3.0.txt)
# SPDX-License-Identifier: GPL-3.0-or-later

from __future__ import annotations

DOCUMENTATION = r"""
module: lxd_trust_certificate
short_description: Manage certificates in the LXD trust store
version_added: "0.1.0"
description:
  - Add, update, and remove client certificates in the legacy trust store of LXD, with project restrictions.
  - For new setups, M(smcavoy.lxd.lxd_auth_identity) with authorization groups gives finer control.
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
  certificate:
    description:
      - The PEM certificate. Required to add it.
      - The module finds the entry by the SHA-256 fingerprint of the certificate.
    type: str
  fingerprint:
    description:
      - The fingerprint of an existing entry. Use it to update or remove an entry without its certificate.
    type: str
  name:
    description:
      - The entry name. It does not identify the entry, because names are not unique.
      - If not set, the module does not manage the name. A new entry then gets an empty name.
    type: str
  state:
    description:
      - The wanted state of the entry.
    type: str
    choices:
      present: The certificate is trusted.
      absent: The certificate is not trusted.
    default: present
  type:
    description:
      - The certificate type.
    type: str
    choices: ["client", "metrics"]
    default: client
  restricted:
    description:
      - Limit the certificate to O(projects).
    type: bool
    default: false
  projects:
    description:
      - The projects of a restricted certificate. The module compares them as a set.
    type: list
    elements: str
notes:
  - The module refuses to remove the certificate that the task connects with. That would lock the task out.
seealso:
  - module: smcavoy.lxd.lxd_trust_token
  - module: smcavoy.lxd.lxd_auth_identity
"""

EXAMPLES = r"""
- name: Trust a CI certificate for one project
  smcavoy.lxd.lxd_trust_certificate:
    name: ci
    certificate: "{{ lookup('ansible.builtin.file', 'ci.crt') }}"
    restricted: true
    projects:
      - ci

- name: Remove an entry by fingerprint
  smcavoy.lxd.lxd_trust_certificate:
    fingerprint: 6b0e06bd9f3ee54252fd857a681401b0eea2695891a336b0e4ca180681144159
    state: absent
"""

RETURN = r"""
certificate:
  description:
    - The entry after the change, as LXD returns it.
    - In check mode, the predicted entry.
    - V(null) after a delete.
  returned: always
  type: dict
  sample:
    name: ci
    type: client
    restricted: true
    projects:
      - ci
    fingerprint: 6b0e06bd9f3ee54252fd857a681401b0eea2695891a336b0e4ca180681144159
"""

import hashlib
import ssl
import typing as t

from ansible_collections.smcavoy.lxd.plugins.module_utils._client import api_path
from ansible_collections.smcavoy.lxd.plugins.module_utils._module import LXDModule

if t.TYPE_CHECKING:  # pragma: no cover
    from ansible_collections.smcavoy.lxd.plugins.module_utils._typing import ArgumentSpecMutT


def pem_fingerprint(pem: str) -> str:
    """Return the SHA-256 fingerprint of a PEM certificate."""
    return hashlib.sha256(ssl.PEM_cert_to_DER_cert(pem.strip() + "\n")).hexdigest()


def pem_body(pem: str) -> str:
    """Return the base64 body of a PEM certificate, as the API takes it."""
    lines = [line.strip() for line in pem.strip().splitlines()]
    return "".join(line for line in lines if line and not line.startswith("-----"))


class TrustCertificateModule:
    """Manage one entry of the LXD trust store."""

    def __init__(self, mod: LXDModule) -> None:
        self.mod = mod
        params = mod.params
        self.fingerprint = (params["fingerprint"] or "").lower()
        if params["certificate"]:
            try:
                self.fingerprint = pem_fingerprint(params["certificate"])
            except ValueError:
                mod.fail("certificate is not a PEM certificate")
        if not self.fingerprint:
            mod.fail("give certificate or fingerprint")
        if params["projects"] and not params["restricted"]:
            mod.fail("projects needs restricted=true")

    def read(self) -> tuple[dict[str, t.Any] | None, str | None]:
        """Read the entry. A fingerprint prefix works too."""
        return self.mod.client.get_or_none(api_path("certificates", self.fingerprint))

    @staticmethod
    def view(entry: dict[str, t.Any]) -> dict[str, t.Any]:
        """Return the managed fields in a stable form."""
        return {
            "name": entry.get("name") or "",
            "type": entry.get("type") or "client",
            "restricted": bool(entry.get("restricted")),
            "projects": sorted(entry.get("projects") or []),
        }

    def wanted(self, current: dict[str, t.Any]) -> dict[str, t.Any]:
        """Return the managed fields after the task."""
        params = self.mod.params
        new = self.view(current)
        if params["name"] is not None:
            new["name"] = params["name"]
        new["type"] = params["type"]
        new["restricted"] = params["restricted"]
        new["projects"] = sorted(set(params["projects"] or [])) if params["restricted"] else []
        return new

    def own_fingerprint(self) -> str | None:
        """Return the fingerprint of the certificate that the task connects with."""
        path = self.mod.params.get("client_cert")
        if not path:
            return None
        try:
            with open(path, encoding="utf-8") as handle:
                return pem_fingerprint(handle.read())
        except (OSError, ValueError):
            return None

    def present(self) -> None:
        """Make sure that the certificate is trusted with the wanted fields."""
        params = self.mod.params
        current, etag = self.read()
        if current is None:
            if not params["certificate"]:
                self.mod.fail(f"certificate {self.fingerprint[:12]} is not trusted, and the task gives no certificate to add")
            after = self.wanted({})
            body = dict(after, certificate=pem_body(params["certificate"]))
            self.mod.write("POST", "/1.0/certificates", body=body)
            self.mod.exit(True, before={}, after=after, certificate=self.final(dict(after, fingerprint=self.fingerprint)))
        before, after = self.view(current), self.wanted(current)
        if before == after:
            self.mod.exit(False, before=before, after=after, certificate=current)
        self.mod.write("PUT", api_path("certificates", current["fingerprint"]), body=dict(after, certificate=current.get("certificate")), etag=etag)
        self.mod.exit(True, before=before, after=after, certificate=self.final(dict(current, **after)))

    def absent(self) -> None:
        """Make sure that the certificate is not trusted."""
        current, _etag = self.read()
        if current is None:
            self.mod.exit(False, before={}, after={}, certificate=None)
        if current.get("fingerprint") == self.own_fingerprint():
            self.mod.fail("the task connects with this certificate. Removing it would lock the task out")
        self.mod.write("DELETE", api_path("certificates", current["fingerprint"]))
        self.mod.exit(True, before=self.view(current), after={}, certificate=None)

    def final(self, predicted: dict[str, t.Any]) -> dict[str, t.Any]:
        """Return the entry from the server, or the prediction in check mode."""
        if self.mod.check_mode:
            return predicted
        entry, _etag = self.read()
        return entry or predicted


def get_argument_spec() -> ArgumentSpecMutT:
    """Return the argument spec of the module."""
    return {
        "certificate": {"type": "str"},
        "fingerprint": {"type": "str"},
        "name": {"type": "str"},
        "state": {"type": "str", "default": "present", "choices": ["present", "absent"]},
        "type": {"type": "str", "default": "client", "choices": ["client", "metrics"]},
        "restricted": {"type": "bool", "default": False},
        "projects": {"type": "list", "elements": "str"},
    }


def main() -> None:
    """Run the module."""
    mod = LXDModule(get_argument_spec(), extensions=["certificate_update"], required_one_of=[["certificate", "fingerprint"]])
    entry = TrustCertificateModule(mod)
    if mod.params["state"] == "present":
        mod.run(entry.present)
    else:
        mod.run(entry.absent)


if __name__ == "__main__":
    main()
