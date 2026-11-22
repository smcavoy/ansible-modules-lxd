# LXD collection testing framework

Status: design for agents that build the framework and write tests.
Read first: the development guide (`01-ansible-module-development-guide.md`) and the module plan (`02-lxd-module-plan.md`).

## 1. Goals

1. Test every module end to end against a real LXD 6.10.1 server.
2. Give each test one simple, stated goal.
3. Make each run repeatable. A run starts from a clean state and leaves nothing behind.
4. Make results clear. Each target gives one line: pass, fail, skip, or error.
5. Run many tests in parallel.
6. Build a cluster when a test needs one. Test on it. Then delete it.
7. List every test that the hardware cannot support, with the reason.

## 2. Design decisions

| Decision | Reason |
|---|---|
| Use `ansible-test integration` targets. | It is the standard for collections. Sanity tests check the targets. Results come as JUnit. |
| Run every test against a nested LXD server in a VM, never against the host LXD. | Tests change global things: networks, pools, server config. A VM per slot isolates them. |
| Use one VM per parallel slot, from a prebuilt image. | Each slot has its own LXD. Names cannot clash. A sandbox is ready in 30 to 39 seconds. |
| Run the controller in a container on the test server. | The nested servers are on a private bridge. The controller must reach them. |
| Fixtures use the `lxc` CLI and `ansible.builtin.uri`, not the modules under test. | A broken module must not break the fixture for other tests. |
| A small Python runner schedules targets on slots. | `ansible-test` runs targets one at a time. The runner adds parallel slots. |

## 3. Test layers

| Layer | Tool | Where | Needs LXD |
|---|---|---|---|
| Sanity | `ansible-test sanity --docker` | Any machine with Docker | No |
| Unit | `ansible-test units --docker` | Any machine with Docker | No |
| Integration | `ansible-test integration` through the runner | The runner container on `<test-server>` | Yes |
| Scenario | `ansible-playbook` through the runner | The runner container | Yes |

Sanity and unit tests run on every change. Integration tests and scenarios run before each merge and on a release tag.
A scenario uses many modules together, as a user does. The scenarios are in `tests/scenarios/`.

## 4. The test server

The table shows the server that the full LXD suite runs on.

| Item | Value |
|---|---|
| Host | `<test-server>`, on a private network |
| CPU | 12 threads |
| Memory | 62 GiB |
| KVM | `/dev/kvm` exists. Nested KVM is on (`kvm_amd nested=1`). |
| LXD | 6.10.1 LTS snap, channel `6/stable`, standalone |
| Storage | Pool `default`, ZFS, about 388 GiB |
| Network | `lxdbr0`, NAT |
| API | `https://<test-server>:8443`, in the CI variable `LXD_CI_URL` |

Limits:

- Automation uses the LXD API only. It never needs root on the host.
- The host LXD stays unchanged except for the test project (the CI variable `LXD_CI_PROJECT` names it), the `lxdtestbr0` bridge, and restricted client certificates.
- Never delete or change the `default` pool, `lxdbr0`, or the server config on the host.
- LXD runs `zpool destroy` when it deletes a ZFS pool that uses a whole pool name. Never point a test pool at a host ZFS pool.

## 5. Infrastructure layout

```text
<test-server> (host LXD 6.10.1)
  network lxdtestbr0        private /24 subnet, NAT, default project
  project <LXD_CI_PROJECT>  features.images/profiles/storage.volumes/storage.buckets = true, not restricted
    image  sandbox/6.10.1              Ubuntu 26.04 VM + LXD snap, pinned revision, 20 GiB root
    ct     lxdtest-runner              controller: ansible-core, ansible-test, lxc client, runner
    vm     sbx-<run>-<n>               one standalone LXD per slot
    vm     cls-<run>-<n>               cluster members, 3 VMs
    vm     ceph-<run>                  MicroCeph, only for Ceph targets
    vm     dr-<run>-<n>                second cluster, only for cluster links and replicators
```

Inside each nested VM:

- LXD listens on `[::]:8443`.
- LXD makes its own server certificate on first start. The SAN holds the VM name, `127.0.0.1`, and `::1`. It does not hold the VM address.
- The runner connects by VM name, for example `https://sbx-ab12-1:8443`. The DNS server of `lxdtestbr0` resolves the name.
- The runner's client certificate is in the trust store.
- The storage pool `default` uses `dir` on the VM disk.
- The bridge `lxdbr0` uses `10.99.0.1/24`. It is private to the VM.
- The VM has a second NIC on `lxdtestbr0` for `macvlan` and `physical` network tests.

### 5.1 Runner container

