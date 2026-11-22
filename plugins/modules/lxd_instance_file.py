#!/usr/bin/python
# Copyright (c) 2026, Sean McAvoy
# GNU General Public License v3.0+ (see LICENSES/GPL-3.0-or-later.txt or https://www.gnu.org/licenses/gpl-3.0.txt)
# SPDX-License-Identifier: GPL-3.0-or-later

from __future__ import annotations

DOCUMENTATION = r"""
module: lxd_instance_file
short_description: Manage files, directories, and symlinks in LXD instances
version_added: "0.1.0"
description:
  - Put a file, a directory, or a symlink into an instance, or remove it, with owner and mode.
  - The module compares file content by SHA-256. It reads the file from the instance for the compare.
    The file streams to a temporary file on disk, and an upload streams from disk, so a large file does not
    need controller memory.
  - LXD cannot write an existing file that root in the instance does not own when the mode gives no write to others,
    for example V("0600") owned by uid 1000. The module then deletes the file and writes it again.
    The file gets a new inode, so hard links to it break.
  - LXD creates or empties a file before it writes it. When LXD then refuses the write, for example on a full disk,
    the module deletes a new file, or tries to write the old content back with the old owner and mode, and fails.
    On a full disk the old content can stay lost. The message says so, and a new run with space writes the file.
    After a broken connection the write can have worked, so the module leaves the file as it is.
  - The module reads a file back after each write and fails when the content differs.
    LXD 6.10.1 on a full btrfs pool answers a small write with success and stores nothing.
author:
  - Sean McAvoy (@smcavoy)
extends_documentation_fragment:
  - smcavoy.lxd._attributes
  - smcavoy.lxd._attributes.action_group
  - smcavoy.lxd._connection
  - smcavoy.lxd._project
attributes:
  check_mode:
    support: full
  diff_mode:
    support: full
  idempotent:
    support: full
options:
  instance:
    description:
      - The instance. It must run, or be a stopped container.
    type: str
    required: true
  path:
    description:
      - The absolute path in the instance.
    type: str
    required: true
  state:
    description:
      - The wanted state of the path.
    type: str
    choices:
      present: The path exists with the wanted type, content, owner, and mode.
      absent: The path does not exist. A directory must be empty.
    default: present
  type:
    description:
      - The type of the path.
      - LXD cannot change the owner or the mode of a directory that exists.
        The module fails when they differ from O(owner_uid), O(owner_gid) or O(mode).
    type: str
    choices: ["file", "directory", "link"]
    default: file
  content:
    description:
      - The file content.
      - Mutually exclusive with O(src).
    type: str
  src:
    description:
      - A file on the controller to copy into the instance.
      - Mutually exclusive with O(content).
    type: path
  link_target:
    description:
      - The target of the symlink.
      - Required when O(type=link).
      - To change the target of a link that exists, the module deletes the link and makes it again.
      - LXD does not set the owner or the mode of a link.
    type: str
  owner_uid:
    description:
      - The owner of the path in the instance.
      - If not set, the module keeps the owner of a path that exists, and uses V(0) for a new path.
    type: int
  owner_gid:
    description:
      - The group of the path in the instance.
      - If not set, the module keeps the group of a path that exists, and uses V(0) for a new path.
    type: int
  mode:
    description:
      - The permissions as an octal string, for example V("0644").
      - If not set, the module keeps the mode of a path that exists.
        For a new path it uses V("0644") for a file and V("0755") for a directory.
      - LXD cannot set the setuid, setgid and sticky bits. The module refuses a mode that has them.
    type: str
seealso:
  - module: smcavoy.lxd.lxd_instance
"""

EXAMPLES = r"""
- name: Write a web page
  smcavoy.lxd.lxd_instance_file:
    instance: web1
    path: /srv/www/index.html
    content: "<h1>Hello</h1>\n"

- name: Enable the OpenRC local service with a symlink
  smcavoy.lxd.lxd_instance_file:
    instance: web1
    path: /etc/runlevels/default/local
    type: link
    link_target: /etc/init.d/local

- name: Remove a file
  smcavoy.lxd.lxd_instance_file:
    instance: web1
    path: /tmp/old.txt
    state: absent
"""

RETURN = r"""
file:
  description:
    - The path after the change.
    - V(null) after a delete.
  returned: always
  type: dict
  contains:
    path:
      description: The path in the instance.
      type: str
    type:
      description: V(file), V(directory), or V(link).
      type: str
    owner_uid:
      description: The owner.
      type: int
    owner_gid:
      description: The group.
      type: int
    mode:
      description: The permissions as an octal string.
      type: str
    sha256:
      description: The SHA-256 of a file, or of the target of a link. V(null) for a directory.
      type: str
  sample:
    path: /srv/www/index.html
    type: file
    owner_uid: 0
    owner_gid: 0
    mode: "0644"
    sha256: 9f86d081884c7d659a2feaa0c55ad015a3bf4f1b2b0b822cd15d6c15b0f00a08
"""

