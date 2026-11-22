# Copyright (c) 2026, Sean McAvoy
# GNU General Public License v3.0+ (see LICENSES/GPL-3.0-or-later.txt or https://www.gnu.org/licenses/gpl-3.0.txt)
# SPDX-License-Identifier: GPL-3.0-or-later

from __future__ import annotations

import typing as t

import pytest

from ansible_collections.smcavoy.lxd.plugins.module_utils._client import LXDClientError
from ansible_collections.smcavoy.lxd.plugins.module_utils._module import LXDModule


class Failed(Exception):
    pass


class FakeAnsibleModule:
    _verbosity = 0

    def fail_json(self, msg: str, **kwargs: t.Any) -> t.NoReturn:
        raise Failed(msg)

    def warn(self, msg: str) -> None:
        pass


def bare_module() -> LXDModule:
    """An LXDModule without a server, to test LXDModule.run."""
    mod = LXDModule.__new__(LXDModule)
    mod.module = FakeAnsibleModule()  # type: ignore[assignment]
    return mod


def calls(*outcomes: t.Any) -> t.Callable[[], t.Any]:
    """Return a function that raises or returns the outcomes in order, one per call."""
    queue = list(outcomes)

    def func() -> t.Any:
        outcome = queue.pop(0)
        if isinstance(outcome, Exception):
            raise outcome
        return outcome

    return func


@pytest.mark.parametrize(
    "error",
    [
        LXDClientError('Project "web" already exists', 409),
        LXDClientError('Error inserting "web" into database: The profile already exists', 400),
        LXDClientError("LXD operation op1 failed: Instance web already exists"),
        LXDClientError("Precondition failed", 412),
    ],
)
def test_run_runs_again_after_a_race(error):
    # Another client made or changed the object between the read and the write.
    assert bare_module().run(calls(error, "updated")) == "updated"


def test_run_runs_again_only_once():
    error = LXDClientError('Project "web" already exists', 409)
    with pytest.raises(Failed, match="already exists"):
        bare_module().run(calls(error, error))


def test_run_fails_at_once_on_other_errors():
    with pytest.raises(Failed, match="bad config key"):
        bare_module().run(calls(LXDClientError("bad config key", 400), "never"))
