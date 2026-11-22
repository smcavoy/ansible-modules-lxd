# Copyright (c) 2026, Sean McAvoy
# GNU General Public License v3.0+ (see LICENSES/GPL-3.0-or-later.txt or https://www.gnu.org/licenses/gpl-3.0.txt)
# SPDX-License-Identifier: GPL-3.0-or-later

"""lxd_image against the in-memory LXD server."""

from __future__ import annotations

import hashlib

import pytest

from ansible_collections.smcavoy.lxd.plugins.module_utils._client import LXDClient
from ansible_collections.smcavoy.lxd.plugins.modules import lxd_image


@pytest.fixture(params=[False, True], ids=["sync", "async"])
def server(request, lxd):
    lxd.async_writes = request.param
    return lxd


@pytest.fixture
def tarball(tmp_path):
    path = tmp_path / "alpine.tar.gz"
    path.write_bytes(b"unified image " * 100000)
    return path


def alias_target(server, name, project=None):
    alias = server.get(f"/1.0/images/aliases/{name}", project)
    return alias and alias["target"]


def test_unified_upload_then_find_by_alias(server, run, tarball, monkeypatch):
    raws = []
    write = LXDClient.write

    def spy(self, method, path, query=None, body=None, etag=None, headers=None, raw=None):
        if raw is not None:
            raws.append((type(raw).__name__, len(raw)))
        return write(self, method, path, query=query, body=body, etag=etag, headers=headers, raw=raw)

    monkeypatch.setattr(LXDClient, "write", spy)
    fingerprint = hashlib.sha256(tarball.read_bytes()).hexdigest()
    args = {"aliases": [{"name": "alpine", "description": "base"}], "source": {"path": str(tarball)}, "properties": {"os": "Alpine"}}

    result = run(lxd_image, args, check_mode=True)
    assert result["changed"] is True, result
    assert server.writes() == []

    result = run(lxd_image, args)
    assert result["changed"] is True, result
    assert result["image"]["fingerprint"] == fingerprint
    # The file streams from disk with its length.
    assert raws == [("ChainedReader", tarball.stat().st_size)]
    assert server.image_uploads[0] == ("application/octet-stream", tarball.read_bytes())
    assert alias_target(server, "alpine") == fingerprint
    assert server.get(f"/1.0/images/{fingerprint}")["properties"] == {"os": "Alpine"}

    # The second run finds the image by its alias and uploads nothing.
    del server.requests[:]
    result = run(lxd_image, args)
    assert result["changed"] is False, result
    assert server.writes() == []
    assert len(server.image_uploads) == 1


def test_split_upload_is_one_multipart_body(lxd, run, tmp_path):
    meta = tmp_path / "meta.tar.xz"
    rootfs = tmp_path / "rootfs.squashfs"
    meta.write_bytes(b"M" * 1000)
    rootfs.write_bytes(b"R" * 3000)
    args = {
        "aliases": [{"name": "vm"}],
        "source": {"metadata_path": str(meta), "rootfs_path": str(rootfs), "image_type": "virtual-machine"},
    }
    result = run(lxd_image, args)
    assert result["changed"] is True, result
    content_type, body = lxd.image_uploads[0]
    assert content_type.startswith("multipart/form-data; boundary=")
    boundary = content_type.split("=", 1)[1].encode()
    assert body.count(b"--" + boundary) == 3
    assert b'name="metadata"; filename="meta.tar.xz"' in body
    assert b'name="rootfs.img"; filename="rootfs.squashfs"' in body
    assert b"M" * 1000 in body and b"R" * 3000 in body


