# Copyright (c) 2026, Sean McAvoy
# GNU General Public License v3.0+ (see LICENSES/GPL-3.0-or-later.txt or https://www.gnu.org/licenses/gpl-3.0.txt)
# SPDX-License-Identifier: GPL-3.0-or-later

from __future__ import annotations

import json
import typing as t

import pytest

from ansible_collections.smcavoy.lxd.plugins.module_utils import _client
from ansible_collections.smcavoy.lxd.plugins.module_utils._client import (
    LXDClient,
    LXDClientError,
    LXDNotFoundError,
    api_path,
    parse_version,
)


class FakeResponse:
    def __init__(self, status, body, headers=None, will_close=False, read_error=None):
        self.status = status
        self.body = json.dumps(body).encode() if not isinstance(body, bytes) else body
        self.headers = headers or {}
        self.will_close = will_close
        self.read_error = read_error

    def read(self):
        if self.read_error:
            raise self.read_error
        return self.body

    def getheaders(self):
        return list(self.headers.items())


class FakeServer:
    """Answer requests from a list. An item is (method, path prefix, status, body, headers) or an exception to raise."""

    def __init__(self, answers):
        self.answers = list(answers)
        self.sent = []
        self.connections = []
        self.response = None

    def connect(self):
        conn = FakeConnection(self)
        self.connections.append(conn)
        return conn

    def handle(self, conn, method, target, body, headers):
        self.sent.append((method, target, body, dict(headers or {}), self.connections.index(conn)))
        answer = self.answers.pop(0)
        if isinstance(answer, EarlyAnswer):
            # The server answers, then the send of the body fails. Without an answer, getresponse fails too.
            self.response = answer.response if answer.response is not None else answer.error
            raise answer.error
        if isinstance(answer, Exception):
            # No answer: a getresponse after this fails too.
            self.response = answer
            raise answer
        if isinstance(answer, FakeResponse):
            self.response = answer
            return
        expected_method, prefix, status, body, headers = answer
        assert method == expected_method, (method, target)
        assert target.startswith(prefix), (prefix, target)
        self.response = FakeResponse(status, body, headers)


class EarlyAnswer:
    """The send of the request fails with O(error); O(response) is the answer that the server sent before."""

    def __init__(self, error, response=None):
        self.error = error
        self.response = response


class FakeSocket:
    def __init__(self, name):
        self.name = name
        self.timeout = None

    def settimeout(self, value):
        self.timeout = value


class FakeConnection:
    def __init__(self, server):
        self.server = server
        self.sock = None
        self.timeout = None
        self.closed = False

    def request(self, method, target, body=None, headers=None):
        assert not self.closed
        if self.sock is None:
            self.sock = FakeSocket(f"socket-{self.server.connections.index(self)}")
        self.server.handle(self, method, target, body, headers)

    def getresponse(self):
        if isinstance(self.server.response, Exception):
            raise self.server.response
        return self.server.response

    def close(self):
        self.closed = True


@pytest.fixture(autouse=True)
def quiet_transport(monkeypatch):
    """No sleeps, and an idle connection stays open unless a test says otherwise."""
    monkeypatch.setattr(_client.time, "sleep", lambda seconds: None)
    monkeypatch.setattr(_client, "_readable", lambda sock: sock is None)


class FakeClient(LXDClient):
    """A client whose connections go to a FakeServer."""

    def __init__(self, answers, **kwargs):
        super().__init__(url="https://lxd.example:8443", validate_certs=False, timeout=5, **kwargs)
        self.server_fake = FakeServer(answers)

    def _new_connection(self) -> t.Any:
        return self.server_fake.connect()


def make_client(answers):
    return FakeClient(answers)


ROOT: tuple[t.Any, ...] = ("GET", "/", 200, {"type": "sync", "metadata": ["/1.0"]}, {})
PROFILE: tuple[t.Any, ...] = ("GET", "/1.0/profiles/web", 200, {"type": "sync", "metadata": {"name": "web"}}, {})
PUT_OK: tuple[t.Any, ...] = ("PUT", "/1.0/profiles/web", 200, {"type": "sync", "metadata": {}}, {})


def test_api_path_encodes_parts():
    assert api_path("instances", "a b", "files") == "/1.0/instances/a%20b/files"
    assert api_path("images", "aliases", "test/alpine") == "/1.0/images/aliases/test%2Falpine"


def test_parse_version():
    assert parse_version("6.10.1") == (6, 10, 1)
    assert parse_version("6.10.1 LTS") == (6, 10, 1)
    assert parse_version("6.11") == (6, 11, 0)
    assert parse_version("") == (0, 0, 0)


def test_client_get_returns_metadata_and_etag():
    client = make_client([("GET", "/1.0/profiles/web", 200, {"type": "sync", "metadata": {"name": "web"}}, {"Etag": '"abc"'})])
    meta, etag = client.get("/1.0/profiles/web")
    assert meta == {"name": "web"}
    assert etag == '"abc"'


