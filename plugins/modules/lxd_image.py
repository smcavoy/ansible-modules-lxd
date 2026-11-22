#!/usr/bin/python
# Copyright (c) 2026, Sean McAvoy
# GNU General Public License v3.0+ (see LICENSES/GPL-3.0-or-later.txt or https://www.gnu.org/licenses/gpl-3.0.txt)
# SPDX-License-Identifier: GPL-3.0-or-later

from __future__ import annotations

DOCUMENTATION = r"""
module: lxd_image
short_description: Manage LXD images
version_added: "0.1.0"
description:
  - Get images into the LXD image store from an image registry, an instance, a file, or another project.
  - Manage the aliases, properties, and other settings of an image, and delete images.
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
  fingerprint:
    description:
      - The fingerprint of the image, or a unique prefix of it.
      - If not set, the module finds the image by the first name in O(aliases).
    type: str
  aliases:
    description:
      - The aliases of the image.
      - If not set, the module does not manage the aliases.
    type: list
    elements: dict
    suboptions:
      name:
        description:
          - The alias name.
        type: str
        required: true
      description:
        description:
          - The alias description.
          - If not set, the module keeps the current description, or uses an empty description for a new alias.
        type: str
  aliases_mode:
    description:
      - How to treat aliases of this image that are not in O(aliases).
    type: str
    choices:
      merge: Keep them.
      exact: Remove them.
    default: merge
  state:
    description:
      - The wanted state of the image.
    type: str
    choices:
      present: The image exists with the wanted settings.
      absent: The image does not exist. LXD removes its aliases too.
    default: present
  source:
    description:
      - Where the image comes from. The module uses it only when the image does not exist.
      - Give exactly one source form.
      - "Registry: O(source.image_registry) with O(source.alias) or O(source.fingerprint)."
      - "Instance: O(source.instance), and O(source.snapshot) for a snapshot."
      - "Split file: O(source.metadata_path) and O(source.rootfs_path)."
      - "Unified file: O(source.path)."
      - "Other project: O(source.project) with O(source.alias) or O(source.fingerprint)."
    type: dict
    suboptions:
      image_registry:
        description:
          - The image registry, for example V(images) or V(ubuntu).
        type: str
      alias:
        description:
          - The alias of the image in the registry or the other project.
        type: str
      fingerprint:
        description:
          - The fingerprint of the image in the registry or the other project.
        type: str
      image_type:
        description:
          - The image type. For a split file, V(virtual-machine) sends the root file system as a VM disk.
        type: str
        choices: ["container", "virtual-machine"]
      copy_aliases:
        description:
          - Copy the aliases of the image from the registry.
        type: bool
      instance:
        description:
          - The instance to publish as an image. LXD needs the instance stopped, unless it is a snapshot.
        type: str
      snapshot:
        description:
          - The snapshot of O(source.instance) to publish.
        type: str
      path:
        description:
          - A unified image tarball on the managed node.
        type: path
      metadata_path:
        description:
          - The metadata tarball of a split image on the managed node.
        type: path
      rootfs_path:
        description:
          - The root file system of a split image on the managed node, a squashfs file or a VM disk.
        type: path
      project:
        description:
          - The project to copy the image from.
        type: str
  properties:
    description:
      - The image properties, for example C(os) and C(release).
      - A value of V(null) removes the property.
      - If not set, the module does not manage the properties.
    type: dict
  properties_mode:
    description:
      - How to treat properties on the image that are not in O(properties).
    type: str
    choices:
      merge: Keep them.
      exact: Remove them. This also removes the properties that the registry or the upload set.
    default: merge
  public:
    description:
      - Whether clients without trust can download the image.
      - Only the V(default) project accepts V(true).
    type: bool
  auto_update:
    description:
      - Whether LXD updates the image from its registry. Only images from a registry can update.
    type: bool
  profiles:
    description:
      - The profiles for instances that start from this image.
    type: list
    elements: str
  expires_at:
    description:
      - The time when LXD deletes the image, as an RFC 3339 time. An empty string means that the image never expires.
      - LXD cannot remove the expiry date of an image. The module fails when the task gives an empty string and the image has a date.
    type: str
  compression_algorithm:
    description:
      - The compression of a published image, for example V(gzip), V(zstd), or V(none).
      - The module uses it only when it publishes an instance.
    type: str
notes:
  - An image from a registry can get a new fingerprint upstream. The module does not refresh it. It finds the image by its local alias or fingerprint.
  - The module sends a file source from disk in chunks. The file does not have to fit in memory.
seealso:
  - module: smcavoy.lxd.lxd_image_alias
  - name: LXD images
    description: The LXD documentation about images.
    link: https://documentation.ubuntu.com/lxd/latest/image-handling/
"""

