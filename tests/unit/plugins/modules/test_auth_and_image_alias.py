# Copyright (c) 2026, Sean McAvoy
# GNU General Public License v3.0+ (see LICENSES/GPL-3.0-or-later.txt or https://www.gnu.org/licenses/gpl-3.0.txt)
# SPDX-License-Identifier: GPL-3.0-or-later

"""lxd_auth_identity and lxd_image_alias against the in-memory LXD server."""

from __future__ import annotations

import base64
import hashlib
import json

import pytest

from ansible_collections.smcavoy.lxd.plugins.modules import lxd_auth_identity, lxd_image_alias


def pem(der: bytes) -> str:
    """A PEM block around some bytes. The module only decodes it to hash it."""
    return "-----BEGIN CERTIFICATE-----\n" + base64.b64encode(der).decode() + "\n-----END CERTIFICATE-----"


@pytest.fixture(params=[False, True], ids=["sync", "async"])
def server(request, lxd):
    lxd.async_writes = request.param
    return lxd


# ----------------------------------------------------------------------
# lxd_auth_identity

BEARER = "/1.0/auth/identities/bearer/ci"
TLS = "/1.0/auth/identities/tls/laptop"


def test_bearer_identity_life_cycle(server, run):
    args = {"type": "bearer", "name": "ci", "groups": ["ops", "dev", "ops"]}
    assert run(lxd_auth_identity, args, check_mode=True)["changed"] is True
    assert server.writes() == []

    result = run(lxd_auth_identity, args)
    assert result["changed"] is True, result
    assert server.get(BEARER)["groups"] == ["dev", "ops"]
    assert server.get(BEARER)["type"] == "Client token bearer"

    del server.requests[:]
    assert run(lxd_auth_identity, args)["changed"] is False
    assert server.writes() == []

    result = run(lxd_auth_identity, dict(args, groups=["dev"]), diff=True)
    assert result["changed"] is True, result
    assert server.get(BEARER)["groups"] == ["dev"]
    assert result["diff"]["before"]["groups"] == ["dev", "ops"]
    assert result["diff"]["after"]["groups"] == ["dev"]

    absent = {"type": "bearer", "name": "ci", "state": "absent"}
    assert run(lxd_auth_identity, absent)["changed"] is True
    assert server.get(BEARER) is None
    assert run(lxd_auth_identity, absent)["changed"] is False


def test_devlxd_bearer_type(lxd, run):
    result = run(lxd_auth_identity, {"type": "bearer", "name": "ci", "bearer_type": "devlxd"})
    assert result["changed"] is True, result
    assert lxd.get(BEARER)["type"] == "DevLXD token bearer"


def test_tls_identity_with_a_certificate_and_a_new_certificate(server, run):
    args = {"type": "tls", "name": "laptop", "certificate": pem(b"cert-one")}
    result = run(lxd_auth_identity, args)
    assert result["changed"] is True, result
    assert result["identity"]["fingerprint"] == hashlib.sha256(b"cert-one").hexdigest()
    assert "join_token" not in result

    del server.requests[:]
    assert run(lxd_auth_identity, args)["changed"] is False
    assert server.writes() == []

    result = run(lxd_auth_identity, dict(args, certificate=pem(b"cert-two")))
    assert result["changed"] is True, result
    assert server.get(TLS)["tls_certificate"] == pem(b"cert-two")
    assert run(lxd_auth_identity, dict(args, certificate=pem(b"cert-two")))["changed"] is False


def test_pending_tls_identity_returns_a_join_token(server, run):
    result = run(lxd_auth_identity, {"type": "tls", "name": "laptop", "pending": True, "groups": ["ops"]})
    assert result["changed"] is True, result
    token = json.loads(base64.b64decode(result["join_token"]))
    assert token["client_name"] == "laptop"
    assert token["secret"] == "s3cret"
    assert server.get(TLS)["groups"] == ["ops"]


def test_pending_tls_identity_in_check_mode_writes_nothing_and_has_no_token(lxd, run):
    result = run(lxd_auth_identity, {"type": "tls", "name": "laptop", "pending": True}, check_mode=True)
    assert result["changed"] is True, result
    assert "join_token" not in result
    assert lxd.writes() == []


@pytest.mark.parametrize(
    ("args", "text"),
    [
        ({"type": "tls", "name": "laptop"}, "certificate or pending is required"),
        ({"type": "oidc", "name": "someone@example.com"}, "only after a login"),
        ({"type": "tls", "name": "laptop", "certificate": "not a certificate"}, "not a valid PEM certificate"),
    ],
    ids=["tls-without-certificate", "oidc", "bad-certificate"],
)
def test_identity_errors(lxd, run, args, text):
    result = run(lxd_auth_identity, args)
    assert result.get("failed") is True, result
    assert text in result["msg"]
    assert lxd.writes() == []


# ----------------------------------------------------------------------
# lxd_image_alias

FP1 = "1" * 64
FP2 = "2" * 64
ALIAS = "/1.0/images/aliases/alpine"


@pytest.fixture
def images(server):
    for fp in (FP1, FP2):
        server.add(f"/1.0/images/{fp}", {"fingerprint": fp, "type": "container", "aliases": []})
    return server


def test_image_alias_life_cycle(images, run):
    args = {"name": "alpine", "target": FP1}
    assert run(lxd_image_alias, args, check_mode=True)["changed"] is True
    assert images.writes() == []

    result = run(lxd_image_alias, dict(args, description="one"))
    assert result["changed"] is True, result
    assert images.get(ALIAS)["target"] == FP1
    assert images.get(ALIAS)["description"] == "one"

    # No description: the current one stays.
    del images.requests[:]
    assert run(lxd_image_alias, args)["changed"] is False
    assert images.writes() == []

    result = run(lxd_image_alias, dict(args, target=FP2), diff=True)
    assert result["changed"] is True, result
    assert images.get(ALIAS)["target"] == FP2
    assert images.get(ALIAS)["description"] == "one"
    assert (result["diff"]["before"]["target"], result["diff"]["after"]["target"]) == (FP1, FP2)

    absent = {"name": "alpine", "state": "absent"}
    assert run(lxd_image_alias, absent)["changed"] is True
    assert images.get(ALIAS) is None
    assert images.get(f"/1.0/images/{FP2}") is not None  # the image stays
    assert run(lxd_image_alias, absent)["changed"] is False


def test_image_alias_to_a_missing_image_fails(lxd, run):
    result = run(lxd_image_alias, {"name": "alpine", "target": "f" * 64})
    assert result.get("failed") is True, result
    assert "not found" in result["msg"]
    assert lxd.writes() == []


def test_image_alias_in_a_project(images, run):
    images.add("/1.0/projects/web", {"name": "web", "config": {"features.images": "false"}, "description": ""})
    images.add(f"/1.0/images/{FP1}", {"fingerprint": FP1, "type": "container"}, project="web")
    result = run(lxd_image_alias, {"name": "alpine", "target": FP1, "project": "web"})
    assert result["changed"] is True, result
    assert images.get(ALIAS, project="web")["target"] == FP1
    assert images.get(ALIAS) is None