- Name `lxdtest-runner`, Ubuntu 26.04, 4 vCPU, 4 GiB.
  `ci/bootstrap.py` sets these limits with `--runner-cpu` and `--runner-memory`. It also changes them on a runner that exists.
  A runner with 1 vCPU and 2 GiB is too small. Slow TLS handshakes on such a runner caused connection resets (see section 10.2).
- Contains Python, `ansible-core` at the pinned version, `community.internal_test_tools`, the `lxc` client, and the runner.
- The tested versions are Python 3.14.4 and `ansible-core` 2.20.11 in `/opt/venv`. Pin these versions.
- Uses the host LXD over HTTPS at the URL in `LXD_CI_URL`, with a restricted client certificate. The certificate gives access to the test project only.
- Has no `proxy` device to the host socket. A restricted certificate can do all fixture work in its project.
- Holds the image cache in `/srv/lxdtest/images`.
- Holds the client certificate for the nested servers in `/srv/lxdtest/pki`.

### 5.2 Sandbox image

The runner builds the image `sandbox/<lxd version>` once per LXD version.

Build steps:

1. Launch `ubuntu:26.04` as a VM with 2 vCPU, 3 GiB, and `-d root,size=20GiB`.
2. Install the `lxd` snap from channel `6/stable`. Hold refreshes.
3. Copy in the standalone preseed, the runner's client certificate, the first-boot script, and its systemd unit.
4. Record the LXD snap revision in `/etc/lxdtest-version`.
5. Check that `server.crt` and `server.key` do not exist in `/var/snap/lxd/common/lxd/`. Delete them if they exist.
6. Run `cloud-init clean --logs --machine-id`.
7. Stop the VM. Publish it to the host remote, for example `lxc publish <remote>:<vm> <remote>: --alias sandbox/6.10.1`. Delete the VM.

The LXD daemon starts on socket activation. It does not start during the build. So the image holds no certificate and no database.
Fixtures install `microovn` and `microceph` only when they need them. Each install takes about 25 seconds.

The first-boot unit `lxd-sandbox-init.service` runs once, after `snap.lxd.daemon.socket` and the network:

1. It reads `user.sandbox.mode` through the LXD guest API at `/dev/lxd/sock`.
2. With no value, it runs `lxd init --preseed` with the standalone preseed.
3. With the value `cluster`, it sets only `core.https_address`. The cluster fixture does the rest.
4. It trusts the runner's client certificate.
5. It writes a marker file, so it does not run again.

Each VM makes its own server certificate on first start. The SAN holds the VM name, not the VM address.
So `lxd_url` uses the VM name. Then `ca_path` verification works. With the IP address, verification fails with "IP address mismatch".

Launch the image with `--vm -d root,size=20GiB`. The image keeps its 20 GiB root disk, but the default volume size is 10 GiB.
Without the option, the launch can fail with "Source image size ... exceeds specified volume size".

The runner does not check the LXD version of the image. The image name holds a hash of the recipe and the snap channels (`ci/lxd_remote.py`, `sandbox_alias`).
The hash also holds the month (`LXD_CI_IMAGE_PERIOD`). So the first full run of each month builds a new image with the current snap revisions. The build takes 10 to 30 minutes.
The recipe stops the build when MicroCeph is not a known good version (`tests/lxd/sandbox/prepare.sh`). When a bootstrap fails in the image build, look at this check first. A move of `tentacle/stable` to Ceph 20.2.4 trips it.

### 5.3 Test images inside sandboxes

Downloads are slow and change over time. The runner keeps pinned copies.

| Alias in the sandbox | Source | Size, estimate |
|---|---|---|
| `test/alpine-ct` | `images:alpine/3.22`, container | about 3 MiB |
| `test/alpine-vm` | `images:alpine/3.22`, VM | about 130 MiB |
| `test/busybox-ct` | `images:busybox/1.36.1`, container | about 1 MiB |

All three aliases exist on the `images:` server. A check on 2026-11-03 found them. Record the real sizes on the first run.

Alpine VMs need `boot.mode=uefi-nosecureboot`. LXD 6.10 has no `security.secureboot` key. The Alpine image does not support secure boot.

The `setup_lxd_images` role uploads them to a sandbox with `ansible.builtin.uri`.
A split image goes up as `multipart/form-data` with the parts `metadata` and `rootfs`.
The fingerprints are in `tests/lxd/images.yml`. Update them only on purpose.
Tests of image registries use the network. They have the alias `lxd/needs/internet`.

## 6. Fixtures

A fixture is a set of nested LXD servers. The runner builds a fixture only if a selected target needs it.

