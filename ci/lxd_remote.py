# Copyright (c) 2026, Sean McAvoy
# GNU General Public License v3.0+ (see LICENSES/GPL-3.0-or-later.txt or https://www.gnu.org/licenses/gpl-3.0.txt)
# SPDX-License-Identifier: GPL-3.0-or-later
"""Run the full LXD suite on a remote test server, through the LXD API only.

The script runs on any CI machine that reaches the LXD API of the test server.
It pushes the collection into the runner container, starts the runner there,
and pulls the results back. The test VMs stay on the private bridge of the server.

Environment:
  LXD_CI_URL          https://host:8443 of the test server.
  LXD_CI_PROJECT      The test project. It has no default.
  LXD_CI_CLIENT_CERT  PEM client certificate, restricted to the test project.
  LXD_CI_CLIENT_KEY   PEM key of that certificate.
  LXD_CI_SERVER_CERT  PEM certificate of the server. The script pins its fingerprint.
  LXD_CI_RUNNER       The runner container. Default: lxdtest-runner.
  LXD_CI_LOCK_OWNER   Optional. The owner of a run lock that ci/bootstrap.py took for this job. The runner takes it over.
  LXD_CI_BASE_IMAGE   Optional. The base image of the sandbox image. Default: ubuntu:26.04.
  LXD_CI_LXD_CHANNEL  Optional. The LXD snap channel of the sandbox image. Default: 6/candidate.

The values of the three PEM variables can be the PEM text or a path to a file.
"""

from __future__ import annotations

import argparse
import hashlib
import http.client
import io
import json
import os
import re
import shutil
import ssl
import sys
import tarfile
import tempfile
import time
import urllib.parse
import uuid
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SKIP_DIRS = {".git", ".nox", "ci-results", "__pycache__", ".venv"}
LOG_TAIL_LINES = 80
# A test prints a line with this marker to put an LXD fact into the CI job log, also when it passes.
FACT_MARKER = "LXDTEST-FACT"
# A network outage between the CI machine and the server must not end a run. The work goes on in LXD.
RETRY_MINUTES = 15
SANDBOX_DIR = ROOT / "tests" / "lxd" / "sandbox"
DEFAULT_BASE_IMAGE = "ubuntu:26.04"
# 6/candidate has LXD 6.10.2 since 2026-11-26; 6/stable still has 6.10.1. Go back to 6/stable when it has
# the version in tests/lxd/sandbox/min-lxd-version or a newer one.
DEFAULT_LXD_CHANNEL = "6/candidate"


def build_settings() -> tuple[str, str]:
    """Return the base image and the LXD channel of the sandbox image."""
    return os.environ.get("LXD_CI_BASE_IMAGE") or DEFAULT_BASE_IMAGE, os.environ.get("LXD_CI_LXD_CHANNEL") or DEFAULT_LXD_CHANNEL


def image_period() -> str:
    """Return the refresh period of the sandbox image: LXD_CI_IMAGE_PERIOD, or the current month in UTC.

    The snap channels move, but the recipe files do not. A new period gives a new alias, so the image picks up new snap revisions once a month.
    A job sets LXD_CI_IMAGE_PERIOD once, so that its setup step and its test step agree at the end of a month.
    """
    period = os.environ.get("LXD_CI_IMAGE_PERIOD") or time.strftime("%Y-%m", time.gmtime())
    return re.sub(r"[^A-Za-z0-9_.-]", "-", period)


def sandbox_alias(base_image: str, lxd_channel: str) -> str:
    """Return the image alias for the current sandbox recipe.

    The recipe is every file in tests/lxd/sandbox, the base image, the LXD channel, and the refresh period.
    A change to any of them gives a new alias. So branches with different recipes do not replace each other's image.
    """
    digest = hashlib.sha256(f"{base_image}\n{lxd_channel}\n{image_period()}\n".encode())
    for path in sorted(SANDBOX_DIR.iterdir()):
        if path.is_file():
            digest.update(path.name.encode() + b"\n" + path.read_bytes() + b"\n")
    return f"lxdtest/sandbox-{digest.hexdigest()[:12]}"


