# Copyright (c) 2026, Sean McAvoy
# GNU General Public License v3.0+ (see LICENSES/GPL-3.0-or-later.txt or https://www.gnu.org/licenses/gpl-3.0.txt)
# SPDX-License-Identifier: GPL-3.0-or-later

"""An in-memory LXD server for the module unit tests.

It answers the requests of LXDClient through LXDClient._exchange, so the client code (retries, ETags,
operations) runs as in a real run. It knows the generic REST shape of LXD: collections, objects with
ETags, POST to create, PUT to replace, PATCH to merge, DELETE, and projects through ?project=.
"""

from __future__ import annotations

import base64
import copy
import hashlib
import json
import posixpath
import ssl
import typing as t
from urllib.parse import parse_qs, unquote, urlsplit

from ansible_collections.smcavoy.lxd.plugins.module_utils._client import LXDResponse

PROJECT_SCOPED = ("instances", "profiles", "networks", "network-acls", "network-zones", "images", "storage-pools", "replicators")
# Collections whose objects hold collections (volumes of a pool, forwards of a network, snapshots of an instance).
PARENT_COLLECTIONS = ("storage-pools", "networks", "instances")
# Keys that a PUT does not replace.
READ_ONLY = ("name", "used_by", "managed", "status", "locations", "created_at", "type", "project", "driver", "authentication_method", "fingerprint")
# Keys that LXD sets on create, by collection. A PUT of an object of that collection does not replace them.
CREATE_ONLY = {
    "peers": ("target_network", "target_project"),
    "image-registries": ("protocol", "builtin"),
    "replicators": ("last_run_status",),
}
ZERO_TIME = "0001-01-01T00:00:00Z"
END_CERT = "-----END CERTIFICATE-----"


def pem_fingerprint(pem: str) -> str:
    """Return the SHA-256 fingerprint of the first certificate of a PEM text."""
    first = pem.strip().split(END_CERT, 1)[0] + END_CERT
    return hashlib.sha256(ssl.PEM_cert_to_DER_cert(first + "\n")).hexdigest()


