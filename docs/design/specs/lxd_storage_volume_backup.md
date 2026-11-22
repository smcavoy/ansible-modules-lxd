# lxd_storage_volume_backup

## 1. Purpose

Create and delete backups of custom storage volumes, and download a backup file to the controller.

## 2. API

| Path | Method | Response | Use |
|---|---|---|---|
| `/1.0/storage-pools/{p}/volumes/custom/{v}/backups/{name}` | `GET` | sync | Read. |
| `/1.0/storage-pools/{p}/volumes/custom/{v}/backups` | `POST` | async | Create. |
| `/1.0/storage-pools/{p}/volumes/custom/{v}/backups/{name}` | `DELETE` | async | Delete. |
| `/1.0/storage-pools/{p}/volumes/custom/{v}/backups/{name}/export` | `GET` | file | Download. |

Required API extensions: `custom_volume_backup`.

## 3. Identity

`pool`, `volume`, `name`, `project`, and `target` for a local pool on a cluster.

## 4. Options

| Option | Type | Default | Required | Rule |
|---|---|---|---|---|
| `pool` | str | | yes | The storage pool. |
| `volume` | str | | yes | The custom volume. |
| `name` | str | | yes | The backup name. |
| `project` | str | | no | The project. |
| `target` | str | | no | The member of the volume. Rule R6. |
| `state` | str | `present` | no | `present` or `absent`. |
| `expires_at` | str | | no | Create-only. An RFC 3339 time. |
| `volume_only` | bool | `false` | no | Create-only. Leave out snapshots. |
| `optimized_storage` | bool | `false` | no | Create-only. Use the driver format. Restore then needs the same driver. |
| `compression_algorithm` | str | | no | Create-only. For example `gzip`, `xz`, or `none`. |
| `dest` | path | | no | A path on the controller. The module downloads the backup there. |
| `force_download` | bool | `false` | no | Download again even if `dest` exists with the same size. |

## 5. Computed keys

Not applicable.

## 6. Behavior per state

### `present`

| Case | Action |
|---|---|
| Absent | `POST .../backups` with the create-only options. Then download to `dest` if set. |
| Present | No new backup. Create-only options do not cause a change. |
| `dest` set and missing | Download. `changed: true`. |
| `dest` set and present | No download, unless `force_download` is true. The module does not compare the size, because LXD does not give it. |

The module downloads to a temporary file next to `dest`. Then it moves the file into place.

### `absent`

| Case | Action |
|---|---|
| Absent | No request. `changed: false`. |
| Present | `DELETE`. The module does not delete `dest`. |

## 7. Check and diff mode

The diff holds the backup name and `dest`. Check mode does not download.

## 8. Return values

| Key | Type | Rule |
|---|---|---|
| `backup` | dict | The backup from `GET`. `null` after a delete. |
| `dest` | str | The downloaded file, if `dest` is set. |
| `size` | int | The size of the downloaded file in bytes. |

```yaml
backup:
  name: nightly
  created_at: "2026-11-03T02:00:00Z"
  expires_at: "2026-11-10T02:00:00Z"
  volume_only: false
  optimized_storage: false
dest: /srv/backups/data-nightly.tar.gz
size: 52428800
```

## 9. Errors

| Case | Message |
|---|---|
| `dest` is in a directory that does not exist. | `directory of dest does not exist: <dir>` |
| The download stops early. | `download of backup <name> stopped after <n> bytes` |

## 10. Cluster behavior

Rule R6 for `target` on a local pool.

## 11. Tests

Fixture: `lxd/standalone`. Standard cases C1 to C3 and C10 to C12. Skip C4 to C9, because backups have no update path.

| ID | Goal | Pass when |
|---|---|---|
| VB1 | `dest` downloads a file. | The file exists and is a tar archive. |
| VB2 | A second run with `dest` does not download again. | `changed` is false. |
| VB3 | The downloaded file imports as a new volume. | `lxd_storage_volume` with `source.backup_path` makes a volume with the same file. |

## 12. Hardware exceptions

None.

## 13. Open questions

1. Should `dest` compare a checksum? LXD publishes neither a checksum nor a size for a backup. The module only checks that `dest` exists, as `lxd_instance_backup` does.