| Fixture | Contents | Build time | vCPU | RAM | Used by |
|---|---|---|---|---|---|
| `standalone` | 1 sandbox VM per slot | 30 to 39 s | 2 per slot | 3 GiB per slot | Most targets |
| `cluster` | 3 VMs, one cluster | about 52 s | 3 | 6 GiB | Targets with `lxd/cluster` |
| `microcloud` | 3 VMs with MicroCloud: LXD, MicroCeph, and MicroOVN | about 2.5 minutes, plus the wait for the cluster slots | 6 | 18 GiB | Targets with `lxd/ovn` or `lxd/ceph` |
| `multicluster` | 2 VMs, each a cluster of 1 member | about 53 s | 2 | 4 GiB | Targets with `lxd/multicluster` |
| `cluster-new` | 3 standalone VMs in cluster mode, not formed into a cluster | about 50 s, after the `cluster` slot ends | 3 | 6 GiB | Targets with `lxd/cluster-new`, which form the cluster themselves (`lxd_cluster`) |

The times are measured values, with a warm image cache. The first pull of the `ubuntu:26.04` VM image (819 MiB) is slow.

The runner builds `standalone` and `cluster`. The cluster time is from one measured run.

Each cluster member has 1 vCPU and 2 GiB. With a cluster slot, the runner keeps at most 2 standalone slots.
The run then uses 7 instances, 8 vCPU, and 14 GiB, with the runner and the lock.
The limits of the CI project are 12 instances, 24 vCPU, and 48 GiB.
The `cluster-new` slot waits for the `cluster` slot and deletes its members first, so the two never run at the same time.
The fixture forms the cluster with `lxc` inside the members. It also makes empty directories `/srv/pools/p1` to `p3` on each member for pool sources.

The `cluster` time is 46 s to first boot and 15 s to form the cluster. The pool and the network add some seconds.
The `ceph` fixture builds the MicroCeph VM at the same time as the cluster. That VM was ready for LXD in about 100 s.
The runner also builds `multicluster`. It runs next to the other slots, in its own slot.
Each server starts with the preseed, so it has the pool `default` and the network `lxdbr0`. Then the slot runs `lxc cluster enable` on each server.
Cluster A is the main server of the tests. The config gives cluster B as `lxd_peer_url`, `lxd_peer_server_cert`, `lxd_peer_ip`, and `lxd_peer_name`.
The test client certificate is trusted on both clusters.
A run with all three fixtures uses 9 instances, 10 vCPU, and 18 GiB.

One `microcloud` fixture serves both `lxd/ovn` and `lxd/ceph`. It replaces the planned `cluster_ovn` and `ceph` fixtures.
It uses the snaps of the MicroCloud 3.4 LTS bundle: `lxd` 6/stable, `microceph` tentacle/stable, `microovn` 26.03/stable, and `microcloud` 3/stable.
The sandbox image holds these snaps with their services off. A member with `user.sandbox.mode=microcloud` starts them on first boot.
The image build stops when MicroCeph is 19.2.6, 20.2.4, or newer, because the Ceph tools of the LXD 6.10 snap do not work with those.
Each member has 2 vCPU, 6 GiB, a root disk of 20 GiB, and a block volume of 8 GiB for one Ceph OSD.
The OVN uplink is the VLAN interface `uplink0` (VLAN 1000) on the NIC of each member, without an address.
LXD refuses a second NIC on the same managed bridge, with `Instance DNS name ... conflict`.
The members share the VLAN through the CI bridge. The uplink subnet is `10.251.0.0/24` with the range `.100` to `.199`. It has no real gateway.
So OVN takes no addresses on the CI subnet. The tests need only traffic inside OVN.
The members run `microcloud preseed` at the same time.
The config gives `lxd_ceph_pool` (`remote`), `lxd_ovn_uplink` (`UPLINK`), `lxd_ovn_network` (`default`), and `lxd_rgw_endpoint`.
The fixture enables the RADOS gateway on the first member for the `cephobject` pools of the bucket tests.
In one measured run, the members booted in 47 s, MicroCloud formed in 130 s, and the RADOS gateway was ready at 149 s.
With all fixtures, a run needs about 19 vCPU and 38 GiB. The project limit is 24 CPUs. When the limit is too small, the MicroCloud slot waits for the cluster slots and deletes their servers first.

A test can put an LXD fact into the CI job log, also when it passes. It prints a line with `LXDTEST-FACT`, for example with `ansible.builtin.debug`.
The CI client prints these lines after the run. Use it for probes of API behavior that a module does not use yet.

The LXD `6.10` snap ships Ceph tools that do not work with Ceph `19.2.6`, `20.2.4`, or newer.
Pin the MicroCeph channel to an older Ceph release. See the known issues in the LXD `6.10.0` release notes.

