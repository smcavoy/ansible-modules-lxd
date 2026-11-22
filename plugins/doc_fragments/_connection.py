# Copyright (c) 2026, Sean McAvoy
# GNU General Public License v3.0+ (see LICENSES/GPL-3.0-or-later.txt or https://www.gnu.org/licenses/gpl-3.0.txt)
# SPDX-License-Identifier: GPL-3.0-or-later

# Note that this doc fragment is **PRIVATE** to the collection. It can have breaking changes at any time.
# Do not use this from other collections or standalone plugins/modules!

from __future__ import annotations


class ModuleDocFragment:
    DOCUMENTATION = r"""
options:
  url:
    description:
      - The LXD API endpoint.
      - Use C(unix:/path/to/socket) for a local socket, or C(https://host:8443) for the network API.
      - If not set, the module uses the first socket that exists, C(/var/snap/lxd/common/lxd/unix.socket) or C(/var/lib/lxd/unix.socket).
      - If not set, the module also reads E(LXD_URL).
    type: str
  client_cert:
    description:
      - The path to a PEM client certificate for TLS client authentication.
      - If not set, the module reads E(LXD_CLIENT_CERT).
      - The module never reads the C(lxc) client config.
    type: path
  client_key:
    description:
      - The path to the PEM key of O(client_cert).
      - If not set, the module reads E(LXD_CLIENT_KEY).
    type: path
  bearer_token:
    description:
      - A bearer token for an LXD bearer identity.
      - If not set, the module reads E(LXD_BEARER_TOKEN).
      - Mutually exclusive with O(client_cert).
    type: str
  server_cert:
    description:
      - The path to the server certificate or its CA certificate, to verify the server.
      - The module still checks the host name. LXD server certificates hold the host name, not the IP address, so use the host name in O(url).
      - If not set, the module reads E(LXD_SERVER_CERT).
      - The module ignores it when O(server_fingerprint) is set.
    type: path
  server_fingerprint:
    description:
      - The SHA-256 fingerprint of the server certificate, as 64 hex characters. Colons are allowed.
      - The module then trusts exactly that certificate. It does not check the chain or the host name, as C(lxc) does for a remote.
      - Use it for a cluster member that presents the cluster certificate, which names another member,
        or for a server that you reach by its IP address.
      - The module checks the fingerprint before it sends a request. It then ignores O(server_cert) and O(validate_certs),
        so a task can set a fingerprint on top of a O(server_cert) in C(module_defaults).
      - LXD shows the fingerprint as C(environment.certificate_fingerprint) in M(smcavoy.lxd.lxd_server_info).
      - If not set, the module reads E(LXD_SERVER_FINGERPRINT).
    type: str
  validate_certs:
    description:
      - Verify the TLS certificate of the server.
      - If not set, the module reads E(LXD_VALIDATE_CERTS).
    type: bool
    default: true
  trust_token:
    description:
      - A trust token from C(lxc config trust add).
      - If the server does not trust the client yet, the module uses the token once to add O(client_cert).
    type: str
  timeout:
    description:
      - Seconds for one request, and for the whole wait on one operation, for example a VM create or a backup.
      - The module waits in slices of up to 60 seconds and keeps waiting through short connection breaks.
      - When the time runs out, the task fails and the operation can still run on the server.
      - If not set, the module reads E(LXD_TIMEOUT).
    type: int
    default: 120
requirements:
  - LXD 6.10.1 or newer.
"""
