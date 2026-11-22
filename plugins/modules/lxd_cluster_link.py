#!/usr/bin/python
# Copyright (c) 2026, Sean McAvoy
# GNU General Public License v3.0+ (see LICENSES/GPL-3.0-or-later.txt or https://www.gnu.org/licenses/gpl-3.0.txt)
# SPDX-License-Identifier: GPL-3.0-or-later

from __future__ import annotations

DOCUMENTATION = r"""
module: lxd_cluster_link
short_description: Manage links between LXD clusters
version_added: "0.1.0"
description:
  - Create, update, and delete links between two LXD clusters. A link is V(bidirectional), V(unidirectional), or V(public).
  - A V(bidirectional) or V(unidirectional) link needs two tasks. The first task runs on cluster B without O(trust_token).
    It makes a pending link and returns a token. The second task runs on cluster A with that token.
  - A V(public) link needs only cluster A. The module confirms it when O(fingerprint) matches the certificate of the other cluster.
author:
  - Sean McAvoy (@smcavoy)
extends_documentation_fragment:
  - smcavoy.lxd._attributes
  - smcavoy.lxd._attributes.action_group
  - smcavoy.lxd._connection
attributes:
  check_mode:
    support: full
  diff_mode:
    support: full
  idempotent:
    support: full
options:
  name:
    description:
      - The link name on this cluster.
    type: str
    required: true
  state:
    description:
      - The wanted state of the link.
    type: str
    choices:
      present: The link exists on this cluster.
      absent: The link does not exist on this cluster. The link on the other cluster stays.
    default: present
  type:
    description:
      - The link type.
      - The module uses it only when it creates the link. On an existing link, the module warns and ignores a different value.
    type: str
    choices: ["bidirectional", "unidirectional", "public"]
    default: bidirectional
  trust_token:
    description:
      - The token from the pending link on the other cluster. With it, the module activates the link on both clusters.
      - Without it, the module makes a pending link and returns a new token.
      - The module uses it only when it creates the link. Not for V(public).
    type: str
  auth_groups:
    description:
      - The authorization groups of the identity that LXD makes for the other cluster.
      - The module uses it only when it creates the link. Not for V(public).
    type: list
    elements: str
  remote_address:
    description:
      - The address of the other cluster, for example V(10.0.0.5:8443). Required to create a V(public) link.
    type: str
  fingerprint:
    description:
      - The expected SHA-256 fingerprint of the certificate of the other cluster, for a V(public) link.
      - If it matches, the module confirms the link. If it does not match or is not set, the link stays pending.
    type: str
  description:
    description:
      - The link description.
      - If not set, the module does not manage the description.
    type: str
  config:
    description:
      - The link config. Only C(user.*) keys.
      - A key with the value V(null) or an empty string is removed.
    type: dict
  config_mode:
    description:
      - How to treat config keys of the link that are not in O(config).
    type: str
    choices:
      merge: Keep them.
      exact: Remove them. The module keeps the C(volatile.*) keys.
    default: merge
notes:
  - The token is a secret. It appears only in the result of the run that makes the pending link. Use C(no_log=true) on the task.
  - Each cluster has its own link object. A delete on one cluster does not delete the link on the other cluster.
  - A pending V(unidirectional) link has no link object on the cluster that issues the token, only a pending identity.
    The module then returns RV(link) as V(null). It finds the pending identity by the link name, and O(state=absent) revokes it.
  - A cluster holds the certificate of another cluster only once. A second link to the same cluster fails with
    C(Certificate already exists).
seealso:
  - module: smcavoy.lxd.lxd_auth_group
"""

EXAMPLES = r"""
- name: Make a pending link on cluster B
  smcavoy.lxd.lxd_cluster_link:
    url: https://cluster-b:8443
    name: site-a
  register: pending
  no_log: true

- name: Activate the link on cluster A with the token
  smcavoy.lxd.lxd_cluster_link:
    url: https://cluster-a:8443
    name: site-b
    trust_token: "{{ pending.trust_token }}"
    auth_groups:
      - replicators
  no_log: true

- name: A public link, confirmed by the fingerprint
  smcavoy.lxd.lxd_cluster_link:
    name: mirror
    type: public
    remote_address: 10.0.0.5:8443
    fingerprint: 6b0e06bd9f3ee54252fd857a681401b0eea2695891a336b0e4ca180681144159
"""