Channel `squid/stable` with Ceph 19.2.3 works. Use this channel.
Make 3 loop OSDs with `microceph disk add loop,4G,3`. Ceph showed `HEALTH_OK` about 45 s after the bootstrap.

MicroOVN 26.03.0 from `latest/stable` works.
LXD finds MicroOVN and MicroCeph by itself through snap interfaces. Do not set `network.ovn.northbound_connection`.

### 6.1 Cluster build

The `setup_lxd_cluster` fixture role does these steps. It follows the Terraform provider CI script.

1. Launch 3 VMs from the sandbox image with `-c user.sandbox.mode=cluster`. The first-boot unit then skips the standalone preseed.
2. On member 1, set `core.https_address` and `cluster.https_address` to `<address>:8443`. Then run `lxc cluster enable <name>`.
3. For each other member, get a join token with `lxc cluster add <name> --quiet` on member 1.
4. On each other member, unset `core.https_address`. Then run `lxd init --preseed` with `cluster.enabled: true`, `server_name`, `server_address`, and `cluster_token`.
5. Wait until `lxc cluster list` shows all members `ONLINE`.
6. Create the pool `default` (`dir`) and the network `lxdbr0` with the pending-then-global flow.
7. Write the member names and addresses to the slot's `integration_config.yml`.

The client certificate that member 1 trusts stays trusted on the whole cluster.
No test shows whether step 4 must unset `core.https_address`.

Open item: the first cluster tests used `validate_certs: false`. Test `ca_path` verification with the cluster certificate before the first cluster target.

### 6.2 Cluster teardown

1. Delete the VMs. Do not evacuate or leave the cluster first. A forced delete of 3 VMs at the same time took 3 seconds.
2. Check that no VM with the run ID remains.

The `lxd_cluster` target is special. It tests cluster formation itself.
It gets 3 fresh, unclustered VMs from the runner. It forms, changes, and removes the cluster with the modules.

### 6.3 Fixture rules

- A fixture never uses a module from the collection under test.
- Close stdin for every scripted `lxc` call, for example with `</dev/null`. Without a terminal, `lxc` waits to read YAML from stdin. It then looks like a hung server.
- Give every `lxc` call and every API call a time limit and one retry. An early nested launch hung for more than 8 minutes. The stdin problem probably caused it.
- Give `lxc publish` the target remote. Without it, the CLI publishes to the local client and fails.
- A fixture fails fast with a clear message, for example "member cls-ab12-2 did not join in 300 s".
- If a fixture fails, its targets report `error`, not `fail`.

## 7. Parallel execution

### 7.1 Slots

A slot is one nested LXD server, or one fixture, plus one copy of the collection.
Each slot runs its targets one after another. Slots run at the same time.

Default capacity on the test server:

| Item | vCPU | RAM |
|---|---|---|
| Runner container | 4 | 4 GiB |
| 4 standalone slots | 8 | 12 GiB |
| 1 cluster-type fixture | 6 to 8 | 9 to 13 GiB |
| Total | 18 to 20 | 25 to 29 GiB |

Some CPU overcommit is safe, because the VMs are idle most of the time.
Memory is the hard limit. Keep the total under 48 GiB.
Use `--slots` to change the number of standalone slots. The default is 4. With the cluster fixture, the run uses at most 2.

### 7.2 Schedule

1. Read the selected targets and their aliases.
2. Put each target in the queue for its fixture.
3. Start the standalone slots and the needed fixtures at the same time.
4. Each standalone slot takes the next target from the shared standalone queue.
5. Each cluster-type fixture runs its own queue, one target at a time.
6. Run at most one cluster-type fixture at a time. This keeps memory under the limit.
7. Run the longest targets first. Read the durations from the last run.

Cluster targets run one at a time on their fixture. They change global resources, such as server config and pools.

### 7.3 Per-slot collection copy

`ansible-test` passes only a few environment variables to the playbook, for example `PATH` and `HOME`.
So each slot gets its own copy of the collection:

```text
/srv/lxdtest/work/<run>/slot-<n>/ansible_collections/smcavoy/lxd/
```

The runner writes `tests/integration/integration_config.yml` in each copy:

```yaml
lxd_url: https://sbx-ab12-1:8443
lxd_client_cert: /srv/lxdtest/pki/client.crt
lxd_client_key: /srv/lxdtest/pki/client.key
lxd_server_cert: /srv/lxdtest/work/ab12/slot-1/server.crt
lxd_run_id: ab12
lxd_slot: 1
lxd_fixture: standalone
lxd_members: []
```

Targets read only these variables. They never read the environment.
`tests/integration/integration_config.yml.template` lists every variable of a standalone slot with a comment, for a run by hand.