def lock_owner() -> str:
    """Return the run lock owner from LXD_CI_LOCK_OWNER, limited to safe characters."""
    return re.sub(r"[^A-Za-z0-9_.:-]", "-", os.environ.get("LXD_CI_LOCK_OWNER", ""))


def required(name: str) -> str:
    """Return a variable that has no default. Stop when it is not set."""
    value = os.environ.get(name, "")
    if not value:
        sys.exit(f"{name} is not set")
    return value


def pem_file(name: str, tmp: Path) -> str:
    """Return a file path for a PEM variable that holds a path or the PEM text."""
    value = os.environ.get(name, "")
    if not value:
        sys.exit(f"{name} is not set")
    if os.path.isfile(value):
        return value
    path = tmp / f"{name.lower()}.pem"
    path.write_text(value if value.endswith("\n") else value + "\n")
    path.chmod(0o600)
    return str(path)


class Api:
    """A minimal LXD API client with a pinned server certificate."""

    def __init__(self, url: str, project: str, cert: str, key: str, server_cert: str) -> None:
        parsed = urllib.parse.urlparse(url)
        self.host = parsed.hostname or ""
        self.port = parsed.port or 8443
        self.project = project
        self.ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
        self.ctx.check_hostname = False
        self.ctx.verify_mode = ssl.CERT_NONE
        self.ctx.load_cert_chain(cert, key)
        der = ssl.PEM_cert_to_DER_cert(Path(server_cert).read_text())
        self.pin = hashlib.sha256(der).hexdigest()

    def call(
        self, method: str, path: str, query: dict | None = None, body: object = None, data: bytes | None = None, headers: dict | None = None, timeout: int = 120
    ) -> tuple[int, dict, bytes]:
        """Send one request. Retry a GET or a DELETE after a network error, for up to RETRY_MINUTES."""
        if method not in ("GET", "DELETE"):
            return self.call_once(method, path, query, body, data, headers, timeout)
        deadline = time.monotonic() + RETRY_MINUTES * 60
        pause = 5
        while True:
            try:
                return self.call_once(method, path, query, body, data, headers, timeout)
            except (OSError, http.client.HTTPException) as exc:
                if time.monotonic() > deadline:
                    raise
                print(f"network error on {method} {path}: {type(exc).__name__}: {exc}. Retrying in {pause} s.", flush=True)
                time.sleep(pause)
                pause = min(pause * 2, 60)

    def call_once(
        self, method: str, path: str, query: dict | None, body: object, data: bytes | None, headers: dict | None, timeout: int
    ) -> tuple[int, dict, bytes]:
        """Send one request. Check the server pin. Return status, headers, and body."""
        params = {"project": self.project}
        params.update(query or {})
        url = path + "?" + urllib.parse.urlencode(params)
        send = dict(headers or {})
        payload = data
        if body is not None:
            payload = json.dumps(body).encode()
            send["Content-Type"] = "application/json"
        conn = http.client.HTTPSConnection(self.host, self.port, context=self.ctx, timeout=timeout)
        try:
            conn.connect()
            peer = conn.sock.getpeercert(binary_form=True) if conn.sock else None
            if not peer or hashlib.sha256(peer).hexdigest() != self.pin:
                sys.exit("The server certificate does not match LXD_CI_SERVER_CERT")
            conn.request(method, url, body=payload, headers=send)
            resp = conn.getresponse()
            return resp.status, {k.lower(): v for k, v in resp.getheaders()}, resp.read()
        finally:
            conn.close()

    def json(self, method: str, path: str, **kwargs: object) -> dict:
        """Send a request and decode the JSON envelope. Wait for an async operation."""
        status, _headers, raw = self.call(method, path, **kwargs)  # type: ignore[arg-type]
        env = json.loads(raw or b"{}")
        if status >= 400:
            sys.exit(f"{method} {path} failed with HTTP {status}: {env.get('error')}")
        if env.get("type") == "async":
            return self.wait(env["operation"].rsplit("/", 1)[-1])
        return env.get("metadata") or {}

    def wait(self, op_id: str, limit_minutes: int = 300) -> dict:
        """Wait for an operation. Return its metadata."""
        deadline = time.monotonic() + limit_minutes * 60
        while True:
            status, _headers, raw = self.call("GET", f"/1.0/operations/{op_id}/wait", query={"timeout": "60"}, timeout=120)
            if status in (403, 404):
                # The operation is gone, for example after a restart or a refresh of LXD. Waiting longer does not help.
                sys.exit(f"operation {op_id} is not known to LXD any more (HTTP {status})")
            meta = (json.loads(raw or b"{}").get("metadata") or {}) if status < 400 else {}
            if meta.get("status") in ("Success", "Failure", "Cancelled"):
                return meta
            if time.monotonic() > deadline:
                sys.exit(f"operation {op_id} did not finish in {limit_minutes} minutes")
            if status >= 400:
                # A server error comes back at once. Pause, so that the loop does not flood the API.
                print(f"waiting for operation {op_id}: HTTP {status}. Retrying in 5 s.", flush=True)
                time.sleep(5)