def test_client_not_found():
    client = make_client([("GET", "/1.0/profiles/x", 404, {"type": "error", "error": "Profile not found"}, {})])
    with pytest.raises(LXDNotFoundError):
        client.get("/1.0/profiles/x")
    client = make_client([("GET", "/1.0/profiles/x", 404, {"type": "error", "error": "Profile not found"}, {})])
    assert client.get_or_none("/1.0/profiles/x") == (None, None)


def test_client_async_write_waits():
    client = make_client(
        [
            ROOT,
            ("POST", "/1.0/networks", 202, {"type": "async", "operation": "/1.0/operations/op1"}, {}),
            ("GET", "/1.0/operations/op1/wait", 200, {"type": "sync", "metadata": {"status": "Success", "metadata": {"x": 1}}}, {}),
        ]
    )
    assert client.write("POST", "/1.0/networks", body={"name": "n"}) == {"x": 1}


def test_client_failed_operation_with_http_200():
    client = make_client(
        [
            ROOT,
            ("POST", "/1.0/storage-pools", 202, {"type": "async", "operation": "/1.0/operations/op2"}, {}),
            (
                "GET",
                "/1.0/operations/op2/wait",
                200,
                {"type": "sync", "status_code": 200, "metadata": {"status": "Failure", "err": "Config key is member specific"}},
                {},
            ),
        ]
    )
    with pytest.raises(LXDClientError) as exc:
        client.write("POST", "/1.0/storage-pools", body={})
    assert "member specific" in exc.value.message
    assert exc.value.operation == "op2"


def test_client_sends_if_match_and_reports_412():
    client = make_client([ROOT, ("PUT", "/1.0/profiles/web", 412, {"type": "error", "error": "ETag does not match"}, {})])
    with pytest.raises(LXDClientError) as exc:
        client.write("PUT", "/1.0/profiles/web", body={}, etag='"abc"')
    assert exc.value.status == 412
    assert client.server_fake.sent[1][3]["If-Match"] == '"abc"'


def test_client_no_secrets_in_log():
    client = FakeClient([("GET", "/1.0", 200, {"type": "sync", "metadata": {"auth": "trusted"}}, {})], bearer_token="EXAMPLE-SECRET")
    client.get("/1.0")
    assert client.server_fake.sent[0][3]["Authorization"] == "Bearer EXAMPLE-SECRET"
    assert "EXAMPLE-SECRET" not in json.dumps(client.http_log)


def test_client_unix_url():
    client = LXDClient(url="unix:/var/snap/lxd/common/lxd/unix.socket")
    assert client.base == "http://unix.socket"
    assert client.unix_socket == "/var/snap/lxd/common/lxd/unix.socket"


def test_client_rejects_bad_url():
    with pytest.raises(LXDClientError):
        LXDClient(url="http://plain.example")


def reset():
    return ConnectionResetError(104, "Connection reset by peer")


def test_requests_share_one_connection():
    client = make_client([PROFILE, PROFILE, PUT_OK])
    client.get("/1.0/profiles/web")
    client.get("/1.0/profiles/web")
    client.write("PUT", "/1.0/profiles/web", body={"config": {}})
    assert len(client.server_fake.connections) == 1
    assert [item[0] for item in client.server_fake.sent] == ["GET", "GET", "PUT"]


def test_get_retries_on_a_new_connection_after_a_reset():
    client = make_client([reset(), PROFILE])
    meta, _etag = client.get("/1.0/profiles/web")
    assert meta == {"name": "web"}
    assert client.http_log[-1]["retried"]
    assert len(client.server_fake.connections) == 2
    assert client.server_fake.connections[0].closed


def test_get_retries_after_a_reset_in_the_body():
    broken = FakeResponse(200, b"{}", read_error=reset())
    client = make_client([broken, PROFILE])
    meta, _etag = client.get("/1.0/profiles/web")
    assert meta == {"name": "web"}
    assert client.http_log[-1]["retried"]


def test_get_gives_up_after_three_attempts():
    client = make_client([reset(), reset(), reset()])
    with pytest.raises(LXDClientError, match="Cannot reach LXD"):
        client.get("/1.0/profiles/web")
    assert len(client.server_fake.sent) == 3


def test_get_does_not_retry_a_bad_certificate():
    client = make_client([_client.ssl.SSLCertVerificationError("certificate verify failed")])
    with pytest.raises(LXDClientError, match="Cannot reach LXD"):
        client.get("/1.0/profiles/web")
    assert len(client.server_fake.sent) == 1


def test_first_write_goes_on_a_connection_that_answered_a_get():
    client = make_client([ROOT, PUT_OK])
    client.write("PUT", "/1.0/profiles/web", body={"config": {}})
    sent = client.server_fake.sent
    assert [(item[0], item[1], item[4]) for item in sent] == [("GET", "/", 0), ("PUT", "/1.0/profiles/web", 0)]


