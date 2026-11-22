#!/usr/bin/python
# Copyright (c) 2026, Sean McAvoy
# GNU General Public License v3.0+ (see LICENSES/GPL-3.0-or-later.txt or https://www.gnu.org/licenses/gpl-3.0.txt)
# SPDX-License-Identifier: GPL-3.0-or-later

from __future__ import annotations

DOCUMENTATION = r"""
module: lxd_cluster
short_description: Form an LXD cluster, join it, or remove a member
version_added: "0.1.0"
description:
  - With O(state=enabled), make the server the first member of a new cluster.
  - With O(state=joined), make the server join a cluster with a join token.
  - With O(state=absent), remove a member from the cluster that the module connects to.
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
  state:
    description:
      - The wanted state.
    type: str
    choices:
      enabled: The server is a cluster member. The module enables clustering on a standalone server.
      joined: The server is a cluster member. The module joins a standalone server to the cluster of O(cluster_token).
      absent: O(member) is not in the cluster.
    default: enabled
  server_name:
    description:
      - The member name of the server. It cannot start with C(@) or be C(none).
      - Required with O(state=enabled) and O(state=joined).
    type: str
  cluster_token:
    description:
      - The join token from M(smcavoy.lxd.lxd_cluster_join_token). This is a secret.
      - Required with O(state=joined).
    type: str
  server_address:
    description:
      - The address of the joining server, for example V(10.0.0.12:8443).
      - Required with O(state=joined).
    type: str
  join_config:
    description:
      - Values for the member-specific keys that the cluster needs from a new member, for example the C(source) of a storage pool.
      - Each item has the keys C(entity), C(name), C(key), and C(value), as in the C(member_config) of C(GET /1.0/cluster).
      - The module converts each C(value) to a string. V(true) becomes C("true"), V(false) becomes C("false"), and V(6) becomes C("6").
    type: list
    elements: dict
  member:
    description:
      - The member to remove. Required with O(state=absent).
    type: str
  force:
    description:
      - With O(state=absent), remove a member that does not answer.
    type: bool
    default: false
notes:
  - With O(state=enabled), LXD needs C(cluster.https_address), or a C(core.https_address) that is not a wildcard. Set it with M(smcavoy.lxd.lxd_server_config).
  - With O(state=joined), the module reads the certificate of the cluster from the addresses in the token.
    It joins only when the SHA-256 fingerprint of that certificate matches the token.
  - With O(state=enabled), LXD makes a new cluster certificate, and the server presents it from then on.
    The module reads it on the connection that still trusts the old certificate, and returns it as RV(certificate).
    Later tasks need it as O(server_cert).
  - A joined server presents the certificate of the cluster too. That certificate names the first member, not the joined server.
    So a later task with the URL of the joined server fails the host name check of O(server_cert).
    Give such a task O(server_fingerprint) with the fingerprint of the cluster certificate instead.
  - The module does not rename members, and it does not check that a clustered server is in the cluster of the token.
seealso:
  - module: smcavoy.lxd.lxd_cluster_join_token
  - module: smcavoy.lxd.lxd_cluster_member
  - module: smcavoy.lxd.lxd_server_config
"""

EXAMPLES = r"""
- name: Make node1 the first member
  smcavoy.lxd.lxd_cluster:
    url: https://node1:8443
    server_name: node1

- name: Get a join token for node2
  smcavoy.lxd.lxd_cluster_join_token:
    url: https://node1:8443
    name: node2
  register: join
  no_log: true

- name: Join node2
  smcavoy.lxd.lxd_cluster:
    url: https://node2:8443
    state: joined
    server_name: node2
    server_address: 10.0.0.12:8443
    cluster_token: "{{ join.token }}"
  no_log: true

- name: Remove node3 from the cluster
  smcavoy.lxd.lxd_cluster:
    url: https://node1:8443
    state: absent
    member: node3
"""

RETURN = r"""
certificate:
  description:
    - The PEM certificate that the server presents after the task. After O(state=enabled) or O(state=joined), it is the cluster certificate.
  returned: when O(state=enabled) or O(state=joined), and not in check mode before a change
  type: str
  sample: "-----BEGIN CERTIFICATE-----\nMIIB...\n-----END CERTIFICATE-----\n"
cluster:
  description:
    - The cluster state of the server after the change, from C(GET /1.0/cluster).
    - In check mode, the predicted state.
  returned: always
  type: dict
  sample:
    server_name: node1
    enabled: true
    member_config: []
"""

import base64
import binascii
import hashlib
import http.client
import json
import socket
import ssl
import typing as t
from urllib.parse import urlsplit

