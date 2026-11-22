#!/usr/bin/python
# Copyright (c) 2026, Sean McAvoy
# GNU General Public License v3.0+ (see LICENSES/GPL-3.0-or-later.txt or https://www.gnu.org/licenses/gpl-3.0.txt)
# SPDX-License-Identifier: GPL-3.0-or-later

from __future__ import annotations

DOCUMENTATION = r"""
module: lxd_instance_log_info
short_description: Read the log files of an LXD instance
version_added: "0.1.0"
description:
  - List the log files of an instance, and read one of them.
author:
  - Sean McAvoy (@smcavoy)
extends_documentation_fragment:
  - smcavoy.lxd._attributes
  - smcavoy.lxd._attributes.info_module
  - smcavoy.lxd._attributes.action_group
  - smcavoy.lxd._connection
  - smcavoy.lxd._project
options:
  instance:
    description:
      - The instance.
    type: str
    required: true
  filename:
    description:
      - One log file to read, for example V(lxc.log), V(lxc.conf), V(qemu.log), or V(qemu.conf).
      - LXD accepts only the names of its own log and config files. Another name fails with the LXD error.
      - A file that does not exist gives an empty content, not a failure.
    type: str
  tail:
    description:
      - Return only the last lines of the file.
    type: int
seealso:
  - module: smcavoy.lxd.lxd_instance_info
"""

EXAMPLES = r"""
- name: Read the last 20 lines of the LXC log of web1
  smcavoy.lxd.lxd_instance_log_info:
    instance: web1
    filename: lxc.log
    tail: 20
  register: log

- name: Print them
  ansible.builtin.debug:
    var: log.lines
"""

RETURN = r"""
logs:
  description:
    - The names of the log files of the instance.
  returned: always
  type: list
  elements: str
  sample:
    - lxc.log
    - lxc.conf
content:
  description:
    - The content of O(filename). An empty string when the file does not exist.
  returned: when O(filename) is set
  type: str
  sample: "lxc web1 20261107100000.123 INFO ..."
lines:
  description:
    - The content split into lines.
  returned: when O(filename) is set
  type: list
  elements: str
  sample:
    - "lxc web1 20261107100000.123 INFO ..."
"""

import typing as t

from ansible.module_utils.common.text.converters import to_text

from ansible_collections.smcavoy.lxd.plugins.module_utils._client import LXDNotFoundError, api_path
from ansible_collections.smcavoy.lxd.plugins.module_utils._module import LXDModule

if t.TYPE_CHECKING:  # pragma: no cover
    from ansible_collections.smcavoy.lxd.plugins.module_utils._typing import ArgumentSpecMutT


def get_argument_spec() -> ArgumentSpecMutT:
    """Return the argument spec of the module."""
    return {
        "instance": {"type": "str", "required": True},
        "project": {"type": "str"},
        "filename": {"type": "str"},
        "tail": {"type": "int"},
    }


def main() -> None:
    """Run the module."""
    mod = LXDModule(get_argument_spec(), extensions=[])

    def read() -> None:
        params = mod.params
        if params["tail"] is not None and params["tail"] < 0:
            mod.fail("tail must be 0 or more")
        base = api_path("instances", params["instance"], "logs")
        urls, _etag = mod.client.get(base, mod.query())
        logs = [str(url).rstrip("/").rsplit("/", 1)[-1] for url in urls or []]
        result: dict[str, t.Any] = {"logs": logs}
        if params["filename"]:
            try:
                data, _headers = mod.client.download(api_path("instances", params["instance"], "logs", params["filename"]), mod.query())
                content = to_text(data, errors="surrogate_or_replace")
            except LXDNotFoundError:
                content = ""
            lines = content.splitlines()
            if params["tail"] is not None:
                lines = lines[-params["tail"] :] if params["tail"] else []
                content = "\n".join(lines) + ("\n" if lines else "")
            result["content"] = content
            result["lines"] = lines
        mod.exit(False, **result)

    mod.run(read)


if __name__ == "__main__":
    main()
