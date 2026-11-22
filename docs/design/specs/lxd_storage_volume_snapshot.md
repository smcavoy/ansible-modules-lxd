# lxd_storage_volume_snapshot

## 1. Purpose

Create, update, restore, and delete snapshots of custom storage volumes.

## 2. API

| Path | Method | Response | Use |
|---|---|---|---|
| `/1.0/storage-pools/{p}/volumes/custom/{v}/snapshots/{name}` | `GET` | sync, `ETag` | Read. |
| `/1.0/storage-pools/{p}/volumes/custom/{v}/snapshots` | `POST` | async | Create. |
| `/1.0/storage-pools/{p}/volumes/custom/{v}/snapshots/{name}` | `PUT` | async, checks `If-Match` | Update `description` and `expires_at`. |
| `/1.0/storage-pools/{p}/volumes/custom/{v}/snapshots/{name}` | `DELETE` | async | Delete. |
| `/1.0/storage-pools/{p}/volumes/custom/{v}` | `PUT` | async | Restore, with `restore: <name>`. |

Required API extensions: `storage_api_volume_snapshots`. With `expires_at`: `custom_volume_snapshot_expiry`.

## 3. Identity

`pool`, `volume`, `name`, `project`, and `target` for a local pool on a cluster.

## 4. Options

| Option | Type | Default | Required | Rule |
|---|---|---|---|---|
| `pool` | str | | yes | The storage pool. |
| `volume` | str | | yes | The custom volume. |
| `name` | str | | yes | The snapshot name. |
| `project` | str | | no | The project. |
| `target` | str | | no | The member of the volume. Rule R6. |
| `state` | str | `present` | no | `present`, `absent`, or `restored`. |
| `description` | str | | no | `null` means "do not manage". |
| `expires_at` | str | | no | An RFC 3339 time. `""` means "never expires". `null` means "do not manage". |

## 5. Computed keys

Not applicable. A snapshot has no config to manage.

## 6. Behavior per state

### `present`

| Case | Action |
|---|---|
| Absent | `POST .../snapshots` with `name`, `description`, and `expires_at`. |
| Present, same | No request. `changed: false`. |
| Present, different | `PUT` with `description` and `expires_at`. |

### `restored`

| Case | Action |
|---|---|
| Absent | Fail. A missing snapshot cannot be restored. |
| Present | Read the volume. `PUT` the volume with its current `config`, `description`, and `restore: <name>`. Always `changed: true`. |

A volume in use by a running instance cannot be restored on most drivers. The module passes the LXD error on.

### `absent`

| Case | Action |
|---|---|
| Absent | No request. `changed: false`. |
| Present | `DELETE`. |

## 7. Check and diff mode

The diff holds `description` and `expires_at`. For `restored`, the diff is empty and `changed` is true.

## 8. Return values

| Key | Type | Rule |
|---|---|---|
| `snapshot` | dict | The snapshot from `GET`, after the change. `null` after a delete. |

```yaml
snapshot:
  name: before-upgrade
  description: ""
  content_type: filesystem
  created_at: "2026-11-03T10:00:00Z"
  expires_at: "2026-11-10T10:00:00Z"
  config:
    size: 5GiB
```

## 9. Errors

| Case | Message |
|---|---|
| `restored` on a missing snapshot. | `snapshot <name> of volume <volume> not found` |
| The volume does not exist. | `storage volume <volume> not found in pool <pool>` |
| A bad `expires_at`. | `expires_at must be an RFC 3339 time` |

## 10. Cluster behavior

Rule R6 for `target` on a local pool.

## 11. Tests

Fixture: `lxd/standalone`. Standard cases C1 to C5 and C9 to C12. Skip C6 to C8, because snapshots have no config.

| ID | Goal | Pass when |
|---|---|---|
| VS1 | `restored` brings back a deleted file. | The file exists again in an instance that uses the volume. |
| VS2 | `restored` always reports a change. | `changed` is true on the second run. |
| VS3 | `expires_at: ""` clears the expiry. | The server has no expiry. |

## 12. Hardware exceptions

None.

## 13. Open questions

None.
