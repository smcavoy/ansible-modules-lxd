# Copyright (c) 2026, Sean McAvoy
# GNU General Public License v3.0+ (see LICENSES/GPL-3.0-or-later.txt or https://www.gnu.org/licenses/gpl-3.0.txt)
# SPDX-License-Identifier: GPL-3.0-or-later

"""The trust store, token, cluster certificate, cluster link, and warning modules against the in-memory LXD server.

Each module runs through main(). The tests check the requests that the server got and the values of the result:
check mode, create, a second run, an update, delete, and the rules of each module.
"""

from __future__ import annotations

import base64
import hashlib
import json
import os
import subprocess
import tempfile

import pytest

from ansible_collections.smcavoy.lxd.plugins.modules import (
    lxd_cluster_certificate,
    lxd_cluster_join_token,
    lxd_cluster_link,
    lxd_trust_certificate,
    lxd_trust_token,
    lxd_warning,
)


def pem(der: bytes) -> str:
    """A PEM block around some bytes. The trust store modules only decode it to hash it."""
    return "-----BEGIN CERTIFICATE-----\n" + base64.b64encode(der).decode() + "\n-----END CERTIFICATE-----"


def fingerprint(der: bytes) -> str:
    return hashlib.sha256(der).hexdigest()


def decoded(token: str) -> dict:
    return json.loads(base64.b64decode(token))


@pytest.fixture(params=[False, True], ids=["sync", "async"])
def server(request, lxd):
    lxd.async_writes = request.param
    return lxd


@pytest.fixture
def cluster(lxd):
    lxd.server_info["environment"]["server_clustered"] = True
    lxd.add("/1.0/cluster/members/node1", {"server_name": "node1", "status": "Online", "roles": [], "groups": ["default"], "config": {}})
    return lxd


# ----------------------------------------------------------------------
# lxd_trust_certificate

DER = b"certificate one"
CERT = pem(DER)
FP = fingerprint(DER)
ENTRY = f"/1.0/certificates/{FP}"


def test_trust_certificate_life_cycle(server, run):
    args = {"certificate": CERT, "name": "ci", "restricted": True, "projects": ["web", "ci", "web"]}
    wanted = {"name": "ci", "type": "client", "restricted": True, "projects": ["ci", "web"]}

    result = run(lxd_trust_certificate, args, check_mode=True)
    assert result["changed"] is True, result
    assert result["certificate"] == dict(wanted, fingerprint=FP)
    assert server.writes() == []

    result = run(lxd_trust_certificate, args, diff=True)
    assert result["changed"] is True, result
    # LXD gets the base64 body of the certificate, without the PEM lines, and the projects once each.
    assert server.writes() == [("POST", "/1.0/certificates", dict(wanted, certificate=base64.b64encode(DER).decode()))]
    assert result["certificate"] == server.get(ENTRY)
    assert result["certificate"]["fingerprint"] == FP
    assert result["diff"] == {"before": {}, "after": wanted}

    # The projects are a set: another order is no change.
    del server.requests[:]
    result = run(lxd_trust_certificate, dict(args, projects=["web", "ci"]))
    assert result["changed"] is False, result
    assert server.writes() == []

    # An update by the start of the fingerprint, without the certificate and without a name: the name stays.
    result = run(lxd_trust_certificate, {"fingerprint": FP[:12].upper(), "type": "metrics"}, diff=True)
    assert result["changed"] is True, result
    after = {"name": "ci", "type": "metrics", "restricted": False, "projects": []}
    assert server.writes() == [("PUT", ENTRY, dict(after, certificate=CERT + "\n"))]
    assert result["diff"] == {"before": wanted, "after": after}
    assert {key: result["certificate"][key] for key in after} == after

    del server.requests[:]
    absent = {"fingerprint": FP, "state": "absent"}
    result = run(lxd_trust_certificate, absent, check_mode=True)
    assert result["changed"] is True, result
    assert server.writes() == [] and server.get(ENTRY) is not None

    result = run(lxd_trust_certificate, absent)
    assert result["changed"] is True, result
    assert server.writes() == [("DELETE", ENTRY, None)]
    assert result["certificate"] is None and server.get(ENTRY) is None

    del server.requests[:]
    result = run(lxd_trust_certificate, absent)
    assert result["changed"] is False, result
    assert server.writes() == []