RETURN = r"""
link:
  description:
    - The link after the change, as LXD returns it.
    - In check mode, the predicted link.
    - V(null) after a delete, and for a pending V(unidirectional) link on the cluster that issues the token.
  returned: always
  type: dict
  sample:
    name: site-b
    type: bidirectional
    description: ""
    config:
      volatile.addresses: 10.250.0.41:8443
    used_by: []
trust_token:
  description:
    - The token for the other cluster. Only when the module makes a pending V(bidirectional) or V(unidirectional) link.
    - This is a secret.
  returned: when the module makes a pending link
  type: str
  sample: eyJjbGllbnRfbmFtZSI6InNpdGUtYSIsLi4u
remote_fingerprint:
  description:
    - The certificate fingerprint of the other cluster, for a new V(public) link.
  returned: when the module makes a public link
  type: str
  sample: 6b0e06bd9f3ee54252fd857a681401b0eea2695891a336b0e4ca180681144159
pending:
  description:
    - Whether the link waits for the other cluster or for a fingerprint.
  returned: when O(state=present)
  type: bool
"""

import base64
import hashlib
import json
import ssl
import typing as t

from ansible_collections.smcavoy.lxd.plugins.module_utils._client import api_path
from ansible_collections.smcavoy.lxd.plugins.module_utils._config import COMPUTED_KEYS
from ansible_collections.smcavoy.lxd.plugins.module_utils._module import LXDModule
from ansible_collections.smcavoy.lxd.plugins.module_utils._resource import create_config, plan_common, warn_create_only

if t.TYPE_CHECKING:  # pragma: no cover
    from ansible_collections.smcavoy.lxd.plugins.module_utils._typing import ArgumentSpecMutT

FIELDS = ("description", "config")
PENDING_TYPE = "Cluster link certificate (pending)"
TYPE_EXTENSIONS = {"unidirectional": "cluster_links_unidirectional", "public": "cluster_links_public"}


def encode_token(meta: dict[str, t.Any]) -> str:
    """Build the token from the answer of a pending create, as the lxc client does: base64 of the JSON object."""
    return base64.b64encode(json.dumps(meta, separators=(",", ":")).encode()).decode()


def is_pending(link: dict[str, t.Any]) -> bool:
    """Return whether the link waits. A pending public link has a pending certificate. An active link has C(volatile.addresses)."""
    config = link.get("config") or {}
    return bool(config.get("volatile.pending_certificate")) or not config.get("volatile.addresses")


