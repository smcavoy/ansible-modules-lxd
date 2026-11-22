#!/usr/bin/python
# Copyright (c) 2026, Sean McAvoy
# GNU General Public License v3.0+ (see LICENSES/GPL-3.0-or-later.txt or https://www.gnu.org/licenses/gpl-3.0.txt)
# SPDX-License-Identifier: GPL-3.0-or-later

from __future__ import annotations

DOCUMENTATION = r"""
module: lxd_server_info
short_description: Read LXD server information
version_added: "0.1.0"
description:
  - Read the LXD server info, the hardware resources, the server state, and the config key metadata.
author:
  - Sean McAvoy (@smcavoy)
extends_documentation_fragment:
  - smcavoy.lxd._attributes
  - smcavoy.lxd._attributes.info_module
  - smcavoy.lxd._attributes.action_group
  - smcavoy.lxd._connection
options:
  gather:
    description:
      - The parts to read.
    type: list
    elements: str
    choices:
      server: The server info from C(GET /1.0), with C(config), C(api_extensions), and C(environment).
      resources: The hardware from C(GET /1.0/resources).
      state: The server state from C(GET /1.0/state).
      metadata: The config key metadata from C(GET /1.0/metadata/configuration).
    default: [server]
  target:
    description:
      - On a cluster, read the resources and the state of this member.
    type: str
notes:
  - The module masks the values of C(loki.auth.password), C(oidc.client.secret), and C(network.ovn.client_key) in the server config.
  - The module masks the password in the URL of C(core.proxy_http) and C(core.proxy_https) in the server config, for example
    C(http://user:********@proxy:3128). The user, the host, and the port stay.
seealso:
  - module: smcavoy.lxd.lxd_server_config
"""

EXAMPLES = r"""
- name: Read the server version and the hardware
  smcavoy.lxd.lxd_server_info:
    gather:
      - server
      - resources
  register: result

- name: Print the version
  ansible.builtin.debug:
    msg: "{{ result.server.environment.server_version }}"
"""

RETURN = r"""
server:
  description:
    - The server info. Secret config values are masked.
  returned: when O(gather) holds V(server)
  type: dict
  sample:
    api_version: "1.0"
    auth: trusted
    environment:
      server_version: 6.10.1
    config:
      core.https_address: "[::]:8443"
resources:
  description:
    - The hardware resources.
  returned: when O(gather) holds V(resources)
  type: dict
  sample:
    cpu:
      total: 2
    memory:
      total: 3221225472
state:
  description:
    - The server state.
  returned: when O(gather) holds V(state)
  type: dict
metadata:
  description:
    - The config key metadata, with the keys of each entity and their scope.
  returned: when O(gather) holds V(metadata)
  type: dict
"""

import typing as t

from ansible_collections.smcavoy.lxd.plugins.module_utils._config import URL_SECRET_KEYS, mask_url_password
from ansible_collections.smcavoy.lxd.plugins.module_utils._module import LXDModule

if t.TYPE_CHECKING:  # pragma: no cover
    from ansible_collections.smcavoy.lxd.plugins.module_utils._typing import ArgumentSpecMutT

SECRET_KEYS = ("loki.auth.password", "oidc.client.secret", "network.ovn.client_key")
PARTS = {
    "resources": ("/1.0/resources", None),
    "state": ("/1.0/state", "server_state"),
    "metadata": ("/1.0/metadata/configuration", "metadata_configuration"),
}


def get_argument_spec() -> ArgumentSpecMutT:
    """Return the argument spec of the module."""
    return {
        "gather": {"type": "list", "elements": "str", "default": ["server"], "choices": ["server", "resources", "state", "metadata"]},
        "target": {"type": "str"},
    }


def main() -> None:
    """Run the module."""
    mod = LXDModule(get_argument_spec())

    def read() -> None:
        params = mod.params
        result: dict[str, t.Any] = {}
        query = {"target": params["target"]} if params["target"] else None
        if "server" in params["gather"]:
            server, _etag = mod.client.get("/1.0", query)
            server = dict(server or {})
            config = dict(server.get("config") or {})
            for key in SECRET_KEYS:
                if config.get(key):
                    config[key] = "********"
            for key in URL_SECRET_KEYS:
                if key in config:
                    config[key] = mask_url_password(config[key])
            server["config"] = config
            result["server"] = server
        for part, (path, extension) in PARTS.items():
            if part not in params["gather"]:
                continue
            if extension and mod.client.missing_extensions([extension]):
                mod.fail(f"LXD server lacks the API extension {extension}, which gather={part} needs")
            value, _etag = mod.client.get(path, query if part != "metadata" else None)
            result[part] = value
        mod.exit(False, **result)

    mod.run(read)


if __name__ == "__main__":
    main()