Each slot also has its own `HOME`, for example `/srv/lxdtest/work/<run>/slot-<n>/home`.
`ansible-test` makes an SSH key in `~/.ansible/test/id_rsa`. With a shared `HOME`, parallel runs race on this file, and one run fails.
A test ran 4 slots, each with its own `HOME`. All passed, each with its own JUnit file.

### 7.4 Command per target

```bash
HOME=/srv/lxdtest/work/ab12/slot-1/home ansible-test integration --allow-unsupported --local --python 3.14 --color no lxd_network
```

The runner starts this command in the slot's collection directory.
With `--include-unstable`, the runner adds `--allow-unstable`. Without it, `ansible-test` skips `unstable` targets.
The `--python` version must be one that the pinned ansible-core supports on the controller.

A test ran `ansible-core` `2.20.11` on Python `3.14`. A small target took 2 to 4 seconds.
`ansible-test` warns "Unable to determine context for the following test targets". This warning is harmless here.

Each test has the time limit of `--timeout`. The default is 20 minutes. The runner does not read the `lxd/timeout/<minutes>` alias yet.
Each test runs in its own process group. On a time limit, the runner stops the whole group, so that no playbook goes on against the sandbox.

## 8. Target layout

```text
tests/integration/targets/
  setup_lxd_connection/       # sets module_defaults for the group
  setup_lxd_images/           # uploads pinned test images
  setup_lxd_project/          # creates the per-target project
  setup_lxd_cluster/          # fixture role, used by the runner
  lxd_network/
    aliases
    meta/main.yml             # dependencies on setup_* roles
    tasks/main.yml
    tasks/bridge.yml
    tasks/ovn.yml
```

### 8.1 Aliases

Every target has these lines in `aliases`:

```text
unsupported
lxd/standalone
```

| Alias | Meaning |
|---|---|
| `unsupported` | Public CI cannot run it. Required, so the sanity test accepts the target. |
| `lxd/standalone`, `lxd/cluster`, `lxd/cluster-new`, `lxd/ovn`, `lxd/ceph`, `lxd/multicluster` | The fixture. Exactly one. |
| `lxd/needs/vm` | Starts a VM inside the sandbox. |
| `lxd/needs/internet` | Downloads from a public image server. |
| `lxd/timeout/<minutes>` | Planned. A time limit for the target. The runner does not read it yet. |
| `lxd/hardware/<item>` | Needs hardware that the server does not have. The runner skips it. |
| `unstable` | The test fails at times. Fix it soon. The runner reports it apart. `ansible-test` skips it without `--allow-unstable`. |

`unsupported`, `unstable`, `disabled`, and `destructive` are `ansible-test` aliases. The `lxd/` aliases belong to the runner.

### 8.2 The first lines of the task file

The first line states the goal. The runner prints it in the summary.

```yaml
# Goal: lxd_network creates, changes, and removes bridge networks idempotently, with check and diff mode.
- name: Run the lxd_network tests
  module_defaults:
    group/smcavoy.lxd.lxd:
      url: "{{ lxd_url }}"
      client_cert: "{{ lxd_client_cert }}"
      client_key: "{{ lxd_client_key }}"
      server_cert: "{{ lxd_server_cert }}"
  block:
    - name: Include the bridge tests
      ansible.builtin.include_tasks: bridge.yml
  always:
    - name: Remove all test resources
      ansible.builtin.include_tasks: cleanup.yml
```

### 8.3 Names

- Every resource name starts with `t-{{ lxd_run_id }}-`.
- Bridge names have a 15-character limit. Use `tb{{ lxd_run_id }}{{ n }}` for them.
- For project-scoped resources, each target uses the project `t-{{ lxd_run_id }}-<target>`.
- `setup_lxd_project` creates it with `features.profiles` and `features.storage.volumes` on, and `features.images` off. Then the pinned images are visible.
- Targets that test images create their own project with `features.images` on.
- Only OVN networks can live in a project other than `default`. Bridge, macvlan, sriov, and physical networks use the `default` project.
- Storage pools, image registries, cluster objects, and server config do not belong to a project. Use run ID names for them.

## 9. Standard test cases

Every resource module target covers these cases, in this order.
Each case has one goal. Each case ends with one `ansible.builtin.assert` task.
Name the tasks `<case id>: <goal>`, so the log reads like a checklist.