import hashlib
import os
import posixpath
import re
import tempfile
import typing as t

from ansible.module_utils.common.text.converters import to_bytes, to_text

from ansible_collections.smcavoy.lxd.plugins.module_utils._client import CHUNK_SIZE, ChainedReader, LXDClientError, LXDNotFoundError, api_path
from ansible_collections.smcavoy.lxd.plugins.module_utils._module import LXDModule

if t.TYPE_CHECKING:  # pragma: no cover
    from ansible_collections.smcavoy.lxd.plugins.module_utils._typing import ArgumentSpecMutT

LXD_TYPES = {"file": "file", "directory": "directory", "link": "symlink"}
TASK_TYPES = {value: key for key, value in LXD_TYPES.items()}
DIFF_TEXT_LIMIT = 65536


class Content:
    """File content: a byte string, or a file on disk. With its SHA-256, and without the whole file in memory."""

    def __init__(self, data: bytes | None = None, path: str | None = None, sha256: str | None = None) -> None:
        self.data = data
        self.path = path
        if sha256 is None:
            sha = hashlib.sha256()
            if data is not None:
                sha.update(data)
            else:
                with open(t.cast(str, path), "rb") as stream:
                    for chunk in iter(lambda: stream.read(CHUNK_SIZE), b""):
                        sha.update(chunk)
            sha256 = sha.hexdigest()
        self.sha256 = sha256

    def reader(self) -> ChainedReader:
        """Return a new reader for an upload. It sends the length of the content."""
        return ChainedReader([self.data if self.data is not None else t.cast(str, self.path)])

    def head(self, limit: int) -> bytes:
        """Return at most O(limit) bytes from the start."""
        if self.data is not None:
            return self.data[:limit]
        with open(t.cast(str, self.path), "rb") as stream:
            return stream.read(limit)