@pytest.mark.parametrize(
    ("args", "text"),
    [
        ({"fingerprint": FP}, f"certificate {FP[:12]} is not trusted, and the task gives no certificate to add"),
        ({"certificate": CERT, "projects": ["web"]}, "projects needs restricted=true"),
        ({"certificate": "not a certificate"}, "certificate is not a PEM certificate"),
    ],
    ids=["unknown-fingerprint", "projects-unrestricted", "not-pem"],
)
def test_trust_certificate_refusals(lxd, run, args, text):
    result = run(lxd_trust_certificate, args)
    assert result["failed"] is True
    assert result["msg"] == text
    assert lxd.writes() == []


def test_trust_certificate_does_not_remove_the_certificate_of_the_task(lxd, run, tmp_path):
    own = tmp_path / "client.crt"
    own.write_text(CERT + "\n")
    key = tmp_path / "client.key"
    key.write_text("key\n")
    other = tmp_path / "other.crt"
    other.write_text(pem(b"another certificate") + "\n")
    run(lxd_trust_certificate, {"certificate": CERT, "name": "me"})
    del lxd.requests[:]

    args = {"fingerprint": FP, "state": "absent", "client_key": str(key)}
    result = run(lxd_trust_certificate, dict(args, client_cert=str(own)))
    assert result["failed"] is True
    assert result["msg"] == "the task connects with this certificate. Removing it would lock the task out"
    assert lxd.writes() == [] and lxd.get(ENTRY) is not None

    result = run(lxd_trust_certificate, dict(args, client_cert=str(other)))
    assert result["changed"] is True, result
    assert lxd.get(ENTRY) is None


# ----------------------------------------------------------------------
# lxd_trust_token


def test_trust_token_life_cycle(lxd, run):
    lxd.next_token_expires_at = "2026-12-01T00:00:00Z"
    args = {"name": "laptop"}

    result = run(lxd_trust_token, args, check_mode=True)
    assert result["changed"] is True, result
    assert "token" not in result
    assert lxd.writes() == [] and lxd.live_operations == {}

    result = run(lxd_trust_token, args)
    assert result["changed"] is True, result
    assert lxd.writes() == [("POST", "/1.0/certificates", {"name": "laptop", "type": "client", "token": True, "restricted": False})]
    # The token is what "lxc remote add" takes: base64 of JSON with the name, the secret, and where the server is.
    assert decoded(result["token"]) == {
        "client_name": "laptop",
        "fingerprint": "c" * 64,
        "addresses": ["192.0.2.1:8443"],
        "secret": "s3cret-1",
        "expires_at": "2026-12-01T00:00:00Z",
    }
    assert result["operation"] == "token-op-1"
    assert result["expires_at"] == "2026-12-01T00:00:00Z"

    # A second run issues no token, and does not show the secret of the open one.
    del lxd.requests[:]
    result = run(lxd_trust_token, args)
    assert result["changed"] is False, result
    assert result["msg"] == "a trust token for laptop is already open"
    assert lxd.writes() == []
    assert "token" not in result and "s3cret" not in json.dumps(result)

    result = run(lxd_trust_token, dict(args, force=True), check_mode=True)
    assert result["changed"] is True and lxd.writes() == []
    result = run(lxd_trust_token, dict(args, force=True))
    assert result["changed"] is True, result
    assert decoded(result["token"])["secret"] == "s3cret-2"
    assert sorted(lxd.live_operations) == ["token-op-1", "token-op-2"]


def test_trust_token_revokes_only_the_tokens_of_its_name(lxd, run):
    run(lxd_trust_token, {"name": "laptop"})
    run(lxd_trust_token, {"name": "laptop", "force": True})
    run(lxd_trust_token, {"name": "desktop"})
    # A join token for a member with the same name is not a trust token.
    lxd.add_operation({"id": "join-1", "class": "token", "status": "Running", "metadata": {"serverName": "laptop", "secret": "j"}})
    del lxd.requests[:]

    absent = {"name": "laptop", "state": "absent"}
    result = run(lxd_trust_token, absent, check_mode=True)
    assert result["changed"] is True, result
    assert result["revoked"] == ["token-op-1", "token-op-2"]
    assert lxd.writes() == []

    result = run(lxd_trust_token, absent)
    assert result["changed"] is True, result
    assert result["revoked"] == ["token-op-1", "token-op-2"]
    assert lxd.writes() == [("DELETE", "/1.0/operations/token-op-1", None), ("DELETE", "/1.0/operations/token-op-2", None)]
    assert sorted(lxd.live_operations) == ["join-1", "token-op-3"]

    del lxd.requests[:]
    result = run(lxd_trust_token, absent)
    assert result["changed"] is False, result
    assert "revoked" not in result and lxd.writes() == []


