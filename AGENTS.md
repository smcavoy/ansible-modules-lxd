<!--
Copyright (c) 2026, Sean McAvoy
GNU General Public License v3.0+ (see LICENSES/GPL-3.0-or-later.txt or https://www.gnu.org/licenses/gpl-3.0.txt)
SPDX-License-Identifier: GPL-3.0-or-later
-->

# AGENTS.md: smcavoy.lxd

A guide for people and coding agents who work in this repository. The Ansible collection `smcavoy.lxd` has 63 modules
for the LXD 6.10 REST API, with no Python dependency outside ansible-core. `CONTRIBUTING.md` explains how to send a
change.

## Layout

- `plugins/module_utils/_client.py`: the one HTTP client. Read retries on a new connection, a write never twice,
  ETag with `If-Match`, operation waits in 60 s slices until `timeout`, streamed files (`download_to`,
  `ChainedReader`). `LXDClientError` has `status`, `operation`, `outcome_unknown` and `detail`.
- `plugins/module_utils/_module.py`: `LXDModule`, the base of every module. Check mode, diff, one second run after
  a 412 or an "already exists" race, client notes as warnings, `http_log` at `-vvvv`.
- `_resource.py` (plan and diff of plain objects), `_config.py` (config values and merge modes), `_backup.py`,
  `_info.py`, `_time.py`, `_cluster.py`.
- `plugins/modules/`: one file per module. `plugins/doc_fragments/`: the shared options.
- `tests/unit/plugins/module_utils/`: client tests against a fake connection (`FakeServer`, `EarlyAnswer`,
  `FakeClock`).
- `tests/unit/plugins/modules/`: modules through `main()` against the in-memory LXD in `fake_lxd.py`
  (`conftest.py` wires it into `LXDClient._exchange`). Extend the fake when a module needs more of the API; do not
  mock single calls in a test.
- `tests/integration/targets/<target>/`: `tasks/main.yml` starts with a one-line `# Goal:` that `lxdtest` reads.
  `aliases` names the fixture (`lxd/standalone`, `lxd/cluster`, `lxd/cluster-new`, `lxd/multicluster`, `lxd/ovn`,
  `lxd/ceph`) and `unsupported`. Fault targets: `lxd_fault_network`, `lxd_fault_server`, `lxd_create_race`.
- `tests/scenarios/`: playbooks that use many modules together.
- `tests/lxd/lxdtest`: the runner of the integration suite (sandbox VMs, slots, the run lock). `tests/lxd/sandbox/`:
  the sandbox image recipe; `root-gib` is the root disk size.
- `ci/`: `run-fast.sh` (the fast checks), `run-smoke.sh`, `run-lxd.sh`, `bootstrap.py` (sets up a test project and
  the runner on an LXD server), `lxd_remote.py` (drives `lxdtest` in the runner through the LXD API),
  `requirements-fast.txt` (pins).
- `changelogs/fragments/` (one fragment per user-visible change), `docs/design/` (plan and specs).

## How to run the checks

- The fast checks need no LXD server: `ci/run-fast.sh`. They run lint, docs, licences, build, sanity and unit tests.
  GitHub Actions runs them on each pull request (`.github/workflows/fast.yml`): Python 3.11 with ansible-core 2.19,
  3.12 with 2.20 and 2.21, 3.13 with 2.22, and ansible-core devel as a job that can fail.
- `ansible-test` needs the tree at `.../ansible_collections/smcavoy/lxd`. Unit tests alone:
  `ansible-test units --venv --python 3.13`.
- Lint as CI does: `nox` from `antsibull-nox.toml`, or ruff with `--config ruff.toml` from a folder that holds
  `ansible_collections/`. Ruff run from the repository root reports false I001 import-order errors.
- `nox -e lint` reformats files on your machine. CI only checks the format (`ruff format --check`), so commit what
  the formatter changed.
- Line limit 160 for Python (ruff) and YAML (yamllint), changelog fragments included.
- The integration suite needs an LXD server that can run nested virtual machines. `ci/bootstrap.py` sets up a test
  project and a runner container there; `LXD_CI_URL`, `LXD_CI_PROJECT`, `LXD_CI_SERVER_CERT`, `LXD_CI_CLIENT_CERT`
  and `LXD_CI_CLIENT_KEY` tell the scripts how to reach it. It does not run in GitHub Actions. The maintainer runs
  it before a merge that changes modules or tests, and before a release.
- To run one target by hand, copy `tests/integration/integration_config.yml.template` to
  `tests/integration/integration_config.yml`, set the values, and use
  `ansible-test integration --allow-unsupported --local <target>`. Use a server that holds nothing you need: the
  targets create and delete objects.

## Rules

- Every fix ships with a test that fails on the old code. Run the new test against the old code to prove it.
- Check an LXD behaviour on a live server before you code around it (a curl or a short playbook).
- A user-visible change gets a changelog fragment.
- Each new `ansible.builtin.uri` read in an integration target gets `retries: 3`, `delay: 2` and
  `until: <var> is not failed`: a busy test server can reset a connection. An assert must be able to fail: no
  `when` that can skip it.
- Never put a key, a token, a host name or an address of a real server in the repository. Use the names of the CI
  variables and example values (`lxd.example.org`, `192.0.2.10`).
- ansible-core 2.22 masks secrets on the controller. In a unit test the raw module output holds `invocation` and a
  `no_log` return value as they are, and names the secrets in `_ansible_new_secrets`.

## LXD 6.10.1 behaviour that the code depends on

- An expired `/operations/<id>/wait` slice answers HTTP 500 "context deadline exceeded"; the operation still runs.
- LXD keeps a finished operation only a short time; after a restart it knows none. The wait then gets 404.
- During its shutdown LXD answers HTTP 500 "... sql: database is closed".
- A command of `lxd_instance_exec` runs on in the instance when LXD restarts. A new run of the task runs it twice.
- LXD can answer an upload (403 on a file it cannot overwrite, 500 on a full disk) before it reads the body and
  then reset the connection. The answer is still readable; `_exchange` reads it.
- LXD cannot overwrite a file that root in the instance does not own when the mode gives no write to others;
  `lxd_instance_file` deletes it and writes it again.
- The `fingerprint` field of an instance source also takes an alias.
- The project limit `limits.disk` counts the configured disk sizes, not use. A VM root disk cannot be smaller
  than its image.
- On a full btrfs pool, exec fails (LXD cannot record the output) and so can a delete; grow the pool instead.
- A `PUT` of a network or a storage pool with `?target=<member>` replaces the whole config, the global keys too.
  Send the config of the member view with the new member-specific keys.
- The automatic cluster roles are `database-voter`, `database-standby` and `database-leader`. The evacuation modes
  are `stop`, `migrate` and `live-migrate`; LXD refuses any other name.
- A file `POST` for a directory that exists answers success and changes nothing. LXD does not replace a link, does
  not set the owner or mode of a link, and drops the setuid, setgid and sticky bits. A `GET` of a link returns its
  target as an absolute path.
- LXD stores ACL rules, forward ports and load balancer backends without spaces in their lists, and IP addresses in
  the canonical form. It returns the URL of a project entity in a permission with `?project=default`.
- A bearer identity keeps the type `Client token bearer` after its token expires; read `expires_at`. Expiry units
  are `S`, `M`, `H`, `d`, `w`, `m`, `y` (`1h` is not valid).
- An image update ignores the zero time in `expires_at`, so the expiry date of an image cannot go away. A snapshot
  create without `expires_at` uses `snapshots.expiry`; the zero time means "never".
- Only custom, container and virtual-machine volumes have a `/state`; an image volume answers 400.
- A restart of a frozen instance without `force` fails ("Instance is not running"); unfreeze it first.
- A failed `HEAD` has no body; the same path as a `GET` gives the error text.
- The listen address `0.0.0.0` or `::` of a network forward means "allocate an address"; a bridge refuses that.
- A `GET` of one instance with `all-projects=true` answers 400; the list with `all-projects=true` and a filter works.
  The filter ignores the case of the value.
- LXD does not delete a cluster group that has members or that is in use (`used_by`: a project with
  `restricted.cluster.groups`, an instance placed with `target=@group`).
- LXD returns the proxy URL of `core.proxy_http` and `core.proxy_https` with its password.