| ID | Goal | Steps | Pass when |
|---|---|---|---|
| C1 | Check mode predicts a create. | Run with `state: present` in check mode. | `changed` is true. The info module shows no resource. |
| C2 | The module creates the resource. | Run with `state: present`. | `changed` is true. The returned values match the input. |
| C3 | A second run makes no change. | Run C2 again. | `changed` is false. |
| C4 | Check mode predicts an update. | Change one option in check mode. | `changed` is true. The diff shows only that option. The server keeps the old value. |
| C5 | The module updates one option. | Run C4 without check mode. | `changed` is true. The info module shows the new value. |
| C6 | `merge` keeps keys that other tools set. | Set a key with the API. Run the task without the key. | `changed` is false. The key stays. |
| C7 | `exact` removes unmanaged keys. | Run with `config_mode: exact`. | `changed` is true. The server no longer has the key. Computed keys stay. |
| C8 | `null` removes one key. | Set the key's value to `null`. | `changed` is true. The server no longer has the key. |
| C9 | Bad input fails with a clear message. | Run with one invalid value, with `ignore_errors: true`. | The result `is failed`. `msg` holds the expected text. |
| C10 | Check mode predicts a delete. | Run with `state: absent` in check mode. | `changed` is true. The resource still exists. |
| C11 | The module deletes the resource. | Run with `state: absent`. | `changed` is true. The info module shows no resource. |
| C12 | A second delete makes no change. | Run C11 again. | `changed` is false. |

Skip C6, C7, and C8 for resources without `config`.
Info modules have their own cases:

| ID | Goal | Pass when |
|---|---|---|
| I1 | List all resources. | The test resources are in the list. |
| I2 | Get one resource by name. | Exactly one result with the right name. |
| I3 | Ask for a missing name. | The result is an empty list. `changed` is false. The module does not fail. |
| I4 | Run in check mode. | The same result as I1. `changed` is false. |

Module specs add cases for their own features. Examples: instance state changes, `wait_for`, `member_config`, snapshots restore.

### 9.1 Rules for assertions

- Check only the values that the case changed.
- Check the server with the info module or `ansible.builtin.uri`, not only with the module result.
- Give each registered variable a unique name, for example `c5_update_result`.
- Use `fail_msg` to show the expected value and the returned value.
- Do not use `ignore_errors` except in error cases.
- Read a key with dots by item access, for example `config['bgp.ipv4.nexthop']`. `map(attribute='a.b')` reads the dots as nesting.
  For a list of results, use `map('dict2items') | flatten | selectattr('key', 'eq', 'a.b')`.
- Ansible does not template dictionary keys in task arguments. Build a key from a variable with a Jinja dictionary,
  for example `member_config: "{{ {lxd_members[1]: {'core.metrics_address': '[::]:9100'}} }}"`.
- Quote an assertion that holds `: `, for example a dictionary literal. YAML reads it as a mapping otherwise.
- Ansible marks a result with a non-zero `rc` as failed, unless the result says `failed: false`.

### 9.2 Cleanup

- Put all deletes in the `always:` block.
- Delete in reverse order of creation: instances, then volumes, then profiles, then networks, then pools, then projects.
- Cleanup tasks use `failed_when: false`. They must not hide the real failure.
- The runner deletes the sandbox VM after the run, so cleanup errors cannot leak to other runs.

## 10. The runner

The runner is `tests/lxd/lxdtest`, a Python 3 script that uses the standard library only.

### 10.1 Commands

The runner has two commands now: `run` and `gc`. Start it with `python3 tests/lxd/lxdtest`. The CI client does this in the runner container.

```bash
python3 tests/lxd/lxdtest run --slots 4 lxd_network lxd_profile
```

```bash
python3 tests/lxd/lxdtest gc --older-than 6h
```

- `run` with no names runs every target and scenario. An unknown name stops the run with exit code 2. A run with no test to run also exits with 2.
- After it takes the lock, `run` stops processes of earlier runs in the runner. It also deletes sandboxes and work directories that are older than 6 hours.
- A test that the runner could not run, for example after an error in the runner itself, gets the status `error`. It never stays `skip`.
- A slot whose sandbox does not start takes no test. The other standalone slots run its tests, and the run ends with a `WARNING` line and
  the slot in `slots_not_started` of `summary.json`. The run passes when every test passed. Only when no slot of a fixture started do its
  tests get the status `error` with the reason `the sandbox did not start`. A special fixture (cluster, multicluster, MicroCloud) has one slot.
- The runner retries only reads and forced deletes. A write such as `launch` gets no retry. When a write fails, the runner checks whether LXD did the work anyway.
- A failed cleanup step is logged. The next steps, the lock release, and the report still run.

The commands below are the original design. They are not built.

```bash
lxdtest image build --lxd-channel 6/stable
```

```bash
lxdtest run --slots 4 lxd_network lxd_profile
```

```bash
lxdtest run --fixture cluster
```

```bash
lxdtest run --all --keep-on-failure
```