class FakeLXD:
    """The state of one fake LXD server."""

    def __init__(self) -> None:
        self.objects: dict[str, dict[str, t.Any]] = {}
        self.requests: list[tuple[str, str, t.Any]] = []
        self.async_writes = False
        # Bearer tokens: how many the server issued, and the expiry time of the next one ("" for none).
        self.tokens_issued = 0
        self.next_token_expires_at = ""
        # Instances whose devices LXD changes only while they are stopped.
        self.cold_only: set[str] = set()
        # Instances that do not stop without force, as a hung guest.
        self.stuck: set[str] = set()
        # Files in instances: (project, instance, path) -> {"type", "uid", "gid", "mode", "content"}.
        self.files: dict[tuple[str, str, str], dict[str, t.Any]] = {}
        # Free bytes on the disk of the instances, or None for no limit. A file write that does not fit fails as on a full
        # btrfs pool in LXD 6.10.1: LXD has already created or emptied the file, then answers 500 from sftp.
        self.disk_free: int | None = None
        # A full btrfs pool in LXD 6.10.1 also answers a small write with success, and stores nothing.
        self.disk_silent = False
        self.operations: dict[str, t.Any] = {}
        # The bodies of POST /1.0/cluster/members/<name>/state, in order.
        self.member_actions: list[dict[str, t.Any]] = []
        # The image uploads: (Content-Type, body).
        self.image_uploads: list[tuple[str, bytes]] = []
        # A cluster: the member-specific keys of each entity, for example {"network-bridge": {"bgp.ipv4.nexthop"}},
        # and the values of those keys: object key -> member -> config.
        self.local_keys: dict[str, set[str]] = {}
        self.member_config: dict[str, dict[str, dict[str, str]]] = {}
        # The operations that the server lists: ID -> (project, the operation as LXD returns it, with its children in full).
        # A trust token or a join token is a running operation of the class "token".
        self.live_operations: dict[str, tuple[str, dict[str, t.Any]]] = {}
        # The template files of instances: (project, instance) -> name -> content.
        self.templates: dict[tuple[str, str], dict[str, bytes]] = {}
        # The log files of instances: (project, instance) -> name -> content.
        self.logs: dict[tuple[str, str], dict[str, bytes]] = {}
        # The answer of GET /1.0/network-allocations: each one with "project", which LXD does not return.
        self.allocations: list[dict[str, t.Any]] = []
        # Replicators: the runs that the server started as (project, name, action), and the errors of the child
        # operations of the next runs of a name. A run with errors fails.
        self.replicator_runs: list[tuple[str, str, str]] = []
        self.replicator_errors: dict[str, list[str]] = {}
        # The certificate that the other cluster shows when a public cluster link is made.
        self.link_remote_certificate = ""
        # Auth: the identity of the caller and the permissions that the server lists.
        self.current_identity: dict[str, t.Any] = {"authentication_method": "tls", "type": "Client certificate", "name": "unit", "groups": []}
        self.permissions: list[dict[str, t.Any]] = []
        self.server_info: dict[str, t.Any] = {
            "auth": "trusted",
            "api_extensions": [],
            "environment": {"server_version": "6.10.1", "server_clustered": False, "server": "lxd"},
            "config": {},
        }
        self.add("/1.0/projects/default", {"name": "default", "description": "Default LXD project", "config": {}, "used_by": []})
        self.add("/1.0/profiles/default", {"name": "default", "description": "Default LXD profile", "config": {}, "devices": {}, "used_by": []})

    # ------------------------------------------------------------------
    # Store

    @staticmethod
    def key(path: str, project: str | None) -> str:
        parts = path.split("/")
        scoped = len(parts) > 2 and parts[2] in PROJECT_SCOPED
        return f"{project or 'default'}:{path}" if scoped else f"default:{path}"

    def add(self, path: str, obj: dict[str, t.Any], project: str | None = None) -> None:
        self.objects[self.key(path, project)] = copy.deepcopy(obj)

    def get(self, path: str, project: str | None = None) -> dict[str, t.Any] | None:
        return self.objects.get(self.key(path, project))

    def writes(self) -> list[tuple[str, str, t.Any]]:
        """Return the requests that change something."""
        return [r for r in self.requests if r[0] not in ("GET", "HEAD")]

    @staticmethod
    def etag(obj: t.Any) -> str:
        return hashlib.sha256(json.dumps(obj, sort_keys=True).encode()).hexdigest()

    # ------------------------------------------------------------------
    # Answers

    @staticmethod
    def sync(meta: t.Any, status: int = 200, headers: dict[str, str] | None = None) -> LXDResponse:
        body = {"type": "sync", "status": "Success", "status_code": 200, "metadata": meta}
        return LXDResponse(status, dict(headers or {}), json.dumps(body).encode())

    @staticmethod
    def error(status: int, text: str) -> LXDResponse:
        return LXDResponse(status, {}, json.dumps({"type": "error", "error": text, "error_code": status}).encode())

    def done(self, meta: t.Any = None) -> LXDResponse:
        """Answer a write: sync, or async with an operation when O(async_writes) is set."""
        if not self.async_writes:
            return self.sync(meta or {})
        op = f"op{len(self.operations) + 1}"
        self.operations[op] = meta
        body = {"type": "async", "status": "Operation created", "status_code": 100, "operation": f"/1.0/operations/{op}", "metadata": {}}
        return LXDResponse(202, {}, json.dumps(body).encode())

    def handle(self, method: str, target: str, data: t.Any, headers: dict[str, str]) -> LXDResponse:
        url = urlsplit(target)
        path = unquote(url.path).rstrip("/") or "/"
        query = {k: v[0] for k, v in parse_qs(url.query).items()}
        project = query.get("project")
        is_json = (headers or {}).get("Content-Type", "").startswith("application/json")
        body = json.loads(data) if is_json and isinstance(data, (bytes, bytearray)) and data else None
        self.requests.append((method, target, body))
        if path == "/":
            return self.sync(["/1.0"])
        if path == "/1.0":
            if method in ("PUT", "PATCH") and body is not None:
                # A key with an empty value goes away.
                config = dict(self.server_info.get("config") or {}, **(body.get("config") or {}))
                self.server_info["config"] = {key: value for key, value in config.items() if value != ""}
                return self.done()
            return self.sync(self.server_info)
        if path == "/1.0/metadata/configuration":
            configs = {name: {"main": {"keys": [{key: {"scope": "local"}} for key in sorted(keys)]}} for name, keys in self.local_keys.items()}
            return self.sync({"configs": configs})
        if path == "/1.0/operations" and method == "GET":
            return self.list_operations(query)
        if path.startswith("/1.0/operations/"):
            op = path.split("/")[3]
            if op in self.live_operations:
                return self.live_operation(method, op, query)
            if op not in self.operations:
                return self.error(404, "Operation not found")
            return self.sync({"id": op, "status": "Success", "status_code": 200, "metadata": self.operations[op]})
        if project and project != "default" and not path.startswith("/1.0/projects") and self.get(f"/1.0/projects/{project}") is None:
            return self.error(404, "Project not found")
        parts = path.split("/")
        if len(parts) == 5 and parts[2] == "instances" and parts[4] == "state":
            return self.instance_state(method, "/".join(parts[:4]), project, body)
        if len(parts) == 5 and parts[2] == "instances" and parts[4] == "rebuild" and method == "POST":
            inst = self.get("/".join(parts[:4]), project)
            if inst is None:
                return self.error(404, "Instance not found")
            if inst.get("status") != "Stopped":
                return self.error(400, "Instance must be stopped to be rebuilt")
            inst["rebuilt_from"] = (body or {}).get("source")
            return self.done()
        if len(parts) == 4 and parts[2] == "instances" and method == "PUT" and parts[3] in self.cold_only:
            inst = self.get(path, project)
            if inst is not None and inst.get("status") != "Stopped" and (body or {}).get("devices") != inst.get("devices"):
                return self.error(400, "Device cannot be changed when instance is running")
        if len(parts) == 7 and parts[2:5] == ["auth", "identities", "bearer"] and parts[6] == "token":
            return self.identity_token(method, "/".join(parts[:6]), body)
        if len(parts) == 8 and parts[2] == "storage-pools" and parts[4] == "volumes" and parts[7] == "state" and method == "GET":
            if self.get("/".join(parts[:7]), project) is None:
                return self.error(404, "Storage volume not found")
            if parts[5] not in ("custom", "container", "virtual-machine"):
                return self.error(400, f'Invalid storage volume type "{parts[5]}"')
            return self.sync({"usage": {"used": 4096, "total": 0}})
        if path == "/1.0/images" and method == "POST":
            return self.create_image(project, body, data, headers or {})
        if len(parts) == 4 and parts[2] == "images" and parts[3] != "aliases" and method in ("GET", "HEAD"):
            return self.image(path, project)
        if len(parts) == 5 and parts[2] == "instances" and parts[4] == "files":
            return self.instance_file(method, parts[3], project, query.get("path", ""), data, headers or {})
        if path == "/1.0/certificates" and method == "POST":
            return self.create_certificate(body or {})
        if len(parts) == 4 and parts[2] == "certificates":
            return self.certificate(method, parts[3], body, headers or {})
        if path == "/1.0/cluster/members" and method == "POST":
            return self.join_token(body or {})
        if path == "/1.0/cluster/certificate" and method == "PUT":
            certificate = (body or {})["cluster_certificate"]
            self.server_info["environment"].update(certificate=certificate, certificate_fingerprint=pem_fingerprint(certificate))
            return self.done()
        if len(parts) == 6 and parts[2:4] == ["cluster", "members"] and parts[5] == "state" and method == "GET":
            if self.get("/".join(parts[:5])) is None:
                return self.error(404, "Cluster member not found")
            return self.sync({"sysinfo": {"uptime": 60, "logical_cpus": 4}, "storage_pools": {}})
        if path == "/1.0/cluster/links" and method == "POST":
            return self.create_cluster_link(body or {})
        if len(parts) == 6 and parts[2:4] == ["cluster", "links"] and parts[5] == "state" and method == "GET":
            return self.cluster_link_state("/".join(parts[:5]))
        if path == "/1.0/warnings" and method == "GET" and project:
            # LXD lists the warnings of one project. A warning of the server has an empty project.
            items = [(p, o) for p, o in self.children(path, None) if o.get("project") == project]
            return self.sync([o if query.get("recursion") else p for p, o in items])
        if len(parts) == 4 and parts[2] == "warnings" and method == "PUT":
            return self.put_warning(path, body or {})
        if len(parts) >= 5 and parts[2] == "instances" and parts[4] == "metadata":
            return self.instance_metadata(method, parts, project, query, body, data)
        if len(parts) in (5, 6) and parts[2] == "instances" and parts[4] == "logs" and method == "GET":
            return self.instance_logs(parts, project)
        if len(parts) == 5 and parts[2] == "replicators" and parts[4] == "state":
            return self.replicator_state(method, "/".join(parts[:4]), project, body)
        if path == "/1.0/auth/identities" and method == "GET":
            items = [item for kind in ("bearer", "oidc", "tls") for item in self.children(f"{path}/{kind}", None)]
            return self.sync([o if query.get("recursion") else p for p, o in items])
        if path == "/1.0/auth/identities/current" and method == "GET":
            return self.sync(self.current_identity)
        if path == "/1.0/auth/permissions" and method == "GET":
            return self.list_permissions(query)
        if path == "/1.0/network-allocations" and method == "GET":
            wanted = None if query.get("all-projects") == "true" else project or "default"
            return self.sync([{k: v for k, v in item.items() if k != "project"} for item in self.allocations if wanted in (None, item.get("project"))])
        handler = getattr(self, "on_" + method.lower())
        return handler(path, query, project, body, headers or {})

    # ------------------------------------------------------------------
    # Operations that stay on the server

    def add_operation(self, operation: dict[str, t.Any], project: str = "default") -> None:
        """Add an operation that the server lists and answers. It needs C(id), C(class), and C(status)."""
        self.live_operations[operation["id"]] = (project, copy.deepcopy(operation))

    @staticmethod
    def shown_operation(operation: dict[str, t.Any], with_children: bool) -> dict[str, t.Any]:
        """Return an operation as LXD answers it: the children in full only at the higher recursion."""
        shown = copy.deepcopy(operation)
        if "children" in shown and not with_children:
            shown["children"] = [f"/1.0/operations/{child['id']}" for child in shown["children"]]
        return shown

    def list_operations(self, query: dict[str, str]) -> LXDResponse:
        """Answer GET /1.0/operations: the operations of one project, or of all, by status."""
        if query.get("all-projects") == "true" and query.get("project"):
            return self.error(400, "Cannot specify a project when requesting all projects")
        wanted = None if query.get("all-projects") == "true" else query.get("project") or "default"
        recursion = int(query.get("recursion") or 0)
        groups: dict[str, list[t.Any]] = {}
        for op_id, (project, operation) in sorted(self.live_operations.items()):
            if wanted not in (None, project):
                continue
            item = self.shown_operation(operation, recursion >= 2) if recursion else f"/1.0/operations/{op_id}"
            groups.setdefault(str(operation["status"]).lower(), []).append(item)
        return self.sync(groups)

    def live_operation(self, method: str, op_id: str, query: dict[str, str]) -> LXDResponse:
        """Answer a read, a wait, or a cancel of a listed operation."""
        if method == "DELETE":
            del self.live_operations[op_id]
            return self.sync({})
        return self.sync(self.shown_operation(self.live_operations[op_id][1], int(query.get("recursion") or 0) >= 1))

    def token_operation(self, meta: dict[str, t.Any]) -> LXDResponse:
        """Start a token operation. It runs until a client uses the token, so the answer holds the operation itself."""
        op_id = f"token-op-{self.tokens_issued}"
        operation = {"id": op_id, "class": "token", "description": "Executing operation", "status": "Running", "status_code": 103, "metadata": meta, "err": ""}
        self.add_operation(operation)
        body = {"type": "async", "status": "Operation created", "status_code": 100, "operation": f"/1.0/operations/{op_id}", "metadata": operation}
        return LXDResponse(202, {}, json.dumps(body).encode())

    def token_fields(self) -> dict[str, t.Any]:
        """Return the secret part of a new token, and count it in O(tokens_issued)."""
        self.tokens_issued += 1
        fingerprint = self.server_info["environment"].get("certificate_fingerprint") or "c" * 64
        return {"secret": f"s3cret-{self.tokens_issued}", "fingerprint": fingerprint, "addresses": ["192.0.2.1:8443"]}

    # ------------------------------------------------------------------
    # The trust store

    def create_certificate(self, body: dict[str, t.Any]) -> LXDResponse:
        """Add a certificate to the trust store, or issue a trust token for a client name."""
        if body.get("token"):
            request = {key: body[key] for key in ("name", "type", "restricted", "projects", "token") if key in body}
            return self.token_operation(dict(self.token_fields(), request=request, expiresAt=self.next_token_expires_at or ZERO_TIME))
        if not body.get("certificate"):
            return self.error(400, "No certificate provided")
        der = base64.b64decode(body["certificate"])
        fingerprint = hashlib.sha256(der).hexdigest()
        path = f"/1.0/certificates/{fingerprint}"
        if self.get(path) is not None:
            return self.error(409, "Certificate already in trust store")
        entry = {
            "name": body.get("name") or "",
            "type": body.get("type") or "client",
            "restricted": bool(body.get("restricted")),
            "projects": list(body.get("projects") or []),
            # LXD returns the certificate as PEM.
            "certificate": "-----BEGIN CERTIFICATE-----\n" + base64.b64encode(der).decode() + "\n" + END_CERT + "\n",
            "fingerprint": fingerprint,
        }
        self.add(path, entry)
        return self.done()

    def certificate(self, method: str, fingerprint: str, body: t.Any, headers: dict[str, str]) -> LXDResponse:
        """Answer a request for one entry of the trust store. As in LXD, the start of a fingerprint finds the entry too."""
        found = [(p, o) for p, o in self.children("/1.0/certificates", None) if o["fingerprint"].startswith(fingerprint)]
        if len(found) != 1:
            return self.error(404, "Certificate not found")
        path, entry = found[0]
        if method in ("GET", "HEAD"):
            return self.sync(entry, headers={"ETag": self.etag(entry)})
        if method == "DELETE":
            del self.objects[self.key(path, None)]
            return self.done()
        if headers.get("If-Match") and headers["If-Match"] != self.etag(entry):
            return self.error(412, "Precondition Failed")
        defaults = {"name": "", "type": "client", "restricted": False, "projects": []}
        for key, default in defaults.items():
            if key in body or method == "PUT":
                entry[key] = copy.deepcopy(body.get(key, default))
        return self.done()

    # ------------------------------------------------------------------
    # Cluster: join tokens and links

    def join_token(self, body: dict[str, t.Any]) -> LXDResponse:
        if not self.server_info["environment"].get("server_clustered"):
            return self.error(400, "This server is not clustered")
        meta = dict(self.token_fields(), serverName=body["server_name"], expiresAt=self.next_token_expires_at or ZERO_TIME)
        return self.token_operation(meta)

    def create_cluster_link(self, body: dict[str, t.Any]) -> LXDResponse:
        """Create a cluster link, as the module sees LXD 6.10 do it.

        Without a token the link is pending: LXD makes a pending identity and returns the token, and only a
        bidirectional link also gets a link object. With a token the link is active. A public link is pending with
        the certificate of the other cluster until a second POST with its fingerprint confirms it.
        """
        name = body["name"]
        path = f"/1.0/cluster/links/{name}"
        identity = f"/1.0/auth/identities/tls/{name}"
        link = self.get(path)
        if body.get("type") == "public" and body.get("fingerprint"):
            pending = ((link or {}).get("config") or {}).get("volatile.pending_certificate")
            if link is None or not pending:
                return self.error(404, "No pending cluster link")
            if pem_fingerprint(pending) != body["fingerprint"]:
                return self.error(400, "Certificate fingerprint does not match")
            del link["config"]["volatile.pending_certificate"]
            link["config"]["volatile.addresses"] = link.pop("remote_address")
            return self.done()
        if link is not None or self.get(identity) is not None:
            return self.error(409, f'Cluster link "{name}" already exists')
        link = {
            "name": name,
            "type": body.get("type") or "bidirectional",
            "description": body.get("description") or "",
            "config": dict(body.get("config") or {}),
            "used_by": [],
        }
        if link["type"] == "public":
            link["config"]["volatile.pending_certificate"] = self.link_remote_certificate
            link["remote_address"] = body["remote_address"]
            self.add(path, link)
            return self.done({"fingerprint": pem_fingerprint(self.link_remote_certificate)})
        groups = list(body.get("auth_groups") or [])
        if body.get("trust_token"):
            link["config"]["volatile.addresses"] = "192.0.2.2:8443"
            self.add(path, link)
            self.add(identity, {"name": name, "authentication_method": "tls", "type": "Cluster link certificate", "groups": groups})
            return self.done()
        self.add(identity, {"name": name, "authentication_method": "tls", "type": "Cluster link certificate (pending)", "groups": groups})
        if link["type"] != "unidirectional":
            self.add(path, link)
        return self.done(dict(self.token_fields(), client_name=name, expires_at=self.next_token_expires_at or ZERO_TIME))

    def cluster_link_state(self, path: str) -> LXDResponse:
        link = self.get(path)
        if link is None:
            return self.error(404, "Cluster link not found")
        addresses = (link.get("config") or {}).get("volatile.addresses")
        if not addresses:
            # A pending link has no member addresses yet.
            return self.error(400, "Cluster link has no addresses")
        return self.sync({"cluster_link_members": [{"address": address, "status": "Active"} for address in addresses.split(",")]})

    # ------------------------------------------------------------------
    # Warnings

    def put_warning(self, path: str, body: dict[str, t.Any]) -> LXDResponse:
        """Set the status of a warning. LXD takes only "new" and "acknowledged", and changes nothing else."""
        warning = self.get(path)
        if warning is None:
            return self.error(404, "Warning not found")
        if body.get("status") not in ("new", "acknowledged"):
            return self.error(400, 'Status may only be set to "acknowledge" or "new"')
        warning["status"] = body["status"]
        return self.sync({})

    # ------------------------------------------------------------------
    # Instance metadata, templates, and logs

    def instance_metadata(self, method: str, parts: list[str], project: str | None, query: dict[str, str], body: t.Any, data: t.Any) -> LXDResponse:
        """Answer /1.0/instances/<name>/metadata and its template files. Every instance has a metadata object."""
        name = parts[3]
        if self.get(f"/1.0/instances/{name}", project) is None:
            return self.error(404, "Instance not found")
        path = f"/1.0/instances/{name}/metadata"
        if self.get(path, project) is None:
            self.add(path, {"architecture": "x86_64", "creation_date": 1700000000, "expiry_date": 0, "properties": {}, "templates": {}}, project)
        files = self.templates.setdefault((project or "default", name), {})
        if len(parts) == 5:
            return getattr(self, "on_" + method.lower())(path, query, project, body, {})
        if parts[5:] != ["templates"]:
            return self.error(404, "Not found")
        template = query.get("path")
        if method == "GET" and not template:
            return self.sync(sorted(files))
        if not template:
            return self.error(400, "No template path provided")
        if method == "POST":
            files[template] = data.read() if hasattr(data, "read") else bytes(data or b"")
            return self.sync({})
        if template not in files:
            return self.error(404, "Template not found")
        if method == "DELETE":
            del files[template]
            return self.sync({})
        return LXDResponse(200, {"Content-Type": "application/octet-stream"}, files[template])

    def instance_logs(self, parts: list[str], project: str | None) -> LXDResponse:
        """Answer the list of the log files of an instance, or the bytes of one file."""
        name = parts[3]
        if self.get(f"/1.0/instances/{name}", project) is None:
            return self.error(404, "Instance not found")
        files = self.logs.get((project or "default", name), {})
        if len(parts) == 5:
            return self.sync([f"/1.0/instances/{name}/logs/{log}" for log in sorted(files)])
        if parts[5] not in files:
            return self.error(404, "Not found")
        return LXDResponse(200, {"Content-Type": "application/octet-stream"}, files[parts[5]])

    # ------------------------------------------------------------------
    # Replicators and auth lists

    def replicator_state(self, method: str, path: str, project: str | None, body: t.Any) -> LXDResponse:
        """Answer the state of a replicator, or start a run: an operation that ends at once, with or without errors."""
        replicator = self.get(path, project)
        if replicator is None:
            return self.error(404, "Replicator not found")
        if method == "GET":
            return self.sync({"status": replicator.get("last_run_status") or "Pending"})
        if (body or {}).get("action") not in ("start", "restore"):
            return self.error(400, "Invalid action")
        if replicator.get("last_run_status") == "Running":
            return self.error(400, "Replicator is already running")
        name = replicator["name"]
        self.replicator_runs.append((project or "default", name, body["action"]))
        op_id = f"run{len(self.replicator_runs)}"
        errors = self.replicator_errors.get(name) or []
        operation: dict[str, t.Any] = {"id": op_id, "class": "task", "status": "Success", "status_code": 200, "metadata": {}, "err": "", "children": []}
        if errors:
            operation.update(status="Failure", status_code=400, err="One or more child operations failed")
            operation["children"] = [
                {"id": f"{op_id}-{n}", "class": "task", "status": "Failure", "status_code": 400, "metadata": {}, "err": err} for n, err in enumerate(errors)
            ]
        replicator["last_run_status"] = "Failed" if errors else "Completed"
        self.add_operation(operation, project or "default")
        answer = {"type": "async", "status": "Operation created", "status_code": 100, "operation": f"/1.0/operations/{op_id}", "metadata": {}}
        return LXDResponse(202, {}, json.dumps(answer).encode())

    def list_permissions(self, query: dict[str, str]) -> LXDResponse:
        """Answer GET /1.0/auth/permissions with its entity-type and project filters."""
        items = []
        for item in self.permissions:
            if query.get("entity-type") and item.get("entity_type") != query["entity-type"]:
                continue
            if query.get("project") and f"project={query['project']}" not in str(item.get("url")):
                continue
            items.append(item)
        return self.sync(items)

    # ------------------------------------------------------------------
    # Cluster: the view of one member of a network or a storage pool

    def entity_local_keys(self, path: str, obj: dict[str, t.Any]) -> set[str]:
        """Return the member-specific keys of a network or a storage pool."""
        kind = path.split("/")[2]
        entity = f"network-{obj.get('type')}" if kind == "networks" else f"storage-{obj.get('driver')}"
        return self.local_keys.get(entity, set())

    def member_view(self, path: str, project: str | None, member: str) -> dict[str, t.Any]:
        """Return the object as one member sees it: the global keys and the keys of the member."""
        view = copy.deepcopy(self.objects[self.key(path, project)])
        view["config"] = dict(view.get("config") or {}, **self.member_config.get(self.key(path, project), {}).get(member, {}))
        return view

    def put_member(self, path: str, project: str | None, member: str, body: dict[str, t.Any], headers: dict[str, str]) -> LXDResponse:
        """Replace the config through one member, as LXD 6.10.1 does: the global keys that the body leaves out go away."""
        key = self.key(path, project)
        obj = self.objects[key]
        if headers.get("If-Match") and headers["If-Match"] != self.etag(self.member_view(path, project, member)):
            return self.error(412, "Precondition Failed")
        local = self.entity_local_keys(path, obj)
        config = dict(body.get("config") or {})
        obj["config"] = {name: value for name, value in config.items() if name not in local}
        obj["description"] = body.get("description") or ""
        self.member_config.setdefault(key, {})[member] = {name: value for name, value in config.items() if name in local}
        return self.done()

    # ------------------------------------------------------------------
    # Instances

    ACTIONS = {"start": "Running", "stop": "Stopped", "restart": "Running", "freeze": "Frozen", "unfreeze": "Running"}

    def instance_state(self, method: str, path: str, project: str | None, body: t.Any) -> LXDResponse:
        inst = self.get(path, project)
        if inst is None:
            return self.error(404, "Instance not found")
        if method == "GET":
            return self.sync({"status": inst["status"], "network": {}, "processes": 1 if inst["status"] == "Running" else -1})
        action = body["action"]
        if action == "stop" and inst["name"] in self.stuck and not body.get("force"):
            return self.error(500, "Failed shutting down instance: context deadline exceeded")
        if action == "freeze" and inst["status"] != "Running":
            return self.error(400, "The instance isn't running")
        if action == "restart" and inst["status"] == "Frozen" and not body.get("force"):
            # LXD 6.10.1, seen live: the restart of a frozen instance fails unless it is forced.
            return self.error(400, "Instance is not running")
        inst["status"] = self.ACTIONS[action]
        inst.setdefault("restarts", 0)
        if action == "restart":
            inst["restarts"] += 1
        return self.done()

    def instance_file(self, method: str, name: str, project: str | None, path: str, data: t.Any, headers: dict[str, str]) -> LXDResponse:
        if self.get(f"/1.0/instances/{name}", project) is None:
            return self.error(404, "Instance not found")
        key = (project or "default", name, path)
        current = self.files.get(key)
        if method in ("GET", "HEAD"):
            if current is None:
                return self.error(404, "Not found")
            meta = {
                "X-LXD-type": current["type"],
                "X-LXD-uid": str(current["uid"]),
                "X-LXD-gid": str(current["gid"]),
                "X-LXD-mode": current["mode"],
            }
            content = current["content"]
            if current["type"] == "symlink":
                # LXD returns the target of a link as an absolute path.
                content = posixpath.normpath(posixpath.join(posixpath.dirname(path), content.decode())).encode()
            return LXDResponse(200, meta, b"" if method == "HEAD" else content)
        if method == "DELETE":
            if current is None:
                return self.error(404, "Not found")
            del self.files[key]
            return self.sync({})
        # POST. LXD 6.10 cannot open an existing file for writing that root does not own,
        # unless the mode gives write to others.
        if current is not None and current["type"] == "file" and current["uid"] != 0 and not int(current["mode"], 8) & 0o002:
            return self.error(403, f'Failed opening "{path}" in instance "{name}": permission denied')
        if current is not None and current["type"] == "directory":
            # LXD 6.10.1 answers success for a directory that exists, and changes nothing.
            return self.sync({})
        if current is not None and current["type"] == "symlink":
            return self.error(500, f'Failed creating symlink "{path}" in instance "{name}": sftp: "file exists" (SSH_FX_FAILURE)')
        content = data.read() if hasattr(data, "read") else bytes(data or b"")
        if headers.get("X-LXD-type") == "symlink":
            # LXD does not set the owner or the mode of a link.
            self.files[key] = {"type": "symlink", "uid": 0, "gid": 0, "mode": "0777", "content": content}
            return self.sync({})
        if self.disk_silent:
            content = b""
        if self.disk_free is not None:
            freed = len(current["content"]) if current is not None and current["type"] == "file" else 0
            if len(content) > self.disk_free + freed:
                if current is not None:
                    current["content"] = b""
                else:
                    self.files[key] = {"type": "file", "uid": 0, "gid": 0, "mode": "0644", "content": b""}
                self.disk_free += freed
                return self.error(500, f'sftp: "write {path}: no space left on device" (SSH_FX_FAILURE)')
            self.disk_free += freed - len(content)
        self.files[key] = {
            "type": headers.get("X-LXD-type", "file"),
            "uid": int(headers.get("X-LXD-uid", "0")),
            "gid": int(headers.get("X-LXD-gid", "0")),
            "mode": headers.get("X-LXD-mode", "0644").lstrip("0").rjust(4, "0") if headers.get("X-LXD-mode") else "0644",
            "content": content,
        }
        return self.sync({})

    def create_instance(self, project: str | None, body: dict[str, t.Any]) -> LXDResponse:
        name = body["name"]
        path = f"/1.0/instances/{name}"
        if self.get(path, project) is not None:
            return self.error(409, f'Instance "{name}" already exists')
        source = body.get("source") or {}
        if source.get("type") == "image" and not (source.get("alias") or source.get("fingerprint")):
            return self.error(400, "No image given")
        inst = {
            "name": name,
            "type": body.get("type") or "container",
            "description": body.get("description", ""),
            "config": dict(body.get("config") or {}),
            "devices": dict(body.get("devices") or {}),
            "profiles": list(body.get("profiles") or ["default"]),
            "ephemeral": bool(body.get("ephemeral")),
            "status": "Running" if body.get("start") else "Stopped",
            "location": "none",
            "used_by": [],
        }
        self.add(path, inst, project)
        return self.done()

    def create_image(self, project: str | None, body: t.Any, data: t.Any, headers: dict[str, str]) -> LXDResponse:
        """Create an image from an upload (a file or multipart) or from a JSON source.

        The fingerprint is the SHA-256 of the upload, or of the JSON source. O(image_uploads) records
        the Content-Type and the bytes of each upload.
        """
        if body is not None:
            fingerprint = hashlib.sha256(json.dumps(body["source"], sort_keys=True).encode()).hexdigest()
            public = bool(body.get("public"))
        else:
            content = data.read() if hasattr(data, "read") else bytes(data or b"")
            self.image_uploads.append((headers.get("Content-Type", ""), content))
            fingerprint = hashlib.sha256(content).hexdigest()
            public = headers.get("X-LXD-public") == "true"
        path = f"/1.0/images/{fingerprint}"
        if self.get(path, project) is None:
            image = {
                "fingerprint": fingerprint,
                "type": "container",
                "public": public,
                "auto_update": False,
                "properties": {},
                "profiles": ["default"],
                "expires_at": "0001-01-01T00:00:00Z",
            }
            self.add(path, image, project)
        return self.done({"fingerprint": fingerprint})

    def image(self, path: str, project: str | None) -> LXDResponse:
        """Answer GET of an image, with its aliases from the alias objects, as LXD does."""
        image = self.get(path, project)
        if image is None:
            return self.error(404, "Image not found")
        fingerprint = image["fingerprint"]
        aliases = [
            {"name": alias["name"], "description": alias.get("description", "")}
            for _p, alias in self.children("/1.0/images/aliases", project)
            if alias.get("target") == fingerprint
        ]
        shown = dict(image, aliases=aliases)
        return self.sync(shown, headers={"ETag": self.etag(image)})

    def create_identity(self, kind: str, body: dict[str, t.Any]) -> LXDResponse:
        """Create a TLS or bearer identity. A pending TLS identity returns its join token."""
        name = body["name"]
        path = f"/1.0/auth/identities/{kind}/{name}"
        if self.get(path) is not None:
            return self.error(409, f'Identity "{name}" already exists')
        identity: dict[str, t.Any] = {"name": name, "authentication_method": kind, "groups": list(body.get("groups") or [])}
        if kind == "tls":
            identity["type"] = "Client certificate (pending)" if body.get("token") else "Client certificate"
            if body.get("certificate"):
                identity["tls_certificate"] = body["certificate"]
        else:
            identity["type"] = body.get("type", "Client token bearer")
        self.add(path, identity)
        if kind == "tls" and body.get("token"):
            return self.done(
                {"client_name": name, "fingerprint": "f" * 64, "addresses": ["192.0.2.1:8443"], "secret": "s3cret", "expires_at": "0001-01-01T00:00:00Z"}
            )
        return self.done()

    def identity_token(self, method: str, path: str, body: t.Any) -> LXDResponse:
        """Issue or revoke the token of a bearer identity. As in LXD 6.10.1, an expired token keeps the type of the identity."""
        identity = self.get(path)
        if identity is None:
            return self.error(404, "Identity not found")
        kind = str(identity.get("type") or "").replace(" (pending)", "")
        if method == "DELETE":
            identity["type"] = kind + " (pending)"
            identity.pop("expires_at", None)
            return self.sync({})
        self.tokens_issued += 1
        identity["type"] = kind
        # The test sets the expiry time of the new token. LXD computes it from the expiry of the request.
        identity["expires_at"] = self.next_token_expires_at
        return self.sync({"token": f"token-{self.tokens_issued}"})

    def children(self, path: str, project: str | None) -> list[tuple[str, dict[str, t.Any]]]:
        prefix = self.key(path, project) + "/"
        out = []
        for key, obj in sorted(self.objects.items()):
            if key.startswith(prefix) and "/" not in key[len(prefix) :]:
                out.append((key.split(":", 1)[1], obj))
        return out

    def all_projects(self, path: str, query: dict[str, str]) -> LXDResponse:
        """Answer a list of all projects, as LXD 6.10.1 does: each object has C(project), and a C(<field> eq <value>) filter ignores the case."""
        if path.count("/") != 2:
            return self.error(400, "All projects queries are not supported")
        if query.get("project"):
            return self.error(400, "Cannot specify a project when requesting all projects")
        field, _eq, wanted = (query.get("filter") or "").partition(" eq ")
        items = []
        for key, obj in sorted(self.objects.items()):
            project, _sep, obj_path = key.partition(":")
            if obj_path.rsplit("/", 1)[0] != path or (wanted and str(obj.get(field)).lower() != wanted.lower()):
                continue
            items.append((obj_path, dict(obj, project=project)))
        if query.get("recursion"):
            return self.sync([o for _p, o in items])
        return self.sync([p if o["project"] == "default" else f"{p}?project={o['project']}" for p, o in items])

    @staticmethod
    def export_data(path: str) -> bytes:
        """Return the bytes of a backup export: fixed, and larger than one chunk of the client."""
        return (path.encode() + b"\n") * 40000

    def on_get(self, path, query, project, body, headers):
        if path.endswith("/export") and self.get(path[: -len("/export")], project) is not None:
            return LXDResponse(200, {"Content-Type": "application/octet-stream"}, self.export_data(path))
        if query.get("all-projects") == "true" and path.split("/")[2] in PROJECT_SCOPED:
            return self.all_projects(path, query)
        obj = self.get(path, project)
        if obj is not None and query.get("target") and path.split("/")[2] in ("networks", "storage-pools"):
            obj = self.member_view(path, project, query["target"])
        if obj is not None:
            return self.sync(obj, headers={"ETag": self.etag(obj)})
        items = self.children(path, project)
        if items or path.count("/") == 2:
            if query.get("recursion"):
                return self.sync([o for _p, o in items])
            return self.sync([p for p, _o in items])
        return self.error(404, "Not found")

    on_head = on_get

    def on_post(self, path, query, project, body, headers):
        if path == "/1.0/instances":
            return self.create_instance(project, body)
        if self.get(path, project) is not None:
            # A POST to an object renames it.
            moved = self.objects.pop(self.key(path, project))
            new = path.rsplit("/", 1)[0] + "/" + body["name"]
            moved["name"] = body["name"]
            self.add(new, moved, project)
            return self.done()
        if path.startswith("/1.0/cluster/members/") and path.endswith("/state"):
            member = self.get(path[: -len("/state")])
            if member is None:
                return self.error(404, "Not found")
            self.member_actions.append(dict(body))
            member["status"] = "Evacuated" if body["action"] == "evacuate" else "Online"
            return self.done()
        if path in ("/1.0/auth/identities/tls", "/1.0/auth/identities/bearer"):
            return self.create_identity(path.rsplit("/", 1)[1], body)
        parts = path.split("/")
        if len(parts) > 4 and parts[2] in PARENT_COLLECTIONS and self.get("/".join(parts[:4]), project) is None:
            # A collection under an object, such as the volumes of a pool: the object must exist.
            return self.error(404, "Not found")
        # Network forwards and load balancers are keyed by their listen address.
        name = (body or {}).get("name") or (body or {}).get("listen_address")
        if not name:
            return self.error(400, "No name provided")
        new = f"{path}/{name}"
        if self.get(new, project) is not None:
            return self.error(409, f'"{name}" already exists')
        obj: dict[str, t.Any] = {"config": {}, "description": "", "used_by": []}
        obj.update(copy.deepcopy(body))
        if parts[-1] == "keys" and parts[-3] == "buckets":
            # LXD makes the keys that the request leaves out.
            obj.setdefault("role", "read-only")
            obj.setdefault("access-key", f"generated-access-{name}")
            obj.setdefault("secret-key", f"generated-secret-{name}")
        if path == "/1.0/image-registries":
            config = obj.get("config") or {}
            obj.update(protocol="lxd" if config.get("cluster") else "simplestreams", builtin=False)
        if parts[-1] == "peers":
            obj.setdefault("target_project", project or "default")
            obj["status"] = "Pending"
        self.add(new, obj, project)
        return self.done()

    def on_put(self, path, query, project, body, headers):
        obj = self.get(path, project)
        if obj is None:
            return self.error(404, "Not found")
        if query.get("target") and path.split("/")[2] in ("networks", "storage-pools"):
            return self.put_member(path, project, query["target"], body, headers)
        if headers.get("If-Match") and headers["If-Match"] != self.etag(obj):
            return self.error(412, "Precondition Failed")
        keep = {k: obj[k] for k in READ_ONLY + CREATE_ONLY.get(path.split("/")[-2], ()) if k in obj}
        obj.clear()
        obj.update(copy.deepcopy(body))
        obj.update(keep)
        return self.done()

    def on_patch(self, path, query, project, body, headers):
        obj = self.get(path, project)
        if obj is None:
            return self.error(404, "Not found")
        for key, value in body.items():
            if isinstance(value, dict) and isinstance(obj.get(key), dict):
                obj[key].update(value)
            else:
                obj[key] = copy.deepcopy(value)
        return self.done()

    def on_delete(self, path, query, project, body, headers):
        key = self.key(path, project)
        if key not in self.objects:
            return self.error(404, "Not found")
        obj = self.objects[key]
        if path.startswith("/1.0/cluster/groups/"):
            # As LXD 6.10.1 answers on a live cluster.
            if obj.get("members"):
                return self.error(400, "Only empty cluster groups can be removed")
            if obj.get("used_by"):
                return self.error(400, "Cluster group is currently in use")
        if path.startswith("/1.0/instances/") and obj.get("status") in ("Running", "Frozen") and query.get("force") != "true":
            return self.error(400, "Instance is running")
        for other in [k for k in self.objects if k == key or k.startswith(key + "/")]:
            del self.objects[other]
        if path.startswith("/1.0/cluster/links/"):
            # The identity of the link goes with it.
            self.objects.pop(self.key("/1.0/auth/identities/tls/" + path.rsplit("/", 1)[1], None), None)
        return self.done()
