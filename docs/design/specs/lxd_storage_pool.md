# lxd_storage_pool

## 1. Purpose

Create, update, and delete LXD storage pools for all drivers, on standalone servers and clusters.

## 2. API

| Path | Method | Response | Use |
|---|---|---|---|
| `/1.0/storage-pools/{name}` | `GET` | sync, `ETag` | Read. With `?target=<member>`, read the local keys of one member. |
| `/1.0/storage-pools` | `POST` | async | Create. With `?target=<member>`, create the pending member part. |
| `/1.0/storage-pools/{name}` | `PUT` | async, checks `If-Match` | Update. With `?target=<member>`, update local keys. |
| `/1.0/storage-pools/{name}` | `DELETE` | async | Delete. |

Required API extensions: `storage`. The module checks the driver against `environment.storage_supported_drivers` from `GET /1.0`.

## 3. Identity

`name`. Pools are global, not per project.

## 4. Options

| Option | Type | Default | Required | Rule |
|---|---|---|---|---|
| `name` | str | | yes | The pool name. It cannot hold `/`. |
| `state` | str | `present` | no | `present` or `absent`. |
| `driver` | str | | yes for create | Create-only. `dir`, `zfs`, `btrfs`, `lvm`, `ceph`, `cephfs`, `cephobject`, `powerflex`, `pure`, `powerstore`, or `alletra`. |
| `description` | str | | no | `null` means "do not manage". |
| `config` | dict | | no | Rule R4. |
| `config_mode` | str | `merge` | no | Rule R4. |
| `member_config` | dict | | no | Rule R6. Member name to local keys. |

## 5. Computed keys

The table in section 5.6 of the module plan, by driver. For example, `dir` has `source`, and `zfs` has `source`, `size`, and `zfs.pool_name`.
A computed key counts only when the task does not set it.

## 6. Behavior per state

### `present`

| Case | Action |
|---|---|
| Absent, standalone | `POST /1.0/storage-pools` with `name`, `driver`, `description`, and `config`. |
| Absent, cluster | The pending-then-global flow from rule R6. |
| Present, `Pending` or `Errored` | Fail: `The storage pool <name> has the status <status>: its cluster create did not finish ...`. The message names the members and says to remove the object with `state=absent` and run the task again. No write. The module does not complete the create. |
| Present, same | No request. `changed: false`. |
| Present, different | `PUT` the global keys. Then `PUT ?target=<member>` for each member whose local keys differ. |
| `driver` differs | Warn and continue. Rule R10. |

Many driver keys can only be set on create, for example `source` and `zfs.pool_name`.
LXD rejects a change of these keys. The module passes the LXD error on.

### `absent`

| Case | Action |
|---|---|
| Absent | No request. `changed: false`. |
| Present | `DELETE`. |

A delete of a pool that LXD created destroys its data. For `zfs`, LXD runs `zpool destroy` on a pool that it made.
The module documentation states this in a `notes` entry.

## 7. Check and diff mode

The diff holds `description`, `config`, and, on a cluster, `members`.

## 8. Return values

| Key | Type | Rule |
|---|---|---|
| `storage_pool` | dict | The pool from `GET`, after the change. `null` after a delete. |
| `storage_pool.members` | dict | On a cluster: member name to local keys. |

```yaml
storage_pool:
  name: t-ab12-pool
  driver: dir
  status: Created
  description: ""
  config:
    source: /var/snap/lxd/common/lxd/storage-pools/t-ab12-pool
  locations:
    - none
  used_by: []
```

## 9. Errors

| Case | Message |
|---|---|
| The driver is not available on the server. | `Storage driver <driver> is not available. Available: <list>` |
| Delete a pool in use. | The LXD error `The storage pool is currently in use` |
| A create-only key changes. | The LXD validation error. |
| A local key without `target` on `PUT`. | The module splits the keys, so LXD never sees this. |

## 10. Cluster behavior

Rule R6. The local keys per driver are in section 5.8 of the module plan.
A test confirmed the create flow for a `dir` pool on 3 members.
A create with a local key and no `target` fails inside the LXD operation, not with `400`. So the module splits the keys first.

## 11. Tests

| Target | Fixture | Cases |
|---|---|---|
| `lxd_storage_pool` | `lxd/standalone` | C1 to C12 for `dir`. S1 to S3. |
| `lxd_storage_pool_drivers` | `lxd/standalone` | S4 for `zfs`, `btrfs`, and `lvm` on loop files. |
| `lxd_storage_pool_cluster` | `lxd/cluster` | S5 and S6. |
| `lxd_storage_pool_ceph` | `lxd/ceph` | C1 to C5, C10 to C12 for `ceph` and `cephfs`. The `dir` target covers C6 to C9, because the config code does not depend on the driver. |

| ID | Goal | Pass when |
|---|---|---|
| S1 | A change of `driver` gives a warning. | `changed` is false. `warnings` names `driver`. |
| S2 | `exact` keeps the computed key `source`. | `source` stays. `changed` is false. |
| S3 | A missing driver fails early. | `msg` holds `not available`. No request is sent. The test picks a driver that the server does not list, and skips when the server lists all. |
| S4 | Each loop-backed driver creates and deletes. | Each pool reaches `Created`, then goes away. |
| S5 | `member_config` gives each member its own `source`. | Each member shows its own path. |
| S6 | A second run on the cluster makes no change. | `changed` is false. |

## 12. Hardware exceptions

`pure`, `powerflex`, `powerstore`, and `alletra` need storage arrays. Unit tests cover the request body.

## 13. Open questions

None.

## 14. Findings from the tests

1. LXD lists some drivers in `storage_supported_drivers` without the hardware, for example `pure`.
   A create with such a driver passes the early check and fails inside the LXD operation.
2. A `PATCH` on a pool merges the config. The module uses `PUT` with the full config.