def test_a_reset_in_the_handshake_hits_only_the_get_before_a_write():
    # LXD closes a connection with a slow TLS handshake before it reads the request. Here the GET gets that reset.
    client = make_client([reset(), ROOT, PUT_OK])
    client.write("PUT", "/1.0/profiles/web", body={"config": {}})
    assert [item[0] for item in client.server_fake.sent] == ["GET", "GET", "PUT"]
    assert [item[4] for item in client.server_fake.sent] == [0, 1, 1]


def test_write_after_an_idle_time_proves_a_new_connection():
    client = make_client([PROFILE, ROOT, PUT_OK])
    client.get("/1.0/profiles/web")
    client._used_at -= _client.IDLE_REUSE_SECONDS + 1
    client.write("PUT", "/1.0/profiles/web", body={"config": {}})
    assert [(item[0], item[4]) for item in client.server_fake.sent] == [("GET", 0), ("GET", 1), ("PUT", 1)]


def test_write_after_the_server_closed_the_connection_proves_a_new_one(monkeypatch):
    client = make_client([PROFILE, ROOT, PUT_OK])
    client.get("/1.0/profiles/web")
    # The server closed the first connection while it was idle, so its socket is readable.
    monkeypatch.setattr(_client, "_readable", lambda sock: sock is None or sock.name == "socket-0")
    client.write("PUT", "/1.0/profiles/web", body={"config": {}})
    assert [(item[0], item[4]) for item in client.server_fake.sent] == [("GET", 0), ("GET", 1), ("PUT", 1)]


def test_write_is_not_sent_twice_after_a_reset():
    client = make_client([ROOT, reset()])
    with pytest.raises(LXDClientError, match="can have applied the change"):
        client.write("PUT", "/1.0/profiles/web", body={"config": {}})
    assert [item[0] for item in client.server_fake.sent] == ["GET", "PUT"]
    assert client.http_log[-1]["error"]


def test_a_reset_while_reading_an_error_body_keeps_the_status():
    broken = FakeResponse(404, b'{"error": "x"}', read_error=reset())
    client = make_client([broken])
    with pytest.raises(LXDNotFoundError):
        client.get("/1.0/profiles/x")
    assert client._conn is None


def test_connection_close_from_the_server_is_honoured():
    closing = FakeResponse(200, {"type": "sync", "metadata": {"name": "web"}}, will_close=True)
    client = make_client([closing, PROFILE])
    client.get("/1.0/profiles/web")
    client.get("/1.0/profiles/web")
    assert len(client.server_fake.connections) == 2


def test_new_connection_without_proxy(monkeypatch):
    monkeypatch.setattr(_client, "getproxies", lambda: {})
    conn = LXDClient(url="https://lxd.example:8443", validate_certs=False)._new_connection()
    assert (conn.host, conn.port) == ("lxd.example", 8443)


def test_new_connection_through_a_proxy(monkeypatch):
    monkeypatch.setattr(_client, "getproxies", lambda: {"https": "http://user:pw@proxy.example:3128"})
    monkeypatch.setattr(_client, "proxy_bypass", lambda host: False)
    conn = LXDClient(url="https://lxd.example:8443", validate_certs=False)._new_connection()
    assert (conn.host, conn.port) == ("proxy.example", 3128)
    tunnel = vars(conn)
    assert (tunnel["_tunnel_host"], tunnel["_tunnel_port"]) == ("lxd.example", 8443)
    assert tunnel["_tunnel_headers"]["Proxy-Authorization"].startswith("Basic ")


def test_new_connection_on_a_unix_socket():
    conn = LXDClient(url="unix:/var/snap/lxd/common/lxd/unix.socket")._new_connection()
    assert vars(conn)["_unix_socket"] == "/var/snap/lxd/common/lxd/unix.socket"
    assert conn.host == "unix.socket"


FINGERPRINT = "ab" * 32


def test_server_fingerprint_is_normalized():
    colons = ":".join(["AB"] * 32)
    assert _client.normalize_fingerprint(colons) == FINGERPRINT


@pytest.mark.parametrize("value", ["", "abc", "zz" * 32, "ab" * 31])
def test_server_fingerprint_must_be_sha256(value):
    with pytest.raises(LXDClientError, match="64 hex characters"):
        _client.normalize_fingerprint(value)


def test_new_connection_with_a_fingerprint_is_pinned(monkeypatch):
    monkeypatch.setattr(_client, "getproxies", lambda: {})
    conn = LXDClient(url="https://10.0.0.1:8443", server_fingerprint=FINGERPRINT)._new_connection()
    assert isinstance(conn, _client.PinnedHTTPSConnection)
    assert conn.fingerprint == FINGERPRINT
    context = vars(conn)["_context"]
    assert context.check_hostname is False


