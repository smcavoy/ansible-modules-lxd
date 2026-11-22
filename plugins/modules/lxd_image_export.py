#!/usr/bin/python
# Copyright (c) 2026, Sean McAvoy
# GNU General Public License v3.0+ (see LICENSES/GPL-3.0-or-later.txt or https://www.gnu.org/licenses/gpl-3.0.txt)
# SPDX-License-Identifier: GPL-3.0-or-later

from __future__ import annotations

DOCUMENTATION = r"""
module: lxd_image_export
short_description: Download an LXD image to the controller
version_added: "0.1.0"
description:
  - Download the files of an image into a directory on the controller.
  - A unified image gives one file. A split image gives a metadata file and a rootfs file.
  - The module checks the SHA-256 of the files against the image fingerprint. It downloads only when the files do not match.
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
      - The image fingerprint, or a unique prefix of it.
    type: str
  alias:
    description:
      - An alias of the image. Mutually exclusive with O(fingerprint).
    type: str
  dest_dir:
    description:
      - The directory for the image files. It must exist.
      - The file names are the names that LXD gives, for example C(meta-<fingerprint>.tar.xz) and C(<fingerprint>.squashfs).
    type: path
    required: true
  force_download:
    description:
      - Download the image even when the files match.
    type: bool
    default: false
notes:
  - The module reads the whole image into memory before it writes the files.
seealso:
  - module: smcavoy.lxd.lxd_image
  - module: smcavoy.lxd.lxd_image_info
"""

EXAMPLES = r"""
- name: Save the image of the alias web-base to /srv/images
  smcavoy.lxd.lxd_image_export:
    alias: web-base
    dest_dir: /srv/images
  register: export

- name: Import the files on another server
  smcavoy.lxd.lxd_image:
    url: https://other.example.net:8443
    source:
      metadata_path: "{{ export.files[0] }}"
      rootfs_path: "{{ export.files[1] }}"
"""

RETURN = r"""
fingerprint:
  description:
    - The full fingerprint of the image.
  returned: always
  type: str
  sample: 32cc6e69adc37342567a7be18e82d6e62f4f5c01b9ca419dcd94e5ea37f3c0b8
files:
  description:
    - The paths of the image files in O(dest_dir). For a split image, the metadata file comes first.
    - In check mode before a download, the paths of the files that exist now.
  returned: always
  type: list
  elements: str
  sample:
    - /srv/images/meta-32cc6e69adc37342567a7be18e82d6e62f4f5c01b9ca419dcd94e5ea37f3c0b8.tar.xz
    - /srv/images/32cc6e69adc37342567a7be18e82d6e62f4f5c01b9ca419dcd94e5ea37f3c0b8.squashfs
"""

import glob
import hashlib
import os
import re
import tempfile
import typing as t

from ansible_collections.smcavoy.lxd.plugins.module_utils._client import CHUNK_SIZE, api_path
from ansible_collections.smcavoy.lxd.plugins.module_utils._module import LXDModule

if t.TYPE_CHECKING:  # pragma: no cover
    from ansible_collections.smcavoy.lxd.plugins.module_utils._typing import ArgumentSpecMutT

FILENAME = re.compile(r'filename\*?=(?:"([^"]+)"|([^;\s]+))', re.IGNORECASE)
BOUNDARY = re.compile(r'boundary="?([^";]+)"?', re.IGNORECASE)
FULL_FINGERPRINT = re.compile(r"^[0-9a-f]{64}$")
EXTENSION = r"(\.[A-Za-z0-9]+)*"


def expected_names(parts: t.Sequence[tuple[str, t.Any]], fingerprint: str) -> bool:
    """Return whether the file names are the names that LXD gives: C(meta-<fp><ext>) and C(<fp><ext>), or one C(<fp><ext>)."""
    meta = re.compile("^meta-" + fingerprint + EXTENSION + "$")
    data = re.compile("^" + fingerprint + EXTENSION + "$")
    names = [name for name, _content in parts]
    if len(names) == 2:
        return bool(meta.match(names[0]) and data.match(names[1]))
    return len(names) == 1 and bool(data.match(names[0]))


def header(headers: t.Mapping[str, str], name: str) -> str:
    """Return a header value, whatever the case of its name."""
    for key, value in headers.items():
        if key.lower() == name.lower():
            return value
    return ""


