# Copyright (c) 2026, Sean McAvoy
# GNU General Public License v3.0+ (see LICENSES/GPL-3.0-or-later.txt or https://www.gnu.org/licenses/gpl-3.0.txt)
# SPDX-License-Identifier: GPL-3.0-or-later

# Note that this module util is **PRIVATE** to the collection. It can have breaking changes at any time.
# Do not use this from other collections or standalone plugins/modules!

"""HTTP client for the LXD REST API."""

from __future__ import annotations

import base64
import hashlib
import http.client
import json
import os
import re
import select
import ssl
import time
import typing as t
from urllib.parse import quote, unquote, urlencode, urlsplit
from urllib.request import getproxies, proxy_bypass

from ansible.module_utils.common.text.converters import to_native, to_text
from ansible.module_utils.urls import UnixHTTPConnection, make_context

COLLECTION_VERSION = "0.1.0"
DEFAULT_SOCKETS = (
    "/var/snap/lxd/common/lxd/unix.socket",
    "/var/lib/lxd/unix.socket",
)
UNIX_BASE = "http://unix.socket"
MIN_SERVER_VERSION = (6, 10, 1)
_VERSION_RE = re.compile(r"^(\d+)\.(\d+)(?:\.(\d+))?")

# LXD gives a new TLS connection 3 seconds for the handshake (the ReadHeaderTimeout of its HTTP server).
# After a slow handshake it closes the socket before it reads the request, and the client sees a reset.
# The client keeps one connection open, and sends a write only on a connection that already gave an answer.
# LXD closes a connection that is idle for 30 seconds. The client does not use a connection that is idle for longer than this.
IDLE_REUSE_SECONDS = 15
# A GET or a HEAD changes nothing. After a connection error, the client sends it again on a new connection.
SAFE_METHODS = ("GET", "HEAD")
SAFE_ATTEMPTS = 3
_CONNECTION_ERRORS = (OSError, http.client.HTTPException)
# Seconds between two waits on an operation when the connection to LXD is broken.
WAIT_RECONNECT_SECONDS = 5
# Bytes per read or write when a file streams to or from LXD.
CHUNK_SIZE = 1024 * 1024
_FINGERPRINT_RE = re.compile(r"^[0-9a-f]{64}$")


def _wait_expired(exc: LXDClientError) -> bool:
    """Tell whether an error of GET /1.0/operations/<id>/wait only means that the wait slice ran out.

    LXD 6.10 answers a wait whose timeout passes with HTTP 500 and "context deadline exceeded".
    The operation itself still runs.
    """
    return exc.status in (500, 504) and "deadline exceeded" in (exc.message or "").lower()


def _server_stopping(exc: LXDClientError) -> bool:
    """Return whether an error is the answer of an LXD that shuts down or restarts.

    LXD 6.10 answers a request during its shutdown with HTTP 500 "... sql: database is closed".
    """
    text = (exc.message or "").lower()
    return exc.status in (500, 503) and ("database is closed" in text or "shutting down" in text)


class ChainedReader:
    """A file-like object that reads byte strings and files one after the other, for a streamed upload."""

    def __init__(self, pieces: t.Sequence[bytes | str]) -> None:
        """O(pieces) holds byte strings and paths of files."""
        self._pieces = list(pieces)
        self._length = sum(len(p) if isinstance(p, bytes) else os.path.getsize(p) for p in self._pieces)
        self._index = 0
        self._current: t.Any = None

    def __len__(self) -> int:
        return self._length

    def read(self, size: int = -1) -> bytes:
        out = bytearray()
        while self._index < len(self._pieces) and (size < 0 or len(out) < size):
            piece = self._pieces[self._index]
            want = -1 if size < 0 else size - len(out)
            if isinstance(piece, bytes):
                if self._current is None:
                    self._current = _BytesReader(piece)
            elif self._current is None:
                self._current = open(piece, "rb")  # noqa: SIM115 - closed below when it is used up
            chunk = self._current.read(want)
            if chunk:
                out += chunk
                if size >= 0 and len(out) >= size:
                    break
                continue
            self._current.close()
            self._current = None
            self._index += 1
        return bytes(out)

    def close(self) -> None:
        if self._current is not None:
            self._current.close()
            self._current = None