class FakeTLSSocket:
    """A socket that only knows its peer certificate."""

    def __init__(self, der):
        self.der = der
        self.closed = False

    def getpeercert(self, binary_form=False):
        return self.der

    def close(self):
        self.closed = True


def pinned_connect(monkeypatch, der):
    """Run PinnedHTTPSConnection.connect with a fake TLS socket that presents O(der)."""
    conn = _client.PinnedHTTPSConnection("10.0.0.1", 8443, fingerprint=_client.hashlib.sha256(b"right").hexdigest())

    def fake_connect(self):
        self.sock = FakeTLSSocket(der)

    monkeypatch.setattr(_client.http.client.HTTPSConnection, "connect", fake_connect)
    conn.connect()
    return conn


def test_pinned_connection_accepts_the_pinned_certificate(monkeypatch):
    conn = pinned_connect(monkeypatch, b"right")
    assert conn.sock is not None


def test_pinned_connection_refuses_another_certificate(monkeypatch):
    with pytest.raises(_client.ssl.SSLCertVerificationError, match="not the server_fingerprint"):
        pinned_connect(monkeypatch, b"wrong")


def test_a_wrong_fingerprint_is_not_retried(monkeypatch):
    calls = []

    def exchange(*args, **kwargs):
        calls.append(args)
        raise _client.ssl.SSLCertVerificationError("the server certificate has the fingerprint x, not the server_fingerprint y")

    client = LXDClient(url="https://10.0.0.1:8443", server_fingerprint=FINGERPRINT)
    monkeypatch.setattr(client, "_exchange", exchange)
    with pytest.raises(LXDClientError, match="not the server_fingerprint") as exc:
        client.get("/1.0")
    assert len(calls) == 1
    # The text, not a Python tuple.
    assert "('" not in exc.value.message
    assert exc.value.message.endswith("not the server_fingerprint y")


# Long operations: LXD answers a wait whose slice runs out with
# HTTP 500 "context deadline exceeded". The operation still runs, so the client waits again.

POST_ASYNC: tuple[t.Any, ...] = ("POST", "/1.0/instances", 202, {"type": "async", "operation": "/1.0/operations/op9"}, {})
WAIT_EXPIRED: tuple[t.Any, ...] = (
    "GET",
    "/1.0/operations/op9/wait",
    500,
    {"type": "error", "error": "context deadline exceeded", "error_code": 500},
    {},
)
WAIT_SUCCESS: tuple[t.Any, ...] = ("GET", "/1.0/operations/op9/wait", 200, {"type": "sync", "metadata": {"status": "Success", "metadata": {"done": True}}}, {})


class FakeClock:
    """A monotonic clock that a sleep moves forward, and that a test can move by hand."""

    def __init__(self):
        self.now = 1000.0

    def monotonic(self):
        return self.now

    def sleep(self, seconds):
        self.now += seconds


@pytest.fixture
def clock(monkeypatch):
    fake = FakeClock()
    monkeypatch.setattr(_client.time, "monotonic", fake.monotonic)
    monkeypatch.setattr(_client.time, "sleep", fake.sleep)
    return fake


def test_wait_continues_after_the_wait_slice_runs_out(clock):
    client = make_client([ROOT, POST_ASYNC, WAIT_EXPIRED, WAIT_EXPIRED, WAIT_SUCCESS])
    assert client.write("POST", "/1.0/instances", body={"name": "vm"}) == {"done": True}
    waits = [s for s in client.server_fake.sent if "/wait" in s[1]]
    assert len(waits) == 3


def test_wait_reports_its_own_deadline_with_the_operation(clock):
    class Expiring(FakeServer):
        def handle(self, conn, method, target, body, headers):
            super().handle(conn, method, target, body, headers)
            if "/wait" in target:
                clock.now += 3  # each slice uses up 3 of the 5 seconds

    client = make_client([])
    client.server_fake = Expiring([ROOT, POST_ASYNC, WAIT_EXPIRED, WAIT_EXPIRED])
    with pytest.raises(LXDClientError) as exc:
        client.write("POST", "/1.0/instances", body={"name": "vm"})
    assert "did not finish in 5 seconds" in exc.value.message
    assert "can still run on the server" in exc.value.message
    assert exc.value.operation == "op9"


def test_wait_does_not_hide_other_server_errors(clock):
    other: tuple[t.Any, ...] = ("GET", "/1.0/operations/op9/wait", 500, {"type": "error", "error": "database is locked", "error_code": 500}, {})
    client = make_client([ROOT, POST_ASYNC, other])
    with pytest.raises(LXDClientError, match="database is locked"):
        client.write("POST", "/1.0/instances", body={"name": "vm"})


def test_wait_says_when_the_operation_is_gone(clock):
    gone: tuple[t.Any, ...] = ("GET", "/1.0/operations/op9/wait", 404, {"type": "error", "error": "Operation not found", "error_code": 404}, {})
    client = make_client([ROOT, POST_ASYNC, gone])
    with pytest.raises(LXDClientError) as exc:
        client.write("POST", "/1.0/instances", body={"name": "vm"})
    assert "does not know operation op9" in exc.value.message
    assert exc.value.operation == "op9"