def collection_tarball() -> bytes:
    """Pack the collection without git data and results."""
    buf = io.BytesIO()

    def keep(info: tarfile.TarInfo) -> tarfile.TarInfo | None:
        parts = Path(info.name).parts
        if any(part in SKIP_DIRS for part in parts) or "tests/output" in info.name:
            return None
        return info

    with tarfile.open(fileobj=buf, mode="w:gz") as tar:
        tar.add(ROOT, arcname=".", filter=keep)
    return buf.getvalue()


def print_failures(results: Path, lines: int = LOG_TAIL_LINES) -> None:
    """Print the end of the log of each test that did not pass. The CI job log is then enough to see why."""
    try:
        summary = json.loads((results / "summary.json").read_text())
    except (OSError, ValueError):
        return
    for test in summary.get("tests") or []:
        if test.get("status") not in ("fail", "error", "timeout"):
            continue
        name = f"{test.get('kind')}-{test.get('name')}"
        print(f"\n----- {test.get('status')}: {name}: {test.get('reason') or ''}")
        log_file = results / "logs" / f"{name}.log"
        if log_file.is_file():
            tail = log_file.read_text(errors="replace").splitlines()[-lines:]
            print(f"----- last {len(tail)} lines of {log_file.name}")
            print("\n".join(tail))
        else:
            print("----- no log file")


def print_facts(results: Path) -> None:
    """Print the lines with FACT_MARKER from the log of each test."""
    logs = results / "logs"
    if not logs.is_dir():
        return
    for log_file in sorted(logs.glob("*.log")):
        lines = log_file.read_text(errors="replace").splitlines()
        for number, line in enumerate(lines):
            if FACT_MARKER not in line:
                continue
            # The YAML callback can wrap a long message. The next lines with more indent belong to it.
            indent = len(line) - len(line.lstrip())
            text = [line.strip()]
            for more in lines[number + 1 :]:
                if not more.strip() or len(more) - len(more.lstrip()) <= indent:
                    break
                text.append(more.strip())
            print(f"{log_file.stem}: {' '.join(text)}")


