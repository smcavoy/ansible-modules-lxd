# lxd_instance_snapshot

## 1. Purpose

Create, update, restore, and delete instance snapshots.

## 2. API

| Path | Method | Response | Use |
|---|---|---|---|
| `/1.0/instances/{name}/snapshots/{snapshot}` | `GET` | sync, `ETag` | Read. |
| `/1.0/instances/{name}/snapshots` | `POST` | async | Create. |
| `/1.0/instances/{name}/snapshots/{snapshot}` | `PUT` | async, checks `If-Match` | Update `expires_at`. |
| `/1.0/instances/{name}/snapshots/{snapshot}` | `DELETE` | async | Delete. |
| `/1.0/instances/{name}` | `PUT` | async | Restore, with `restore: <snapshot>`. |

Required API extensions: `instances`. With `expires_at` on create: `snapshot_expiry_creation`.
With `disk_volumes_mode`: `instance_snapshots_multi_volume`.

## 3. Identity

`instance`, `name`, and `project`.

## 4. Options

| Option | Type | Default | Required | Rule |
|---|---|---|---|---|
| `instance` | str | | yes | The instance. |
| `name` | str | | yes | The snapshot name. |
| `project` | str | | no | The project. |
| `state` | str | `present` | no | `present`, `absent`, or `restored`. |
| `stateful` | bool | `false` | no | Create-only. Save the running state. Needs `migration.stateful` on the instance. With `restored`, restore the running state. |
| `expires_at` | str | | no | An RFC 3339 time. `""` means "never expires". `null` means "do not manage". |
| `disk_volumes_mode` | str | | no | Create-only. `root` or `all-exclusive`. `all-exclusive` also snapshots attached custom volumes. |

## 5. Computed keys

Not applicable.

## 6. Behavior per state

### `present`

| Case | Action |
|---|---|
| Absent | `POST .../snapshots` with `name`, `stateful`, `expires_at`, and `disk_volumes_mode`. `expires_at: ""` goes as the zero time; without the field LXD uses `snapshots.expiry` of the instance. |
| Present, same | No request. `changed: false`. |
| Present, different `expires_at` | `PUT` with `expires_at`. |

### `restored`

| Case | Action |
|---|---|
| Absent | Fail. |
| Present | Read the instance. `PUT` the instance with `restore: <name>` and `stateful`. Always `changed: true`. |

### `absent`

| Case | Action |
|---|---|
| Absent | No request. `changed: false`. |
| Present | `DELETE`. |

## 7. Check and diff mode

The diff holds `expires_at`. For `restored`, the diff is empty and `changed` is true.

## 8. Return values

| Key | Type | Rule |
|---|---|---|
| `snapshot` | dict | The snapshot from `GET`, after the change. `null` after a delete. |

```yaml
snapshot:
  name: before-upgrade
  stateful: false
  created_at: "2026-11-03T10:00:00Z"
  expires_at: "0001-01-01T00:00:00Z"
  size: 2097152
  config:
    limits.cpu: "2"
```

## 9. Errors

| Case | Message |
|---|---|
| `restored` on a missing snapshot. | `snapshot <name> of instance <instance> not found` |
| `stateful` without `migration.stateful`. | The LXD error. |
| A bad `expires_at`. | `expires_at must be an RFC 3339 time` |

## 10. Cluster behavior

None. LXD sends the request to the member of the instance.

## 11. Tests

Fixture: `lxd/standalone`. Standard cases C1 to C5 and C9 to C12. Skip C6 to C8, because snapshots have no config.

| ID | Goal | Pass when |
|---|---|---|
| IS1 | `restored` brings back a deleted file. | The file exists again. |
| IS2 | `restored` always reports a change. | `changed` is true on the second run. |
| IS3 | `disk_volumes_mode: all-exclusive` snapshots an attached volume. | The volume has a snapshot whose description names the instance snapshot. |

## 12. Hardware exceptions

Stateful snapshots of VMs need nested KVM. The sandbox has it. Mark that case `lxd/needs/vm`.

## 13. Open questions

None. The source confirms the two `disk_volumes_mode` values.

## 14. Findings from the tests

1. With `all-exclusive`, LXD names each volume snapshot after the snapshot pattern of the volume, for example `snap0`.
   The description of the volume snapshot is `Created alongside container <instance>/<snapshot> snapshot in project <project>`.