from ansible_collections.smcavoy.lxd.plugins.module_utils._client import LXDClientError, api_path
from ansible_collections.smcavoy.lxd.plugins.module_utils._config import to_lxd_value
from ansible_collections.smcavoy.lxd.plugins.module_utils._module import LXDModule

if t.TYPE_CHECKING:  # pragma: no cover
    from ansible_collections.smcavoy.lxd.plugins.module_utils._typing import ArgumentSpecMutT


def decode_token(token: str) -> dict[str, t.Any] | None:
    """Return the fields of a join token, or None when it is not a join token."""
    text = token.strip()
    try:
        data = json.loads(base64.b64decode(text + "=" * (-len(text) % 4)))
    except (binascii.Error, ValueError, UnicodeDecodeError):
        return None
    if not isinstance(data, dict) or not data.get("fingerprint") or not data.get("addresses") or not data.get("secret"):
        return None
    return data


def fetch_certificate(address: str, fingerprint: str, timeout: int) -> str | None:
    """Return the PEM certificate at an address when its SHA-256 fingerprint matches, else None."""
    try:
        parts = urlsplit("//" + address)
        host, port = parts.hostname or "", parts.port or 8443
    except ValueError:
        # A bare IPv6 address has no brackets and no port.
        host, port = address, 8443
    context = ssl.create_default_context()
    context.check_hostname = False
    context.verify_mode = ssl.CERT_NONE
    try:
        with socket.create_connection((host, port), timeout=timeout) as raw:
            with context.wrap_socket(raw, server_hostname=host) as tls:
                der = tls.getpeercert(binary_form=True)
    except (OSError, ValueError):
        return None
    if not der or hashlib.sha256(der).hexdigest() != fingerprint.lower():
        return None
    return ssl.DER_cert_to_PEM_cert(der)


def join_member_config(items: list[dict[str, t.Any]] | None) -> list[dict[str, str]]:
    """Return O(join_config) in the form of the join request. Each value goes in its LXD string form, so V(false) is C("false")."""
    result = []
    for item in items or []:
        entry = {key: str(item.get(key) or "") for key in ("entity", "name", "key")}
        entry["value"] = to_lxd_value(f"join_config {entry['key']}", item.get("value")) or ""
        result.append(entry)
    return result


