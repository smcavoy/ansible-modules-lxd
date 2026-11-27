# Copyright (c) 2026, Sean McAvoy
# GNU General Public License v3.0+ (see LICENSES/GPL-3.0-or-later.txt or https://www.gnu.org/licenses/gpl-3.0.txt)
# SPDX-License-Identifier: GPL-3.0-or-later
"""Set up a test project on an LXD server for the tier 2 suite.

The tier 2 CI jobs run it as their first step, with --yes. When everything exists, it only checks, in seconds.
It also runs by hand, from any machine that reaches the LXD API:

    python3 ci/bootstrap.py --check      # read only: show the state and the plan
    python3 ci/bootstrap.py              # do the plan, after a typed confirmation

The owner first creates the project, its default profile (root disk and NIC), and the bridge.
The owner also trusts the client certificate, restricted to the project.
By default the runner uses that client certificate too, so no other trust entry is needed.
With --token-file, the runner gets its own identity from a trust token instead.
This script changes nothing outside the project, and it changes no trust entry except the one a runner token creates.

Steps. Each step is skipped when its result exists.
  1. Check the API, the project, and its default profile. Read only.
  2. Take the run lock (the stopped container lxdtest-lock). Wait while a test run holds it. The lock expires
     20 minutes after its last renewal; the holder renews it every 5 minutes while it lives.
  3. Create and start the runner container.
  4. Check that the runner reaches the host API. Stop if it does not.
  5. Install the runner software: Python venv, ansible-core, git, openssl, the lxc client.
  6. Add the host as an lxc remote in the runner. It uses the client certificate, or the trust token if one is given.
  7. Make the test client certificate for the sandboxes, in /root/pki of the runner.
  8. Build the sandbox image from tests/lxd/sandbox/, if no image exists for the current recipe.
     The image name holds a hash of the recipe. Old images are deleted, except the newest few.
  9. Put the test container image into /srv/lxdtest/images of the runner.
 10. Write /etc/lxdtest/config.json in the runner. tests/lxd/lxdtest reads the remote and the project from it.
 11. Release the run lock, or hand it to the test run (LXD_CI_LOCK_OWNER). Then no other run can start in between.

Connection options (the environment variables are the same as for ci/lxd_remote.py):
  --url          LXD_CI_URL          https://host:8443 of the server.
  --project      LXD_CI_PROJECT      The test project.
  --client-cert  LXD_CI_CLIENT_CERT  Client certificate, restricted to the project. A path or the PEM text.
  --client-key   LXD_CI_CLIENT_KEY   Its key. A path or the PEM text.
  --server-cert  LXD_CI_SERVER_CERT  Server certificate. The script pins its fingerprint. A path or the PEM text.
  --token-file   LXD_RUNNER_TOKEN    Optional. A trust token that gives the runner its own identity. The script never prints it.
"""

from __future__ import annotations

import argparse
import datetime
import hashlib
import json
import os
import re
import socket
import ssl
import sys
import tempfile
import threading
import time
import typing as t
import urllib.parse
import uuid
from pathlib import Path

from lxd_remote import Api, build_settings, lock_owner, sandbox_alias

ROOT = Path(__file__).resolve().parents[1]
SANDBOX_FILES = ROOT / "tests" / "lxd" / "sandbox"
SANDBOX_PREFIX = "lxdtest/sandbox-"
RUNNER_STAMP = "/etc/lxdtest/runner.json"
LOCK_NAME = "lxdtest-lock"
# The lock expires this many minutes after its last renewal. The bootstrap renews it every LOCK_BEAT_SECONDS
# while it works, so a lock whose job was killed frees itself soon. The test run (tests/lxd/lxdtest) does the same.
LOCK_MINUTES = 20
LOCK_BEAT_SECONDS = 300
LXC_CONF = "/root/snap/lxd/common/config"
MIN_VERSION = (6, 10, 1)

# Script for step 4. It runs in the runner and needs only python3.
REACH_CHECK = """
import ssl, sys, urllib.request
ctx = ssl.create_default_context()
ctx.check_hostname = False
ctx.verify_mode = ssl.CERT_NONE
try:
    with urllib.request.urlopen(sys.argv[1] + "/1.0", context=ctx, timeout=15) as resp:
        print("HTTP", resp.status)
except Exception as exc:
    print(type(exc).__name__, exc)
    sys.exit(1)
"""

# Script for step 5. It runs in the runner as root.
INSTALL = """
set -eu
export DEBIAN_FRONTEND=noninteractive
apt-get update -q
apt-get install -y -q python3-venv git ca-certificates openssl curl iptables
snap wait system seed.loaded
if snap list lxd >/dev/null 2>&1; then
  snap refresh lxd --channel="$LXD_CHANNEL"
else
  snap install lxd --channel="$LXD_CHANNEL"
fi
snap refresh --hold lxd
if [ ! -x /opt/venv/bin/ansible-test ] || [ "$(/opt/venv/bin/ansible --version | head -1)" != "ansible [core $ANSIBLE_CORE]" ]; then
  python3 -m venv /opt/venv
  /opt/venv/bin/pip install -q "ansible-core==$ANSIBLE_CORE"
fi
mkdir -p /srv/lxdtest/work /srv/lxdtest/images /srv/lxdtest/ci /etc/lxdtest
install -d -m 700 /root/pki
/opt/venv/bin/ansible --version | head -1
"""

