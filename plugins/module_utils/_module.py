# Copyright (c) 2026, Sean McAvoy
# GNU General Public License v3.0+ (see LICENSES/GPL-3.0-or-later.txt or https://www.gnu.org/licenses/gpl-3.0.txt)
# SPDX-License-Identifier: GPL-3.0-or-later

# Note that this module util is **PRIVATE** to the collection. It can have breaking changes at any time.
# Do not use this from other collections or standalone plugins/modules!

"""Base class for the LXD modules."""

from __future__ import annotations

import re
import typing as t
from collections.abc import Callable, Iterable, Mapping

from ansible.module_utils.basic import AnsibleModule, env_fallback

from ansible_collections.smcavoy.lxd.plugins.module_utils._client import (
    MIN_SERVER_VERSION,
    LXDClient,
    LXDClientError,
)
from ansible_collections.smcavoy.lxd.plugins.module_utils._config import ConfigValueError

if t.TYPE_CHECKING:  # pragma: no cover
    from ansible_collections.smcavoy.lxd.plugins.module_utils._typing import ArgumentSpecMutT

_T = t.TypeVar("_T")

MASK = "********"


def mask_secrets(value: t.Any, pattern: re.Pattern[str]) -> t.Any:
    """Return a copy of a result with each non-empty value masked whose key matches O(pattern), at any depth."""
    if isinstance(value, Mapping):
        return {
            key: (MASK if isinstance(key, str) and pattern.search(key) and item not in (None, "") else mask_secrets(item, pattern))
            for key, item in value.items()
        }
    if isinstance(value, (list, tuple)):
        return [mask_secrets(item, pattern) for item in value]
    return value


def connection_argument_spec() -> ArgumentSpecMutT:
    """Return the argument spec of the connection options."""
    return {
        "url": {"type": "str", "fallback": (env_fallback, ["LXD_URL"])},
        "client_cert": {"type": "path", "fallback": (env_fallback, ["LXD_CLIENT_CERT"])},
        "client_key": {"type": "path", "fallback": (env_fallback, ["LXD_CLIENT_KEY"]), "no_log": False},
        "bearer_token": {"type": "str", "no_log": True, "fallback": (env_fallback, ["LXD_BEARER_TOKEN"])},
        "server_cert": {"type": "path", "fallback": (env_fallback, ["LXD_SERVER_CERT"])},
        "server_fingerprint": {"type": "str", "fallback": (env_fallback, ["LXD_SERVER_FINGERPRINT"])},
        "validate_certs": {"type": "bool", "default": True, "fallback": (env_fallback, ["LXD_VALIDATE_CERTS"])},
        "trust_token": {"type": "str", "no_log": True},
        "timeout": {"type": "int", "default": 120, "fallback": (env_fallback, ["LXD_TIMEOUT"])},
    }


def _already_exists(exc: LXDClientError) -> bool:
    """Tell whether LXD refused a create because the object exists.

    LXD says so with HTTP 409 or 400 on the request, or in the error of a failed operation.
    """
    return "already exists" in (exc.message or "").lower()


