#!/usr/bin/python
# Copyright (c) 2026, Sean McAvoy
# GNU General Public License v3.0+ (see LICENSES/GPL-3.0-or-later.txt or https://www.gnu.org/licenses/gpl-3.0.txt)
# SPDX-License-Identifier: GPL-3.0-or-later

from __future__ import annotations

DOCUMENTATION = r"""
module: lxd_instance_exec
short_description: Run a command in an LXD instance
version_added: "0.1.0"
description:
  - Run a command in a running LXD instance through the LXD API, and return its exit code and output.
  - The module needs no SSH and no agent in the instance, except the VM agent for virtual machines.
author:
  - Sean McAvoy (@smcavoy)
extends_documentation_fragment:
  - smcavoy.lxd._attributes
  - smcavoy.lxd._attributes.action_group
  - smcavoy.lxd._connection
  - smcavoy.lxd._project
attributes:
  check_mode:
    support: partial
    details:
      - Check mode does not run the command. It checks O(creates) and O(removes), and predicts RV(ignore:changed).
  diff_mode:
    support: none
  idempotent:
    support: none
    details:
      - The command runs on every run, unless O(creates) or O(removes) stop it.
options:
  instance:
    description:
      - The instance. It must run.
    type: str
    required: true
  command:
    description:
      - The command and its arguments. The module does not use a shell, unless the list starts with one, for example V([sh, -c, ...]).
    type: list
    elements: str
    required: true
  environment:
    description:
      - Environment variables for the command.
    type: dict
  user:
    description:
      - The user ID that runs the command.
    type: int
  group:
    description:
      - The group ID that runs the command.
    type: int
  cwd:
    description:
      - The working directory of the command.
    type: str
  creates:
    description:
      - A path in the instance. If it exists, the command does not run.
    type: str
  removes:
    description:
      - A path in the instance. If it does not exist, the command does not run.
    type: str
  ok_rc:
    description:
      - The exit codes that count as success.
    type: list
    elements: int
    default: [0]
notes:
  - The module cannot send input to the command. The API needs a websocket for that.
  - LXD reports the exit codes 127 and 126 as errors, C(Command not found) and C(not executable).
    The module returns them as RV(rc), so O(ok_rc) works for them too.
seealso:
  - module: smcavoy.lxd.lxd_instance_file
"""

EXAMPLES = r"""
- name: Install a package in a container, once
  smcavoy.lxd.lxd_instance_exec:
    instance: web1
    command: [apk, add, nginx]
    creates: /usr/sbin/nginx

- name: Run a shell pipeline
  smcavoy.lxd.lxd_instance_exec:
    instance: web1
    command: [sh, -c, "ps | grep -c nginx"]
    ok_rc: [0, 1]
  register: result
"""

RETURN = r"""
rc:
  description:
    - The exit code of the command.
  returned: when the command runs
  type: int
  sample: 0
stdout:
  description:
    - The standard output.
  returned: when the command runs
  type: str
  sample: "Alpine Linux 3.22\n"
stderr:
  description:
    - The standard error.
  returned: when the command runs
  type: str
  sample: ""
stdout_lines:
  description:
    - RV(stdout) split into lines.
  returned: when the command runs
  type: list
  elements: str
stderr_lines:
  description:
    - RV(stderr) split into lines.
  returned: when the command runs
  type: list
  elements: str
skipped_reason:
  description:
    - Why the command did not run, because of O(creates) or O(removes).
  returned: when the command does not run
  type: str
  sample: /usr/sbin/nginx exists
"""

import typing as t
from urllib.parse import urlparse

from ansible_collections.smcavoy.lxd.plugins.module_utils._client import LXDClientError, api_path
from ansible_collections.smcavoy.lxd.plugins.module_utils._module import LXDModule

if t.TYPE_CHECKING:  # pragma: no cover
    from ansible_collections.smcavoy.lxd.plugins.module_utils._typing import ArgumentSpecMutT