def test_trust_token_restricted_to_projects(lxd, run):
    result = run(lxd_trust_token, {"name": "ci", "restricted": True, "projects": ["web"]})
    assert result["changed"] is True, result
    assert lxd.writes()[0][2] == {"name": "ci", "type": "client", "token": True, "restricted": True, "projects": ["web"]}

    # A restricted token without projects sends an empty list, not a missing key.
    result = run(lxd_trust_token, {"name": "ci2", "restricted": True})
    assert lxd.writes()[1][2]["projects"] == []

    del lxd.requests[:]
    result = run(lxd_trust_token, {"name": "ci3", "projects": ["web"]})
    assert result["failed"] is True
    assert result["msg"] == "projects needs restricted=true"
    assert lxd.writes() == []


# ----------------------------------------------------------------------
# lxd_cluster_certificate
#
# Two self-signed test pairs (EC P-256, CN unit-test-a and unit-test-b). The module checks the pair with OpenSSL, so the
# tests need real ones. The tests make them when they start; the repository holds no private key.


def make_pair(common_name: str) -> tuple[str, str]:
    """Return a new self-signed certificate and its key as PEM text. It needs the openssl program, as the module does."""
    with tempfile.TemporaryDirectory() as folder:
        key, cert = os.path.join(folder, "key.pem"), os.path.join(folder, "cert.pem")
        command = ["openssl", "req", "-x509", "-newkey", "ec", "-pkeyopt", "ec_paramgen_curve:prime256v1", "-nodes"]
        command += ["-keyout", key, "-out", cert, "-days", "2", "-subj", f"/CN={common_name}"]
        subprocess.run(command, check=True, capture_output=True)
        with open(cert, encoding="utf-8") as cert_file, open(key, encoding="utf-8") as key_file:
            return cert_file.read(), key_file.read()


CERT_A, KEY_A = make_pair("unit-test-a")
CERT_B, KEY_B = make_pair("unit-test-b")


def pem_fp(text: str) -> str:
    body = "".join(line for line in text.strip().splitlines() if not line.startswith("-----"))
    return fingerprint(base64.b64decode(body))


FP_A, FP_B = pem_fp(CERT_A), pem_fp(CERT_B)


@pytest.fixture
def with_cert_a(server):
    server.server_info["environment"]["certificate_fingerprint"] = FP_A
    return server


def test_cluster_certificate_replaces_another_certificate(with_cert_a, run):
    server = with_cert_a
    args = {"certificate": CERT_B, "key": KEY_B}

    result = run(lxd_cluster_certificate, args, check_mode=True)
    assert result["changed"] is True, result
    assert (result["fingerprint"], result["previous_fingerprint"]) == (FP_B, FP_A)
    assert server.writes() == []

    result = run(lxd_cluster_certificate, args, diff=True)
    assert result["changed"] is True, result
    assert server.writes() == [("PUT", "/1.0/cluster/certificate", {"cluster_certificate": CERT_B, "cluster_certificate_key": KEY_B})]
    assert (result["fingerprint"], result["previous_fingerprint"]) == (FP_B, FP_A)
    assert result["diff"] == {"before": {"fingerprint": FP_A}, "after": {"fingerprint": FP_B}}
    # The key is a secret. No line of it is in the result.
    assert not [line for line in KEY_B.splitlines()[1:-1] if line in json.dumps(result)]

    del server.requests[:]
    result = run(lxd_cluster_certificate, args)
    assert result["changed"] is False, result
    assert (result["fingerprint"], result["previous_fingerprint"]) == (FP_B, FP_B)
    assert server.writes() == []


