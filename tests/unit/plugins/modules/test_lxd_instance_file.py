# Copyright (c) 2026, Sean McAvoy
# GNU General Public License v3.0+ (see LICENSES/GPL-3.0-or-later.txt or https://www.gnu.org/licenses/gpl-3.0.txt)
# SPDX-License-Identifier: GPL-3.0-or-later

"""lxd_instance_file against the in-memory LXD server."""

from __future__ import annotations

import hashlib
import os

import pytest

from ansible_collections.smcavoy.lxd.plugins.module_utils._client import CHUNK_SIZE, LXDClient
from ansible_collections.smcavoy.lxd.plugins.modules import lxd_instance_file

KEY = ("default", "web", "/etc/app.conf")


@pytest.fixture
def lxd_web(lxd):
    lxd.add("/1.0/instances/web", {"name": "web", "type": "container", "status": "Running", "config": {}, "devices": {}, "profiles": ["default"]})
    return lxd


def args(**extra):
    return dict({"instance": "web", "path": "/etc/app.conf"}, **extra)


def test_create_then_no_change(lxd_web, run):
    result = run(lxd_instance_file, args(content="a=1\n"))
    assert result["changed"] is True, result
    assert lxd_web.files[KEY]["content"] == b"a=1\n"
    assert (lxd_web.files[KEY]["uid"], lxd_web.files[KEY]["mode"]) == (0, "0644")
    assert result["file"]["sha256"] == hashlib.sha256(b"a=1\n").hexdigest()
    del lxd_web.requests[:]
    assert run(lxd_instance_file, args(content="a=1\n"))["changed"] is False
    assert lxd_web.writes() == []


def test_check_mode_and_diff(lxd_web, run):
    lxd_web.files[KEY] = {"type": "file", "uid": 0, "gid": 0, "mode": "0644", "content": b"a=1\n"}
    result = run(lxd_instance_file, args(content="a=2\n"), check_mode=True, diff=True)
    assert result["changed"] is True
    assert result["diff"]["before"]["content"] == "a=1\n"
    assert result["diff"]["after"]["content"] == "a=2\n"
    assert lxd_web.files[KEY]["content"] == b"a=1\n"


def test_content_change_keeps_owner_and_mode(lxd_web, run):
    # The owner and the mode stay, and the LXD refusal to overwrite a 0600 file of another owner.
    lxd_web.files[KEY] = {"type": "file", "uid": 1000, "gid": 1000, "mode": "0600", "content": b"a=1\n"}
    result = run(lxd_instance_file, args(content="a=2\n"))
    assert result["changed"] is True, result
    assert lxd_web.files[KEY] == {"type": "file", "uid": 1000, "gid": 1000, "mode": "0600", "content": b"a=2\n"}
    assert run(lxd_instance_file, args(content="a=2\n"))["changed"] is False


def test_owner_and_mode_change_only(lxd_web, run):
    lxd_web.files[KEY] = {"type": "file", "uid": 0, "gid": 0, "mode": "0644", "content": b"a=1\n"}
    result = run(lxd_instance_file, args(owner_uid=33, mode="0640"))
    assert result["changed"] is True, result
    assert lxd_web.files[KEY]["content"] == b"a=1\n"
    assert (lxd_web.files[KEY]["uid"], lxd_web.files[KEY]["mode"]) == (33, "0640")


def test_absent(lxd_web, run):
    lxd_web.files[KEY] = {"type": "file", "uid": 0, "gid": 0, "mode": "0644", "content": b"x"}
    assert run(lxd_instance_file, args(state="absent"))["changed"] is True
    assert KEY not in lxd_web.files
    assert run(lxd_instance_file, args(state="absent"))["changed"] is False


def test_absent_in_an_instance_that_does_not_exist_warns(lxd, run):
    # A missing parent is absent, with a warning.
    result = run(lxd_instance_file, args(instance="gone", state="absent"))
    assert result["changed"] is False
    assert any("/1.0/instances/gone does not exist" in str(w) for w in result.get("warnings", [])), result


def test_relative_path_fails(lxd_web, run):
    result = run(lxd_instance_file, args(path="etc/app.conf", content="x"))
    assert result["failed"] is True
    assert "absolute" in result["msg"]


@pytest.fixture
def no_whole_download(monkeypatch):
    """Fail the test when the module reads a file whole into memory."""

    def refuse(self, path, query=None):
        raise AssertionError("lxd_instance_file must stream the file with download_to, not download")

    monkeypatch.setattr(LXDClient, "download", refuse)


