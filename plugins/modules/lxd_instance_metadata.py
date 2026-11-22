#!/usr/bin/python
# Copyright (c) 2026, Sean McAvoy
# GNU General Public License v3.0+ (see LICENSES/GPL-3.0-or-later.txt or https://www.gnu.org/licenses/gpl-3.0.txt)
# SPDX-License-Identifier: GPL-3.0-or-later

from __future__ import annotations

DOCUMENTATION = r"""
module: lxd_instance_metadata
short_description: Manage the metadata and templates of an LXD instance
version_added: "0.1.0"
description:
  - Manage the properties and the template entries in the C(metadata.yaml) of an instance, and the template files.
  - LXD renders a template into a file of the instance on the events of its entry, for example when a copy of the instance is made.
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
      - The instance.
    type: str
    required: true
  properties:
    description:
      - The metadata properties, for example C(description) or C(os).
      - If not set, the module does not manage the properties. A value of V(null) removes the property.
    type: dict
  properties_mode:
    description:
      - How to treat properties that are not in O(properties).
    type: str
    choices:
      merge: Keep them.
      exact: Remove them.
    default: merge
  templates:
    description:
      - The template entries. Each entry renders one file in the instance.
      - If not set, the module does not manage the templates.
    type: list
    elements: dict
    suboptions:
      path:
        description:
          - The path of the file in the instance.
        type: str
        required: true
      when:
        description:
          - The events that render the template.
        type: list
        elements: str
        choices: ["create", "copy", "start", "rename"]
        required: true
      template:
        description:
          - The name of the template file.
        type: str
        required: true
      create_only:
        description:
          - Write the file in the instance only when it does not exist.
        type: bool
        default: false
      properties:
        description:
          - Properties for the template.
        type: dict
        default: {}
      content:
        description:
          - The content of the template file. LXD templates use the Pongo2 syntax.
          - If not set, the template file must exist already.
        type: str
  templates_mode:
    description:
      - How to treat template entries and template files that are not in O(templates).
    type: str
    choices:
      merge: Keep them.
      exact: Remove the other entries, and the template files that no entry uses.
    default: merge
notes:
  - The module never changes C(architecture), C(creation_date), or C(expiry_date).
  - The module compares template files by SHA-256.
seealso:
  - module: smcavoy.lxd.lxd_instance
  - name: LXD image format
    description: The format of C(metadata.yaml) and the templates.
    link: https://documentation.ubuntu.com/lxd/latest/reference/image_format/
"""

EXAMPLES = r"""
- name: Write the instance name into /etc/motd of each copy of the template instance
  smcavoy.lxd.lxd_instance_metadata:
    instance: golden
    properties:
      description: Golden image for web servers
    templates:
      - path: /etc/motd
        when:
          - create
          - copy
        template: motd.tpl
        content: "Welcome to {{ '{{' }} instance.name {{ '}}' }}\n"
"""

RETURN = r"""
metadata:
  description:
    - The metadata after the change, without the content of the template files.
    - In check mode, the predicted metadata.
  returned: always
  type: dict
  sample:
    architecture: x86_64
    creation_date: 1762160000
    properties:
      description: Web server
    templates:
      /etc/hostname:
        when:
          - create
          - copy
        create_only: false
        template: hostname.tpl
        properties: {}
"""

import copy
import hashlib
import typing as t

from ansible_collections.smcavoy.lxd.plugins.module_utils._client import LXDNotFoundError, api_path
from ansible_collections.smcavoy.lxd.plugins.module_utils._module import LXDModule

if t.TYPE_CHECKING:  # pragma: no cover
    from ansible_collections.smcavoy.lxd.plugins.module_utils._typing import ArgumentSpecMutT

ENTRY_KEYS = ("when", "create_only", "template", "properties")


def sha256(data: bytes) -> str:
    """Return the SHA-256 of some bytes."""
    return hashlib.sha256(data).hexdigest()


def clean_entry(entry: t.Mapping[str, t.Any]) -> dict[str, t.Any]:
    """Return a template entry with the keys that LXD stores, in a form that compares well."""
    return {
        "when": list(entry.get("when") or []),
        "create_only": bool(entry.get("create_only")),
        "template": entry.get("template") or "",
        "properties": {str(key): str(value) for key, value in (entry.get("properties") or {}).items()},
    }