def test_cluster_certificate_compares_the_first_certificate_of_a_chain(with_cert_a, run):
    result = run(lxd_cluster_certificate, {"certificate": CERT_A + CERT_B, "key": KEY_A})
    assert result["changed"] is False, result
    assert result["fingerprint"] == FP_A
    assert with_cert_a.writes() == []


@pytest.mark.parametrize(
    ("args", "text"),
    [
        ({"certificate": CERT_B, "key": KEY_A}, "key does not match certificate"),
        ({"certificate": CERT_B, "key": KEY_B.replace("PRIVATE", "ENCRYPTED PRIVATE")}, "key is encrypted. Give the key without a passphrase."),
        ({"certificate": "not a certificate", "key": KEY_B}, "certificate is not a PEM certificate"),
    ],
    ids=["other-key", "encrypted-key", "not-pem"],
)
def test_cluster_certificate_checks_the_pair_before_it_sends_it(lxd, run, args, text):
    lxd.server_info["environment"]["certificate_fingerprint"] = FP_A
    result = run(lxd_cluster_certificate, args)
    assert result["failed"] is True
    assert result["msg"] == text
    assert lxd.writes() == []
    assert lxd.server_info["environment"]["certificate_fingerprint"] == FP_A


# ----------------------------------------------------------------------
# lxd_cluster_join_token


def test_join_token_needs_a_cluster(lxd, run):
    result = run(lxd_cluster_join_token, {"name": "node4"})
    assert result["failed"] is True
    assert result["msg"] == "This server is not clustered"
    assert lxd.writes() == []


def test_join_token_life_cycle(cluster, run):
    args = {"name": "node4"}
    result = run(lxd_cluster_join_token, args, check_mode=True)
    assert result["changed"] is True, result
    assert "token" not in result and cluster.writes() == []

    result = run(lxd_cluster_join_token, args)
    assert result["changed"] is True, result
    assert cluster.writes() == [("POST", "/1.0/cluster/members", {"server_name": "node4"})]
    assert decoded(result["token"]) == {
        "server_name": "node4",
        "fingerprint": "c" * 64,
        "addresses": ["192.0.2.1:8443"],
        "secret": "s3cret-1",
        "expires_at": "0001-01-01T00:00:00Z",
    }
    assert result["operation"] == "token-op-1"

    del cluster.requests[:]
    result = run(lxd_cluster_join_token, args)
    assert result["changed"] is False, result
    assert result["msg"] == "a join token for node4 is already open"
    assert "token" not in result and "s3cret" not in json.dumps(result)
    assert cluster.writes() == []

    result = run(lxd_cluster_join_token, dict(args, force=True))
    assert result["changed"] is True, result
    assert decoded(result["token"])["secret"] == "s3cret-2"

    # Absent revokes the tokens of this name only: not the one of node5, and not a trust token for a client "node4".
    run(lxd_cluster_join_token, {"name": "node5"})
    cluster.add_operation({"id": "trust-1", "class": "token", "status": "Running", "metadata": {"request": {"name": "node4"}, "secret": "t"}})
    del cluster.requests[:]
    absent = dict(args, state="absent")
    result = run(lxd_cluster_join_token, absent, check_mode=True)
    assert result["changed"] is True and result["revoked"] == ["token-op-1", "token-op-2"]
    assert cluster.writes() == []

    result = run(lxd_cluster_join_token, absent)
    assert result["changed"] is True, result
    assert cluster.writes() == [("DELETE", "/1.0/operations/token-op-1", None), ("DELETE", "/1.0/operations/token-op-2", None)]
    assert sorted(cluster.live_operations) == ["token-op-3", "trust-1"]

    result = run(lxd_cluster_join_token, absent)
    assert result["changed"] is False, result


@pytest.mark.parametrize("force", [False, True])
def test_join_token_for_a_name_that_is_a_member_issues_nothing(cluster, run, force):
    result = run(lxd_cluster_join_token, {"name": "node1", "force": force})
    assert result["changed"] is False, result
    assert result["msg"] == "node1 is already a cluster member"
    assert "token" not in result
    assert cluster.writes() == []


# ----------------------------------------------------------------------
# lxd_cluster_link