def filename_of(disposition: str) -> str | None:
    """Return the file name of a C(Content-Disposition) value, without a directory part."""
    match = FILENAME.search(disposition or "")
    if not match:
        return None
    return os.path.basename(match.group(1) or match.group(2))


def split_multipart(src: t.IO[bytes], boundary: str, dest_dir: str) -> tuple[list[tuple[str, str]], str]:
    """Split a multipart body from a file into one temporary file per named part, in chunks.

    Return the file name and the temporary path of each part, in order, and the SHA-256 of the part
    contents one after the other. The caller removes the temporary files.
    """
    delimiter = b"--" + boundary.encode("ascii")
    separator = b"\r\n" + delimiter
    sha = hashlib.sha256()
    parts: list[tuple[str, str]] = []

    def more() -> bytes:
        return src.read(CHUNK_SIZE)

    buf = more()
    while delimiter not in buf:
        chunk = more()
        if not chunk:
            return parts, sha.hexdigest()
        buf = buf[-len(delimiter) :] + chunk
    buf = buf[buf.index(delimiter) + len(delimiter) :]
    while True:
        while len(buf) < 2:
            chunk = more()
            if not chunk:
                return parts, sha.hexdigest()
            buf += chunk
        if buf.startswith(b"--"):
            return parts, sha.hexdigest()
        if buf.startswith(b"\r\n"):
            buf = buf[2:]
        while b"\r\n\r\n" not in buf:
            chunk = more()
            if not chunk or len(buf) > 65536:
                raise ValueError("a multipart part has no end of its headers")
            buf += chunk
        head, _end, buf = buf.partition(b"\r\n\r\n")
        disposition = ""
        for line in head.decode("latin-1").split("\r\n"):
            name, _colon, value = line.partition(":")
            if name.strip().lower() == "content-disposition":
                disposition = value.strip()
        filename = filename_of(disposition)
        handle, temp = tempfile.mkstemp(dir=dest_dir, prefix=".lxd-image-")
        with os.fdopen(handle, "wb") as out:
            while True:
                index = buf.find(separator)
                if index >= 0:
                    piece, buf = buf[:index], buf[index + len(separator) :]
                    out.write(piece)
                    if filename:
                        sha.update(piece)
                    break
                keep = len(separator) - 1
                if len(buf) > keep:
                    piece, buf = buf[:-keep], buf[-keep:]
                    out.write(piece)
                    if filename:
                        sha.update(piece)
                chunk = more()
                if not chunk:
                    os.unlink(temp)
                    raise ValueError("a multipart part has no end")
                buf += chunk
        if filename:
            parts.append((filename, temp))
        else:
            os.unlink(temp)


def candidate_sets(dest_dir: str, fingerprint: str) -> list[list[str]]:
    """Return the sets of files in O(dest_dir) that can be the image: a metadata file with a rootfs file, or one unified file."""
    meta = sorted(glob.glob(os.path.join(glob.escape(dest_dir), "meta-" + fingerprint + "*")))
    other = sorted(glob.glob(os.path.join(glob.escape(dest_dir), fingerprint + "*")))
    return [[m, o] for m in meta for o in other] + [[o] for o in other]


def matching_files(dest_dir: str, fingerprint: str) -> tuple[list[str], bool]:
    """Return the image files in O(dest_dir), and whether they match the fingerprint.

    Old files with other extensions can lie next to the right ones, so the module tries each set.
    """
    sets = candidate_sets(dest_dir, fingerprint)
    for files in sets:
        if digest(files) == fingerprint:
            return files, True
    return (sets[0] if sets else []), False


def digest(paths: t.Sequence[str]) -> str:
    """Return the SHA-256 of the files, read one after the other."""
    sha = hashlib.sha256()
    for path in paths:
        with open(path, "rb") as handle:
            for block in iter(lambda: handle.read(1 << 20), b""):
                sha.update(block)
    return sha.hexdigest()