EXAMPLES = r"""
- name: Copy Alpine from the images registry and give it a local alias
  smcavoy.lxd.lxd_image:
    aliases:
      - name: base/alpine
    source:
      image_registry: images
      alias: alpine/3.22

- name: Publish a stopped instance as an image
  smcavoy.lxd.lxd_image:
    aliases:
      - name: golden/web
        description: Web server, built on 2026-11-06
    properties:
      os: Alpine
      purpose: web
    source:
      instance: web-build

- name: Upload a split image from files on the managed node
  smcavoy.lxd.lxd_image:
    aliases:
      - name: custom/appliance
    source:
      metadata_path: /srv/images/appliance.meta.tar.xz
      rootfs_path: /srv/images/appliance.squashfs

- name: Delete the image
  smcavoy.lxd.lxd_image:
    aliases:
      - name: golden/web
    state: absent
"""

RETURN = r"""
image:
  description:
    - The image after the change, as LXD returns it.
    - In check mode, the predicted image. The fingerprint of a new image is then V(unknown), unless the task sets it.
    - V(null) after a delete.
  returned: always
  type: dict
  sample:
    fingerprint: 32cc6e69adc37342567a7be18e82d6e62f4f5c01b9ca419dcd94e5ea37f3c0b8
    type: container
    architecture: x86_64
    public: false
    auto_update: false
    size: 3145728
    aliases:
      - name: test/alpine-ct
        description: ""
    properties:
      os: Alpine
      release: "3.22"
    profiles:
      - default
    expires_at: "0001-01-01T00:00:00Z"
"""

import os
import typing as t
import uuid

from ansible_collections.smcavoy.lxd.plugins.module_utils._client import ChainedReader, LXDClientError, api_path
from ansible_collections.smcavoy.lxd.plugins.module_utils._config import merge_config, normalize_config
from ansible_collections.smcavoy.lxd.plugins.module_utils._module import LXDModule
from ansible_collections.smcavoy.lxd.plugins.module_utils._time import format_time, parse_time

if t.TYPE_CHECKING:  # pragma: no cover
    from ansible_collections.smcavoy.lxd.plugins.module_utils._typing import ArgumentSpecMutT

DIFF_FIELDS = ("aliases", "properties", "public", "auto_update", "profiles", "expires_at")
SOURCE_FORMS = {
    "registry": ("image_registry",),
    "instance": ("instance",),
    "unified": ("path",),
    "split": ("metadata_path", "rootfs_path"),
    "project": ("project",),
}