LINK = "/1.0/cluster/links/site-b"
LINK_IDENTITY = "/1.0/auth/identities/tls/site-b"


@pytest.mark.parametrize(
    ("args", "text"),
    [
        ({"type": "public", "link_token": "abc"}, "link_token and auth_groups are not for a public link"),
        ({"type": "public", "auth_groups": ["g"]}, "link_token and auth_groups are not for a public link"),
        ({"remote_address": "192.0.2.9:8443"}, "remote_address and fingerprint are only for a public link"),
        ({"type": "unidirectional", "fingerprint": "0" * 64}, "remote_address and fingerprint are only for a public link"),
        ({"config": {"limits.x": "1"}}, "config key limits.x is not a user.* key"),
        ({"type": "public"}, "remote_address is required to create a public link"),
    ],
)
def test_cluster_link_refusals(lxd, run, args, text):
    result = run(lxd_cluster_link, dict(args, name="site-b"))
    assert result["failed"] is True
    assert result["msg"] == text
    assert lxd.writes() == []


def test_cluster_link_warns_when_a_task_gives_only_the_connection_option_trust_token(server, run):
    """A task from before 0.2.0 gave the link token as trust_token. It makes a pending link now, with a warning that says why."""
    result = run(lxd_cluster_link, {"name": "site-b", "trust_token": "t0ken-fr0m-b"})
    assert result["changed"] is True and result["pending"] is True, result
    assert any("link_token since version 0.2.0" in str(warning) for warning in result.get("warnings", [])), result
    assert [body for method, path, body in server.writes() if "trust_token" in (body or {})] == []


def test_cluster_link_pending_then_updated_then_deleted(server, run):
    args = {"name": "site-b", "description": "link to B", "config": {"user.a": 1}, "auth_groups": ["links"]}

    result = run(lxd_cluster_link, args, check_mode=True)
    assert result["changed"] is True, result
    assert result["pending"] is True and "link_token" not in result
    assert server.writes() == []

    result = run(lxd_cluster_link, args)
    assert result["changed"] is True, result
    body = {"name": "site-b", "type": "bidirectional", "description": "link to B", "config": {"user.a": "1"}, "auth_groups": ["links"]}
    assert server.writes() == [("POST", "/1.0/cluster/links", body)]
    assert result["pending"] is True
    assert result["link"]["type"] == "bidirectional"
    # The token for the other cluster is the answer of LXD, as base64 of JSON.
    assert decoded(result["link_token"])["secret"] == "s3cret-1"
    assert decoded(result["link_token"])["client_name"] == "site-b"

    # A second run makes no second token.
    del server.requests[:]
    result = run(lxd_cluster_link, args)
    assert result["changed"] is False, result
    assert result["pending"] is True and "link_token" not in result
    assert server.writes() == []

    # The other cluster used the token: the link has addresses. An exact config keeps the volatile keys.
    server.get(LINK)["config"]["volatile.addresses"] = "192.0.2.2:8443"
    update = {"name": "site-b", "description": "to B", "config": {"user.b": "2"}, "config_mode": "exact"}
    result = run(lxd_cluster_link, update, check_mode=True)
    assert result["changed"] is True and server.writes() == []

    result = run(lxd_cluster_link, update, diff=True)
    assert result["changed"] is True, result
    assert server.writes() == [("PUT", LINK, {"description": "to B", "config": {"user.b": "2", "volatile.addresses": "192.0.2.2:8443"}})]
    assert result["pending"] is False
    assert result["diff"]["before"]["config"] == {"user.a": "1", "volatile.addresses": "192.0.2.2:8443"}
    assert result["link"]["description"] == "to B"

    # The type applies only on create.
    del server.requests[:]
    result = run(lxd_cluster_link, dict(update, type="unidirectional"))
    assert result["changed"] is False, result
    assert any("type applies only on create" in str(w) for w in result["warnings"]), result
    assert server.writes() == [] and server.get(LINK)["type"] == "bidirectional"

    absent = {"name": "site-b", "state": "absent"}
    result = run(lxd_cluster_link, absent, check_mode=True)
    assert result["changed"] is True and server.writes() == []

    result = run(lxd_cluster_link, absent)
    assert result["changed"] is True, result
    assert server.writes() == [("DELETE", LINK, None)]
    assert result["link"] is None and server.get(LINK) is None

    del server.requests[:]
    result = run(lxd_cluster_link, absent)
    assert result["changed"] is False, result
    assert server.writes() == []