class ExportModule:
    """Download one image."""

    def __init__(self, mod: LXDModule) -> None:
        self.mod = mod

    def resolve(self) -> str:
        """Return the full fingerprint of the image."""
        params = self.mod.params
        if params["alias"]:
            alias, _etag = self.mod.client.get_or_none(api_path("images", "aliases", params["alias"]), self.mod.query())
            if not alias:
                self.mod.fail(f"image alias {params['alias']} not found")
            reference = alias.get("target") or ""
        else:
            reference = params["fingerprint"]
        image, _etag = self.mod.client.get_or_none(api_path("images", reference), self.mod.query())
        if not image:
            self.mod.fail(f"image {reference} not found")
        fingerprint = str(image.get("fingerprint") or "")
        if not FULL_FINGERPRINT.match(fingerprint):
            self.mod.fail(f"LXD returned a fingerprint that is not a SHA-256: {fingerprint}")
        return fingerprint

    def download(self, fingerprint: str, dest_dir: str) -> list[str]:
        """Download the image, check it, and move the files into place. Return the paths.

        The download streams to a temporary file in O(dest_dir), so a large image does not have to fit in memory.
        """
        temps: list[str] = []
        try:
            handle, whole = tempfile.mkstemp(dir=dest_dir, prefix=".lxd-image-")
            temps.append(whole)
            with os.fdopen(handle, "w+b") as out:
                resp = self.mod.client.download_to(api_path("images", fingerprint, "export"), out, self.mod.query())
                content_type = header(resp.headers, "Content-Type")
                if content_type.lower().startswith("multipart/"):
                    match = BOUNDARY.search(content_type)
                    out.seek(0)
                    try:
                        parts, sha = split_multipart(out, match.group(1), dest_dir) if match else ([], "")
                    except ValueError as exc:
                        self.mod.fail(f"LXD returned a broken multipart image: {exc}")
                    temps.extend(path for _name, path in parts)
                else:
                    name = filename_of(header(resp.headers, "Content-Disposition")) or fingerprint
                    parts, sha = [(name, whole)], resp.sha256
            if not parts or len(parts) > 2:
                self.mod.fail(f"LXD returned {len(parts)} image files, not one or two")
            if not expected_names(parts, fingerprint):
                # The names come from the server. Only the names that LXD gives can land in dest_dir.
                self.mod.fail(f"LXD returned unexpected image file names: {', '.join(name for name, _path in parts)}")
            if sha != fingerprint:
                self.mod.fail(f"downloaded files do not match fingerprint {fingerprint}")
            paths = []
            # mkstemp makes the file 0600. Give it the usual mode of a new file.
            umask = os.umask(0)
            os.umask(umask)
            for name, temp in parts:
                os.chmod(temp, 0o666 & ~umask)
                path = os.path.join(dest_dir, name)
                os.replace(temp, path)
                temps.remove(temp)
                paths.append(path)
            return paths
        finally:
            for temp in temps:
                if os.path.exists(temp):
                    os.unlink(temp)

    def run(self) -> None:
        """Make sure that O(dest_dir) holds the image files."""
        params = self.mod.params
        dest_dir = params["dest_dir"]
        if not os.path.isdir(dest_dir):
            self.mod.fail(f"dest_dir does not exist: {dest_dir}")
        fingerprint = self.resolve()
        files, matched = matching_files(dest_dir, fingerprint)
        if matched and not params["force_download"]:
            self.mod.exit(False, before={"files": files}, after={"files": files}, fingerprint=fingerprint, files=files)
        if self.mod.check_mode:
            # The names of new files are known only after the download, because LXD adds the file extensions.
            self.mod.exit(True, before={"files": files, "download": False}, after={"files": files, "download": True}, fingerprint=fingerprint, files=files)
        paths = self.download(fingerprint, dest_dir)
        self.mod.exit(True, before={"files": files}, after={"files": paths}, fingerprint=fingerprint, files=paths)


def get_argument_spec() -> ArgumentSpecMutT:
    """Return the argument spec of the module."""
    return {
        "fingerprint": {"type": "str"},
        "alias": {"type": "str"},
        "project": {"type": "str"},
        "dest_dir": {"type": "path", "required": True},
        "force_download": {"type": "bool", "default": False},
    }


def main() -> None:
    """Run the module."""
    mod = LXDModule(
        get_argument_spec(),
        extensions=[],
        mutually_exclusive=[["fingerprint", "alias"]],
        required_one_of=[["fingerprint", "alias"]],
    )
    mod.run(ExportModule(mod).run)


if __name__ == "__main__":
    main()