class _BytesReader:
    def __init__(self, data: bytes) -> None:
        self._data = data
        self._pos = 0

    def read(self, size: int = -1) -> bytes:
        end = len(self._data) if size < 0 else self._pos + size
        chunk = self._data[self._pos : end]
        self._pos += len(chunk)
        return chunk

    def close(self) -> None:
        pass


def _stream_length(raw: t.Any) -> int | None:
    """Return the number of bytes left in an upload body, if it can be known."""
    if isinstance(raw, (bytes, bytearray)):
        return None  # http.client sets the length of a byte string itself.
    if isinstance(raw, ChainedReader):
        return len(raw)
    try:
        return os.fstat(raw.fileno()).st_size - raw.tell()
    except (AttributeError, OSError, ValueError):
        return None


def normalize_fingerprint(value: str) -> str:
    """Return a SHA-256 fingerprint in lower case without colons. Raise L(LXDClientError) for another value."""
    fingerprint = value.strip().lower().replace(":", "")
    if not _FINGERPRINT_RE.match(fingerprint):
        raise LXDClientError("server_fingerprint must be the SHA-256 fingerprint of the server certificate: 64 hex characters, colons allowed")
    return fingerprint


class PinnedHTTPSConnection(http.client.HTTPSConnection):
    """An HTTPS connection that trusts exactly one server certificate, by its SHA-256 fingerprint.

    It checks neither the chain nor the host name, as C(lxc) does for a remote. It checks the certificate before it sends a request.
    """

    def __init__(self, *args: t.Any, fingerprint: str, **kwargs: t.Any) -> None:
        super().__init__(*args, **kwargs)
        self.fingerprint = fingerprint

    def connect(self) -> None:
        """Connect, then compare the server certificate with the pinned fingerprint."""
        super().connect()
        peer = getattr(self.sock, "getpeercert", None)
        der = peer(binary_form=True) if peer else None
        got = hashlib.sha256(der).hexdigest() if der else "none"
        if got != self.fingerprint:
            self.close()
            raise ssl.SSLCertVerificationError(f"the server certificate has the fingerprint {got}, not the server_fingerprint {self.fingerprint}")


def _exc_text(exc: BaseException) -> str:
    """Return the text of an error. An SSL error with one text argument prints that text, not a tuple."""
    if len(exc.args) == 1 and isinstance(exc.args[0], str):
        return exc.args[0]
    return to_native(exc)


def _readable(sock: t.Any) -> bool:
    """Return whether an idle socket has something to read. On an idle HTTP connection, that is the close by the server."""
    if sock is None:
        return True
    try:
        ready, _writable, _errors = select.select([sock], [], [], 0)
    except (OSError, ValueError, TypeError):
        return True
    return bool(ready)


class LXDClientError(Exception):
    """An error from the LXD API or the transport."""

    def __init__(self, message: str, status: int | None = None, operation: str | None = None, outcome_unknown: bool = False, detail: str | None = None) -> None:
        super().__init__(message)
        self.message = message
        self.status = status
        self.operation = operation
        # True when a write was sent but the client cannot tell whether LXD did it, or whether it still runs:
        # the connection broke after the request, or the wait for its operation timed out or lost the operation.
        self.outcome_unknown = outcome_unknown
        # The facts of the message without the advice, for a module that gives its own advice.
        self.detail = detail or message


class LXDNotFoundError(LXDClientError):
    """The object does not exist (HTTP 404)."""


class LXDResponse:
    """A decoded LXD response."""

    def __init__(self, status: int, headers: dict[str, str], body: bytes, size: int = 0, sha256: str = "") -> None:
        self.status = status
        self.headers = {k.lower(): v for k, v in headers.items()}
        self.body = body
        # For a response that streamed into a file: its size and SHA-256.
        self.size = size
        self.sha256 = sha256
        self._envelope: dict[str, t.Any] | None = None

    @property
    def envelope(self) -> dict[str, t.Any]:
        """Return the JSON envelope of the response."""
        if self._envelope is None:
            try:
                self._envelope = json.loads(self.body or b"{}")
            except ValueError as exc:
                raise LXDClientError(f"LXD returned a body that is not JSON (HTTP {self.status})", self.status) from exc
        return self._envelope

    @property
    def etag(self) -> str | None:
        """Return the ETag header, if the server sent one."""
        return self.headers.get("etag")