class MetadataModule:
    """Manage the metadata of one instance."""

    def __init__(self, mod: LXDModule) -> None:
        self.mod = mod
        self.path = api_path("instances", mod.params["instance"], "metadata")
        self.templates_path = f"{self.path}/templates"

    def read_file(self, name: str) -> bytes | None:
        """Return a template file, or None when it does not exist."""
        try:
            data, _headers = self.mod.client.download(self.templates_path, self.mod.query(path=name))
        except LXDNotFoundError:
            return None
        return data

    def list_files(self) -> list[str]:
        """Return the names of the template files."""
        items, _etag = self.mod.client.get(self.templates_path, self.mod.query())
        return [str(item).rstrip("/").rsplit("/", 1)[-1] for item in items or []]

    def run(self) -> None:
        """Make sure that the metadata and the template files match the task."""
        params = self.mod.params
        current, _etag = self.mod.client.get(self.path, self.mod.query())
        current = current or {}
        new = copy.deepcopy(current)
        changed_parts: list[str] = []

        if params["properties"] is not None:
            props = dict(current.get("properties") or {})
            wanted = {str(key): None if value is None else str(value) for key, value in params["properties"].items()}
            if params["properties_mode"] == "exact":
                props = {key: value for key, value in props.items() if key in wanted}
            for key, value in wanted.items():
                if value is None:
                    props.pop(key, None)
                else:
                    props[key] = value
            if props != (current.get("properties") or {}):
                new["properties"] = props
                changed_parts.append("properties")

        uploads: dict[str, bytes] = {}
        deletes: list[str] = []
        file_hashes: dict[str, str] = {}
        old_hashes: dict[str, str] = {}
        if params["templates"] is not None:
            have = {path: clean_entry(entry) for path, entry in (current.get("templates") or {}).items()}
            entries = {} if params["templates_mode"] == "exact" else dict(have)
            for entry in params["templates"]:
                entries[entry["path"]] = clean_entry(entry)
            if entries != have:
                new["templates"] = entries
                changed_parts.append("templates")
            files = self.list_files()
            for entry in params["templates"]:
                name = entry["template"]
                data = None if name not in files else self.read_file(name)
                if data is not None:
                    old_hashes[name] = sha256(data)
                content = entry.get("content")
                if content is None:
                    if data is None:
                        self.mod.fail(f"template {name} has no file and no content")
                    file_hashes[name] = sha256(data)
                    continue
                wanted_data = content.encode("utf-8")
                file_hashes[name] = sha256(wanted_data)
                if data is None or sha256(data) != file_hashes[name]:
                    uploads[name] = wanted_data
            if params["templates_mode"] == "exact":
                used = {entry["template"] for entry in entries.values()}
                deletes = sorted(name for name in files if name not in used)
                # The diff shows a deleted file on the before side only. Its content does not matter, so it has no hash.
                for name in deletes:
                    old_hashes.setdefault(name, "")

        before = {key: current.get(key) for key in ("properties", "templates")}
        after = {key: new.get(key) for key in ("properties", "templates")}
        if file_hashes or deletes:
            # Both sides hold the files that the task names, so a task without a change shows no diff.
            before["template_files"] = dict(sorted(old_hashes.items()))
            after["template_files"] = dict(sorted(file_hashes.items()))
        changed = bool(changed_parts or uploads or deletes)
        if not changed:
            self.mod.exit(False, before=before, after=after, metadata=current)
        if not self.mod.check_mode:
            # Write the files first. An entry that names a missing file would break the next copy of the instance.
            for name, data in uploads.items():
                self.mod.client.write(
                    "POST", self.templates_path, query=self.mod.query(path=name), raw=data, headers={"Content-Type": "application/octet-stream"}
                )
            if changed_parts:
                self.mod.client.write("PUT", self.path, query=self.mod.query(), body=new)
            for name in deletes:
                self.mod.client.write("DELETE", self.templates_path, query=self.mod.query(path=name))
            new = self.mod.client.get(self.path, self.mod.query())[0] or new
        self.mod.exit(True, before=before, after=after, metadata=new)


def get_argument_spec() -> ArgumentSpecMutT:
    """Return the argument spec of the module."""
    return {
        "instance": {"type": "str", "required": True},
        "project": {"type": "str"},
        "properties": {"type": "dict"},
        "properties_mode": {"type": "str", "default": "merge", "choices": ["merge", "exact"]},
        "templates": {
            "type": "list",
            "elements": "dict",
            "options": {
                "path": {"type": "str", "required": True},
                "when": {"type": "list", "elements": "str", "required": True, "choices": ["create", "copy", "start", "rename"]},
                "template": {"type": "str", "required": True},
                "create_only": {"type": "bool", "default": False},
                "properties": {"type": "dict", "default": {}},
                "content": {"type": "str"},
            },
        },
        "templates_mode": {"type": "str", "default": "merge", "choices": ["merge", "exact"]},
    }


def main() -> None:
    """Run the module."""
    mod = LXDModule(get_argument_spec(), extensions=["container_edit_metadata"])
    mod.run(MetadataModule(mod).run)


if __name__ == "__main__":
    main()