def test_cluster_link_with_a_token_is_active_and_hides_the_token(server, run):
    args = {"name": "site-b", "link_token": "t0ken-fr0m-b"}
    result = run(lxd_cluster_link, args, check_mode=True)
    assert result["changed"] is True and result["pending"] is False
    assert server.writes() == []

    result = run(lxd_cluster_link, args)
    assert result["changed"] is True, result
    assert server.writes() == [
        ("POST", "/1.0/cluster/links", {"name": "site-b", "type": "bidirectional", "description": "", "config": {}, "trust_token": "t0ken-fr0m-b"})
    ]
    assert result["pending"] is False
    assert "link_token" not in result
    assert "t0ken-fr0m-b" not in json.dumps(result)

    del server.requests[:]
    result = run(lxd_cluster_link, args)
    assert result["changed"] is False, result
    assert result["pending"] is False and server.writes() == []


def test_cluster_link_pending_unidirectional_is_only_an_identity(server, run):
    args = {"name": "site-b", "type": "unidirectional"}
    result = run(lxd_cluster_link, args)
    assert result["changed"] is True, result
    assert result["link"] is None and result["pending"] is True
    assert decoded(result["link_token"])["secret"] == "s3cret-1"
    assert server.get(LINK) is None and server.get(LINK_IDENTITY) is not None

    del server.requests[:]
    result = run(lxd_cluster_link, args)
    assert result["changed"] is False, result
    assert result["msg"] == "a token for link site-b is already open"
    assert result["pending"] is True and "link_token" not in result
    assert server.writes() == []

    absent = {"name": "site-b", "state": "absent"}
    result = run(lxd_cluster_link, absent, check_mode=True)
    assert result["changed"] is True and server.writes() == []

    result = run(lxd_cluster_link, absent)
    assert result["changed"] is True, result
    assert server.writes() == [("DELETE", LINK_IDENTITY, None)]

    del server.requests[:]
    result = run(lxd_cluster_link, absent)
    assert result["changed"] is False, result
    assert server.writes() == []


REMOTE_DER = b"the certificate of the other cluster"
PUBLIC = {"name": "site-b", "type": "public", "remote_address": "192.0.2.9:8443"}
PUBLIC_BODY = {"name": "site-b", "type": "public", "description": "", "config": {}, "remote_address": "192.0.2.9:8443"}
CONFIRM_BODY = {"name": "site-b", "type": "public", "fingerprint": fingerprint(REMOTE_DER)}


def test_public_cluster_link_in_two_steps(server, run):
    server.link_remote_certificate = pem(REMOTE_DER)
    result = run(lxd_cluster_link, PUBLIC)
    assert result["changed"] is True, result
    assert server.writes() == [("POST", "/1.0/cluster/links", PUBLIC_BODY)]
    assert result["remote_fingerprint"] == fingerprint(REMOTE_DER)
    assert result["pending"] is True

    del server.requests[:]
    result = run(lxd_cluster_link, PUBLIC)
    assert result["changed"] is False and result["pending"] is True
    assert server.writes() == []

    # The fingerprint confirms the certificate that the pending link holds. Upper case is the same fingerprint.
    confirm = dict(PUBLIC, fingerprint=fingerprint(REMOTE_DER).upper())
    result = run(lxd_cluster_link, confirm, check_mode=True)
    assert result["changed"] is True and server.writes() == []

    result = run(lxd_cluster_link, confirm)
    assert result["changed"] is True, result
    assert server.writes() == [("POST", "/1.0/cluster/links", CONFIRM_BODY)]
    assert result["remote_fingerprint"] == fingerprint(REMOTE_DER)
    assert "volatile.pending_certificate" not in result["link"]["config"]

    del server.requests[:]
    result = run(lxd_cluster_link, confirm)
    assert result["changed"] is False, result
    assert result["pending"] is False and server.writes() == []


