# Copyright (c) 2026, Sean McAvoy
# GNU General Public License v3.0+ (see LICENSES/GPL-3.0-or-later.txt or https://www.gnu.org/licenses/gpl-3.0.txt)
# SPDX-License-Identifier: GPL-3.0-or-later

from __future__ import annotations

import hashlib
import io

import pytest

from ansible_collections.smcavoy.lxd.plugins.module_utils import _client
from ansible_collections.smcavoy.lxd.plugins.modules import lxd_image_export


def multipart(boundary: str, parts: list[tuple[str, bytes]]) -> bytes:
    out = b""
    for name, content in parts:
        out += (
            (f'--{boundary}\r\nContent-Disposition: form-data; name="x"; filename="{name}"\r\nContent-Type: application/octet-stream\r\n\r\n').encode()
            + content
            + b"\r\n"
        )
    return out + f"--{boundary}--\r\n".encode()


@pytest.mark.parametrize("chunk_size", [1, 7, 64, 1 << 20])
def test_split_multipart_streams_parts_to_files(tmp_path, monkeypatch, chunk_size):
    # The chunk size moves the delimiter across chunk borders, which is where a streaming parser breaks.
    monkeypatch.setattr(lxd_image_export, "CHUNK_SIZE", chunk_size)
    meta = b"metadata\r\n--not-the-boundary\r\n"
    rootfs = bytes(range(256)) * 50
    body = multipart("b0und", [("meta-abc.tar.xz", meta), ("abc.squashfs", rootfs)])
    parts, sha = lxd_image_export.split_multipart(io.BytesIO(body), "b0und", str(tmp_path))
    assert [name for name, _path in parts] == ["meta-abc.tar.xz", "abc.squashfs"]
    assert open(parts[0][1], "rb").read() == meta
    assert open(parts[1][1], "rb").read() == rootfs
    assert sha == hashlib.sha256(meta + rootfs).hexdigest()


def test_split_multipart_refuses_a_part_without_an_end(tmp_path):
    body = b'--b\r\nContent-Disposition: form-data; name="x"; filename="f"\r\n\r\nno end here'
    with pytest.raises(ValueError, match="no end"):
        lxd_image_export.split_multipart(io.BytesIO(body), "b", str(tmp_path))
    assert list(tmp_path.iterdir()) == []


def test_chunk_size_is_shared():
    assert lxd_image_export.CHUNK_SIZE == _client.CHUNK_SIZE