class ExecModule:
    """Run one command in an instance."""

    def __init__(self, mod: LXDModule) -> None:
        self.mod = mod
        self.instance: str = mod.params["instance"]
        self.path = api_path("instances", self.instance)

    def exists(self, path: str) -> bool:
        """Return whether a path exists in the instance."""
        return self.mod.client.head(f"{self.path}/files", self.mod.query(path=path)) is not None

    def skip_reason(self) -> str | None:
        """Return why the command must not run, or None."""
        params = self.mod.params
        if params["creates"] and self.exists(params["creates"]):
            return f"{params['creates']} exists"
        if params["removes"] and not self.exists(params["removes"]):
            # LXD answers 404 for a missing path and for a missing instance. Only the first is a reason to skip.
            instance, _etag = self.mod.client.get_or_none(self.path, self.mod.query())
            if instance is None:
                self.mod.fail(f"instance {self.instance} not found")
            return f"{params['removes']} does not exist"
        return None

    def output(self, url: str | None) -> str:
        """Read one output file of the command, then delete it."""
        if not url:
            return ""
        path = urlparse(url).path
        try:
            data, _headers = self.mod.client.download(path, self.mod.query())
        finally:
            try:
                self.mod.client.request("DELETE", path, query=self.mod.query())
            except LXDClientError:
                pass
        return data.decode("utf-8", errors="replace")

    @staticmethod
    def special_exit_code(message: str) -> int | None:
        """Return the exit code behind an LXD exec error, or None for other errors."""
        if "Command not found" in message:
            return 127
        if "not executable" in message.lower():
            return 126
        return None

    def failed_outputs(self, operation: str | None) -> dict[str, t.Any]:
        """Return the output files of a failed exec operation, if LXD still has them."""
        if not operation:
            return {}
        op_id = operation.rstrip("/").rsplit("/", 1)[-1]
        try:
            op, _etag = self.mod.client.get(api_path("operations", op_id))
        except LXDClientError:
            return {}
        return dict(((op or {}).get("metadata") or {}).get("output") or {})

    def run(self) -> None:
        """Run the command, unless creates or removes stop it."""
        params = self.mod.params
        reason = self.skip_reason()
        if reason:
            self.mod.exit(False, skipped_reason=reason)
        if self.mod.check_mode:
            self.mod.exit(True)
        body: dict[str, t.Any] = {
            "command": params["command"],
            "environment": {str(key): str(value) for key, value in (params["environment"] or {}).items()},
            "record-output": True,
            "wait-for-websocket": False,
            "interactive": False,
        }
        for key in ("user", "group", "cwd"):
            if params[key] is not None:
                body[key] = params[key]
        try:
            meta = self.mod.write("POST", f"{self.path}/exec", query=self.mod.query(), body=body) or {}
        except LXDClientError as exc:
            if exc.outcome_unknown:
                # The command runs on in the instance when LXD restarts or the connection breaks.
                self.mod.fail(
                    f"{exc.detail} The command can still run in the instance, or it ran. A new run of the task runs "
                    "the command again: run it again only when the command is safe to repeat, or when creates or removes stop it.",
                    changed=True,
                )
            # LXD turns the exit codes 127 and 126 into a failed operation. The module turns them back into rc.
            rc_from_error = self.special_exit_code(exc.message)
            if rc_from_error is None:
                raise
            meta = {"return": rc_from_error, "output": self.failed_outputs(exc.operation)}
        rc = int(meta.get("return", -1))
        outputs = meta.get("output") or {}
        stdout = self.output(outputs.get("1"))
        stderr = self.output(outputs.get("2"))
        result: dict[str, t.Any] = {
            "rc": rc,
            "stdout": stdout,
            "stderr": stderr,
            "stdout_lines": stdout.splitlines(),
            "stderr_lines": stderr.splitlines(),
        }
        if rc not in params["ok_rc"]:
            self.mod.fail(f"command exited with code {rc}", changed=True, **result)
        # Ansible marks a result with a non-zero rc as failed, unless the result says otherwise.
        self.mod.exit(True, failed=False, **result)


def get_argument_spec() -> ArgumentSpecMutT:
    """Return the argument spec of the module."""
    return {
        "instance": {"type": "str", "required": True},
        "project": {"type": "str"},
        "command": {"type": "list", "elements": "str", "required": True},
        "environment": {"type": "dict"},
        "user": {"type": "int"},
        "group": {"type": "int"},
        "cwd": {"type": "str"},
        "creates": {"type": "str"},
        "removes": {"type": "str"},
        "ok_rc": {"type": "list", "elements": "int", "default": [0]},
    }


def main() -> None:
    """Run the module."""
    mod = LXDModule(get_argument_spec(), extensions=["container_exec_recording"])
    if any(mod.params[key] is not None for key in ("user", "group", "cwd")):
        missing = mod.client.missing_extensions(["container_exec_user_group_cwd"])
        if missing:
            mod.fail("LXD server lacks the API extension container_exec_user_group_cwd, which user, group, and cwd need")
    mod.run(ExecModule(mod).run)


if __name__ == "__main__":
    main()
