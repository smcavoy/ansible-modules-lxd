# Copyright (c) 2026, Sean McAvoy
# GNU General Public License v3.0+ (see LICENSES/GPL-3.0-or-later.txt or https://www.gnu.org/licenses/gpl-3.0.txt)
# SPDX-License-Identifier: GPL-3.0-or-later

"""The scheduler of tests/lxd/lxdtest when a sandbox does not start.

The tests load the runner script as a module and replace the slots, the host and the lock with fakes.
No LXD server and no lxc client are needed.
"""

from __future__ import annotations

import argparse
import importlib.machinery
import importlib.util
import json
import queue
import threading
import typing as t
from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parents[2] / "lxd" / "lxdtest"

FIXTURE_OF_SLOT = {
    "Slot": "lxd/standalone",
    "ClusterSlot": "lxd/cluster",
    "NewClusterSlot": "lxd/cluster-new",
    "MultiClusterSlot": "lxd/multicluster",
    "MicroCloudSlot": "lxd/ovn",
}


@pytest.fixture(scope="module")
def runner() -> t.Any:
    """Return the runner script as a module."""
    loader = importlib.machinery.SourceFileLoader("lxdtest_under_test", str(SCRIPT))
    spec = importlib.util.spec_from_loader(loader.name, loader)
    assert spec is not None
    module = importlib.util.module_from_spec(spec)
    loader.exec_module(module)
    return module


class FakeHost:
    """A host LXD that only records the lock calls."""

    def __init__(self, remote: str, project: str) -> None:
        self.remote = remote
        self.project = project
        self.released = False

    def take_lock(self, owner: str, **kwargs: t.Any) -> None:
        pass

    def release_lock(self) -> None:
        self.released = True

    def cpu_limit(self) -> int:
        return 0


class FakeBeat:
    """A lock renewal that does nothing."""

    def __init__(self, host: FakeHost, owner: str) -> None:
        pass

    def start(self) -> None:
        pass

    def stop(self) -> None:
        pass


class FakeMonitor:
    """A connection monitor that does nothing."""

    def start(self) -> None:
        pass

    def finish(self) -> None:
        pass


class World:
    """The fakes of one test: which slots do not start, and which slot ran which test."""

    def __init__(self) -> None:
        self.broken: set[tuple[str, int]] = set()
        self.ran: list[tuple[int, str]] = []
        self.cleaned: list[int] = []
        self.lock = threading.Lock()
        # Set when every broken standalone slot has failed. The good slots wait for it, so that on the old code
        # the broken slot reaches the queue first. The new code gives the same result in any order.
        self.broken_done = threading.Event()
        self.pending_broken = 0
        self.wait_for_broken = False


def install(runner: t.Any, monkeypatch: pytest.MonkeyPatch, tmp_path: Path, world: World, tests: dict[str, str]) -> None:
    """Replace the parts of the runner that need a server. O(tests) maps a test name to its fixture alias."""

    def fake_slot(kind: str) -> type:
        class FakeSlot:
            def __init__(self, run: t.Any, number: int) -> None:
                self.run = run
                self.number = number
                self.failed = False
                self.start_error = ""
                self.kind = kind

            def prepare(self) -> None:
                if (kind, self.number) in world.broken or (kind, 0) in world.broken:
                    with world.lock:
                        world.pending_broken -= 1
                        if world.pending_broken <= 0:
                            world.broken_done.set()
                    raise runner.RunError(f"no address for sbx-{self.number}")
                if kind == "Slot" and world.wait_for_broken:
                    world.broken_done.wait(10)
                    # Give the thread of the broken slot time to reach the queue after its error.
                    threading.Event().wait(0.3)

            def execute(self, test: t.Any) -> None:
                assert test.fixture == FIXTURE_OF_SLOT[kind]
                with world.lock:
                    world.ran.append((self.number, test.name))
                test.status = "pass"

            def cleanup(self) -> None:
                world.cleaned.append(self.number)

        FakeSlot.__name__ = kind
        return FakeSlot

    # The subclass relations stay: the runner looks for the cluster slot with isinstance.
    slot = fake_slot("Slot")
    cluster = type("ClusterSlot", (fake_slot("ClusterSlot"), slot), {})
    monkeypatch.setattr(runner, "Slot", slot)
    monkeypatch.setattr(runner, "ClusterSlot", cluster)
    monkeypatch.setattr(runner, "NewClusterSlot", type("NewClusterSlot", (fake_slot("NewClusterSlot"), cluster), {}))
    monkeypatch.setattr(runner, "MultiClusterSlot", type("MultiClusterSlot", (fake_slot("MultiClusterSlot"), slot), {}))
    monkeypatch.setattr(runner, "MicroCloudSlot", type("MicroCloudSlot", (fake_slot("MicroCloudSlot"), slot), {}))
    monkeypatch.setattr(runner, "Host", FakeHost)
    monkeypatch.setattr(runner, "LockBeat", FakeBeat)
    monkeypatch.setattr(runner, "MONITOR", FakeMonitor())
    monkeypatch.setattr(runner, "WORK", tmp_path / "work")
    monkeypatch.setattr(runner, "stop_old_processes", lambda run_id: None)
    monkeypatch.setattr(runner, "collect_garbage", lambda host, hours: None)

    def discover(collection: Path, names: list[str], kinds: set[str]) -> list[t.Any]:
        found = []
        for name, fixture in tests.items():
            test = runner.Test("target", name, tmp_path / "none" / name)
            test.aliases = {fixture}
            found.append(test)
        return found

    monkeypatch.setattr(runner, "discover", discover)