def test_update_fields_and_aliases(server, run, tarball):
    run(lxd_image, {"aliases": [{"name": "alpine"}, {"name": "old"}], "source": {"path": str(tarball)}, "properties": {"os": "Alpine", "release": "3.20"}})
    fingerprint = alias_target(server, "alpine")

    args = {
        "fingerprint": fingerprint,
        "aliases": [{"name": "alpine", "description": "new"}, {"name": "edge"}],
        "aliases_mode": "exact",
        "properties": {"os": "Alpine Linux"},
        "auto_update": True,
        "expires_at": "2030-01-01T00:00:00Z",
    }
    result = run(lxd_image, args, diff=True)
    assert result["changed"] is True, result
    image = server.get(f"/1.0/images/{fingerprint}")
    # properties merge: release stays.
    assert image["properties"] == {"os": "Alpine Linux", "release": "3.20"}
    assert image["auto_update"] is True
    assert image["expires_at"].startswith("2030-01-01T00:00:00")
    assert alias_target(server, "old") is None
    assert alias_target(server, "edge") == fingerprint
    assert server.get("/1.0/images/aliases/alpine")["description"] == "new"

    del server.requests[:]
    assert run(lxd_image, args)["changed"] is False
    assert server.writes() == []

    result = run(lxd_image, {"fingerprint": fingerprint, "properties": {"os": "x"}, "properties_mode": "exact"})
    assert result["changed"] is True, result
    assert server.get(f"/1.0/images/{fingerprint}")["properties"] == {"os": "x"}


def test_alias_of_another_image_fails(lxd, run, tarball, tmp_path):
    other = tmp_path / "other.tar.gz"
    other.write_bytes(b"other image")
    run(lxd_image, {"aliases": [{"name": "taken"}], "source": {"path": str(other)}})
    run(lxd_image, {"aliases": [{"name": "alpine"}], "source": {"path": str(tarball)}})
    fingerprint = alias_target(lxd, "alpine")
    result = run(lxd_image, {"fingerprint": fingerprint, "aliases": [{"name": "taken"}]})
    assert result.get("failed") is True, result
    assert "alias taken already points to image" in result["msg"]


def test_delete_by_alias(server, run, tarball):
    run(lxd_image, {"aliases": [{"name": "alpine"}], "source": {"path": str(tarball)}})
    fingerprint = alias_target(server, "alpine")
    absent = {"aliases": [{"name": "alpine"}], "state": "absent"}
    assert run(lxd_image, absent, check_mode=True)["changed"] is True
    assert server.get(f"/1.0/images/{fingerprint}") is not None
    assert run(lxd_image, absent)["changed"] is True
    assert server.get(f"/1.0/images/{fingerprint}") is None


def test_image_from_an_instance_sends_the_source(lxd, run):
    result = run(lxd_image, {"aliases": [{"name": "snap"}], "source": {"instance": "web", "snapshot": "s1"}, "compression_algorithm": "zstd"})
    assert result["changed"] is True, result
    post = [r[2] for r in lxd.requests if r[0] == "POST" and r[1].split("?")[0] == "/1.0/images"][0]
    assert post == {"source": {"type": "snapshot", "name": "web/s1"}, "compression_algorithm": "zstd"}


@pytest.mark.parametrize(
    ("args", "text"),
    [
        ({"source": {"path": "/x"}}, "give fingerprint or at least one alias"),
        ({"aliases": [{"name": "a"}], "public": True, "project": "web"}, "public images are only allowed in the default project"),
        ({"aliases": [{"name": "a"}]}, "image not found and no source given"),
        ({"aliases": [{"name": "a"}], "source": {"path": "/x", "instance": "web"}}, "source needs exactly one form"),
        ({"aliases": [{"name": "a"}], "source": {"metadata_path": "/x"}}, "needs both metadata_path and rootfs_path"),
        ({"aliases": [{"name": "a"}], "source": {"image_registry": "images"}}, "needs alias or fingerprint"),
        ({"aliases": [{"name": "a"}], "source": {"path": "/no/such/file"}}, "cannot read /no/such/file"),
        ({"aliases": [{"name": "a"}], "expires_at": "soon", "source": {"path": "/x"}}, "RFC 3339"),
    ],
    ids=["no-key", "public-in-project", "no-source", "two-forms", "split-half", "registry-no-alias", "unreadable", "bad-expiry"],
)
def test_image_errors(lxd, run, args, text):
    lxd.add("/1.0/projects/web", {"name": "web", "config": {}, "description": ""})
    result = run(lxd_image, args)
    assert result.get("failed") is True, result
    assert text in result["msg"]
    assert lxd.writes() == []