```bash
lxdtest list --all
```

```bash
lxdtest gc --older-than 6h
```

| Command | What it does |
|---|---|
| `image build` | Builds the sandbox image for the LXD channel. |
| `run` | Runs targets by name, by fixture, or all. |
| `list` | Shows targets with their goal, fixture, and exceptions. |
| `gc` | Deletes test VMs and work directories older than the limit. |

Options for `run`:

| Option | Default | Meaning |
|---|---|---|
| `--slots N` | 4 | Number of standalone slots. |
| `--keep-on-failure` | off | Keep the VMs of failed targets for debugging. `gc` removes them later. |
| `--include-unstable` | off | Run targets with `unstable`. Adds `--allow-unstable` to `ansible-test`. |
| `--offline` | off | Skip targets with `lxd/needs/internet`. |
| `--no-vm` | off | Skip targets with `lxd/needs/vm`. |

The runner never retries a failed target. A flaky test gets the `unstable` alias and an issue.

### 10.2 Run flow

1. Make a run ID of 4 random letters and digits.
2. Check the host, the image, the free memory, and leftovers from old runs.
3. Copy the collection into each slot directory.
4. Start the slots and fixtures.
5. Run the targets with the schedule from section 7.2.
6. Collect the JUnit files and logs.
7. Delete all VMs of the run, except kept ones.
8. Print the summary. Write `summary.json`. Exit.

During the run, a thread makes one TLS handshake to each sandbox every 5 seconds. It also measures the stalls of the runner.
Before the runner deletes a sandbox, it prints the handshake times and the TCP reset counters of the sandbox.
These `PROBE` lines show how close a run comes to the 3-second handshake limit of LXD.
Section 4.1 of the module plan explains the limit.

### 10.3 Trigger from a workstation or a CI job

`ci/lxd_remote.py` starts a run from any machine that reaches the LXD API of the host:

```bash
ci/run-lxd.sh lxd_network
```

The script pins the server certificate and pushes the collection to the runner with the files API.
Then it starts `lxdtest` with the exec API.
It prints the summary and the end of the log of each failed test. The CI jobs use the same script.

### 10.4 Run lock

The lock is a stopped container named `lxdtest-lock` in the test project. `lxdtest` takes it before a run and deletes it after the run.
A second run waits for the lock. A lock past its `user.lock.expires` time is stale, and the next run removes it.

In CI, `ci/bootstrap.py` takes the lock first and hands it to the runner with `--lock-owner`.

## 11. Results

### 11.1 Status of a target

| Status | Meaning |
|---|---|
| `pass` | All cases passed and cleanup ran. |
| `fail` | A test case failed. |
| `error` | The fixture or the runner failed. The run did not test the module. |
| `skip` | The target needs hardware or an option that this run does not have. The reason is in the summary. |
| `timeout` | The target ran longer than its limit. |

### 11.2 Summary

The runner prints one line per target, then the totals:

```text
RUN ab12  LXD 6.10.1 (snap rev 41228)  ansible-core 2.20.11  slots 4
PASS     lxd_network          2m10s  slot-2      lxd_network creates, changes, and removes bridge networks
PASS     lxd_profile          0m48s  slot-1      lxd_profile manages config and devices idempotently
FAIL     lxd_storage_pool     1m02s  slot-3      C7: exact removes unmanaged keys
SKIP     lxd_network (sriov)         hardware    needs an SR-IOV NIC
ERROR    lxd_storage_bucket          ceph        fixture ceph: OSD did not come up in 600 s
TOTAL 5  pass 2  fail 1  error 1  skip 1  time 9m31s
```

A failed line names the first failed case.

### 11.3 Files

```text
<results>/             # --results, default ci-results
  summary.json          # run id, counts, and one entry per test: kind, name, goal, status, reason, seconds
  junit.xml             # one test case per target or scenario
  logs/<kind>-<name>.log  # full output of each test
```

The design also had per-target JUnit files, fixture logs, and `versions.txt`. They are not built.

### 11.4 Exit codes

| Code | Meaning |
|---|---|
| 0 | All selected targets passed or skipped. |
| 1 | One or more targets failed or timed out. |
| 2 | An infrastructure error. No target result is valid. |
| 3 | Bad command line. |

## 12. Repeatability

- Pin the LXD snap revision in the sandbox image. Record it in `versions.txt`.
- Pin the test image fingerprints.
- Pin `ansible-core` and Python in the runner.
- Start each target on a clean sandbox or a clean project.
- Use the run ID in all names. Two runs can share the host.
- Delete everything at the end. `gc` removes anything left by a crash.
- A test must not depend on the order of other tests.
- A test must not depend on time of day or on the public internet, except targets with `lxd/needs/internet`.