def test_wait_survives_a_connection_break_longer_than_the_read_retries(clock):
    # Three resets use up the read retries of one wait request. The wait goes on after a pause.
    client = make_client([ROOT, POST_ASYNC, reset(), reset(), reset(), WAIT_SUCCESS])
    client.timeout = 60
    assert client.write("POST", "/1.0/instances", body={"name": "vm"}) == {"done": True}


# A 404 for a missing project or a missing parent.

NOT_FOUND = {"type": "error", "error": "Not found", "error_code": 404}


def test_get_or_none_fails_for_a_missing_project():
    client = make_client(
        [
            ("GET", "/1.0/instances/web", 404, NOT_FOUND, {}),
            ("GET", "/1.0/projects/pord", 404, NOT_FOUND, {}),
        ]
    )
    with pytest.raises(LXDClientError) as exc:
        client.get_or_none("/1.0/instances/web", {"project": "pord"})
    assert not isinstance(exc.value, LXDNotFoundError)
    assert 'Project "pord" does not exist' in exc.value.message


def test_get_or_none_returns_none_when_only_the_object_is_missing():
    client = make_client(
        [
            ("GET", "/1.0/instances/web", 404, NOT_FOUND, {}),
            ("GET", "/1.0/projects/prod", 200, {"type": "sync", "metadata": {"name": "prod"}}, {}),
        ]
    )
    assert client.get_or_none("/1.0/instances/web", {"project": "prod"}) == (None, None)
    assert client.notes == []


def test_get_or_none_notes_a_missing_parent():
    client = make_client(
        [
            ("GET", "/1.0/instances/web/snapshots/s1", 404, NOT_FOUND, {}),
            ("GET", "/1.0/instances/web", 404, NOT_FOUND, {}),
        ]
    )
    assert client.get_or_none("/1.0/instances/web/snapshots/s1") == (None, None)
    assert client.notes == ["/1.0/instances/web does not exist, so /1.0/instances/web/snapshots/s1 does not exist either."]


def test_get_or_none_does_not_guess_when_the_project_cannot_be_read():
    client = make_client(
        [
            ("GET", "/1.0/instances/web", 404, NOT_FOUND, {}),
            ("GET", "/1.0/projects/ci", 403, {"type": "error", "error": "Certificate is restricted", "error_code": 403}, {}),
        ]
    )
    assert client.get_or_none("/1.0/instances/web", {"project": "ci"}) == (None, None)


# A trust token works once, so check mode must not use it.

UNTRUSTED: tuple[t.Any, ...] = ("GET", "/1.0", 200, {"type": "sync", "metadata": {"auth": "untrusted", "api_extensions": []}}, {})


def test_check_mode_does_not_use_the_trust_token():
    client = make_client([UNTRUSTED])
    with pytest.raises(LXDClientError, match="only outside check mode"):
        client.ensure_trusted("token", check_mode=True)
    assert [s[0] for s in client.server_fake.sent] == ["GET"]


# Large files stream in chunks.


class ChunkedResponse(FakeResponse):
    """A response whose body comes in pieces, and that can break after some of them."""

    def __init__(self, status, pieces, headers=None, break_after=None):
        super().__init__(status, b"".join(pieces), headers)
        self.pieces = list(pieces)
        self.break_after = break_after
        self.reads = 0

    def read(self, size=-1):
        if size is None or size < 0:
            return super().read()
        if self.break_after is not None and self.reads >= self.break_after:
            raise ConnectionResetError(104, "Connection reset by peer")
        self.reads += 1
        return self.pieces.pop(0) if self.pieces else b""


def test_download_to_streams_into_the_file_with_size_and_sha(tmp_path):
    import hashlib

    client = make_client([ChunkedResponse(200, [b"abc", b"def"], {"Content-Type": "application/octet-stream"})])
    with open(tmp_path / "out", "w+b") as out:
        resp = client.download_to("/1.0/images/f/export", out)
    assert (tmp_path / "out").read_bytes() == b"abcdef"
    assert resp.size == 6
    assert resp.sha256 == hashlib.sha256(b"abcdef").hexdigest()
    assert resp.body == b""


def test_download_to_starts_the_file_again_after_a_broken_read(tmp_path):
    client = make_client(
        [
            ChunkedResponse(200, [b"abc", b"XXX"], break_after=1),
            ChunkedResponse(200, [b"abc", b"def"]),
        ]
    )
    with open(tmp_path / "out", "w+b") as out:
        resp = client.download_to("/1.0/images/f/export", out)
    assert (tmp_path / "out").read_bytes() == b"abcdef"
    assert resp.size == 6