class ClusterModule:
    """Form a cluster, join one, or remove a member."""

    def __init__(self, mod: LXDModule) -> None:
        self.mod = mod

    def read(self) -> dict[str, t.Any]:
        """Return the cluster state of the server."""
        cluster, _etag = self.mod.client.get("/1.0/cluster")
        return cluster or {}

    def check_name(self, current: dict[str, t.Any]) -> bool:
        """Return whether the server is a member already. Fail when it has another name."""
        if not current.get("enabled"):
            return False
        name = self.mod.params["server_name"]
        if current.get("server_name") != name:
            self.mod.fail(f"the server is a cluster member with the name {current.get('server_name')}, not {name}. The module does not rename members.")
        return True

    def enabled(self) -> None:
        """Make the server the first member of a new cluster."""
        params = self.mod.params
        current = self.read()
        before = {"enabled": bool(current.get("enabled")), "server_name": current.get("server_name") or ""}
        after = {"enabled": True, "server_name": params["server_name"]}
        if self.check_name(current):
            self.mod.exit(False, before=before, after=after, cluster=current, certificate=self.certificate())
        self.mod.write("PUT", "/1.0/cluster", body={"server_name": params["server_name"], "enabled": True})
        if self.mod.check_mode:
            self.mod.exit(True, before=before, after=after, cluster=dict(current, **after))
        # LXD makes a new cluster certificate. The open connection still trusts the old one, so it reads the new one safely.
        try:
            cluster = self.read()
            certificate = str((self.mod.client.refresh_server().get("environment") or {}).get("certificate") or "")
        except LXDClientError as exc:
            self.mod.fail(
                f"clustering is enabled, but the module cannot read the new cluster certificate: {exc.message}. "
                "Read it on the server in /var/snap/lxd/common/lxd/cluster.crt."
            )
        self.mod.exit(True, before=before, after=after, cluster=cluster, certificate=certificate)

    def certificate(self) -> str:
        """Return the certificate that the server presents now."""
        return str((self.mod.client.server().get("environment") or {}).get("certificate") or "")

    def joined(self) -> None:
        """Join the server to the cluster of the token."""
        params = self.mod.params
        current = self.read()
        before = {"enabled": bool(current.get("enabled")), "server_name": current.get("server_name") or ""}
        after = {"enabled": True, "server_name": params["server_name"]}
        if self.check_name(current):
            self.mod.exit(False, before=before, after=after, cluster=current, certificate=self.certificate())
        token = decode_token(params["cluster_token"])
        if token is None:
            self.mod.fail("cluster_token is not a valid join token")
        if self.mod.check_mode:
            # Check mode sends no request, so it does not read the certificate from the token addresses either.
            self.mod.exit(True, before=before, after=after, cluster=dict(current, **after))
        address, pem = "", None
        for candidate in token["addresses"]:
            pem = fetch_certificate(str(candidate), str(token["fingerprint"]), min(self.mod.client.timeout, 30))
            if pem:
                address = str(candidate)
                break
        if not pem:
            self.mod.fail("no address in cluster_token answers with the certificate of the token")
        body = {
            "server_name": params["server_name"],
            "enabled": True,
            "server_address": params["server_address"],
            "cluster_address": address,
            "cluster_certificate": pem,
            "cluster_token": params["cluster_token"],
            "member_config": join_member_config(params["join_config"]),
        }
        try:
            self.mod.client.write("PUT", "/1.0/cluster", body=body)
        except LXDClientError as exc:
            # A failed operation or an HTTP error is a real failure. Only a broken connection needs the check below.
            if exc.status is not None or exc.operation is not None:
                raise
            # The server changes its certificate when it joins. The wait for the operation can then break.
            self.mod.warn(f"The connection broke during the join: {exc.message}. The module checks the result.")
        self.mod.client.close()
        cluster = self.read_with_cluster_cert(pem)
        if not cluster.get("enabled"):
            self.mod.fail("the server did not join the cluster")
        self.mod.exit(True, before=before, after=after, cluster=cluster, certificate=pem)

    def read_with_cluster_cert(self, pem: str) -> dict[str, t.Any]:
        """Read C(GET /1.0/cluster) on a new connection that trusts only the cluster certificate.

        The cluster certificate names the first member, not this server. So this connection checks the certificate, but not the host name.
        """
        if self.mod.client.unix_socket:
            # The unix socket has no certificate, so the normal client still works.
            return self.read()
        url = urlsplit(self.mod.client.base)
        context = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
        context.check_hostname = False
        context.verify_mode = ssl.CERT_REQUIRED
        context.load_verify_locations(cadata=pem)
        params = self.mod.params
        if params["client_cert"]:
            context.load_cert_chain(params["client_cert"], params["client_key"])
        conn = http.client.HTTPSConnection(url.hostname or "", url.port or 8443, timeout=min(self.mod.client.timeout, 60), context=context)
        try:
            conn.request("GET", "/1.0/cluster", headers=dict(self.mod.client.headers))
            response = conn.getresponse()
            reply = json.loads(response.read() or b"{}")
            if response.status >= 400:
                self.mod.fail(f"cannot read the cluster state after the join: {reply.get('error') or response.status}")
        except (OSError, ValueError, http.client.HTTPException) as exc:
            self.mod.fail(f"cannot read the cluster state after the join: {exc}")
        finally:
            conn.close()
        return reply.get("metadata") or {}

    def absent(self) -> None:
        """Remove a member from the cluster."""
        params = self.mod.params
        path = api_path("cluster", "members", params["member"])
        member, _etag = self.mod.client.get_or_none(path)
        if member is None:
            self.mod.exit(False, before={}, after={}, cluster=self.read())
        query = {"force": 1} if params["force"] else None
        self.mod.write("DELETE", path, query=query)
        before = {"member": params["member"]}
        self.mod.exit(True, before=before, after={}, cluster=self.read())


def get_argument_spec() -> ArgumentSpecMutT:
    """Return the argument spec of the module."""
    return {
        "state": {"type": "str", "default": "enabled", "choices": ["enabled", "joined", "absent"]},
        "server_name": {"type": "str"},
        "cluster_token": {"type": "str", "no_log": True},
        "server_address": {"type": "str"},
        "join_config": {"type": "list", "elements": "dict"},
        "member": {"type": "str"},
        "force": {"type": "bool", "default": False},
    }


def main() -> None:
    """Run the module."""
    mod = LXDModule(
        get_argument_spec(),
        extensions=["clustering"],
        required_if=[
            ["state", "enabled", ["server_name"]],
            ["state", "joined", ["server_name", "cluster_token", "server_address"]],
            ["state", "absent", ["member"]],
        ],
    )
    cluster = ClusterModule(mod)
    state = mod.params["state"]
    if state == "joined":
        missing = mod.client.missing_extensions(["clustering_join_token", "explicit_trust_token"])
        if missing:
            mod.fail(f"LXD server lacks the API extensions {', '.join(missing)}, which a join with a token needs")
    mod.run({"enabled": cluster.enabled, "joined": cluster.joined, "absent": cluster.absent}[state])


if __name__ == "__main__":
    main()
