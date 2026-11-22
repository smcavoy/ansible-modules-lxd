#!/usr/bin/python
# Copyright (c) 2026, Sean McAvoy
# GNU General Public License v3.0+ (see LICENSES/GPL-3.0-or-later.txt or https://www.gnu.org/licenses/gpl-3.0.txt)
# SPDX-License-Identifier: GPL-3.0-or-later

from __future__ import annotations

DOCUMENTATION = r"""
module: lxd_operation_info
short_description: Read LXD operations
version_added: "0.1.0"
description:
  - Read the operations of a project, of all projects, or one operation by ID.
  - The module removes secrets from the result.
  - A websocket operation, for example an exec or a migration, keeps live websocket secrets in its metadata.
    An exec can also hold an environment with secrets. So the module removes the whole metadata of a websocket operation.
  - From other operations, the module removes C(metadata.secret), C(metadata.secrets), and C(metadata.fds).
author:
  - Sean McAvoy (@smcavoy)
extends_documentation_fragment:
  - smcavoy.lxd._attributes
  - smcavoy.lxd._attributes.info_module
  - smcavoy.lxd._attributes.action_group
  - smcavoy.lxd._connection
  - smcavoy.lxd._project
options:
  id:
    description:
      - One operation. A missing operation gives an empty list.
    type: str
  all_projects:
    description:
      - Read the operations of all projects. Mutually exclusive with O(project) and O(id).
    type: bool
    default: false
  status:
    description:
      - Keep only the operations with one of these statuses, for example V(Running).
    type: list
    elements: str
  class:
    description:
      - Keep only the operations of this class.
    type: str
    choices: ["task", "websocket", "token", "durable"]
  include_children:
    description:
      - Add the child operations of each operation in the key C(children). A replicator run, for example, has one child per instance.
      - LXD lists only the parent operations. A child holds the error of its own part of the work.
    type: bool
    default: false
notes:
  - LXD keeps a finished operation only for a short time.
seealso:
  - module: smcavoy.lxd.lxd_server_info
"""

EXAMPLES = r"""
- name: Read the running tasks
  smcavoy.lxd.lxd_operation_info:
    class: task
    status:
      - Running
  register: result
"""

RETURN = r"""
operations:
  description:
    - The operations, as LXD returns them, without secrets. A websocket operation has an empty C(metadata).
  returned: always
  type: list
  elements: dict
  sample:
    - id: 01a1a00a-6ae7-7412-8972-aea8529f209b
      class: task
      description: Creating instance
      status: Running
      status_code: 103
      resources:
        instances:
          - /1.0/instances/web1
      may_cancel: false
      err: ""
      location: none
"""

import typing as t

from ansible_collections.smcavoy.lxd.plugins.module_utils._client import api_path
from ansible_collections.smcavoy.lxd.plugins.module_utils._info import check_all_projects
from ansible_collections.smcavoy.lxd.plugins.module_utils._module import LXDModule

if t.TYPE_CHECKING:  # pragma: no cover
    from ansible_collections.smcavoy.lxd.plugins.module_utils._typing import ArgumentSpecMutT

SECRET_KEYS = ("secret", "secrets", "fds")


def without_secrets(operation: dict[str, t.Any]) -> dict[str, t.Any]:
    """Return a copy of an operation and its children without the secrets in their metadata."""
    result = dict(operation)
    metadata = result.get("metadata")
    if result.get("class") == "websocket":
        result["metadata"] = {}
    elif isinstance(metadata, dict):
        result["metadata"] = {key: value for key, value in metadata.items() if key not in SECRET_KEYS}
    if isinstance(result.get("children"), list):
        result["children"] = [without_secrets(child) for child in result["children"] if isinstance(child, dict)]
    return result


def flatten(listing: t.Any) -> list[dict[str, t.Any]]:
    """Return the operations of a listing. LXD groups them by status, for example C(running) and C(success)."""
    if isinstance(listing, list):
        return [item for item in listing if isinstance(item, dict)]
    if isinstance(listing, dict):
        return [item for group in listing.values() if isinstance(group, list) for item in group if isinstance(item, dict)]
    return []


def get_argument_spec() -> ArgumentSpecMutT:
    """Return the argument spec of the module."""
    return {
        "id": {"type": "str"},
        "project": {"type": "str"},
        "all_projects": {"type": "bool", "default": False},
        "status": {"type": "list", "elements": "str"},
        "class": {"type": "str", "choices": ["task", "websocket", "token", "durable"]},
        "include_children": {"type": "bool", "default": False},
    }


def main() -> None:
    """Run the module."""
    mod = LXDModule(get_argument_spec(), extensions=[], mutually_exclusive=[["id", "all_projects"]])

    def read() -> None:
        params = mod.params
        check_all_projects(mod, "operations_get_query_all_projects")
        if params["id"]:
            query = mod.query(recursion=1 if params["include_children"] else None)
            item, _etag = mod.client.get_or_none(api_path("operations", params["id"]), query)
            operations = [item] if isinstance(item, dict) else []
        else:
            query = mod.query(recursion=2 if params["include_children"] else 1)
            if params["all_projects"]:
                query["all-projects"] = "true"
            listing, _etag = mod.client.get("/1.0/operations", query)
            operations = flatten(listing)
        if params["status"]:
            wanted = {status.lower() for status in params["status"]}
            operations = [item for item in operations if str(item.get("status") or "").lower() in wanted]
        if params["class"]:
            operations = [item for item in operations if item.get("class") == params["class"]]
        mod.exit(False, operations=[without_secrets(item) for item in operations])

    mod.run(read)


if __name__ == "__main__":
    main()