class FileModule:
    """Manage one path in an instance."""

    def __init__(self, mod: LXDModule) -> None:
        self.mod = mod
        self.instance: str = mod.params["instance"]
        self.path: str = mod.params["path"]
        self.endpoint = api_path("instances", self.instance, "files")
        if not self.path.startswith("/"):
            mod.fail("path must be absolute")

    def read(self) -> tuple[dict[str, t.Any] | None, Content | None]:
        """Read the path. Return its metadata and, for a file or a link, its content in a temporary file."""
        query = self.mod.query(path=self.path)
        headers = self.mod.client.head(self.endpoint, query)
        if headers is None:
            return None, None
        info = {
            "path": self.path,
            "type": TASK_TYPES.get(headers.get("x-lxd-type", "file"), "file"),
            "owner_uid": int(headers.get("x-lxd-uid", "0")),
            "owner_gid": int(headers.get("x-lxd-gid", "0")),
            "mode": headers.get("x-lxd-mode", "0000").rjust(4, "0"),
            "sha256": None,
        }
        content: Content | None = None
        if info["type"] != "directory":
            handle, temp = tempfile.mkstemp(dir=self.mod.module.tmpdir, prefix="lxd-file-")
            try:
                with os.fdopen(handle, "w+b") as sink:
                    resp = self.mod.client.download_to(self.endpoint, sink, query)
            except LXDNotFoundError:
                os.unlink(temp)
                return None, None
            content = Content(path=temp, sha256=resp.sha256)
            info["sha256"] = content.sha256
        return info, content

    def wanted_content(self) -> Content | None:
        """Return the wanted content, or C(None) when the task does not set it."""
        params = self.mod.params
        if params["type"] == "link":
            return Content(to_bytes(params["link_target"]))
        if params["type"] == "directory":
            return None
        if params["src"] is not None:
            if not os.path.isfile(params["src"]):
                self.mod.fail(f"src {params['src']} is not a file")
            return Content(path=params["src"])
        if params["content"] is not None:
            return Content(to_bytes(params["content"]))
        return None

    def present(self) -> None:
        """Make sure that the path exists with the wanted settings."""
        params = self.mod.params
        current, current_content = self.read()
        # An option that the task does not set keeps the value of a path that exists (like ansible.builtin.copy).
        keep = current if current is not None and current["type"] == params["type"] else None
        mode = params["mode"] or (keep["mode"] if keep else ("0755" if params["type"] == "directory" else "0644"))
        if params["type"] == "link":
            mode = "0777"
        mode = mode.rjust(4, "0")
        if not re.fullmatch(r"0[0-7]{3}", mode):
            # LXD 6.10.1 drops the setuid, setgid and sticky bits, so such a mode can never be reached.
            self.mod.fail(
                f'mode {params["mode"]} is not valid. Give three octal digits, for example "0644". LXD cannot set the setuid, setgid and sticky bits.'
            )
        uid = params["owner_uid"] if params["owner_uid"] is not None else (keep["owner_uid"] if keep else 0)
        gid = params["owner_gid"] if params["owner_gid"] is not None else (keep["owner_gid"] if keep else 0)
        data = self.wanted_content()
        wanted = {
            "path": self.path,
            "type": params["type"],
            "owner_uid": uid,
            "owner_gid": gid,
            "mode": mode,
            "sha256": data.sha256 if data is not None else None,
        }
        if current is not None and current["type"] != params["type"]:
            self.mod.fail(f"{self.path} is a {current['type']}, not a {params['type']}")
        if current is not None and data is None and params["type"] == "file":
            wanted["sha256"] = current["sha256"]
        if params["type"] == "link":
            # LXD returns the target of a link as an absolute path, so the compare uses that form.
            # A target that passes through other links still differs, and the module then makes the link again.
            resolved = posixpath.normpath(posixpath.join(posixpath.dirname(self.path), params["link_target"]))
            wanted["sha256"] = Content(to_bytes(resolved)).sha256
            if current is not None:
                # LXD does not change the owner or the mode of a link.
                wanted.update(mode=current["mode"], owner_uid=current["owner_uid"], owner_gid=current["owner_gid"])
        changed = current != wanted
        if changed and current is not None and params["type"] == "directory":
            # LXD 6.10.1 answers a POST for a directory that exists with success, and changes nothing.
            self.mod.fail(
                f"{self.path} exists with owner {current['owner_uid']}:{current['owner_gid']} and mode {current['mode']}. "
                f"LXD cannot change the owner or the mode of a directory that exists. "
                f"Change it in the instance, for example with lxd_instance_exec and chown or chmod."
            )
        if changed and not self.mod.check_mode:
            if current is not None and params["type"] == "link":
                # LXD cannot replace a link. The module deletes it and makes it again.
                self.mod.client.write("DELETE", self.endpoint, query=self.mod.query(path=self.path))
            previous = (current, current_content) if current is not None and current["type"] == "file" and current_content is not None else None
            sent = data if data is not None else (current_content or Content(b""))
            headers = self.send(sent, mode, uid, gid, exists=current is not None, previous=previous)
        result: dict[str, t.Any] | None = wanted
        if changed and not self.mod.check_mode:
            result, _content = self.read()
            got = (result or {}).get("sha256")
            if params["type"] == "file" and got != sent.sha256:
                # LXD 6.10.1 on a full btrfs pool answers a small write with success, and stores nothing.
                note = self.undo(previous, headers)
                self.mod.fail(
                    f"LXD accepted the write of {self.path}, but the file holds other content now (SHA-256 {got}). A full disk can cause this. {note}"
                )
        before, after = self.diff_parts(current, current_content, wanted, data)
        self.mod.exit(changed, before=before, after=after, file=result)

    def send(
        self,
        data: Content,
        mode: str,
        uid: int,
        gid: int,
        exists: bool = False,
        previous: tuple[dict[str, t.Any], Content] | None = None,
    ) -> dict[str, str]:
        """Write the path with its owner and mode, and return the headers. Undo a refused write of a file, see L(undo).

        LXD 6.10 cannot open an existing file for writing when root in the instance does not own it and
        the mode gives no write to others (for example 0600 owned by uid 1000). It answers 403
        "permission denied". The module then deletes the file and writes it again with the wanted owner
        and mode. The file gets a new inode, so hard links to it break.
        """
        params = self.mod.params
        headers = {
            "X-LXD-type": LXD_TYPES[params["type"]],
            "X-LXD-uid": str(uid),
            "X-LXD-gid": str(gid),
            "X-LXD-mode": mode if mode.startswith("0") else "0" + mode,
            "X-LXD-write": "overwrite",
        }
        if params["type"] != "link" and not self.mod.client.missing_extensions(["instances_files_modify_permissions"]):
            headers["X-LXD-modify-perm"] = "uid,gid,mode"
        if params["type"] == "directory":
            data = Content(b"")
        query = self.mod.query(path=self.path)
        try:
            try:
                self.mod.client.write("POST", self.endpoint, query=query, raw=data.reader(), headers=headers)
            except LXDClientError as exc:
                if not (exists and params["type"] == "file" and exc.status == 403 and "permission denied" in exc.message.lower()):
                    raise
                self.mod.client.write("DELETE", self.endpoint, query=query)
                self.mod.client.write("POST", self.endpoint, query=query, raw=data.reader(), headers=headers)
        except LXDClientError as exc:
            # Only an answer from LXD says that the write failed. After a broken connection the write can have worked.
            if params["type"] != "file" or exc.status is None or exc.outcome_unknown:
                raise
            note = self.undo(previous, headers)
            raise LXDClientError(f"{exc.message}. {note}", status=exc.status, operation=exc.operation) from exc
        return headers

    def undo(self, previous: tuple[dict[str, t.Any], Content] | None, headers: dict[str, str]) -> str:
        """Undo a write that LXD refused. Return a note for the error message.

        LXD 6.10 opens the file, and truncates it, before it writes. A write that fails, for example on a full disk,
        leaves an empty new file, or an existing file without its content. The module deletes the new file, or
        writes the old content back with the old owner and mode, and reads it back to check it.
        On a full btrfs pool the write-back can fail too: LXD then answers a small write with success and stores nothing.
        """
        query = self.mod.query(path=self.path)
        if previous is None:
            try:
                self.mod.client.write("DELETE", self.endpoint, query=query)
            except LXDNotFoundError:
                return f"LXD did not create {self.path}."
            except LXDClientError as exc:
                return f"LXD left an empty {self.path}, and the module could not delete it: {exc.message}"
            return f"The module deleted the {self.path} that LXD left."
        info, content = previous
        old_headers = dict(
            headers,
            **{"X-LXD-uid": str(info["owner_uid"]), "X-LXD-gid": str(info["owner_gid"]), "X-LXD-mode": "0" + info["mode"].lstrip("0").rjust(3, "0")},
        )
        lost = f"LXD emptied {self.path}, and the module could not write the old content back"
        try:
            self.mod.client.write("POST", self.endpoint, query=query, raw=content.reader(), headers=old_headers)
            back, _content = self.read()
        except LXDClientError as exc:
            return f"{lost}: {exc.message}. Run the task again when there is space."
        if (back or {}).get("sha256") != content.sha256:
            return f"{lost}: the file holds other content. Run the task again when there is space."
        return f"The module wrote the old content of {self.path} back."

    def diff_parts(
        self,
        current: dict[str, t.Any] | None,
        current_content: Content | None,
        wanted: dict[str, t.Any],
        data: Content | None,
    ) -> tuple[dict[str, t.Any], dict[str, t.Any]]:
        """Return the diff, with text content for small text files."""
        before = dict(current or {})
        after = dict(wanted)
        for part, content in ((before, current_content), (after, data)):
            if content is None:
                continue
            text = content.head(DIFF_TEXT_LIMIT + 1)
            if len(text) <= DIFF_TEXT_LIMIT and b"\0" not in text:
                part["content"] = to_text(text, errors="surrogate_or_replace")
        return before, after

    def absent(self) -> None:
        """Make sure that the path does not exist."""
        current, _content = self.read()
        if current is None:
            self.mod.exit(False, before={}, after={}, file=None)
        self.mod.write("DELETE", self.endpoint, query=self.mod.query(path=self.path))
        self.mod.exit(True, before=current, after={}, file=None)


def get_argument_spec() -> ArgumentSpecMutT:
    """Return the argument spec of the module."""
    return {
        "instance": {"type": "str", "required": True},
        "project": {"type": "str"},
        "path": {"type": "str", "required": True},
        "state": {"type": "str", "default": "present", "choices": ["present", "absent"]},
        "type": {"type": "str", "default": "file", "choices": ["file", "directory", "link"]},
        "content": {"type": "str"},
        "src": {"type": "path"},
        "link_target": {"type": "str"},
        "owner_uid": {"type": "int"},
        "owner_gid": {"type": "int"},
        "mode": {"type": "str"},
    }


def main() -> None:
    """Run the module."""
    mod = LXDModule(
        get_argument_spec(),
        extensions=["file_delete", "instance_file_head"],
        mutually_exclusive=[["content", "src"]],
        required_if=[["type", "link", ["link_target"]]],
    )
    if mod.params["type"] == "link":
        missing = mod.client.missing_extensions(["file_symlinks"])
        if missing:
            mod.fail(f"LXD server lacks the API extensions: {', '.join(missing)}")
    module = FileModule(mod)
    if mod.params["state"] == "present":
        mod.run(module.present)
    else:
        mod.run(module.absent)


if __name__ == "__main__":
    main()