# Script for step 7. It makes the key only when none exists.
MAKE_CERT = """
set -eu
cd /root/pki
if [ ! -s client.key ] || [ ! -s client.crt ]; then
  umask 077
  openssl req -x509 -newkey ec -pkeyopt ec_paramgen_curve:secp384r1 -nodes -days 3650 \\
    -subj "/CN=lxdtest-sandbox-client" -addext "extendedKeyUsage=clientAuth" \\
    -keyout client.key -out client.crt
  chmod 644 client.crt
  echo "made a new test client certificate"
fi
"""


def log(msg: str) -> None:
    """Print one timestamped line."""
    stamp = datetime.datetime.now(datetime.timezone.utc).strftime("%H:%M:%S")
    print(f"[{stamp}] {msg}", flush=True)


def lock_expiry() -> str:
    """Return the expiry time of a lock that lives LOCK_MINUTES from now."""
    return (datetime.datetime.now(datetime.timezone.utc) + datetime.timedelta(minutes=LOCK_MINUTES)).isoformat()


def fail(msg: str) -> t.NoReturn:
    """Stop with a message. The finally blocks still release the lock."""
    raise SystemExit(f"SETUP FAILED (bootstrap): {msg}")


def pem_path(value: str, name: str, tmp: Path) -> str:
    """Return a file path for a value that is a path or the PEM text."""
    if not value:
        fail(f"{name} is not set")
    if os.path.isfile(value):
        return value
    path = tmp / f"{name}.pem"
    path.write_text(value if value.endswith("\n") else value + "\n")
    path.chmod(0o600)
    return str(path)


def image_ref(value: str) -> tuple[str, str]:
    """Split C(registry:alias), for example C(ubuntu:26.04)."""
    registry, sep, alias = value.partition(":")
    if not sep or not registry or not alias:
        fail(f"image {value!r} is not in the form registry:alias")
    return registry, alias


def min_lxd_version() -> str:
    """Return the oldest LXD version that a sandbox may run, from the image recipe."""
    lines = (SANDBOX_FILES / "min-lxd-version").read_text().splitlines()
    return next(line.strip() for line in lines if line.strip() and not line.startswith("#"))


def parse_version(text: str) -> tuple[int, ...]:
    """Parse C(6.10.1) or C(6.10.1 LTS)."""
    parts = []
    for item in text.split()[0].split("."):
        parts.append(int(item) if item.isdigit() else 0)
    return tuple(parts)


def split_multipart(content_type: str, body: bytes) -> dict[str, bytes]:
    """Return the parts of a multipart body by their form field name.

    A plain byte split: a VM image is large, and the email parser is slow on large binary parts.
    A delimiter counts only at the start of a line, followed by a line end or by "--".
    """
    match = re.search(r'boundary="?([^";]+)"?', content_type)
    if not match:
        return {}
    delimiter = b"\r\n--" + match.group(1).encode()
    data = b"\r\n" + body
    parts: dict[str, bytes] = {}
    pos = data.find(delimiter)
    while pos != -1:
        start = pos + len(delimiter)
        if data[start : start + 2] == b"--":
            break
        nxt = data.find(delimiter, start)
        while nxt != -1 and data[nxt + len(delimiter) : nxt + len(delimiter) + 2] not in (b"\r\n", b"--"):
            nxt = data.find(delimiter, nxt + 1)
        chunk = data[start + 2 : nxt if nxt != -1 else len(data)]
        head, sep, payload = chunk.partition(b"\r\n\r\n")
        name = re.search(rb'name="([^"]+)"', head)
        if sep and name:
            parts[name.group(1).decode()] = payload
        pos = nxt
    return parts