class LXDModule:
    """Wrap C(AnsibleModule) with the LXD client and the shared rules of the collection."""

    def __init__(
        self,
        argument_spec: ArgumentSpecMutT,
        extensions: Iterable[str] = (),
        mutually_exclusive: list[t.Any] | None = None,
        required_together: list[t.Any] | None = None,
        required_one_of: list[t.Any] | None = None,
        required_if: list[t.Any] | None = None,
        required_by: dict[str, t.Any] | None = None,
    ) -> None:
        spec = connection_argument_spec()
        spec.update(argument_spec)
        self.module = AnsibleModule(
            argument_spec=spec,
            supports_check_mode=True,
            mutually_exclusive=[["bearer_token", "client_cert"]] + list(mutually_exclusive or []),
            required_together=[["client_cert", "client_key"]] + list(required_together or []),
            required_one_of=required_one_of or [],
            required_if=required_if or [],
            required_by=required_by or {},
        )
        self.params = self.module.params
        self.check_mode = self.module.check_mode
        self.client: LXDClient
        try:
            self.client = LXDClient(
                url=self.params["url"],
                client_cert=self.params["client_cert"],
                client_key=self.params["client_key"],
                bearer_token=self.params["bearer_token"],
                server_cert=self.params["server_cert"],
                validate_certs=self.params["validate_certs"],
                timeout=self.params["timeout"],
                server_fingerprint=self.params["server_fingerprint"],
            )
            self.client.ensure_trusted(self.params["trust_token"], check_mode=self.check_mode)
            version = self.client.server_version()
            if version < MIN_SERVER_VERSION:
                text = ".".join(str(part) for part in version)
                self.fail(f"LXD server version {text} is older than 6.10.1")
            missing = self.client.missing_extensions(extensions)
            if missing:
                self.fail(f"LXD server lacks the API extensions: {', '.join(missing)}")
        except LXDClientError as exc:
            self.fail(exc.message)

    # ------------------------------------------------------------------
    # Results

    def _extra(self) -> dict[str, t.Any]:
        extra: dict[str, t.Any] = {}
        client = getattr(self, "client", None)
        for note in getattr(client, "notes", None) or []:
            self.module.warn(note)
        if client is not None and self.module._verbosity >= 4:
            extra["http_log"] = client.http_log
        return extra

    def fail(self, msg: str, **kwargs: t.Any) -> t.NoReturn:
        """Fail the task with O(msg)."""
        kwargs.update(self._extra())
        self.module.fail_json(msg=msg, **kwargs)
        raise AssertionError("unreachable")  # pragma: no cover  # pylint: disable=unreachable

    def warn(self, msg: str) -> None:
        """Add a warning to the result."""
        self.module.warn(msg)

    _secret_re: re.Pattern[str] | None = None

    def hide_secrets(self, pattern: str) -> None:
        """Treat the config keys that match O(pattern) as secrets.

        The module then masks their values in every result and diff. It also names the values of the task to Ansible,
        which masks them everywhere in the output, also in invocation.module_args.
        """
        self._secret_re = re.compile(pattern)

        def walk(value: t.Any) -> None:
            if not isinstance(value, Mapping):
                return
            for key, item in value.items():
                if isinstance(key, str) and self._secret_re is not None and self._secret_re.search(key) and item not in (None, ""):
                    self.module.no_log_values.add(str(item))
                walk(item)

        for option in ("config", "member_config"):
            walk(self.params.get(option))

    def exit(
        self,
        changed: bool,
        before: Mapping[str, t.Any] | None = None,
        after: Mapping[str, t.Any] | None = None,
        **result: t.Any,
    ) -> t.NoReturn:
        """End the task. Add the diff in diff mode."""
        if self._secret_re is not None:
            before = mask_secrets(before, self._secret_re) if before is not None else None
            after = mask_secrets(after, self._secret_re) if after is not None else None
            result = mask_secrets(result, self._secret_re)
        if self.module._diff and (before is not None or after is not None):
            result["diff"] = {"before": dict(before or {}), "after": dict(after or {})}
        result.update(self._extra())
        self.module.exit_json(changed=changed, **result)
        raise AssertionError("unreachable")  # pragma: no cover  # pylint: disable=unreachable

    # ------------------------------------------------------------------
    # Requests

    def query(self, **extra: t.Any) -> dict[str, t.Any]:
        """Return the query string parameters, with O(project) when the task sets it."""
        result: dict[str, t.Any] = {}
        project = self.params.get("project")
        if project:
            result["project"] = project
        result.update({key: value for key, value in extra.items() if value is not None})
        return result

    def check_target(self) -> None:
        """Fail if the task sets O(target) on a standalone server."""
        if self.params.get("target") and not self.client.is_clustered():
            self.fail("target is only valid on a clustered server")

    def write(self, method: str, path: str, **kwargs: t.Any) -> t.Any:
        """Send a write, except in check mode."""
        if self.check_mode:
            return None
        return self.client.write(method, path, **kwargs)

    def run(self, func: Callable[[], _T]) -> _T:
        """Run O(func) with error handling.

        Run it a second time after one HTTP 412 answer (the object changed between the read and the
        write), or after one "already exists" answer (another client made the object between the read
        and the create). The second run reads the object again and takes the update path.
        """
        try:
            try:
                return func()
            except LXDClientError as exc:
                if not (exc.status == 412 or _already_exists(exc)):
                    raise
                return func()
        except LXDClientError as exc:
            self.fail(exc.message)
        except ConfigValueError as exc:
            self.fail(str(exc))
