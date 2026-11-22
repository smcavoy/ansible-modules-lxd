# lxd_instance

## 1. Purpose

Create, configure, start, stop, and delete LXD containers and virtual machines.

## 2. API

| Path | Method | Response | Use |
|---|---|---|---|
| `/1.0/instances/{name}?recursion=1` | `GET` | sync, `ETag` | Read config and state. |
| `/1.0/instances` | `POST` | async | Create. `?target=` selects the member. |
| `/1.0/instances/{name}` | `PUT` | async, checks `If-Match` | Update config, devices, profiles, and description. |
| `/1.0/instances/{name}/state` | `PUT` | async | `start`, `stop`, `restart`, `freeze`, `unfreeze`. |
| `/1.0/instances/{name}` | `DELETE` | async | Delete. `?force=true` stops a running instance first. |

Required API extensions: `instances`. With `force` on delete: `instance_force_delete`.
A registry source needs `image_registries`. `wait_for` with `ready` needs `instance_ready_state`.

## 3. Identity

`name` and `project`. The module does not rename or move instances.

## 4. Options

| Option | Type | Default | Required | Rule |
|---|---|---|---|---|
| `name` | str | | yes | The instance name. |
| `project` | str | | no | The project. |
| `target` | str | | no | Create-only. A member, or `@<group>`. Rule R6. |
| `state` | str | `started` | no | `present`, `started`, `stopped`, `frozen`, `restarted`, or `absent`. |
| `type` | str | `container` | no | Create-only. `container` or `virtual-machine`. |
| `source` | dict | | no | Create-only. See the source table. |
| `profiles` | list | | no | The profile list. Order matters. `null` means "do not manage". `[]` means no profiles. |
| `config` | dict | | no | Rule R4. |
| `config_mode` | str | `merge` | no | Rule R4. |
| `devices` | dict | | no | Rule R5. Only instance devices, not profile devices. |
| `devices_mode` | str | `merge` | no | Rule R5. |
| `ephemeral` | bool | | no | `null` means "do not manage". |
| `description` | str | | no | `null` means "do not manage". |
| `instance_type` | str | | no | Create-only. A cloud instance type, for example `c2-m4`. |
| `force` | bool | `false` | no | Force a stop. With `state: absent`, delete a running instance in one call. |
| `stop_timeout` | int | `30` | no | Seconds for a clean stop. Then the module fails, unless `force` is true. |
| `allow_restart` | bool | `false` | no | Restart the instance when LXD cannot apply a change live. |
| `wait_for` | list of dict | | no | Conditions after a start. See the wait table. |
| `wait_timeout` | int | `300` | no | Seconds for all `wait_for` conditions. |

Source forms. `source` holds exactly one form:

| Form | Keys | Request `source` |
|---|---|---|
| Image | `image` (alias or fingerprint), optional `image_registry`, `project` | `type: image`, with `alias` or `fingerprint`. |
| Copy | `instance`, optional `snapshot`, `project`, `instance_only`, `refresh` | `type: copy`, `source: <name>` or `<name>/<snapshot>`. |
| Empty | `empty: true` | `type: none`. |
| Backup | `backup_path` on the controller, optional `pool` | No JSON. A binary `POST /1.0/instances` with the file, `X-LXD-name`, and `X-LXD-pool`. Then the module applies the managed fields like an update. Needs `container_backup` and `backup_override_name`, and `container_backup_override_pool` for `pool`. |

Without `image_registry`, an image source uses the local image store.

Wait conditions:

| Type | Pass when |
|---|---|
| `agent` | A VM agent answers. `state.processes` is 0 or more. Containers pass at once. |
| `ipv4` | A NIC, other than `lo`, has a global IPv4 address. Optional `nic` names the NIC. |
| `ipv6` | The same for a global IPv6 address. |
| `ready` | The instance status is `Ready`. The guest sets it through `/dev/lxd`. |
| `delay` | `seconds` passed. |

## 5. Computed keys

`volatile.*` and `image.*`.

## 6. Behavior per state

### `present`, `started`, `stopped`, `frozen`

| Case | Action |
|---|---|
| Absent | `POST /1.0/instances`. Then apply the state. `present` and `stopped` leave the new instance stopped. |
| Present, same config | No config request. |
| Present, different config | `PUT` with the full object: `config`, `devices`, `profiles`, `ephemeral`, `description`. |
| Present, wrong run state | `PUT .../state` with the action for the wanted state. |
| `type`, `source`, or `instance_type` differs on an existing instance | Warn and continue. Rule R10. |

