# Copyright (c) 2026, Sean McAvoy
# GNU General Public License v3.0+ (see LICENSES/GPL-3.0-or-later.txt or https://www.gnu.org/licenses/gpl-3.0.txt)
# SPDX-License-Identifier: GPL-3.0-or-later

from __future__ import annotations

import hashlib
import json
import typing as t

import pytest
from ansible.module_utils.testing import patch_module_args

from ansible_collections.smcavoy.lxd.plugins.module_utils._client import LXDClient, LXDResponse

from .fake_lxd import FakeLXD

CONNECTION = {"url": "https://lxd.test:8443", "validate_certs": False}


@pytest.fixture
def lxd(monkeypatch) -> FakeLXD:
    """An in-memory LXD server. Every LXDClient of the test talks to it."""
    server = FakeLXD()

    def exchange(self, method, target, data, headers, timeout, sink=None, error_only=False):
        resp = server.handle(method, target, data, headers)
        if method == "HEAD" and resp.status >= 400:
            # The answer to a HEAD has no body. The client reads the error text with a GET.
            return LXDResponse(resp.status, resp.headers, b"")
        if error_only and resp.status < 400:
            return LXDResponse(resp.status, resp.headers, b"")
        if sink is not None and resp.status < 400:
            # Like the real client: the body goes into the file, and the response holds its size and SHA-256.
            sink.seek(0)
            sink.truncate()
            sink.write(resp.body)
            return LXDResponse(resp.status, resp.headers, b"", size=len(resp.body), sha256=hashlib.sha256(resp.body).hexdigest())
        return resp

    monkeypatch.setattr(LXDClient, "_exchange", exchange)
    monkeypatch.setattr(LXDClient, "missing_extensions", lambda self, names: [])
    return server


@pytest.fixture
def run(capsys):
    """Return a function that runs the main() of a module: run(module, args, check_mode=False, diff=False)."""

    def runner(module: t.Any, args: dict[str, t.Any], check_mode: bool = False, diff: bool = False) -> dict[str, t.Any]:
        full = dict(CONNECTION, **args)
        if check_mode:
            full["_ansible_check_mode"] = True
        if diff:
            full["_ansible_diff"] = True
        capsys.readouterr()
        with patch_module_args(full), pytest.raises(SystemExit):
            module.main()
        return json.loads(capsys.readouterr().out)

    return runner