## 13. Exceptions

The test server cannot test these features. Mark each target or task file with `lxd/hardware/<item>`.
The spec for each module must say how other tests cover the feature.

| Feature | Modules | Reason | Cover instead with |
|---|---|---|---|
| `sriov` networks and SR-IOV NICs | `lxd_network`, `lxd_instance` | No SR-IOV NIC. | Unit tests and the request payload. |
| `gpu` devices, CDI, MIG | `lxd_instance`, `lxd_profile` | No GPU. | Unit tests. Profile config tests without a start. |
| `pci` devices | `lxd_instance` | No spare PCI device for passthrough. | Unit tests. |
| `usb` devices | `lxd_instance` | No USB device to pass through. | Unit tests. Create the device on a stopped instance. |
| `infiniband` devices | `lxd_instance` | No InfiniBand hardware. | Unit tests. |
| Pure Storage driver | `lxd_storage_pool` | Needs a Pure FlashArray. | Unit tests. |
| Dell PowerFlex and PowerStore drivers | `lxd_storage_pool` | Needs Dell storage arrays. | Unit tests. |
| HPE Alletra driver | `lxd_storage_pool` | Needs an HPE Alletra array. | Unit tests. |
| Fibre Channel and NVMe over Fabrics | `lxd_storage_pool` | Needs a SAN. | Unit tests. |
| Ceph RBD mirroring for replicators | `lxd_replicator` | Needs two Ceph clusters. Too large for one host. | Replicator tests with `dir` pools. |
| ACME server certificates | `lxd_server_config` | Needs public DNS and port 80. | Config key tests only. |
| OIDC identities | `lxd_auth_identity`, `lxd_auth_identity_provider_group` | Needs an identity provider. LXD creates OIDC identities only at login. | Unit tests. Add an IdP fixture later if needed. |
| Changed block tracking | `lxd_storage_volume`, `lxd_instance_snapshot` | Feature preview. Must not be on in production LXD. | Out of scope. |
| Live migration of VMs between members | `lxd_instance`, `lxd_cluster_member` | Needs VMs inside VMs inside a cluster. Possible but slow. | Mark `lxd/needs/vm` and run each night only. |

Features that look like exceptions but are testable:

| Feature | How |
|---|---|
| `macvlan` and `physical` networks | Use the sandbox VM's second NIC as the parent. |
| `tpm` devices | The LXD snap includes `swtpm`. |
| `unix-char`, `unix-block`, `unix-hotplug` devices | Use `/dev/null` and loop devices in the sandbox. |
| `zfs`, `btrfs`, `lvm`, `dir` pools | Loop-backed pools in the sandbox. |
| `ceph`, `cephfs`, `cephobject` pools and buckets | The `ceph` fixture. |
| OVN networks, forwards, load balancers, peers | The `cluster_ovn` fixture. |
| VM instances | Nested KVM in the sandbox. |

## 14. One-time setup

The maintainer of the test server does these steps once. They change the host LXD, so an agent must ask before it runs them.

1. Create the `lxdtestbr0` bridge with a private /24 subnet and NAT.
2. Create the test project with separate images, profiles, storage volumes, and buckets.
3. Add a `default` profile in the test project with a root disk on pool `default` and a NIC on `lxdtestbr0`.
4. Create the `lxdtest-runner` container. Give it a restricted client certificate for the host, limited to the test project.
5. Install the runner software. Generate the client certificate for the nested servers.
6. Build the sandbox image with `lxdtest image build`.
7. Add an `lxc` remote for the host on each workstation, with a trust token.

`ci/bootstrap.py` does steps 4 to 6 for any project, and the CI jobs run it as their first step.

Facts about the restricted certificate:

- The runner uses a restricted client certificate, not a `proxy` device to the host socket.
- The host trusts the certificate only for the test project. A request for the `default` project fails with `Certificate is restricted`.
- A restricted certificate can do all fixture work. It can launch, publish, and delete VMs, images, and profiles.
- A restricted certificate can also attach a NIC on `lxdtestbr0` from the `default` project. It cannot see other projects.
- The `lxc` client uses only `client.crt` and `client.key`. It has no folder for a certificate per remote. So the host certificate is the default client certificate in the runner.

## 15. Safety rules

- Never run tests against the host LXD directly.
- Never change the host's `default` pool, `lxdbr0`, or server config.
- Create host objects only in the test project, except `lxdtestbr0`.
- Never print certificates, keys, or tokens in logs or summaries.
- Ask the maintainer of the test server before you change the one-time setup.
- Never widen a restricted certificate. Ask the maintainer of the test server.
- Run `lxdtest gc` after a crash.