def test_public_cluster_link_in_one_step(server, run):
    server.link_remote_certificate = pem(REMOTE_DER)
    result = run(lxd_cluster_link, dict(PUBLIC, fingerprint=fingerprint(REMOTE_DER)))
    assert result["changed"] is True, result
    assert server.writes() == [("POST", "/1.0/cluster/links", PUBLIC_BODY), ("POST", "/1.0/cluster/links", CONFIRM_BODY)]
    assert result["pending"] is False
    assert result["link"]["config"]["volatile.addresses"] == "192.0.2.9:8443"


@pytest.mark.parametrize("exists", [False, True], ids=["on-create", "on-a-pending-link"])
def test_public_cluster_link_with_a_wrong_fingerprint_stays_pending(lxd, run, exists):
    lxd.link_remote_certificate = pem(REMOTE_DER)
    if exists:
        run(lxd_cluster_link, PUBLIC)
        del lxd.requests[:]
    result = run(lxd_cluster_link, dict(PUBLIC, fingerprint="0" * 64))
    assert result["failed"] is True
    assert result["msg"] == f"remote fingerprint {fingerprint(REMOTE_DER)} does not match {'0' * 64}"
    assert result["remote_fingerprint"] == fingerprint(REMOTE_DER)
    assert result["link"]["config"]["volatile.pending_certificate"] == pem(REMOTE_DER)
    # No confirmation went to the server.
    assert lxd.writes() == ([] if exists else [("POST", "/1.0/cluster/links", PUBLIC_BODY)])
    assert "volatile.addresses" not in lxd.get(LINK)["config"]


# ----------------------------------------------------------------------
# lxd_warning

UUID = "e9f1b4a0-4a43-4c0f-9a6b-0b5f8a0c1d2e"
WARNING_PATH = f"/1.0/warnings/{UUID}"
WARNING = {
    "uuid": UUID,
    "type": "Couldn't find the CGroup memory swap accounting",
    "severity": "low",
    "status": "new",
    "count": 3,
    "location": "none",
    "project": "",
    "last_message": "swap",
}


def test_warning_status_and_delete(lxd, run):
    lxd.add(WARNING_PATH, WARNING)
    args = {"uuid": UUID, "status": "acknowledged"}

    result = run(lxd_warning, args, check_mode=True, diff=True)
    assert result["changed"] is True, result
    assert result["warning"] == dict(WARNING, status="acknowledged")
    assert result["diff"] == {"before": {"status": "new"}, "after": {"status": "acknowledged"}}
    assert lxd.writes() == [] and lxd.get(WARNING_PATH)["status"] == "new"

    result = run(lxd_warning, args)
    assert result["changed"] is True, result
    # Only the status goes to LXD.
    assert lxd.writes() == [("PUT", WARNING_PATH, {"status": "acknowledged"})]
    assert result["warning"] == dict(WARNING, status="acknowledged") == lxd.get(WARNING_PATH)

    del lxd.requests[:]
    result = run(lxd_warning, args)
    assert result["changed"] is False, result
    assert lxd.writes() == []

    # Without a status the module only checks that the warning exists.
    result = run(lxd_warning, {"uuid": UUID})
    assert result["changed"] is False, result
    assert result["warning"]["status"] == "acknowledged"
    assert lxd.writes() == []

    result = run(lxd_warning, {"uuid": UUID, "status": "new"})
    assert result["changed"] is True, result
    assert lxd.writes() == [("PUT", WARNING_PATH, {"status": "new"})]

    del lxd.requests[:]
    absent = {"uuid": UUID, "state": "absent"}
    result = run(lxd_warning, absent, check_mode=True)
    assert result["changed"] is True and lxd.writes() == []

    result = run(lxd_warning, absent, diff=True)
    assert result["changed"] is True, result
    assert lxd.writes() == [("DELETE", WARNING_PATH, None)]
    assert result["warning"] is None
    assert result["diff"] == {"before": {"status": "new"}, "after": {}}

    del lxd.requests[:]
    result = run(lxd_warning, absent)
    assert result["changed"] is False, result
    assert lxd.writes() == []


def test_warning_that_does_not_exist_cannot_be_made(lxd, run):
    result = run(lxd_warning, {"uuid": UUID, "status": "acknowledged"})
    assert result["failed"] is True
    assert result["msg"] == f"warning {UUID} not found"
    assert lxd.writes() == []