class Lxd:
    """The steps of the bootstrap, on top of the pinned API client."""

    def __init__(self, api: Api) -> None:
        self.api = api

    # Plain API calls

    def get(self, path: str) -> dict | None:
        """Return the metadata of a GET, or None for 404."""
        status, _headers, raw = self.api.call("GET", path)
        if status == 404:
            return None
        env = json.loads(raw or b"{}")
        if status >= 400:
            fail(f"GET {path} failed with HTTP {status}: {env.get('error')}")
        return env.get("metadata")

    def write(self, method: str, path: str, body: object = None, timeout_minutes: int = 60) -> dict:
        """Send a write. Wait for an async operation and check that it worked."""
        status, _headers, raw = self.api.call(method, path, body=body, timeout=600)
        env = json.loads(raw or b"{}")
        if method == "DELETE" and status == 404:
            # The client retries a DELETE after a network error. A 404 then means that the first DELETE worked.
            return {}
        if status >= 400:
            fail(f"{method} {path} failed with HTTP {status}: {env.get('error')}")
        if env.get("type") != "async":
            return env.get("metadata") or {}
        meta = self.api.wait(env["operation"].rsplit("/", 1)[-1], limit_minutes=timeout_minutes)
        if meta.get("status") != "Success":
            fail(f"{method} {path} failed: {meta.get('err')}")
        return meta

    def state(self, name: str, action: str, force: bool = False) -> None:
        """Start or stop an instance."""
        self.write("PUT", f"/1.0/instances/{name}/state", body={"action": action, "timeout": 60, "force": force})

    # Exec and files

    def exec(self, name: str, command: list[str], env: dict[str, str] | None = None, timeout_minutes: int = 30) -> tuple[int, str, str]:
        """Run a command in an instance. Return the exit code, stdout, and stderr. The code is -1 when LXD cannot start it."""
        body = {
            "command": command,
            "environment": env or {},
            "record-output": True,
            "wait-for-websocket": False,
            "interactive": False,
        }
        status, _headers, raw = self.api.call("POST", f"/1.0/instances/{name}/exec", body=body, timeout=120)
        envelope = json.loads(raw or b"{}")
        if status >= 400:
            return -1, "", str(envelope.get("error"))
        meta = self.api.wait(envelope["operation"].rsplit("/", 1)[-1], limit_minutes=timeout_minutes)
        inner = meta.get("metadata") or {}
        if meta.get("status") != "Success" and "return" not in inner:
            return -1, "", str(meta.get("err"))
        output = ["", ""]
        for index, stream in enumerate(("1", "2")):
            url = (inner.get("output") or {}).get(stream)
            if url:
                path = urllib.parse.urlparse(url).path
                got, _h, data = self.api.call("GET", path)
                if got < 400:
                    output[index] = data.decode(errors="replace")
                self.api.call("DELETE", path)
        return int(inner.get("return", -1)), output[0], output[1]

    def run(self, name: str, script: str, env: dict[str, str] | None = None, what: str = "", timeout_minutes: int = 30) -> str:
        """Run a shell script in an instance with a trace. Stop on failure, and show the end of the trace.

        The script runs under C(timeout), 30 seconds shorter than the wait for the LXD operation.
        So a script that hangs still returns its trace, and the error shows the last command.
        """
        self.push(name, "/root/lxdtest-step.sh", script.encode(), mode="0700")
        seconds = max(30, timeout_minutes * 60 - 30)
        wrapped = (
            f"timeout {seconds} sh -x /root/lxdtest-step.sh >/root/lxdtest-step.out 2>/root/lxdtest-step.log; rc=$?; "
            "cat /root/lxdtest-step.out; [ $rc -eq 0 ] || tail -c 12000 /root/lxdtest-step.log >&2; exit $rc"
        )
        code, out, err = self.exec(name, ["sh", "-c", wrapped], env=env, timeout_minutes=timeout_minutes)
        if code != 0:
            reason = " (time limit)" if code == 124 else ""
            fail(f"{what or 'script'} failed in {name} (exit {code}{reason}):\n{(out + err)[-4000:]}")
        return out

    def wait_exec(self, name: str, minutes: int = 5) -> None:
        """Wait until LXD can run a command in the instance."""
        deadline = time.monotonic() + minutes * 60
        last = ""
        while time.monotonic() < deadline:
            code, _out, last = self.exec(name, ["true"], timeout_minutes=1)
            if code == 0:
                return
            time.sleep(3)
        fail(f"{name} did not accept commands in {minutes} minutes: {last}")

    def push(self, name: str, path: str, data: bytes, mode: str = "0644") -> None:
        """Write a file into an instance."""
        status, _headers, raw = self.api.call(
            "POST",
            f"/1.0/instances/{name}/files",
            query={"path": path},
            data=data,
            headers={"X-LXD-type": "file", "X-LXD-write": "overwrite", "X-LXD-mode": mode, "X-LXD-uid": "0", "X-LXD-gid": "0"},
            timeout=600,
        )
        if status >= 400:
            fail(f"writing {path} into {name} failed with HTTP {status}: {raw[:200]!r}")

    def pull(self, name: str, path: str) -> bytes | None:
        """Read a file from an instance. Return None when it does not exist."""
        status, _headers, raw = self.api.call("GET", f"/1.0/instances/{name}/files", query={"path": path}, timeout=600)
        if status == 404:
            return None
        if status >= 400:
            fail(f"reading {path} from {name} failed with HTTP {status}")
        return raw

    # Instances and images

    def create_instance(self, name: str, kind: str, image: tuple[str, str] | None, config: dict, devices: dict | None = None) -> None:
        """Create an instance from a registry image, or an empty one."""
        source: dict = {"type": "none"}
        if image:
            source = {"type": "image", "image_registry": image[0], "alias": image[1]}
        body = {"name": name, "type": kind, "source": source, "config": config, "devices": devices or {}}
        self.write("POST", "/1.0/instances", body=body, timeout_minutes=60)

    def delete_instance(self, name: str) -> None:
        """Delete an instance. Stop it first."""
        current = self.get(f"/1.0/instances/{name}")
        if current is None:
            return
        if current.get("status") != "Stopped":
            self.state(name, "stop", force=True)
        self.write("DELETE", f"/1.0/instances/{name}")

    def alias_target(self, alias: str) -> str:
        """Return the fingerprint that an image alias points to, or an empty string."""
        meta = self.get(f"/1.0/images/aliases/{urllib.parse.quote(alias, safe='')}")
        return (meta or {}).get("target", "")

    def set_alias(self, alias: str, fingerprint: str, description: str) -> None:
        """Point an image alias to a fingerprint."""
        path = f"/1.0/images/aliases/{urllib.parse.quote(alias, safe='')}"
        if self.get(path) is None:
            self.write("POST", "/1.0/images/aliases", body={"name": alias, "target": fingerprint, "description": description})
        else:
            self.write("PUT", path, body={"target": fingerprint, "description": description})