class ClusterLinkModule:
    """Manage the link object on one cluster."""

    def __init__(self, mod: LXDModule) -> None:
        self.mod = mod
        params = mod.params
        self.name: str = params["name"]
        self.path = api_path("cluster", "links", self.name)
        if params["trust_token"]:
            mod.module.no_log_values.add(params["trust_token"])
        public = params["type"] == "public"
        if public and (params["trust_token"] or params["auth_groups"]):
            mod.fail("trust_token and auth_groups are not for a public link")
        if not public and (params["remote_address"] or params["fingerprint"]):
            mod.fail("remote_address and fingerprint are only for a public link")
        for key in params["config"] or {}:
            if not str(key).startswith("user."):
                mod.fail(f"config key {key} is not a user.* key")

    def read(self) -> tuple[dict[str, t.Any] | None, str | None]:
        """Read the link."""
        return self.mod.client.get_or_none(self.path)

    def present(self) -> None:
        """Make sure that the link exists with the wanted fields."""
        params = self.mod.params
        current, etag = self.read()
        if current is None:
            self.create()
        warn_create_only(self.mod, current, {"type": current.get("type")})
        plan = plan_common(self.mod, current, FIELDS, COMPUTED_KEYS["cluster_link"])
        result: dict[str, t.Any] = {}
        if current.get("type") == "public" and is_pending(current) and params["fingerprint"]:
            result = self.confirm_public(current)
        if not plan.is_changed:
            if result:
                self.mod.exit(True, before=plan.before(), after=plan.after(), link=self.final(current), **result)
            self.mod.exit(False, before=plan.before(), after=plan.after(), link=current, pending=is_pending(current))
        body = {"description": plan.new.get("description") or "", "config": plan.new.get("config") or {}}
        self.mod.write("PUT", self.path, body=body, etag=etag)
        link = self.final(dict(current, **plan.new))
        self.mod.exit(True, before=plan.before(), after=plan.after(), link=link, pending=is_pending(link), **result)

    def create(self) -> t.NoReturn:
        """Create the link. Exit the module."""
        params = self.mod.params
        link_type = params["type"]
        missing = self.mod.client.missing_extensions([TYPE_EXTENSIONS[link_type]] if link_type in TYPE_EXTENSIONS else [])
        if missing:
            self.mod.fail(f"LXD server lacks the API extensions: {', '.join(missing)}")
        body: dict[str, t.Any] = {"name": self.name, "type": link_type, "description": params["description"] or "", "config": create_config(self.mod)}
        after = {key: body[key] for key in FIELDS}
        predicted = dict(after, name=self.name, type=link_type, used_by=[])
        if link_type == "public":
            if not params["remote_address"]:
                self.mod.fail("remote_address is required to create a public link")
            body["remote_address"] = params["remote_address"]
            if self.mod.check_mode:
                self.mod.exit(True, before={}, after=after, link=predicted, pending=not params["fingerprint"])
            meta = self.mod.client.write("POST", "/1.0/cluster/links", body=body) or {}
            remote = str(meta.get("fingerprint") or "")
            current, _etag = self.read()
            link = current or predicted
            public_result: dict[str, t.Any] = {"remote_fingerprint": remote}
            if params["fingerprint"]:
                public_result.update(self.confirm_public(link, remote))
                link = self.final(link)
            self.mod.exit(True, before={}, after=after, link=link, pending=is_pending(link), **public_result)
        if params["auth_groups"] is not None:
            body["auth_groups"] = params["auth_groups"]
        if params["trust_token"]:
            body["trust_token"] = params["trust_token"]
        elif self.pending_identity() is not None:
            # A pending unidirectional link has no link object on this cluster, only the pending identity.
            self.mod.exit(False, before={}, after={}, link=None, pending=True, msg=f"a token for link {self.name} is already open")
        if self.mod.check_mode:
            self.mod.exit(True, before={}, after=after, link=predicted, pending=not params["trust_token"])
        meta = self.mod.client.write("POST", "/1.0/cluster/links", body=body)
        new_link, _etag = self.read()
        result: dict[str, t.Any] = {}
        if not params["trust_token"]:
            if not isinstance(meta, dict) or not meta.get("secret"):
                self.mod.fail("LXD did not return a token for the pending link")
            token = encode_token(meta)
            result["trust_token"] = token
        self.mod.exit(True, before={}, after=after, link=new_link, pending=new_link is None or is_pending(new_link), **result)

    def pending_identity(self) -> dict[str, t.Any] | None:
        """Return the pending cluster link identity with the link name, or None."""
        identities, _etag = self.mod.client.get("/1.0/auth/identities", {"recursion": 1})
        for identity in identities or []:
            if identity.get("name") == self.name and str(identity.get("type") or "").startswith(PENDING_TYPE):
                return dict(identity)
        return None

    def confirm_public(self, link: dict[str, t.Any], remote: str | None = None) -> dict[str, t.Any]:
        """Confirm a pending public link when the fingerprint matches. Return the result keys."""
        wanted = self.mod.params["fingerprint"].lower()
        if remote is None:
            remote = self.pending_fingerprint(link)
        if remote and remote.lower() != wanted:
            self.mod.fail(f"remote fingerprint {remote} does not match {wanted}", remote_fingerprint=remote, link=link)
        if not self.mod.check_mode:
            self.mod.client.write("POST", "/1.0/cluster/links", body={"name": self.name, "type": "public", "fingerprint": wanted})
        return {"remote_fingerprint": remote or wanted}

    @staticmethod
    def pending_fingerprint(link: dict[str, t.Any]) -> str:
        """Return the fingerprint of the pending certificate of a public link."""
        pem = str((link.get("config") or {}).get("volatile.pending_certificate") or "")
        if not pem:
            return ""
        try:
            return hashlib.sha256(ssl.PEM_cert_to_DER_cert(pem.strip() + "\n")).hexdigest()
        except ValueError:
            return ""

    def absent(self) -> None:
        """Make sure that the link does not exist on this cluster. Also revoke a pending identity of a unidirectional link."""
        current, _etag = self.read()
        if current is None:
            identity = self.pending_identity()
            if identity is None:
                self.mod.exit(False, before={}, after={}, link=None)
            method = identity.get("authentication_method") or "tls"
            self.mod.write("DELETE", api_path("auth", "identities", method, identity.get("id") or self.name))
            self.mod.exit(True, before={"pending": True}, after={}, link=None)
        self.mod.write("DELETE", self.path)
        self.mod.exit(True, before={key: current.get(key) for key in FIELDS}, after={}, link=None)

    def final(self, predicted: dict[str, t.Any]) -> dict[str, t.Any]:
        """Return the link from the server, or the prediction in check mode."""
        if self.mod.check_mode:
            return predicted
        link, _etag = self.read()
        return link or predicted


def get_argument_spec() -> ArgumentSpecMutT:
    """Return the argument spec of the module."""
    return {
        "name": {"type": "str", "required": True},
        "state": {"type": "str", "default": "present", "choices": ["present", "absent"]},
        "type": {"type": "str", "default": "bidirectional", "choices": ["bidirectional", "unidirectional", "public"]},
        "trust_token": {"type": "str", "no_log": True},
        "auth_groups": {"type": "list", "elements": "str"},
        "remote_address": {"type": "str"},
        "fingerprint": {"type": "str"},
        "description": {"type": "str"},
        "config": {"type": "dict"},
        "config_mode": {"type": "str", "default": "merge", "choices": ["merge", "exact"]},
    }


def main() -> None:
    """Run the module."""
    mod = LXDModule(get_argument_spec(), extensions=["cluster_links"])
    link = ClusterLinkModule(mod)
    if mod.params["state"] == "present":
        mod.run(link.present)
    else:
        mod.run(link.absent)


if __name__ == "__main__":
    main()