def test_large_src_streams_in_chunks_both_ways(lxd_web, run, tmp_path, no_whole_download):
    # The file goes to LXD from disk, and comes back to a temporary file.
    data = os.urandom(3 * CHUNK_SIZE + 17)
    src = tmp_path / "big.bin"
    src.write_bytes(data)
    result = run(lxd_instance_file, args(src=str(src)), diff=True)
    assert result["changed"] is True, result
    assert lxd_web.files[KEY]["content"] == data
    assert result["file"]["sha256"] == hashlib.sha256(data).hexdigest()
    assert "content" not in result["diff"]["after"]
    assert run(lxd_instance_file, args(src=str(src)))["changed"] is False


def test_owner_change_of_a_large_file_resends_it_from_disk(lxd_web, run, no_whole_download):
    # An owner or mode change writes the file again. The content comes from the temporary file of the read,
    # also when LXD refuses the first write (0600 file of uid 1000) and the module writes a second time.
    data = os.urandom(2 * CHUNK_SIZE + 5)
    lxd_web.files[KEY] = {"type": "file", "uid": 1000, "gid": 1000, "mode": "0600", "content": data}
    result = run(lxd_instance_file, args(owner_uid=1001))
    assert result["changed"] is True, result
    assert lxd_web.files[KEY] == {"type": "file", "uid": 1001, "gid": 1000, "mode": "0600", "content": data}
    assert [r[0] for r in lxd_web.writes()].count("POST") == 2


def test_uploads_are_streams_with_a_length(lxd_web, run, monkeypatch):
    seen = []
    write = LXDClient.write

    def spy(self, method, path, query=None, body=None, etag=None, headers=None, raw=None):
        if raw is not None:
            seen.append((type(raw).__name__, len(raw)))
        return write(self, method, path, query=query, body=body, etag=etag, headers=headers, raw=raw)

    monkeypatch.setattr(LXDClient, "write", spy)
    run(lxd_instance_file, args(content="a=1\n"))
    assert seen == [("ChainedReader", 4)]


def test_text_diff_stops_at_the_limit(lxd_web, run):
    big = "x" * (lxd_instance_file.DIFF_TEXT_LIMIT + 1)
    lxd_web.files[KEY] = {"type": "file", "uid": 0, "gid": 0, "mode": "0644", "content": b"small\n"}
    result = run(lxd_instance_file, args(content=big), check_mode=True, diff=True)
    assert result["diff"]["before"]["content"] == "small\n"
    assert "content" not in result["diff"]["after"]


def test_a_new_file_that_does_not_fit_is_deleted(lxd_web, run):
    # LXD 6.10.1 creates the file, then fails the write on a full disk, and leaves an empty file.
    lxd_web.disk_free = 10
    result = run(lxd_instance_file, args(content="x" * 100))
    assert result.get("failed") is True, result
    assert "no space left on device" in result["msg"]
    assert "deleted the /etc/app.conf that LXD left" in result["msg"]
    assert KEY not in lxd_web.files


def test_an_existing_file_that_does_not_fit_gets_its_old_content_back(lxd_web, run):
    # LXD 6.10.1 empties the file, then fails the write on a full disk. The old content is lost unless the module writes it back.
    lxd_web.files[KEY] = {"type": "file", "uid": 1000, "gid": 1000, "mode": "0640", "content": b"old=1\n"}
    lxd_web.disk_free = 10
    result = run(lxd_instance_file, args(content="x" * 100))
    assert result.get("failed") is True, result
    assert "no space left on device" in result["msg"]
    assert "wrote the old content of /etc/app.conf back" in result["msg"]
    assert lxd_web.files[KEY] == {"type": "file", "uid": 1000, "gid": 1000, "mode": "0640", "content": b"old=1\n"}


def test_the_write_converges_once_there_is_space(lxd_web, run):
    lxd_web.files[KEY] = {"type": "file", "uid": 0, "gid": 0, "mode": "0644", "content": b"old=1\n"}
    lxd_web.disk_free = 10
    assert run(lxd_instance_file, args(content="x" * 100)).get("failed") is True
    lxd_web.disk_free = 1000
    result = run(lxd_instance_file, args(content="x" * 100))
    assert result["changed"] is True
    assert lxd_web.files[KEY]["content"] == b"x" * 100


def test_a_write_that_lxd_accepts_but_does_not_store_fails(lxd_web, run):
    # LXD 6.10.1 on a full btrfs pool answers a small write with success and stores nothing.
    lxd_web.files[KEY] = {"type": "file", "uid": 0, "gid": 0, "mode": "0644", "content": b"old=1\n"}
    lxd_web.disk_silent = True
    result = run(lxd_instance_file, args(content="new=1\n"))
    assert result.get("failed") is True, result
    assert "holds other content" in result["msg"]
    assert "could not write the old content back" in result["msg"]


def test_a_new_file_that_lxd_does_not_store_is_deleted(lxd_web, run):
    lxd_web.disk_silent = True
    result = run(lxd_instance_file, args(content="new=1\n"))
    assert result.get("failed") is True, result
    assert "deleted the /etc/app.conf that LXD left" in result["msg"]
    assert KEY not in lxd_web.files