def run(runner: t.Any, tmp_path: Path, slots: int = 3) -> tuple[int, dict[str, t.Any]]:
    """Run the runner. Return its exit code and its summary."""
    args = argparse.Namespace(
        names=[],
        collection=str(tmp_path),
        slots=slots,
        image="sandbox/test",
        results=str(tmp_path / "results"),
        timeout=1,
        lock_wait=1,
        keep_on_failure=False,
        lock_owner="",
        scenarios_only=False,
        targets_only=False,
        verbose=False,
        remote="test",
        project="test",
    )
    code = runner.Run(args).main()
    return code, json.loads((tmp_path / "results" / "summary.json").read_text())


def by_name(summary: dict[str, t.Any]) -> dict[str, dict[str, t.Any]]:
    return {test["name"]: test for test in summary["tests"]}


def test_work_leaves_the_queue_to_the_other_slots(runner, monkeypatch, tmp_path):
    """The direct check of Run.work: a slot that does not start takes no test from the shared queue."""
    world = World()
    install(runner, monkeypatch, tmp_path, world, {})
    world.broken = {("Slot", 1)}
    one_run = runner.Run(argparse.Namespace(collection=str(tmp_path), results=str(tmp_path / "results"), remote="test", project="test"))
    tests = [runner.Test("target", name, tmp_path / name) for name in ("a", "b", "c")]
    jobs: queue.Queue = queue.Queue()
    for test in tests:
        jobs.put(test)
    one_run.work(runner.Slot(one_run, 1), jobs)
    assert jobs.qsize() == 3
    assert [test.status for test in tests] == ["skip", "skip", "skip"]
    one_run.work(runner.Slot(one_run, 2), jobs)
    assert [test.status for test in tests] == ["pass", "pass", "pass"]
    assert world.ran == [(2, "a"), (2, "b"), (2, "c")]


def test_one_slot_does_not_start_the_others_run_every_test(runner, monkeypatch, tmp_path, capsys):
    world = World()
    names = {f"t{index}": "lxd/standalone" for index in range(6)}
    install(runner, monkeypatch, tmp_path, world, names)
    world.broken = {("Slot", 1)}
    world.pending_broken = 1
    world.wait_for_broken = True
    code, summary = run(runner, tmp_path)
    assert {test["status"] for test in summary["tests"]} == {"pass"}
    assert sorted(name for _slot, name in world.ran) == sorted(names)
    assert 1 not in {slot for slot, _name in world.ran}
    # Every test ran and passed, so the run passes. The slot that did not start stays visible.
    assert code == 0
    assert summary["slots_not_started"] == [{"slot": 1, "error": "RunError: no address for sbx-1"}]
    out = capsys.readouterr().out
    assert "WARNING slot 1 did not start" in out
    assert sorted(world.cleaned) == [1, 2, 3]


def test_no_standalone_slot_starts_the_tests_are_errors(runner, monkeypatch, tmp_path, capsys):
    world = World()
    install(runner, monkeypatch, tmp_path, world, {"t1": "lxd/standalone", "t2": "lxd/standalone", "c1": "lxd/cluster"})
    world.broken = {("Slot", 0)}
    code, summary = run(runner, tmp_path, slots=2)
    tests = by_name(summary)
    assert code == 2
    for name in ("t1", "t2"):
        assert tests[name]["status"] == "error"
        assert tests[name]["reason"].startswith("the sandbox did not start: slot 1: RunError: no address for sbx-1; slot 2: ")
    # The cluster test has its own slot, and that slot started.
    assert tests["c1"]["status"] == "pass"
    assert [slot["slot"] for slot in summary["slots_not_started"]] == [1, 2]
    assert "WARNING slot 2 did not start" in capsys.readouterr().out


def test_a_special_slot_does_not_start_only_its_tests_are_errors(runner, monkeypatch, tmp_path):
    """A cluster test runs only on the cluster slot. No standalone slot takes it over."""
    world = World()
    tests_in = {
        "t1": "lxd/standalone",
        "c1": "lxd/cluster",
        "c2": "lxd/cluster",
        "n1": "lxd/cluster-new",
        "m1": "lxd/multicluster",
        "o1": "lxd/ovn",
    }
    install(runner, monkeypatch, tmp_path, world, tests_in)
    world.broken = {("ClusterSlot", 0)}
    code, summary = run(runner, tmp_path)
    tests = by_name(summary)
    assert code == 2
    assert {name: test["status"] for name, test in tests.items()} == {
        "t1": "pass",
        "c1": "error",
        "c2": "error",
        "n1": "pass",
        "m1": "pass",
        "o1": "pass",
    }
    assert "the sandbox did not start: slot 2: RunError" in tests["c1"]["reason"]
    assert [slot["slot"] for slot in summary["slots_not_started"]] == [2]


def test_all_slots_start_no_warning(runner, monkeypatch, tmp_path, capsys):
    world = World()
    install(runner, monkeypatch, tmp_path, world, {"t1": "lxd/standalone", "c1": "lxd/cluster"})
    code, summary = run(runner, tmp_path)
    assert code == 0
    assert summary["slots_not_started"] == []
    assert "WARNING" not in capsys.readouterr().out