`present` does not change the run state of an existing instance.
`started` on a frozen instance sends `unfreeze`. `frozen` on a stopped instance sends `start`, then `freeze`.
`stopped` sends `stop` with `timeout: stop_timeout`. If the stop fails and `force` is true, the module sends `stop` with `force: true`.

LXD applies most changes to a running instance live. For a VM, some keys fail with `Key ... cannot be updated when VM is running`.
With `allow_restart: true`, the module then stops the instance, sends the `PUT`, and starts it again.
Without it, the module fails and names the key.

### `restarted`

| Case | Action |
|---|---|
| Absent | Create, then start. |
| Present | Apply config changes, then send `restart`. Always `changed: true`. |

### `absent`

| Case | Action |
|---|---|
| Absent | No request. `changed: false`. |
| Present, stopped | `DELETE`. |
| Present, running | With `force: true`, `DELETE ?force=true`. Without it, `stop`, then `DELETE`. |

## 7. Check and diff mode

The diff holds `config`, `devices`, `profiles`, `ephemeral`, `description`, and `state`.
In check mode, `wait_for` does not run.

## 8. Return values

| Key | Type | Rule |
|---|---|---|
| `instance` | dict | The instance from `GET ?recursion=1`, after the change and after `wait_for`. `null` after a delete. |
| `addresses` | dict | NIC name to a list of global addresses, from `instance.state.network`. |
| `restarted` | bool | True when `allow_restart` caused a restart. |

```yaml
instance:
  name: web1
  type: container
  status: Running
  location: none
  profiles:
    - default
  config:
    limits.cpu: "2"
    image.os: Alpine
    volatile.base_image: 32cc6e69adc3...
  devices: {}
  ephemeral: false
  state:
    status: Running
    processes: 4
    network:
      eth0:
        addresses:
          - family: inet
            address: 10.99.0.12
            netmask: "24"
            scope: global
addresses:
  eth0:
    - 10.99.0.12
restarted: false
```

## 9. Errors

| Case | Message |
|---|---|
| Absent and no `source`. | `source is required to create instance <name>` |
| A change needs a restart, without `allow_restart`. | `LXD cannot apply <key> while the instance runs. Set allow_restart.` |
| `wait_for` does not pass in time. | `instance <name> did not reach <condition> in <n> seconds` |
| A stop does not finish in `stop_timeout`. | `instance <name> did not stop in <n> seconds. Set force to force the stop.` |
| A start on an evacuated member. | The LXD error `Cluster member is evacuated` |
| A start in a standby replica project. | The LXD error `Cannot start instances in a standby replica project` |

## 10. Cluster behavior

`target` places the instance on create. On an existing instance, a different `target` gives a warning, not a move.
The result `instance.location` shows the member.

## 11. Tests

| Target | Fixture | Cases |
|---|---|---|
| `lxd_instance` | `lxd/standalone` | C1 to C12 on a container. IN1 to IN9. |
| `lxd_instance_vm` | `lxd/standalone`, `lxd/needs/vm` | IN10 to IN12. |
| `lxd_instance_cluster` | `lxd/cluster` | IN13. |

| ID | Goal | Pass when |
|---|---|---|
| IN1 | `state: stopped` stops a running container. | `status` is `Stopped`. |
| IN2 | `state: frozen` freezes, and `started` thaws. | `status` is `Frozen`, then `Running`. |
| IN3 | `restarted` always reports a change. | `changed` is true on the second run. |
| IN4 | `wait_for: ipv4` returns an address. | `addresses.eth0` holds an IPv4 address. |
| IN5 | `profiles: []` removes all profiles. | The instance has no profiles. |
| IN6 | Profile devices do not count as instance devices. | `devices_mode: exact` with `{}` makes no change. |
| IN7 | A copy from a snapshot. | The copy has the file from the snapshot time. |
| IN8 | `force` deletes a running container in one call. | The container is gone. |
| IN9 | `present` keeps the run state. | A stopped instance stays stopped. |
| IN10 | A VM with `wait_for: agent`. | The agent answers. `state.processes` is more than 0. |
| IN11 | A key that needs a restart fails without `allow_restart`. | `msg` names the key. |
| IN12 | The same change with `allow_restart`. | `restarted` is true. The key has the new value. |
| IN13 | `target` places the instance on member 2. | `location` is member 2. |

VM tests use `test/alpine-vm` with `config: {"boot.mode": "uefi-nosecureboot"}`.

## 12. Hardware exceptions

GPU, PCI, USB, SR-IOV, and InfiniBand devices. Live migration between members. See section 13 of the testing framework.

## 13. Open questions

1. Should `state` default to `started`, as here, or to `present`? The community.general module uses `started`.
2. Should a different `target` on an existing instance move it? This spec warns only. A move is a rename-like action that the plan leaves out.