def main() -> int:
    """Push the collection, run the suite in the runner, and pull the results."""
    parser = argparse.ArgumentParser(prog="lxd_remote")
    parser.add_argument("names", nargs="*", help="Targets or scenarios. Empty means all.")
    parser.add_argument("--all", action="store_true", help="Run every target and scenario. The same as no names.")
    parser.add_argument("--slots", type=int, default=4)
    parser.add_argument("--results", default=str(ROOT / "ci-results" / "lxd"))
    parser.add_argument("--scenarios-only", action="store_true")
    parser.add_argument("--targets-only", action="store_true")
    args = parser.parse_args()
    if args.all and (args.names or args.scenarios_only or args.targets_only):
        parser.error("--all does not go with names, --scenarios-only, or --targets-only")

    with tempfile.TemporaryDirectory() as tmpdir:
        tmp = Path(tmpdir)
        api = Api(
            required("LXD_CI_URL"),
            required("LXD_CI_PROJECT"),
            pem_file("LXD_CI_CLIENT_CERT", tmp),
            pem_file("LXD_CI_CLIENT_KEY", tmp),
            pem_file("LXD_CI_SERVER_CERT", tmp),
        )
        runner = os.environ.get("LXD_CI_RUNNER", "lxdtest-runner")
        job = uuid.uuid4().hex[:8]
        base = f"/srv/lxdtest/ci/{job}"
        files = f"/1.0/instances/{runner}/files"

        print(f"job {job}: pushing the collection to {runner}", flush=True)
        api.json(
            "POST",
            f"/1.0/instances/{runner}/exec",
            body={
                "command": ["mkdir", "-p", base],
                "record-output": False,
                "wait-for-websocket": False,
                "interactive": False,
            },
        )
        status, _h, raw = api.call(
            "POST",
            files,
            query={"path": f"{base}/collection.tgz"},
            data=collection_tarball(),
            headers={"X-LXD-type": "file", "X-LXD-write": "overwrite", "X-LXD-mode": "0644", "Content-Type": "application/octet-stream"},
            timeout=600,
        )
        if status >= 400:
            sys.exit(f"push failed: HTTP {status} {raw[:200]!r}")

        options = [f"--slots {args.slots}", f"--results {base}/results", f"--image {sandbox_alias(*build_settings())}"]
        if lock_owner():
            options.append(f"--lock-owner {lock_owner()}")
        if args.scenarios_only:
            options.append("--scenarios-only")
        if args.targets_only:
            options.append("--targets-only")
        names = " ".join(args.names)
        script = (
            f"set -e; mkdir -p {base}/src; tar xzf {base}/collection.tgz -C {base}/src; cd {base}/src; "
            f"set +e; python3 tests/lxd/lxdtest run --collection {base}/src {' '.join(options)} {names}; rc=$?; "
            f"tar czf {base}/results.tgz -C {base} results; exit $rc"
        )
        print(f"job {job}: running the suite", flush=True)
        meta = api.json(
            "POST",
            f"/1.0/instances/{runner}/exec",
            body={
                "command": ["bash", "-c", script],
                "record-output": True,
                "wait-for-websocket": False,
                "interactive": False,
            },
            timeout=300,
        )
        inner = meta.get("metadata") or {}
        code = int(inner.get("return", 2))
        for stream in ("1", "2"):
            out_url = (inner.get("output") or {}).get(stream)
            if out_url:
                st, _h, body = api.call("GET", urllib.parse.urlparse(out_url).path)
                if st < 400:
                    sys.stdout.write(body.decode(errors="replace"))
                api.call("DELETE", urllib.parse.urlparse(out_url).path)

        results = Path(args.results)
        results.mkdir(parents=True, exist_ok=True)
        st, _h, body = api.call("GET", files, query={"path": f"{base}/results.tgz"}, timeout=600)
        if st < 400:
            unpack = tmp / "unpack"
            with tarfile.open(fileobj=io.BytesIO(body), mode="r:gz") as tar:
                tar.extractall(unpack, filter="data")
            shutil.copytree(unpack / "results", results, dirs_exist_ok=True)
            print(f"job {job}: results in {results}")
            print_facts(results)
            print_failures(results)
        api.json(
            "POST",
            f"/1.0/instances/{runner}/exec",
            body={
                "command": ["rm", "-rf", base],
                "record-output": False,
                "wait-for-websocket": False,
                "interactive": False,
            },
        )
        print(f"=== TESTS {'PASSED' if code == 0 else 'FAILED'} (runner exit code {code})")
        return code


if __name__ == "__main__":
    sys.exit(main())
