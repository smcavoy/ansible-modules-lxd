# Copyright (c) 2026, Sean McAvoy
# GNU General Public License v3.0+ (see LICENSES/GPL-3.0-or-later.txt or https://www.gnu.org/licenses/gpl-3.0.txt)
# SPDX-License-Identifier: GPL-3.0-or-later

"""The LXD version guard of tests/lxd/lxdtest: a sandbox with an LXD older than the minimum fails the run.

The tests load the runner script as a module. No LXD server and no lxc client are needed.
"""

from __future__ import annotations

import argparse
import importlib.machinery
import importlib.util
import typing as t
from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parents[2] / "lxd" / "lxdtest"


def load(name: str) -> t.Any:
    """Return the runner script as a new module."""
    loader = importlib.machinery.SourceFileLoader(name, str(SCRIPT))
    spec = importlib.util.spec_from_loader(loader.name, loader)
    assert spec is not None
    module = importlib.util.module_from_spec(spec)
    loader.exec_module(module)
    return module


@pytest.fixture
def runner(monkeypatch: pytest.MonkeyPatch) -> t.Any:
    """Return the runner script as a module, with the minimum 6.10.2 and an empty list of old sandboxes."""
    module = load("lxdtest_version_under_test")
    monkeypatch.setattr(module, "MIN_LXD_VERSION", "6.10.2")
    monkeypatch.setattr(module, "OLD_LXD", [])
    return module


class SnapHost:
    """A host LXD whose exec returns one line of C(snap list lxd): version, revision, channel."""

    def __init__(self, line: str) -> None:
        self.line = line
        self.calls = 0

    def exec(self, instance: str, script: str, timeout: int = 0) -> str:
        assert "snap list lxd" in script
        self.calls += 1
        return self.line


def test_the_minimum_comes_from_the_image_recipe():
    """The file is in the recipe folder, so a new minimum gives a new image alias."""
    module = load("lxdtest_minimum_under_test")
    assert module.version_tuple(module.MIN_LXD_VERSION) >= (6, 10, 2)
    assert (SCRIPT.parent / "sandbox" / "min-lxd-version").is_file()


@pytest.mark.parametrize(
    ("text", "numbers"),
    [("6.10.2-fa810fd", (6, 10, 2)), ("6.10.1-f5c750d", (6, 10, 1)), ("6.11", (6, 11)), ("7.0.0", (7, 0, 0)), ("git-21e61d6", ()), ("?", ())],
)
def test_version_tuple(runner, text, numbers):
    assert runner.version_tuple(text) == numbers


@pytest.mark.parametrize(
    "line",
    ["6.10.2-fa810fd 41487 6/candidate\n", "6.10.3-0000000 50000 6/stable\n", "6.11-abc 50001 6/stable\n", "7.0.1-abc 60000 7/stable\n"],
)
def test_a_new_enough_sandbox_passes_and_prints_its_snap(runner, capsys, line):
    host = SnapHost(line)
    sandbox = runner.Sandbox(host, "sbx-test-1", "sandbox/test")
    sandbox.check_lxd_version()
    sandbox.check_lxd_version()
    version, revision, channel = line.split()
    assert f"sandbox sbx-test-1: LXD {version}, snap revision {revision}, channel {channel}" in capsys.readouterr().out
    assert host.calls == 1
    assert runner.OLD_LXD == []


@pytest.mark.parametrize(
    "line",
    ["6.10.1-f5c750d 41228 6/stable\n", "6.9-abc 30000 6/stable\n", "5.21.4-abc 20000 5.21/stable\n", "git-21e61d6 41468 6/edge\n", ""],
)
def test_an_old_or_unknown_lxd_fails_the_sandbox(runner, line):
    sandbox = runner.Sandbox(SnapHost(line), "sbx-test-1", "sandbox/test")
    with pytest.raises(runner.RunError, match="older than 6.10.2"):
        sandbox.check_lxd_version()
    assert len(runner.OLD_LXD) == 1
    assert "sbx-test-1" in runner.OLD_LXD[0]


def test_an_old_sandbox_fails_a_run_whose_tests_all_passed(runner, tmp_path, capsys):
    """The other slots can run every test. The run must still fail, with the reason in the log."""
    one_run = runner.Run(argparse.Namespace(collection=str(tmp_path), results=str(tmp_path / "results"), remote="test", project="test"))
    test = runner.Test("target", "lxd_project", tmp_path / "lxd_project")
    test.status = "pass"
    assert one_run.report([test]) == 0
    sandbox = runner.Sandbox(SnapHost("6.10.1-f5c750d 41228 6/stable\n"), "sbx-test-2", "sandbox/test")
    with pytest.raises(runner.RunError):
        sandbox.check_lxd_version()
    assert one_run.report([test]) == 2
    out = capsys.readouterr().out
    assert "ERROR sandbox sbx-test-2 runs LXD 6.10.1-f5c750d (snap revision 41228, channel 6/stable), which is older than 6.10.2" in out
    assert "every sandbox must run LXD 6.10.2 or newer" in out