def test_download_to_starts_again_after_a_body_that_ends_early(tmp_path):
    # http.client gives an empty read, and no error, when the server closes the connection in the middle of the body.
    client = make_client(
        [
            ChunkedResponse(200, [b"abc"], {"Content-Length": "6"}),
            ChunkedResponse(200, [b"abc", b"def"], {"Content-Length": "6"}),
        ]
    )
    with open(tmp_path / "out", "w+b") as out:
        resp = client.download_to("/1.0/instances/c1/backups/b1/export", out)
    assert (tmp_path / "out").read_bytes() == b"abcdef"
    assert resp.size == 6
    assert len(client.server_fake.connections) == 2


def test_download_to_fails_when_the_body_always_ends_early(tmp_path):
    client = make_client([ChunkedResponse(200, [b"abc"], {"content-length": "6"}) for _attempt in range(_client.SAFE_ATTEMPTS)])
    with open(tmp_path / "out", "w+b") as out, pytest.raises(LXDClientError, match="Cannot reach LXD"):
        # Before: the client returned the 3 bytes as the whole file.
        client.download_to("/1.0/instances/c1/backups/b1/export", out)


def test_download_to_keeps_an_error_in_memory(tmp_path):
    client = make_client([("GET", "/1.0/images/f/export", 404, {"type": "error", "error": "Image not found", "error_code": 404}, {})])
    with open(tmp_path / "out", "w+b") as out, pytest.raises(LXDNotFoundError, match="Image not found"):
        client.download_to("/1.0/images/f/export", out)
    assert (tmp_path / "out").read_bytes() == b""


def test_chained_reader_reads_bytes_and_files_in_order(tmp_path):
    (tmp_path / "a").write_bytes(b"0123456789")
    reader = _client.ChainedReader([b"head-", str(tmp_path / "a"), b"-tail"])
    assert len(reader) == 20
    chunks = []
    while True:
        chunk = reader.read(4)
        if not chunk:
            break
        chunks.append(chunk)
    assert b"".join(chunks) == b"head-0123456789-tail"
    assert all(len(c) == 4 for c in chunks)


def test_a_streamed_upload_sends_its_length(tmp_path):
    (tmp_path / "img").write_bytes(b"x" * 100)
    client = make_client([ROOT, ("POST", "/1.0/images", 200, {"type": "sync", "metadata": {}}, {})])
    client.write("POST", "/1.0/images", raw=_client.ChainedReader([b"12345", str(tmp_path / "img")]))
    _method, _target, body, headers, _conn = client.server_fake.sent[-1]
    assert headers["Content-Length"] == "105"
    assert isinstance(body, _client.ChainedReader)


# A connection that hangs during a wait (found by the lxd_fault_network target, FN3): the read retries
# must not run past the deadline of the operation.


class HangingServer(FakeServer):
    """A server whose wait requests hang until the socket timeout, which moves the fake clock."""

    def __init__(self, answers, clock, hangs):
        super().__init__(answers)
        self.clock = clock
        self.hangs = hangs

    def handle(self, conn, method, target, body, headers):
        if "/wait" in target and self.hangs > 0:
            self.hangs -= 1
            self.sent.append((method, target, body, dict(headers or {}), self.connections.index(conn)))
            self.clock.now += conn.timeout
            raise TimeoutError("The read operation timed out")
        super().handle(conn, method, target, body, headers)


def test_wait_gives_up_near_the_deadline_when_the_connection_hangs(clock):
    client = make_client([])
    client.timeout = 40
    client.server_fake = HangingServer([ROOT, POST_ASYNC], clock, hangs=10)
    start = clock.now
    with pytest.raises(LXDClientError) as exc:
        client.write("POST", "/1.0/instances", body={"name": "vm"})
    assert "did not finish in 40 seconds" in exc.value.message
    # 40 s of timeout and 30 s of grace for the answer, and not three socket timeouts more.
    assert clock.now - start <= 40 + 30 + 5
    waits = [s for s in client.server_fake.sent if "/wait" in s[1]]
    assert len(waits) == 1


def test_wait_says_the_operation_can_have_finished_during_a_break(clock):
    gone: tuple[t.Any, ...] = ("GET", "/1.0/operations/op9/wait", 404, {"type": "error", "error": "Operation not found", "error_code": 404}, {})
    client = make_client([ROOT, POST_ASYNC, reset(), reset(), reset(), gone])
    client.timeout = 60
    with pytest.raises(LXDClientError) as exc:
        client.write("POST", "/1.0/instances", body={"name": "vm"})
    assert "finished while the connection to LXD was broken" in exc.value.message
    assert "cannot tell whether it worked" in exc.value.message


# ----------------------------------------------------------------------
# A server that answers before it reads the whole body

PERMISSION_DENIED = {"type": "error", "error_code": 403, "error": 'Failed opening "/etc/app.conf" in instance "web": permission denied'}