class Bootstrap:
    """The plan and its steps."""

    def __init__(self, args: argparse.Namespace, lxd: Lxd, new_lxd: t.Callable[[], Lxd] | None = None) -> None:
        self.args = args
        self.lxd = lxd
        # A second client for the lock renewal thread: one API connection is not shared between threads.
        self.new_lxd = new_lxd
        self.runner = args.runner
        self.plan: list[str] = []
        self.pool = ""
        self.client_pem = b""
        self.alias = sandbox_alias(args.base_image, args.lxd_channel)
        self.install_stamp = {
            "ansible_core": args.ansible_core,
            "lxd_channel": args.lxd_channel,
            "install": hashlib.sha256(INSTALL.encode()).hexdigest()[:12],
        }

    # Step 1: read only.

    def check(self) -> None:
        """Check the server, the project, and the profile. Build the plan."""
        server = self.lxd.get("/1.0") or {}
        if server.get("auth") != "trusted":
            fail("the server does not trust the client certificate")
        env = server.get("environment") or {}
        version = env.get("server_version", "0")
        log(f"server: LXD {version}, auth {server.get('auth')}, auth method {server.get('auth_method', '?')}")
        if parse_version(version) < MIN_VERSION:
            fail(f"LXD {version} is older than 6.10.1")
        if "image_registries" not in (server.get("api_extensions") or []):
            fail("the server lacks the API extension image_registries")

        project = self.lxd.get(f"/1.0/projects/{self.args.project}")
        if project is None:
            fail(f"project {self.args.project} does not exist, or the certificate cannot see it")
        pconf = (project or {}).get("config") or {}
        log(f"project {self.args.project}: " + ", ".join(f"{k}={v}" for k, v in sorted(pconf.items()) if k.startswith(("features.", "limits.", "restricted"))))
        if pconf.get("features.images") != "true":
            log("WARNING: features.images is not true. The sandbox image goes into the image store of the default project.")

        profile = self.lxd.get("/1.0/profiles/default") or {}
        devices = profile.get("devices") or {}
        roots = [d for d in devices.values() if d.get("type") == "disk" and d.get("path") == "/"]
        nics = [d for d in devices.values() if d.get("type") == "nic"]
        if not roots or not nics:
            fail("the default profile of the project needs a root disk and a NIC")
        self.pool = roots[0].get("pool", "")
        log(f"default profile: root on pool {self.pool}, NIC on {nics[0].get('network') or nics[0].get('parent')}")

        lock = self.lxd.get(f"/1.0/instances/{LOCK_NAME}")
        if lock is not None:
            owner = (lock.get("config") or {}).get("user.lock.owner", "?")
            log(f"{LOCK_NAME} is held by {owner}")
            self.plan.append(f"wait up to {self.args.lock_wait} minutes for the lock {LOCK_NAME}, then take it")
        else:
            self.plan.append(f"take the lock {LOCK_NAME}")

        runner = self.lxd.get(f"/1.0/instances/{self.runner}")
        if runner is None:
            self.plan.append(f"create the runner container {self.runner} from {self.args.base_image}")
        elif runner.get("status") != "Running":
            self.plan.append(f"start the runner container {self.runner}")
        else:
            log(f"runner {self.runner} is running")
        self.plan.append(f"check that the runner reaches {self.args.runner_url}")
        self.plan.append(f"install the runner software if it changed: ansible-core {self.args.ansible_core}, lxc {self.args.lxd_channel}")
        how = "with the trust token" if (self.args.token_file or os.environ.get("LXD_RUNNER_TOKEN")) else "with the client certificate"
        self.plan.append(f"add the lxc remote {self.args.remote_name} in the runner {how}, if it is missing")
        self.plan.append("make the test client certificate in /root/pki of the runner, if it is missing")

        target = self.lxd.alias_target(self.alias)
        if not target:
            self.plan.append(f"build the sandbox image {self.alias} for the current recipe (about 5 minutes)")
        else:
            image = self.lxd.get(f"/1.0/images/{target}") or {}
            client = (image.get("properties") or {}).get("lxdtest.client", "?")
            log(f"sandbox image {self.alias}: {target[:12]}, test client {client[:12]}")
            when = "now (forced)" if self.args.rebuild_image else "only if the test client certificate changed"
            self.plan.append(f"build the sandbox image {self.alias} again {when}")
        self.plan.append(f"put the container and VM test images of {self.args.test_image} into the runner, if they are missing")
        self.plan.append("write /etc/lxdtest/config.json in the runner")
        if self.args.lock_owner:
            self.plan.append(f"hand the lock {LOCK_NAME} to the test run {self.args.lock_owner}")
        else:
            self.plan.append(f"release the lock {LOCK_NAME}")

    # Steps 2 to 11.

    def take_lock(self) -> None:
        """Step 2. Wait while another run holds the lock. Remove a lock that is past its expiry."""
        owner = self.args.lock_owner or f"bootstrap@{socket.gethostname()}"
        # The lock lives LOCK_MINUTES. A thread renews it while the bootstrap works (L(start_lock_beat)), and
        # L(refresh_lock) renews it before each long step. A hand-over lock lives LOCK_MINUTES after the bootstrap,
        # and the test step of the same job takes it within seconds.
        deadline = time.monotonic() + self.args.lock_wait * 60
        while True:
            expires = lock_expiry()
            body = {"name": LOCK_NAME, "type": "container", "source": {"type": "none"}, "config": {"user.lock.owner": owner, "user.lock.expires": expires}}
            status, _headers, raw = self.lxd.api.call("POST", "/1.0/instances", body=body)
            envelope = json.loads(raw or b"{}")
            if status < 400:
                if envelope.get("type") == "async":
                    meta = self.lxd.api.wait(envelope["operation"].rsplit("/", 1)[-1], limit_minutes=5)
                    if meta.get("status") != "Success":
                        fail(f"taking the lock failed: {meta.get('err')}")
                log(f"took the lock {LOCK_NAME} as {owner}")
                return
            if "already exists" not in str(envelope.get("error")):
                fail(f"taking the lock failed with HTTP {status}: {envelope.get('error')}")
            lock = self.lxd.get(f"/1.0/instances/{LOCK_NAME}") or {}
            config = lock.get("config") or {}
            if config.get("user.lock.owner") == owner:
                log(f"the lock {LOCK_NAME} is already ours ({owner})")
                return
            if self.lock_expired(config.get("user.lock.expires", "")):
                log(f"the lock of {config.get('user.lock.owner', '?')} is stale. Removing it.")
                self.lxd.delete_instance(LOCK_NAME)
                continue
            if time.monotonic() >= deadline:
                fail(f"test server busy: {config.get('user.lock.owner', '?')} holds the lock {LOCK_NAME}")
            log(f"{config.get('user.lock.owner', '?')} holds the lock. Waiting 60 s.")
            time.sleep(60)

    def refresh_lock(self, lxd: Lxd | None = None) -> None:
        """Move the expiry of our lock on by LOCK_MINUTES, from now."""
        (lxd or self.lxd).write("PATCH", f"/1.0/instances/{LOCK_NAME}", body={"config": {"user.lock.expires": lock_expiry()}})

    def start_lock_beat(self) -> threading.Event:
        """Renew the lock every LOCK_BEAT_SECONDS in a thread, until the returned event is set."""
        done = threading.Event()
        if self.new_lxd is None:
            return done
        lxd = self.new_lxd()

        def beat() -> None:
            while not done.wait(LOCK_BEAT_SECONDS):
                try:
                    self.refresh_lock(lxd)
                except Exception as exc:  # noqa: BLE001 - a failed renewal must not stop the bootstrap; the next one tries again
                    log(f"lock renewal failed, trying again in {LOCK_BEAT_SECONDS} s: {exc}")

        threading.Thread(target=beat, name="lock-beat", daemon=True).start()
        return done

    @staticmethod
    def lock_expired(value: str) -> bool:
        """Return whether a lock expiry time is in the past. A lock without one never expires."""
        if not value:
            return False
        try:
            return datetime.datetime.fromisoformat(value) < datetime.datetime.now(datetime.timezone.utc)
        except ValueError:
            return True

    def release_lock(self) -> None:
        """Step 11."""
        self.lxd.delete_instance(LOCK_NAME)
        log(f"released the lock {LOCK_NAME}")

    def ensure_runner(self) -> None:
        """Step 3."""
        current = self.lxd.get(f"/1.0/instances/{self.runner}")
        if current is None:
            log(f"creating the runner {self.runner}")
            config = {"limits.cpu": self.args.runner_cpu, "limits.memory": self.args.runner_memory}
            self.lxd.create_instance(self.runner, "container", image_ref(self.args.base_image), config)
            current = {"status": "Stopped"}
        else:
            self.update_runner_limits(current)
        if current.get("status") == "Running":
            log(f"runner {self.runner} is running")
            return
        self.lxd.state(self.runner, "start")
        self.lxd.wait_exec(self.runner)
        self.lxd.exec(self.runner, ["cloud-init", "status", "--wait"], timeout_minutes=10)
        log(f"runner {self.runner} is ready")

    def update_runner_limits(self, current: dict) -> None:
        """Give an existing runner the CPU and memory limits of the options. LXD applies them to a running container at once."""
        wanted = {"limits.cpu": self.args.runner_cpu, "limits.memory": self.args.runner_memory}
        config = current.get("config") or {}
        changes = {key: value for key, value in wanted.items() if config.get(key) != value}
        if not changes:
            return
        old = ", ".join(f"{key}={config.get(key, '')}" for key in changes)
        log(f"changing the limits of the runner {self.runner}: {old} -> " + ", ".join(f"{key}={value}" for key, value in changes.items()))
        self.lxd.write("PATCH", f"/1.0/instances/{self.runner}", body={"config": changes})

    def check_reach(self) -> None:
        """Step 4."""
        code, output, err = self.lxd.exec(self.runner, ["python3", "-c", REACH_CHECK, self.args.runner_url], timeout_minutes=2)
        output += err
        if code != 0:
            fail(
                f"the runner cannot reach the host API at {self.args.runner_url}: {output.strip()}\n"
                "Check the host firewall for the bridge of the project. This script adds no firewall rule."
            )
        log(f"the runner reaches {self.args.runner_url}: {output.strip()}")

    def install(self) -> None:
        """Step 5. Skip it when the stamp file shows the same software and the same install script."""
        stamp = self.lxd.pull(self.runner, RUNNER_STAMP)
        try:
            current = json.loads(stamp) if stamp else {}
        except ValueError:
            current = {}
        if current == self.install_stamp:
            log(f"runner software is current: ansible-core {self.args.ansible_core}, lxc {self.args.lxd_channel}")
            return
        log("installing the runner software (about 1 minute)")
        env = {"LXD_CHANNEL": self.args.lxd_channel, "ANSIBLE_CORE": self.args.ansible_core}
        output = self.lxd.run(self.runner, INSTALL, env=env, what="software install", timeout_minutes=30)
        self.lxd.push(self.runner, RUNNER_STAMP, (json.dumps(self.install_stamp, indent=2) + "\n").encode())
        log(f"runner software: {output.strip().splitlines()[-1] if output.strip() else '?'}")

    def ensure_remote(self) -> None:
        """Step 6."""
        name = self.args.remote_name
        code, output, _err = self.lxd.exec(self.runner, ["sh", "-c", "lxc remote list --format json </dev/null"], timeout_minutes=2)
        try:
            remotes = json.loads(output) if code == 0 else {}
        except ValueError:
            remotes = {}
        if name not in remotes:
            token = self.read_token()
            if token:
                self.add_remote_with_token(name, token)
            else:
                self.add_remote_with_cert(name)
        query = f"{name}:/1.0?project={urllib.parse.quote(self.args.project)}"
        code, output, err = self.lxd.exec(self.runner, ["sh", "-c", f"lxc query '{query}' </dev/null"], timeout_minutes=2)
        try:
            auth = json.loads(output).get("auth") if code == 0 else None
        except ValueError:
            auth = None
        if auth != "trusted":
            fail(f"the runner remote {name} is not trusted for project {self.args.project}: {(output + err).strip()[-500:]}")
        log(f"the runner remote {name} is trusted for project {self.args.project}")

    def add_remote_with_token(self, name: str, token: str) -> None:
        """Add the remote with a trust token. The runner gets its own identity."""
        log(f"adding the lxc remote {name} in the runner, with a trust token")
        env = {"BOOT_TOKEN": token, "BOOT_REMOTE": name, "BOOT_URL": self.args.runner_url}
        script = 'lxc remote add "$BOOT_REMOTE" "$BOOT_URL" --token "$BOOT_TOKEN" </dev/null'
        code, output, err = self.lxd.exec(self.runner, ["sh", "-c", script], env=env, timeout_minutes=2)
        if code != 0:
            fail(f"lxc remote add failed: {(output + err).replace(token, '<token>').strip()[-2000:]}")

    def add_remote_with_cert(self, name: str) -> None:
        """Add the remote with the client certificate of this script. Check the server certificate against the pin."""
        log(f"adding the lxc remote {name} in the runner, with the client certificate")
        self.lxd.run(self.runner, f"install -d -m 700 {LXC_CONF}", what="lxc config folder", timeout_minutes=1)
        self.lxd.push(self.runner, f"{LXC_CONF}/client.crt", Path(self.args.cert_path).read_bytes())
        self.lxd.push(self.runner, f"{LXC_CONF}/client.key", Path(self.args.key_path).read_bytes(), mode="0600")
        env = {"BOOT_REMOTE": name, "BOOT_URL": self.args.runner_url}
        script = 'lxc remote add "$BOOT_REMOTE" "$BOOT_URL" --accept-certificate --auth-type tls </dev/null'
        code, output, err = self.lxd.exec(self.runner, ["sh", "-c", script], env=env, timeout_minutes=2)
        if code != 0:
            fail(f"lxc remote add failed: {(output + err).strip()[-2000:]}")
        served = self.lxd.pull(self.runner, f"{LXC_CONF}/servercerts/{name}.crt") or b""
        try:
            fingerprint = hashlib.sha256(ssl.PEM_cert_to_DER_cert(served.decode())).hexdigest()
        except ValueError:
            fingerprint = ""
        if fingerprint != self.lxd.api.pin:
            self.lxd.exec(self.runner, ["lxc", "remote", "remove", name], timeout_minutes=1)
            fail(f"the runner sees another server certificate at {self.args.runner_url} than the pinned one. It removed the remote.")
        log(f"the server certificate that the runner sees matches the pin {fingerprint[:12]}")

    def read_token(self) -> str:
        """Read the optional trust token for the runner. Never print it."""
        token = os.environ.get("LXD_RUNNER_TOKEN", "")
        if self.args.token_file:
            token = Path(self.args.token_file).read_text().strip()
        return token

    def ensure_test_cert(self) -> str:
        """Step 7. Return the fingerprint of the test client certificate."""
        output = self.lxd.run(self.runner, MAKE_CERT, what="test certificate", timeout_minutes=2)
        if output.strip():
            log(output.strip())
        pem = self.lxd.pull(self.runner, "/root/pki/client.crt")
        if not pem:
            fail("/root/pki/client.crt is missing in the runner")
        self.client_pem = pem
        fingerprint = hashlib.sha256(ssl.PEM_cert_to_DER_cert(pem.decode())).hexdigest()
        log(f"test client certificate: {fingerprint[:12]}")
        return fingerprint

    def ensure_sandbox_image(self, client_fp: str) -> None:
        """Step 8."""
        alias = self.alias
        old = self.lxd.alias_target(alias)
        if old and not self.args.rebuild_image:
            props = (self.lxd.get(f"/1.0/images/{old}") or {}).get("properties") or {}
            if props.get("lxdtest.client") == client_fp:
                log(f"sandbox image {alias} is current")
                return
            log(f"sandbox image {alias} trusts another test client certificate. Building it again.")
        name = f"lxdtest-build-{uuid.uuid4().hex[:6]}"
        log(f"building the sandbox image in {name}")
        config = {"limits.cpu": "2", "limits.memory": "3GiB"}
        # The image gets the disk size of the build VM, and a sandbox cannot have a smaller root disk than its image.
        lines = (SANDBOX_FILES / "root-gib").read_text().splitlines()
        root_gib = int(next(line for line in lines if line.strip() and not line.startswith("#")))
        devices = {"root": {"type": "disk", "pool": self.pool, "path": "/", "size": f"{root_gib}GiB"}}
        try:
            self.lxd.create_instance(name, "virtual-machine", image_ref(self.args.base_image), config, devices)
            self.lxd.state(name, "start")
            self.lxd.wait_exec(name, minutes=5)
            prepare = (SANDBOX_FILES / "prepare.sh").read_text()
            build_env = {"LXD_CHANNEL": self.args.lxd_channel, "LXD_MIN_VERSION": min_lxd_version()}
            self.lxd.run(name, prepare, env=build_env, what="sandbox preparation", timeout_minutes=45)
            self.lxd.push(name, "/etc/lxd-sandbox/preseed.yaml", (SANDBOX_FILES / "preseed.yaml").read_bytes())
            self.lxd.push(name, "/etc/lxd-sandbox/client.crt", self.client_pem)
            self.lxd.push(name, "/usr/local/sbin/lxd-sandbox-init", (SANDBOX_FILES / "lxd-sandbox-init").read_bytes(), mode="0755")
            self.lxd.push(name, "/etc/systemd/system/lxd-sandbox-init.service", (SANDBOX_FILES / "lxd-sandbox-init.service").read_bytes())
            self.lxd.run(name, (SANDBOX_FILES / "seal.sh").read_text(), what="sandbox seal", timeout_minutes=5)
            self.lxd.state(name, "stop")
            log("publishing the sandbox image (about 2 minutes)")
            body = {
                "source": {"type": "instance", "name": name},
                "public": False,
                "properties": {
                    "description": f"LXD test sandbox, lxd snap {self.args.lxd_channel}",
                    "lxdtest.client": client_fp,
                    "lxdtest.lxd_channel": self.args.lxd_channel,
                    "lxdtest.base_image": self.args.base_image,
                    "lxdtest.recipe": alias[len(SANDBOX_PREFIX) :],
                },
            }
            self.refresh_lock()
            meta = self.lxd.write("POST", "/1.0/images", body=body, timeout_minutes=60)
            new = (meta.get("metadata") or {}).get("fingerprint", "")
            if not new:
                fail("the publish returned no fingerprint")
            self.lxd.set_alias(alias, new, "LXD test sandbox")
            log(f"sandbox image {alias} is {new[:12]}")
            if old and old != new:
                self.lxd.write("DELETE", f"/1.0/images/{old}")
                log(f"deleted the old sandbox image {old[:12]}")
        finally:
            self.lxd.delete_instance(name)
        self.prune_images(keep_fingerprint=new)

    def prune_images(self, keep_fingerprint: str) -> None:
        """Delete old sandbox images. Keep the newest few, so branches with another recipe can still run."""
        status, _headers, raw = self.lxd.api.call("GET", "/1.0/images", query={"recursion": "1"})
        if status >= 400:
            fail(f"listing the images failed with HTTP {status}")
        images: list[dict] = json.loads(raw or b"{}").get("metadata") or []
        sandboxes = [img for img in images if any(a.get("name", "").startswith(SANDBOX_PREFIX) for a in img.get("aliases") or [])]
        sandboxes.sort(key=lambda img: img.get("uploaded_at") or img.get("created_at") or "", reverse=True)
        keep = {keep_fingerprint} | {img.get("fingerprint") for img in sandboxes[: self.args.keep_images]}
        for img in sandboxes:
            if img.get("fingerprint") not in keep:
                self.lxd.write("DELETE", f"/1.0/images/{img['fingerprint']}")
                names = ", ".join(a.get("name", "") for a in img.get("aliases") or [])
                log(f"deleted the old sandbox image {names}")

    def ensure_test_images(self) -> None:
        """Step 9. Put the split test images into the runner: a container image and a VM image."""
        for name, image_type, rootfs_part in (("alpine-ct", "container", "rootfs"), ("alpine-vm", "virtual-machine", "rootfs.img")):
            self.ensure_test_image(name, image_type, rootfs_part)

    def ensure_test_image(self, name: str, image_type: str, rootfs_part: str) -> None:
        """Copy one test image from its registry, export it, and push its two files into the runner."""
        meta_path = f"/srv/lxdtest/images/{name}.meta"
        root_path = f"/srv/lxdtest/images/{name}.root"
        code, _out, _err = self.lxd.exec(self.runner, ["test", "-s", meta_path, "-a", "-s", root_path], timeout_minutes=1)
        if code == 0:
            log(f"test image {name} is in the runner")
            return
        registry, alias = image_ref(self.args.test_image)
        log(f"copying the {image_type} image {self.args.test_image} into the runner as {name}")
        body = {"source": {"type": "image", "mode": "pull", "image_registry": registry, "alias": alias, "image_type": image_type}}
        meta = self.lxd.write("POST", "/1.0/images", body=body, timeout_minutes=30)
        fingerprint = (meta.get("metadata") or {}).get("fingerprint", "")
        if not fingerprint:
            fail("the image copy returned no fingerprint")
        try:
            status, headers, raw = self.lxd.api.call("GET", f"/1.0/images/{fingerprint}/export", timeout=1800)
            if status >= 400:
                fail(f"image export failed with HTTP {status}")
            ctype = headers.get("content-type", "")
            if not ctype.startswith("multipart/"):
                fail(f"the {image_type} image {self.args.test_image} is not a split image. The runner needs a metadata file and a rootfs file.")
            parts = split_multipart(ctype, raw)
            if "metadata" not in parts or rootfs_part not in parts:
                fail(f"the export of {self.args.test_image} has the parts {sorted(parts)}, not metadata and {rootfs_part}")
            self.lxd.push(self.runner, meta_path, parts["metadata"])
            self.lxd.push(self.runner, root_path, parts[rootfs_part])
        finally:
            self.lxd.write("DELETE", f"/1.0/images/{fingerprint}")
        log(f"test image {name} is in the runner")

    def write_config(self) -> None:
        """Step 10."""
        config = {"remote": self.args.remote_name, "project": self.args.project, "image": self.alias}
        self.lxd.push(self.runner, "/etc/lxdtest/config.json", (json.dumps(config, indent=2) + "\n").encode())
        log("wrote /etc/lxdtest/config.json in the runner")

    def apply(self) -> None:
        """Run steps 2 to 11."""
        self.take_lock()
        beat = self.start_lock_beat()
        handed_over = False
        try:
            self.ensure_runner()
            self.check_reach()
            self.install()
            self.ensure_remote()
            client_fp = self.ensure_test_cert()
            self.refresh_lock()
            self.ensure_sandbox_image(client_fp)
            self.refresh_lock()
            self.ensure_test_images()
            self.refresh_lock()
            self.write_config()
            if self.args.lock_owner:
                handed_over = True
                log(f"the lock {LOCK_NAME} stays for the test run {self.args.lock_owner}")
        finally:
            beat.set()
            if not handed_over:
                self.release_lock()


