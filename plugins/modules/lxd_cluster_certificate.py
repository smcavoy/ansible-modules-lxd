#!/usr/bin/python
# Copyright (c) 2026, Sean McAvoy
# GNU General Public License v3.0+ (see LICENSES/GPL-3.0-or-later.txt or https://www.gnu.org/licenses/gpl-3.0.txt)
# SPDX-License-Identifier: GPL-3.0-or-later

from __future__ import annotations

DOCUMENTATION = r"""
module: lxd_cluster_certificate
short_description: Replace the certificate of an LXD cluster
version_added: "0.1.0"
description:
  - Replace the server certificate and key of a cluster. LXD sends them to every member.
  - The module compares the SHA-256 fingerprint of O(certificate) with the fingerprint of the server.
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
      - The new certificate, in PEM format. It can be a chain, with the certificate of the server first.
    type: str
    required: true
  key:
    description:
      - The private key of O(certificate), in PEM format, without a passphrase. This is a secret.
    type: str
    required: true
notes:
  - After the change, a client that pins the old certificate with O(server_cert) fails. Give the next tasks the new certificate.
  - The module checks that the key matches the certificate before it sends them.
seealso:
  - module: smcavoy.lxd.lxd_server_info
"""

EXAMPLES = r"""
- name: Install the certificate of the cluster
  smcavoy.lxd.lxd_cluster_certificate:
    certificate: "{{ lookup('ansible.builtin.file', 'cluster.crt') }}"
    key: "{{ lookup('ansible.builtin.file', 'cluster.key') }}"
  no_log: true
"""

RETURN = r"""
fingerprint:
  description:
    - The SHA-256 fingerprint of the certificate of the server after the change.
  returned: always
  type: str
  sample: 7b88d1d5f1a0c9e8b7a6f5e4d3c2b1a09f8e7d6c5b4a39281706f5e4d3c2b1a0
previous_fingerprint:
  description:
    - The fingerprint before the change.
  returned: always
  type: str
  sample: fdc8a7b6c5d4e3f2a1b0c9d8e7f6a5b4c3d2e1f0a9b8c7d6e5f4a3b2c1d0e9f8
"""

import hashlib
import os
import ssl
import tempfile
import typing as t

from ansible_collections.smcavoy.lxd.plugins.module_utils._module import LXDModule

if t.TYPE_CHECKING:  # pragma: no cover
    from ansible_collections.smcavoy.lxd.plugins.module_utils._typing import ArgumentSpecMutT


END_CERT = "-----END CERTIFICATE-----"


def fingerprint_of(pem: str) -> str:
    """Return the SHA-256 fingerprint of a PEM certificate. In a chain, the first certificate is the one of the server."""
    first = pem.strip().split(END_CERT, 1)[0] + END_CERT
    return hashlib.sha256(ssl.PEM_cert_to_DER_cert(first + "\n")).hexdigest()


def key_matches(certificate: str, key: str) -> bool:
    """Return whether the key belongs to the certificate. OpenSSL checks it when it loads the pair."""
    folder = tempfile.mkdtemp(prefix="lxd-cert-")
    cert_path = os.path.join(folder, "cert.pem")
    key_path = os.path.join(folder, "key.pem")
    try:
        with open(cert_path, "w") as handle:
            handle.write(certificate.strip() + "\n")
        with os.fdopen(os.open(key_path, os.O_WRONLY | os.O_CREAT, 0o600), "w") as handle:
            handle.write(key.strip() + "\n")
        context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
        context.load_cert_chain(cert_path, key_path)
        return True
    except ssl.SSLError:
        return False
    finally:
        for path in (cert_path, key_path):
            if os.path.exists(path):
                os.unlink(path)
        os.rmdir(folder)


def get_argument_spec() -> ArgumentSpecMutT:
    """Return the argument spec of the module."""
    return {
        "certificate": {"type": "str", "required": True},
        "key": {"type": "str", "required": True, "no_log": True},
    }


def main() -> None:
    """Run the module."""
    mod = LXDModule(get_argument_spec(), extensions=["clustering_update_cert"])

    def run() -> None:
        params = mod.params
        try:
            wanted = fingerprint_of(params["certificate"])
        except ValueError:
            mod.fail("certificate is not a PEM certificate")
        if "ENCRYPTED" in params["key"]:
            mod.fail("key is encrypted. Give the key without a passphrase.")
        if not key_matches(params["certificate"], params["key"]):
            mod.fail("key does not match certificate")
        previous = str((mod.client.server().get("environment") or {}).get("certificate_fingerprint") or "")
        before = {"fingerprint": previous}
        after = {"fingerprint": wanted}
        if previous == wanted:
            mod.exit(False, before=before, after=after, fingerprint=previous, previous_fingerprint=previous)
        mod.write(
            "PUT",
            "/1.0/cluster/certificate",
            body={"cluster_certificate": params["certificate"], "cluster_certificate_key": params["key"]},
        )
        mod.exit(True, before=before, after=after, fingerprint=wanted, previous_fingerprint=previous)

    mod.run(run)


if __name__ == "__main__":
    main()