class ImageModule:
    """Manage one LXD image."""

    def __init__(self, mod: LXDModule) -> None:
        self.mod = mod
        params = mod.params
        self.aliases: list[dict[str, str]] | None = params["aliases"]
        self.expires = None
        if params["expires_at"] is not None:
            try:
                self.expires = parse_time(params["expires_at"])
            except ValueError:
                mod.fail("expires_at must be an RFC 3339 time")
        if params["public"] and (params["project"] or "default") != "default":
            mod.fail("public images are only allowed in the default project")
        if not params["fingerprint"] and not self.aliases:
            mod.fail("give fingerprint or at least one alias, so the module can find the image")

    # Find

    def find(self) -> tuple[dict[str, t.Any] | None, str | None]:
        """Find the image by fingerprint, else by the first alias."""
        fingerprint = self.mod.params["fingerprint"]
        if not fingerprint and self.aliases:
            alias, _etag = self.mod.client.get_or_none(api_path("images", "aliases", self.aliases[0]["name"]), self.mod.query())
            if alias is None:
                return None, None
            fingerprint = alias["target"]
        try:
            return self.mod.client.get_or_none(api_path("images", fingerprint), self.mod.query())
        except LXDClientError as exc:
            if "more than one" in exc.message.lower() or "multiple" in exc.message.lower():
                self.mod.fail(f"fingerprint prefix {fingerprint} matches more than one image")
            raise

    # Create

    def source_form(self) -> str:
        """Return the one source form of the task. Fail on none or more than one."""
        source = self.mod.params["source"] or {}
        forms = [name for name, keys in SOURCE_FORMS.items() if any(source.get(key) for key in keys)]
        if len(forms) != 1:
            self.mod.fail(f"source needs exactly one form: registry, instance, unified file, split file, or project. Found: {', '.join(forms) or 'none'}")
        form = forms[0]
        if form == "split" and not (source.get("metadata_path") and source.get("rootfs_path")):
            self.mod.fail("a split file source needs both metadata_path and rootfs_path")
        if form in ("registry", "project") and not (source.get("alias") or source.get("fingerprint")):
            self.mod.fail(f"a {form} source needs alias or fingerprint")
        return form

    def create(self) -> str:
        """Get the image into the store. Return its fingerprint."""
        params = self.mod.params
        source = params["source"] or {}
        form = self.source_form()
        if form == "registry":
            missing = self.mod.client.missing_extensions(["image_registries"])
            if missing:
                self.mod.fail("LXD server lacks the API extension image_registries")
            image_source = {"type": "image", "mode": "pull", "image_registry": source["image_registry"]}
            for key in ("alias", "fingerprint", "image_type", "copy_aliases"):
                if source.get(key) is not None:
                    image_source[key] = source[key]
            return self.post_json({"source": image_source})
        if form == "instance":
            if source.get("snapshot"):
                image_source = {"type": "snapshot", "name": f"{source['instance']}/{source['snapshot']}"}
            else:
                image_source = {"type": "instance", "name": source["instance"]}
            body: dict[str, t.Any] = {"source": image_source}
            if params["compression_algorithm"]:
                body["compression_algorithm"] = params["compression_algorithm"]
            return self.post_json(body)
        if form == "project":
            fingerprint = source.get("fingerprint")
            if not fingerprint:
                alias, _etag = self.mod.client.get_or_none(api_path("images", "aliases", source["alias"]), {"project": source["project"]})
                if alias is None:
                    self.mod.fail(f"image alias {source['alias']} not found in project {source['project']}")
                fingerprint = alias["target"]
            return self.post_json({"source": {"type": "image", "fingerprint": fingerprint, "project": source["project"]}})
        # The files stream from disk in chunks, so a large image does not have to fit in memory.
        if form == "unified":
            self.check_file(source["path"])
            headers = {"X-LXD-filename": os.path.basename(source["path"]), "Content-Type": "application/octet-stream"}
            return self.post_raw(ChainedReader([source["path"]]), headers)
        rootfs_part = "rootfs.img" if source.get("image_type") == "virtual-machine" else "rootfs"
        boundary = uuid.uuid4().hex
        pieces: list[bytes | str] = []
        for field, path in (("metadata", source["metadata_path"]), (rootfs_part, source["rootfs_path"])):
            self.check_file(path)
            header = (
                f'--{boundary}\r\nContent-Disposition: form-data; name="{field}"; filename="{os.path.basename(path)}"\r\n'
                "Content-Type: application/octet-stream\r\n\r\n"
            )
            pieces += [header.encode(), path, b"\r\n"]
        pieces.append(f"--{boundary}--\r\n".encode())
        return self.post_raw(ChainedReader(pieces), {"Content-Type": f"multipart/form-data; boundary={boundary}"})

    def check_file(self, path: str) -> None:
        """Fail unless a source file on the managed node can be read."""
        try:
            with open(path, "rb"):
                pass
        except OSError as exc:
            self.mod.fail(f"cannot read {path}: {exc}")

    def post_json(self, body: dict[str, t.Any]) -> str:
        """Create the image with a JSON request. Return its fingerprint."""
        return self.fingerprint_of(self.mod.write("POST", "/1.0/images", query=self.mod.query(), body=body))

    def post_raw(self, data: ChainedReader, headers: dict[str, str]) -> str:
        """Upload the image file. Return its fingerprint."""
        headers = dict(headers, **{"X-LXD-public": "false"})
        return self.fingerprint_of(self.mod.write("POST", "/1.0/images", query=self.mod.query(), raw=data, headers=headers))

    def fingerprint_of(self, meta: t.Any) -> str:
        """Return the fingerprint from the metadata of a finished create operation."""
        fingerprint = (meta or {}).get("fingerprint") if isinstance(meta, dict) else None
        if not fingerprint:
            self.mod.fail("LXD did not return the fingerprint of the new image")
        return str(fingerprint)

    # Compare and update

    def wanted(self, current: dict[str, t.Any]) -> dict[str, t.Any]:
        """Return the managed fields of the image after the task."""
        params = self.mod.params
        new = self.view(current)
        if params["properties"] is not None:
            properties, _changed = merge_config(current.get("properties") or {}, normalize_config(params["properties"]), params["properties_mode"])
            new["properties"] = properties
        for key in ("public", "auto_update", "profiles"):
            if params[key] is not None:
                new[key] = params[key]
        if params["expires_at"] is not None:
            new["expires_at"] = format_time(self.expires)
            if self.expires is None and new["expires_at"] != self.view(current)["expires_at"]:
                # LXD 6.10.1 ignores the zero time in an image update, so the expiry date would stay, and each run would report a change.
                self.mod.fail(
                    f"The image expires at {current.get('expires_at')}. LXD cannot remove the expiry date of an image. Set expires_at to a later date."
                )
        if self.aliases is not None:
            current_aliases = {item["name"]: item.get("description") or "" for item in current.get("aliases") or []}
            wanted = {
                item["name"]: item["description"] if item.get("description") is not None else current_aliases.get(item["name"], "") for item in self.aliases
            }
            if params["aliases_mode"] == "merge":
                current_aliases.update(wanted)
                wanted = current_aliases
            new["aliases"] = [{"name": name, "description": wanted[name]} for name in sorted(wanted)]
        return new

    @staticmethod
    def view(image: dict[str, t.Any]) -> dict[str, t.Any]:
        """Return the managed fields of an image in a stable form."""
        expires: str | None
        try:
            expires = format_time(parse_time(image.get("expires_at")))
        except ValueError:
            expires = image.get("expires_at")
        aliases = sorted(({"name": a["name"], "description": a.get("description") or ""} for a in image.get("aliases") or []), key=lambda a: a["name"])
        return {
            "aliases": aliases,
            "properties": dict(image.get("properties") or {}),
            "public": bool(image.get("public")),
            "auto_update": bool(image.get("auto_update")),
            "profiles": list(image.get("profiles") or []),
            "expires_at": expires,
        }

    def update(self, fingerprint: str, etag: str | None, before: dict[str, t.Any], after: dict[str, t.Any]) -> None:
        """Send the changes: a PUT for the fields, and alias requests for the aliases."""
        fields = ("properties", "public", "auto_update", "profiles", "expires_at")
        if any(before[key] != after[key] for key in fields):
            body = {key: after[key] for key in fields}
            self.mod.write("PUT", api_path("images", fingerprint), query=self.mod.query(), body=body, etag=etag)
        old = {item["name"]: item["description"] for item in before["aliases"]}
        new = {item["name"]: item["description"] for item in after["aliases"]}
        for name in sorted(set(old) - set(new)):
            self.mod.write("DELETE", api_path("images", "aliases", name), query=self.mod.query())
        for name, description in sorted(new.items()):
            if name not in old:
                other, _etag = self.mod.client.get_or_none(api_path("images", "aliases", name), self.mod.query())
                if other is not None and other.get("target") != fingerprint:
                    self.mod.fail(f"alias {name} already points to image {other.get('target')}")
                body = {"name": name, "target": fingerprint, "description": description}
                self.mod.write("POST", "/1.0/images/aliases", query=self.mod.query(), body=body)
            elif old[name] != description:
                body = {"target": fingerprint, "description": description}
                self.mod.write("PUT", api_path("images", "aliases", name), query=self.mod.query(), body=body)

    def present(self) -> None:
        """Make sure that the image exists with the wanted settings."""
        current, etag = self.find()
        if current is None:
            if not self.mod.params["source"]:
                self.mod.fail("image not found and no source given")
            self.source_form()
            if self.mod.check_mode:
                predicted: dict[str, t.Any] = {
                    "fingerprint": self.mod.params["fingerprint"] or "unknown",
                    "aliases": [],
                    "properties": {},
                    "profiles": ["default"],
                }
                after = self.wanted(predicted)
                self.mod.exit(True, before={}, after=after, image=dict(predicted, **after))
            fingerprint = self.create()
            current, etag = self.mod.client.get(api_path("images", fingerprint), self.mod.query())
            before, after = self.view(current), self.wanted(current)
            self.update(fingerprint, etag, before, after)
            self.mod.exit(True, before={}, after=after, image=self.final(fingerprint, current))
        fingerprint = current["fingerprint"]
        before, after = self.view(current), self.wanted(current)
        if before == after:
            self.mod.exit(False, before=before, after=after, image=current)
        self.update(fingerprint, etag, before, after)
        self.mod.exit(True, before=before, after=after, image=self.final(fingerprint, dict(current, **after)))

    def absent(self) -> None:
        """Make sure that the image does not exist."""
        current, _etag = self.find()
        if current is None:
            self.mod.exit(False, before={}, after={}, image=None)
        self.mod.write("DELETE", api_path("images", current["fingerprint"]), query=self.mod.query())
        self.mod.exit(True, before=self.view(current), after={}, image=None)

    def final(self, fingerprint: str, predicted: dict[str, t.Any]) -> dict[str, t.Any]:
        """Return the image from the server, or the prediction in check mode."""
        if self.mod.check_mode:
            return predicted
        image, _etag = self.mod.client.get_or_none(api_path("images", fingerprint), self.mod.query())
        return image or predicted