def test_an_answer_before_a_failed_send_is_the_error():
    # LXD 6.10 answers a large upload to a file that it cannot overwrite with 403 before it reads the body,
    # and closes the connection. The send then fails with a reset, but the answer can be read: lxd_instance_file
    # needs the 403 to delete the file and write it again (seen in full run 1377 with a 50 MiB file).
    client = make_client([ROOT, EarlyAnswer(ConnectionResetError(104, "Connection reset by peer"), FakeResponse(403, PERMISSION_DENIED))])
    with pytest.raises(LXDClientError) as caught:
        client.request("POST", "/1.0/instances/web/files", query={"path": "/etc/app.conf"}, raw=b"x" * 100)
    assert caught.value.status == 403
    assert "permission denied" in caught.value.message
    assert client.server_fake.connections[-1].closed


NO_SPACE = {"type": "error", "error_code": 500, "error": 'sftp: "write /etc/app.conf: no space left on device" (SSH_FX_FAILURE)'}


def test_an_early_answer_on_a_full_disk_is_the_error():
    # Seen live on LXD 6.10.1: a 1 MiB upload into an instance with a full disk. LXD answers 500 and resets the
    # connection; the answer holds the real cause, and the outcome is known (nothing written).
    client = make_client([ROOT, EarlyAnswer(ConnectionResetError(104, "Connection reset by peer"), FakeResponse(500, NO_SPACE))])
    with pytest.raises(LXDClientError) as caught:
        client.request("POST", "/1.0/instances/web/files", query={"path": "/etc/app.conf"}, raw=b"x" * 100)
    assert caught.value.status == 500
    assert "no space left on device" in caught.value.message
    assert "broke" not in caught.value.message
    assert caught.value.outcome_unknown is False
    assert client.server_fake.connections[-1].closed


def test_a_failed_send_without_an_answer_is_a_broken_connection():
    client = make_client([ROOT, EarlyAnswer(ConnectionResetError(104, "Connection reset by peer"))])
    with pytest.raises(LXDClientError) as caught:
        client.request("POST", "/1.0/instances/web/files", query={"path": "/etc/app.conf"}, raw=b"x" * 100)
    assert caught.value.status is None
    assert "broke after the POST request was sent" in caught.value.message
    assert caught.value.outcome_unknown is True
    assert caught.value.detail.endswith("Connection reset by peer.")
    assert "Run the task again" not in caught.value.detail


def test_a_failed_send_after_http_client_dropped_the_socket_is_a_broken_connection():
    # Seen live: on a reset during the send, http.client can close its socket. getresponse then raises
    # AttributeError ("'NoneType' object has no attribute 'makefile'"), which must not escape.
    client = make_client([ROOT, EarlyAnswer(ConnectionResetError(104, "Connection reset by peer"), AttributeError("makefile"))])
    with pytest.raises(LXDClientError) as caught:
        client.request("POST", "/1.0/profiles", body={"name": "web"})
    assert "broke after the POST request was sent" in caught.value.message


def test_a_read_retry_after_a_reset_during_the_send():
    # A GET whose send fails on a dead kept-alive connection goes again on a new connection.
    client = make_client([ROOT, EarlyAnswer(ConnectionResetError(104, "reset"), AttributeError("makefile")), PROFILE])
    client.request("GET", "/")
    meta, _etag = client.get("/1.0/profiles/web")
    assert meta == {"name": "web"}


def test_a_lost_operation_has_an_unknown_outcome():
    client = make_client(
        [
            ROOT,
            ("POST", "/1.0/instances/web/exec", 202, {"type": "async", "operation": "/1.0/operations/op1", "metadata": {}}, {}),
            ("GET", "/1.0/operations/op1/wait", 404, {"type": "error", "error_code": 404, "error": "Operation not found"}, {}),
        ]
    )
    with pytest.raises(LXDClientError) as caught:
        client.write("POST", "/1.0/instances/web/exec", body={"command": ["true"]})
    assert caught.value.outcome_unknown is True
    assert caught.value.detail == "LXD does not know operation op1 any more (Operation not found)."


def test_the_wait_rides_out_an_lxd_shutdown():
    # Seen live on LXD 6.10.1: during a restart, LXD answers the wait with 500 "database is closed", then
    # refuses connections, then no longer knows the operation.
    closed = {"type": "error", "error_code": 500, "error": "Failed getting identity details: Failed beginning transaction: sql: database is closed"}
    client = make_client(
        [
            ROOT,
            ("POST", "/1.0/instances/web/exec", 202, {"type": "async", "operation": "/1.0/operations/op1", "metadata": {}}, {}),
            ("GET", "/1.0/operations/op1/wait", 500, closed, {}),
            ConnectionRefusedError(111, "Connection refused"),
            ConnectionRefusedError(111, "Connection refused"),
            ConnectionRefusedError(111, "Connection refused"),
            ("GET", "/1.0/operations/op1/wait", 404, {"type": "error", "error_code": 404, "error": "Operation not found"}, {}),
        ]
    )
    with pytest.raises(LXDClientError) as caught:
        client.write("POST", "/1.0/instances/web/exec", body={"command": ["true"]})
    assert caught.value.outcome_unknown is True
    assert "database is closed" not in caught.value.message
    assert "LXD restarted and lost it" in caught.value.message