def main() -> int:
    """Parse the options, show the plan, and run it."""
    parser = argparse.ArgumentParser(prog="bootstrap", description="Set up a test project on an LXD server for the tier 2 suite.")
    parser.add_argument("--url", default=os.environ.get("LXD_CI_URL", ""))
    parser.add_argument("--project", default=os.environ.get("LXD_CI_PROJECT", ""))
    parser.add_argument("--client-cert", default=os.environ.get("LXD_CI_CLIENT_CERT", ""))
    parser.add_argument("--client-key", default=os.environ.get("LXD_CI_CLIENT_KEY", ""))
    parser.add_argument("--server-cert", default=os.environ.get("LXD_CI_SERVER_CERT", ""))
    parser.add_argument("--token-file", default="", help="Optional. File with a trust token that gives the runner its own identity.")
    parser.add_argument("--runner", default="lxdtest-runner", help="Name of the runner container.")
    parser.add_argument("--runner-url", default="", help="Host API URL that the runner uses. Default: --url.")
    parser.add_argument("--remote-name", default="testhost", help="Name of the lxc remote for the host in the runner.")
    parser.add_argument("--runner-cpu", default="4", help="limits.cpu of the runner. Each test slot runs its Ansible processes in the runner.")
    parser.add_argument("--runner-memory", default="4GiB", help="limits.memory of the runner.")
    base_image, lxd_channel = build_settings()
    parser.add_argument("--base-image", default=base_image, help="Registry and alias of the runner and sandbox base image. Env: LXD_CI_BASE_IMAGE.")
    parser.add_argument("--test-image", default="images:alpine/3.22", help="Registry and alias of the test container image.")
    parser.add_argument("--lxd-channel", default=lxd_channel, help="Snap channel of LXD in the sandboxes and of lxc in the runner. Env: LXD_CI_LXD_CHANNEL.")
    parser.add_argument("--keep-images", type=int, default=3, help="Number of sandbox images to keep for other recipes.")
    parser.add_argument("--lock-owner", default=lock_owner(), help="Hand the run lock to the test run with this owner. Env: LXD_CI_LOCK_OWNER.")
    parser.add_argument("--lock-wait", type=int, default=120, help="Minutes to wait for the run lock.")
    parser.add_argument("--ansible-core", default="2.20.11")
    parser.add_argument("--rebuild-image", action="store_true", help="Build the sandbox image even when it is current.")
    parser.add_argument("--check", action="store_true", help="Read only. Show the state and the plan, then stop.")
    parser.add_argument("--yes", action="store_true", help="Do not ask for confirmation.")
    args = parser.parse_args()
    if not args.url or not args.project:
        parser.error("set --url and --project, or LXD_CI_URL and LXD_CI_PROJECT")
    args.runner_url = args.runner_url or args.url
    image_ref(args.base_image)
    image_ref(args.test_image)

    with tempfile.TemporaryDirectory() as tmpdir:
        tmp = Path(tmpdir)
        args.cert_path = pem_path(args.client_cert, "client-cert", tmp)
        args.key_path = pem_path(args.client_key, "client-key", tmp)
        server_cert_path = pem_path(args.server_cert, "server-cert", tmp)
        api = Api(args.url, args.project, args.cert_path, args.key_path, server_cert_path)
        boot = Bootstrap(args, Lxd(api), new_lxd=lambda: Lxd(Api(args.url, args.project, args.cert_path, args.key_path, server_cert_path)))
        log(f"server {args.url}, project {args.project}")
        boot.check()
        print("\nPlan:")
        for number, step in enumerate(boot.plan, start=2):
            print(f"  {number:2}. {step}")
        print()
        if args.check:
            log("check only: nothing changed")
            return 0
        if not args.yes:
            answer = input(f"Type the project name ({args.project}) to go on: ").strip()
            if answer != args.project:
                log("stopped: nothing changed")
                return 1
        boot.apply()
    log(f"=== SETUP DONE. Sandbox image {boot.alias}.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