def get_argument_spec() -> ArgumentSpecMutT:
    """Return the argument spec of the module."""
    return {
        "fingerprint": {"type": "str"},
        "aliases": {
            "type": "list",
            "elements": "dict",
            "options": {
                "name": {"type": "str", "required": True},
                "description": {"type": "str"},
            },
        },
        "aliases_mode": {"type": "str", "default": "merge", "choices": ["merge", "exact"]},
        "project": {"type": "str"},
        "state": {"type": "str", "default": "present", "choices": ["present", "absent"]},
        "source": {
            "type": "dict",
            "options": {
                "image_registry": {"type": "str"},
                "alias": {"type": "str"},
                "fingerprint": {"type": "str"},
                "image_type": {"type": "str", "choices": ["container", "virtual-machine"]},
                "copy_aliases": {"type": "bool"},
                "instance": {"type": "str"},
                "snapshot": {"type": "str"},
                "path": {"type": "path"},
                "metadata_path": {"type": "path"},
                "rootfs_path": {"type": "path"},
                "project": {"type": "str"},
            },
        },
        "properties": {"type": "dict"},
        "properties_mode": {"type": "str", "default": "merge", "choices": ["merge", "exact"]},
        "public": {"type": "bool"},
        "auto_update": {"type": "bool"},
        "profiles": {"type": "list", "elements": "str"},
        "expires_at": {"type": "str"},
        "compression_algorithm": {"type": "str"},
    }


def main() -> None:
    """Run the module."""
    mod = LXDModule(get_argument_spec())
    image = ImageModule(mod)
    if mod.params["state"] == "present":
        mod.run(image.present)
    else:
        mod.run(image.absent)


if __name__ == "__main__":
    main()