def api_path(*parts: str) -> str:
    """Build an API path from parts. Each part is URL-encoded."""
    return "/1.0/" + "/".join(quote(str(p), safe="") for p in parts if p != "")


def parse_version(text: str) -> tuple[int, int, int]:
    """Parse a server version such as C(6.10.1) or C(6.10.1 LTS)."""
    match = _VERSION_RE.match(text or "")
    if not match:
        return (0, 0, 0)
    return (int(match.group(1)), int(match.group(2)), int(match.group(3) or 0))


class LXDClient:
    """A small client for the LXD REST API.

    The client follows the shared rules of the collection:
    every write accepts sync and async responses, and an async write waits for its operation.
    """

    def __init__(
        self,
        url: str | None = None,
        client_cert: str | None = None,
        client_key: str | None = None,
        bearer_token: str | None = None,
        server_cert: str | None = None,
        validate_certs: bool = True,
        timeout: int = 120,
        server_fingerprint: str | None = None,
    ) -> None:
        self.timeout = timeout
        self.http_log: list[dict[str, t.Any]] = []
        # Notes for the user, for example a parent object that does not exist. The module shows them as warnings.
        self.notes: list[str] = []
        self._server: dict[str, t.Any] | None = None
        self.unix_socket: str | None = None
        if not url:
            url = self._default_socket()
        if url.startswith("unix:"):
            self.unix_socket = url[len("unix:") :] or None
            if not self.unix_socket:
                raise LXDClientError("The url unix: needs a socket path, for example unix:/var/snap/lxd/common/lxd/unix.socket")
            self.base = UNIX_BASE
        elif url.startswith("https://"):
            self.base = url.rstrip("/")
        else:
            raise LXDClientError(f"url must start with unix: or https://, got {url!r}")
        self.headers = {"User-Agent": f"smcavoy.lxd/{COLLECTION_VERSION}"}
        if bearer_token:
            self.headers["Authorization"] = f"Bearer {bearer_token}"
        self._tls = {"client_cert": client_cert, "client_key": client_key, "server_cert": server_cert, "validate_certs": validate_certs}
        self._fingerprint = normalize_fingerprint(server_fingerprint) if server_fingerprint else None
        self._context: ssl.SSLContext | None = None
        self._conn: http.client.HTTPConnection | None = None
        self._proven = False
        self._used_at = 0.0

    @staticmethod
    def _default_socket() -> str:
        for path in DEFAULT_SOCKETS:
            if os.path.exists(path):
                return "unix:" + path
        raise LXDClientError("No LXD socket found. Set url.")

    # ------------------------------------------------------------------
    # Transport

    def _new_connection(self) -> http.client.HTTPConnection:
        """Return a new, not yet connected, HTTP connection to the server."""
        if self.unix_socket:
            return UnixHTTPConnection(self.unix_socket)("unix.socket", timeout=self.timeout)
        if self._context is None:
            if self._fingerprint:
                # The pin replaces the chain and host name checks. The connection checks the fingerprint itself.
                self._context = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
                self._context.check_hostname = False
                self._context.verify_mode = ssl.CERT_NONE
                client_cert, client_key = self._tls["client_cert"], self._tls["client_key"]
                if isinstance(client_cert, str):
                    self._context.load_cert_chain(client_cert, client_key if isinstance(client_key, str) else None)
            else:
                self._context = make_context(
                    cafile=self._tls["server_cert"],
                    validate_certs=self._tls["validate_certs"],
                    client_cert=self._tls["client_cert"],
                    client_key=self._tls["client_key"],
                )
        url = urlsplit(self.base)
        host, port = url.hostname or "", url.port or 443
        proxy = getproxies().get("https")
        if not proxy or proxy_bypass(host):
            return self._https(host, port)
        purl = urlsplit(proxy if "://" in proxy else "http://" + proxy)
        conn = self._https(purl.hostname or "", purl.port or 3128)
        tunnel_headers = {}
        if purl.username:
            auth = f"{unquote(purl.username)}:{unquote(purl.password or '')}".encode()
            tunnel_headers["Proxy-Authorization"] = "Basic " + base64.b64encode(auth).decode()
        conn.set_tunnel(host, port, headers=tunnel_headers)
        return conn

    def _https(self, host: str, port: int) -> http.client.HTTPSConnection:
        """Return a new HTTPS connection, pinned when O(server_fingerprint) is set."""
        if self._fingerprint:
            return PinnedHTTPSConnection(host, port, timeout=self.timeout, context=self._context, fingerprint=self._fingerprint)
        return http.client.HTTPSConnection(host, port, timeout=self.timeout, context=self._context)

    def close(self) -> None:
        """Close the connection to the server."""
        if self._conn is not None:
            try:
                self._conn.close()
            except _CONNECTION_ERRORS:
                pass
        self._conn = None
        self._proven = False

    def _ready_for_write(self) -> bool:
        """Return whether the open connection gave an answer, is not idle for long, and is not closed by the server."""
        if self._conn is None or not self._proven:
            return False
        if time.monotonic() - self._used_at > IDLE_REUSE_SECONDS:
            return False
        return not _readable(self._conn.sock)

    def _exchange(
        self,
        method: str,
        target: str,
        data: t.Any,
        headers: dict[str, str],
        timeout: int,
        sink: t.IO[bytes] | None = None,
        error_only: bool = False,
    ) -> LXDResponse:
        """Send one request on the open connection, or on a new one. Read the whole answer.

        With O(sink), a successful answer streams into that file in chunks, and the response holds only
        its size and SHA-256. An error answer is small and stays in memory.
        With O(error_only), the body of a successful answer is not read (it can be a large file), and the connection closes.
        """
        if self._conn is not None and (time.monotonic() - self._used_at > IDLE_REUSE_SECONDS or _readable(self._conn.sock)):
            self.close()
        if self._conn is None:
            self._conn = self._new_connection()
            self._proven = False
        conn = self._conn
        conn.timeout = timeout
        if conn.sock is not None:
            conn.sock.settimeout(timeout)
        send_failed = False
        try:
            conn.request(method, target, body=data, headers=headers)
        except _CONNECTION_ERRORS:
            # LXD can answer and close the connection before it reads the whole body: a 403 on a file that it
            # cannot overwrite, or a full disk in the instance. Its answer is often still readable, and it holds
            # the real cause. Without an answer, the send error stands.
            send_failed = True
            try:
                resp = conn.getresponse() if conn.sock is not None else None
            except (*_CONNECTION_ERRORS, AttributeError):
                # http.client can drop the socket after a failed send; getresponse then fails with AttributeError.
                resp = None
            if resp is None:
                self.close()
                raise
        else:
            resp = conn.getresponse()
        if error_only and resp.status < 400:
            result = LXDResponse(resp.status, dict(resp.getheaders()), b"")
            self.close()
            return result
        size = 0
        sha = hashlib.sha256()
        try:
            if sink is not None and resp.status < 400:
                # A retry after a broken read starts the file again.
                sink.seek(0)
                sink.truncate()
                body = b""
                while True:
                    chunk = resp.read(CHUNK_SIZE)
                    if not chunk:
                        break
                    sink.write(chunk)
                    sha.update(chunk)
                    size += len(chunk)
                # http.client gives an empty read when the server closes the connection in the middle of the body.
                # Without this check, a download that broke looks complete.
                expected = next((value for name, value in resp.getheaders() if name.lower() == "content-length"), None)
                if expected is not None and expected.strip().isdigit() and int(expected) != size:
                    raise http.client.IncompleteRead(b"", int(expected) - size)
            else:
                body = resp.read()
        except _CONNECTION_ERRORS:
            if resp.status < 400:
                raise
            # The connection can break while the client reads the error text. The status code is still known.
            body = b""
            self.close()
        result = LXDResponse(resp.status, dict(resp.getheaders()), body, size=size, sha256=sha.hexdigest() if sink is not None else "")
        if resp.will_close or send_failed or self._conn is None:
            self.close()
        else:
            self._proven = True
            self._used_at = time.monotonic()
        return result

    def request(
        self,
        method: str,
        path: str,
        query: dict[str, t.Any] | None = None,
        body: t.Any = None,
        headers: dict[str, str] | None = None,
        raw: bytes | t.IO[bytes] | ChainedReader | None = None,
        timeout: int | None = None,
        sink: t.IO[bytes] | None = None,
        deadline: float | None = None,
    ) -> LXDResponse:
        """Send one request and return the response. HTTP errors raise L(LXDClientError).

        A GET or a HEAD goes again on a new connection after a connection error.
        Any other method goes only on a connection that already gave an answer, and never goes twice.
        O(raw) can be an open file or a L(ChainedReader); it is sent in chunks with its length.
        O(sink) receives the body of a successful answer in chunks (see L(_exchange)).
        O(deadline) (a time.monotonic() value) bounds the attempts: no attempt waits past it, and no retry starts after it.
        """
        target = path
        clean_query = {k: v for k, v in (query or {}).items() if v is not None}
        if clean_query:
            target += ("&" if "?" in target else "?") + urlencode(clean_query)
        send_headers = dict(self.headers)
        send_headers.update(headers or {})
        data: t.Any = None
        if raw is not None:
            data = raw
            send_headers.setdefault("Content-Type", "application/octet-stream")
            length = _stream_length(raw)
            if length is not None:
                send_headers.setdefault("Content-Length", str(length))
        elif body is not None:
            data = json.dumps(body).encode("utf-8")
            send_headers.setdefault("Content-Type", "application/json")
        safe = method in SAFE_METHODS
        if not safe and not self._ready_for_write():
            # A small GET proves that the TLS handshake of the connection is complete on the server.
            self.close()
            self.request("GET", "/")
        started = time.monotonic()
        entry: dict[str, t.Any] = {"method": method, "path": path, "query": clean_query}
        attempts = SAFE_ATTEMPTS if safe else 1
        for attempt in range(attempts):
            attempt_timeout = timeout or self.timeout
            if deadline is not None:
                attempt_timeout = max(1, min(attempt_timeout, int(deadline - time.monotonic())))
            try:
                result = self._exchange(method, target, data, send_headers, attempt_timeout, sink=sink)
                break
            except _CONNECTION_ERRORS as exc:
                self.close()
                # A certificate that does not verify stays wrong. Only a broken connection gets a retry.
                in_time = deadline is None or time.monotonic() + attempt + 1 < deadline
                if attempt + 1 < attempts and in_time and not isinstance(exc, ssl.SSLCertVerificationError):
                    entry["retried"] = _exc_text(exc)
                    time.sleep(attempt + 1)
                    continue
                entry["error"] = _exc_text(exc)
                self.http_log.append(entry)
                where = self.unix_socket or self.base
                if safe:
                    raise LXDClientError(f"Cannot reach LXD at {where}: {_exc_text(exc)}") from exc
                detail = f"The connection to LXD at {where} broke after the {method} request was sent: {_exc_text(exc)}."
                raise LXDClientError(
                    f"{detail} LXD can have applied the change. Run the task again. The module reads the current state first.",
                    outcome_unknown=True,
                    detail=detail,
                ) from exc
        entry["status"] = result.status
        entry["seconds"] = round(time.monotonic() - started, 3)
        self.http_log.append(entry)
        if result.status >= 400:
            message = self._error_text(result)
            if method == "HEAD" and result.status != 404 and not result.body:
                message = self._head_error_text(path, clean_query, target, send_headers, timeout or self.timeout, result.status) or message
            if result.status == 404:
                raise LXDNotFoundError(message, 404)
            raise LXDClientError(message, result.status)
        return result

    def _head_error_text(self, path: str, query: dict[str, t.Any], target: str, headers: dict[str, str], timeout: int, status: int) -> str | None:
        """Return the LXD error text of a failed HEAD, or C(None) when LXD does not give it.

        The answer to a HEAD has no body, so LXD 6.10.1 sends only the status code (for example 500 for the path
        C(/etc/hostname/x) in an instance). The same path goes again as a GET, which is also a read, and its error
        body holds the text. If the GET succeeds, its body is not read: it can be a large file.
        A 404 does not come here: L(head) explains it.
        """
        entry: dict[str, t.Any] = {"method": "GET", "path": path, "query": query, "reason": "error text of the failed HEAD"}
        try:
            result = self._exchange("GET", target, None, headers, timeout, error_only=True)
        except _CONNECTION_ERRORS as exc:
            self.close()
            entry["error"] = _exc_text(exc)
            self.http_log.append(entry)
            return None
        entry["status"] = result.status
        self.http_log.append(entry)
        if result.status != status:
            return None
        return self._error_text(result)

    @staticmethod
    def _error_text(result: LXDResponse) -> str:
        try:
            env = json.loads(result.body or b"{}")
            text = env.get("error") or ""
        except ValueError:
            text = to_text(result.body[:200], errors="surrogate_or_replace")
        return text or f"HTTP {result.status}"

    # ------------------------------------------------------------------
    # JSON API

    def get(self, path: str, query: dict[str, t.Any] | None = None) -> tuple[t.Any, str | None]:
        """GET a path. Return the metadata and the ETag. A 404 raises L(LXDNotFoundError)."""
        resp = self.request("GET", path, query=query)
        return resp.envelope.get("metadata"), resp.etag

    def get_or_none(self, path: str, query: dict[str, t.Any] | None = None) -> tuple[t.Any, str | None]:
        """GET a path. Return C((None, None)) on 404.

        A 404 can also mean that the project or a parent object does not exist. A missing project
        raises L(LXDClientError), because it is almost always a wrong name in the task. A missing
        parent object (for example the instance of a file or a snapshot) adds a note.
        """
        try:
            return self.get(path, query)
        except LXDNotFoundError:
            self._explain_missing(path, query)
            return None, None

    def _explain_missing(self, path: str, query: dict[str, t.Any] | None) -> None:
        project = (query or {}).get("project")
        if project and project != "default":
            try:
                self.get(api_path("projects", project))
            except LXDNotFoundError as exc:
                raise LXDClientError(f'Project "{project}" does not exist. Check the project option.', 404) from exc
            except LXDClientError:
                pass  # For example a certificate that cannot read projects. Do not guess.
        parts = path.rstrip("/").split("/")
        parent_query = {"project": project} if project else None
        for end in range(4, len(parts)):
            parent = "/".join(parts[:end])
            try:
                self.get(parent, parent_query)
            except LXDNotFoundError:
                self.notes.append(f"{parent} does not exist, so {path} does not exist either.")
                return
            except LXDClientError:
                return

    def write(
        self,
        method: str,
        path: str,
        query: dict[str, t.Any] | None = None,
        body: t.Any = None,
        etag: str | None = None,
        headers: dict[str, str] | None = None,
        raw: bytes | t.IO[bytes] | ChainedReader | None = None,
    ) -> t.Any:
        """Send a write and wait for its operation if it is async. Return the result metadata."""
        send_headers = dict(headers or {})
        if etag:
            send_headers["If-Match"] = etag
        resp = self.request(method, path, query=query, body=body, headers=send_headers, raw=raw)
        env = resp.envelope
        if env.get("type") == "async":
            return self.wait_operation(env.get("operation") or "")
        return env.get("metadata")

    def wait_operation(self, operation: str) -> t.Any:
        """Wait for an operation. Return its metadata. A failed operation raises L(LXDClientError)."""
        op_id = operation.rstrip("/").rsplit("/", 1)[-1]
        if not op_id:
            raise LXDClientError("LXD returned an async response without an operation")
        deadline = time.monotonic() + self.timeout
        not_done = f"LXD operation {op_id} did not finish in {self.timeout} seconds."
        still_running = f"{not_done} It can still run on the server. Set a larger timeout, or run the task again when the operation is done."
        # LXD answers a wait slice on time. Allow it this much more for the answer to arrive.
        grace = 30
        broke = False
        while True:
            remaining = max(1, int(deadline - time.monotonic()))
            try:
                resp = self.request(
                    "GET",
                    api_path("operations", op_id, "wait"),
                    query={"timeout": min(remaining, 60)},
                    timeout=min(remaining, 60) + grace,
                    deadline=deadline + grace,
                )
            except LXDNotFoundError as exc:
                if broke:
                    why = (
                        "It finished while the connection to LXD was broken, or LXD restarted and lost it. LXD keeps a "
                        "finished operation only for a short time. The module cannot tell whether it worked. Check the result, "
                        "then run the task again."
                    )
                else:
                    why = "LXD restarted, or another client deleted the operation. Run the task again. The module reads the current state first."
                lost = f"LXD does not know operation {op_id} any more ({exc.message})."
                raise LXDClientError(f"{lost} {why}", operation=op_id, outcome_unknown=True, detail=lost) from exc
            except LXDClientError as exc:
                stopping = _server_stopping(exc)
                if exc.status is not None and not _wait_expired(exc) and not stopping:
                    raise
                if exc.status is None or stopping:
                    # The connection broke, or LXD shuts down: wait until it is back.
                    broke = True
                # The wait slice ran out on the server (LXD answers 500 "context deadline exceeded"),
                # or the connection broke after the read retries. The operation can still run.
                if time.monotonic() >= deadline:
                    last = f"The last error: {exc.message.rstrip('.')}."
                    raise LXDClientError(f"{still_running} {last}", operation=op_id, outcome_unknown=True, detail=f"{not_done} {last}") from exc
                if exc.status is None or stopping:
                    time.sleep(min(WAIT_RECONNECT_SECONDS, max(0.0, deadline - time.monotonic())))
                continue
            meta = resp.envelope.get("metadata") or {}
            status = meta.get("status")
            if status == "Success":
                return meta.get("metadata")
            if status in ("Failure", "Cancelled"):
                raise LXDClientError(f"LXD operation {op_id} failed: {meta.get('err') or status}", operation=op_id)
            if time.monotonic() >= deadline:
                raise LXDClientError(still_running, operation=op_id, outcome_unknown=True, detail=not_done)

    # ------------------------------------------------------------------
    # Server

    def server(self) -> dict[str, t.Any]:
        """Return C(GET /1.0), read once per client."""
        if self._server is None:
            meta, _etag = self.get("/1.0")
            self._server = meta or {}
        return self._server

    def refresh_server(self) -> dict[str, t.Any]:
        """Read C(GET /1.0) again."""
        self._server = None
        return self.server()

    def missing_extensions(self, names: t.Iterable[str]) -> list[str]:
        """Return the extensions in O(names) that the server does not have."""
        have = set(self.server().get("api_extensions") or [])
        return [name for name in names if name not in have]

    def is_clustered(self) -> bool:
        """Return whether the server is part of a cluster."""
        return bool((self.server().get("environment") or {}).get("server_clustered"))

    def server_version(self) -> tuple[int, int, int]:
        """Return the server version as a tuple."""
        return parse_version((self.server().get("environment") or {}).get("server_version") or "")

    def ensure_trusted(self, trust_token: str | None, check_mode: bool = False) -> None:
        """Make sure that the server trusts this client. Use O(trust_token) once if it does not.

        A trust token works only once, so check mode never uses it.
        """
        if self.server().get("auth") == "trusted":
            return
        if trust_token and check_mode:
            raise LXDClientError(
                "The LXD server does not trust this client yet. The module uses trust_token only outside check mode, because a token works only once."
            )
        if trust_token:
            self.write("POST", "/1.0/certificates", body={"type": "client", "trust_token": trust_token})
            if self.refresh_server().get("auth") == "trusted":
                return
        raise LXDClientError("The LXD server does not trust this client")

    # ------------------------------------------------------------------
    # Raw files

    def download(self, path: str, query: dict[str, t.Any] | None = None) -> tuple[bytes, dict[str, str]]:
        """GET a raw file into memory. Return the bytes and the headers. Use L(download_to) for a large file."""
        resp = self.request("GET", path, query=query)
        return resp.body, resp.headers

    def download_to(self, path: str, sink: t.IO[bytes], query: dict[str, t.Any] | None = None) -> LXDResponse:
        """GET a raw file and stream it into O(sink). Return the response with its headers, size and SHA-256."""
        return self.request("GET", path, query=query, sink=sink)

    def head(self, path: str, query: dict[str, t.Any] | None = None) -> dict[str, str] | None:
        """HEAD a path. Return the headers, or C(None) on 404. A 404 is explained as in L(get_or_none).

        Any other error has the text that LXD gives for a GET of the same path (see L(_head_error_text)).
        """
        try:
            return self.request("HEAD", path, query=query).headers
        except LXDNotFoundError:
            self._explain_missing(path, query)
            return None