def test_the_wait_succeeds_after_an_lxd_shutdown_answer():
    closed = {"type": "error", "error_code": 500, "error": "sql: database is closed"}
    done = {"type": "sync", "metadata": {"id": "op1", "status": "Success", "metadata": {"return": 0}}}
    client = make_client(
        [
            ROOT,
            ("POST", "/1.0/instances/web/exec", 202, {"type": "async", "operation": "/1.0/operations/op1", "metadata": {}}, {}),
            ("GET", "/1.0/operations/op1/wait", 500, closed, {}),
            ("GET", "/1.0/operations/op1/wait", 200, done, {}),
        ]
    )
    assert client.write("POST", "/1.0/instances/web/exec", body={"command": ["true"]}) == {"return": 0}


def test_another_500_in_the_wait_still_fails_at_once():
    client = make_client(
        [
            ROOT,
            ("POST", "/1.0/instances/web/exec", 202, {"type": "async", "operation": "/1.0/operations/op1", "metadata": {}}, {}),
            ("GET", "/1.0/operations/op1/wait", 500, {"type": "error", "error_code": 500, "error": "something else"}, {}),
        ]
    )
    with pytest.raises(LXDClientError, match="something else"):
        client.write("POST", "/1.0/instances/web/exec", body={"command": ["true"]})


# ----------------------------------------------------------------------
# A failed HEAD: the answer has no body

NOT_A_DIRECTORY = {
    "type": "error",
    "error_code": 500,
    "error": 'Failed accessing "/etc/hostname/x" in instance "web": sftp: "lstat /etc/hostname/x: not a directory" (SSH_FX_FAILURE)',
}
FILES = "/1.0/instances/web/files"


class UnreadResponse(FakeResponse):
    """An answer whose body the client must not read: it stands for a large file."""

    def read(self):
        raise AssertionError("the client read the body of a successful answer")


def test_a_failed_head_gives_the_error_text_of_a_get():
    # Seen live on LXD 6.10.1: HEAD of /etc/hostname/x answers 500 with a Content-Length and no body; the GET has the text.
    client = make_client([FakeResponse(500, b"", {"content-length": "231"}), ("GET", FILES + "?path=", 500, NOT_A_DIRECTORY, {})])
    with pytest.raises(LXDClientError) as caught:
        client.head(FILES, {"path": "/etc/hostname/x"})
    # Before: the message was "HTTP 500".
    assert "not a directory" in caught.value.message
    assert caught.value.status == 500
    sent = client.server_fake.sent
    assert [(item[0], item[1]) for item in sent] == [("HEAD", FILES + "?path=%2Fetc%2Fhostname%2Fx"), ("GET", FILES + "?path=%2Fetc%2Fhostname%2Fx")]
    assert [entry.get("status") for entry in client.http_log] == [500, 500]


def test_a_failed_head_does_not_read_a_file_when_the_get_succeeds():
    # The error can be gone at the GET. The client must not download the file only to find no error text.
    client = make_client([FakeResponse(500, b""), UnreadResponse(200, b"x" * 100)])
    with pytest.raises(LXDClientError) as caught:
        client.head(FILES, {"path": "/var/big"})
    assert caught.value.message == "HTTP 500"
    assert caught.value.status == 500
    assert client.server_fake.connections[-1].closed


def test_a_failed_head_keeps_its_status_when_the_get_fails_in_another_way():
    client = make_client([FakeResponse(500, b""), ("GET", FILES, 403, {"type": "error", "error": "Forbidden"}, {})])
    with pytest.raises(LXDClientError) as caught:
        client.head(FILES, {"path": "/x"})
    assert (caught.value.status, caught.value.message) == (500, "HTTP 500")
    client = make_client([FakeResponse(500, b""), ConnectionResetError(104, "Connection reset by peer")])
    with pytest.raises(LXDClientError) as caught:
        client.head(FILES, {"path": "/x"})
    assert (caught.value.status, caught.value.message) == (500, "HTTP 500")


def test_a_head_of_a_missing_path_sends_no_get_for_the_error_text():
    # A 404 is the usual answer for a file that does not exist (creates, removes). It costs no extra request for its text.
    client = make_client([FakeResponse(404, b""), ("GET", "/1.0/instances/web", 200, {"type": "sync", "metadata": {"name": "web"}}, {})])
    assert client.head(FILES, {"path": "/nope"}) is None
    assert [(item[0], item[1]) for item in client.server_fake.sent] == [("HEAD", FILES + "?path=%2Fnope"), ("GET", "/1.0/instances/web")]
