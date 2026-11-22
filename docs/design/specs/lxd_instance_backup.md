# lxd_instance_backup

## 1. Purpose

Create and delete instance backups, and download a backup file to the controller.

## 2. API

| Path | Method | Response | Use |
|---|---|---|---|
| `/1.0/instances/{name}/backups/{backup}` | `GET` | sync | Read. |
| `/1.0/instances/{name}/backups` | `POST` | async | Create. |
| `/1.0/instances/{name}/backups/{backup}` | `DELETE` | async | Delete. |
| `/1.0/instances/{name}/backups/{backup}/export` | `GET` | file | Download. |

Required API extensions: `container_backup`. With `compression_algorithm`: `backup_compression_algorithm`.

## 3. Identity

`instance`, `name`, and `project`.

## 4. Options

| Option | Type | Default | Required | Rule |
|---|---|---|---|---|
| `instance` | str | | yes | The instance. |
| `name` | str | | yes | The backup name. |
| `project` | str | | no | The project. |
| `state` | str | `present` | no | `present` or `absent`. |
| `expires_at` | str | | no | Create-only. An RFC 3339 time. |
| `instance_only` | bool | `false` | no | Create-only. Leave out snapshots. |
| `optimized_storage` | bool | `false` | no | Create-only. Use the driver format. |
| `compression_algorithm` | str | | no | Create-only. For example `gzip`, `zstd`, or `none`. |
| `dest` | path | | no | A path on the controller. The module downloads the backup there. |
| `force_download` | bool | `false` | no | Download again even if `dest` exists with the same size. |

## 5. Computed keys

Not applicable.

## 6. Behavior per state

### `present`

| Case | Action |
|---|---|
| Absent | `POST .../backups` with the create-only options. Then download to `dest` if set. |
| Present | No new backup. Create-only options do not cause a change. Rule R10. |
| `dest` set and missing | Download. `changed: true`. |
| `dest` set and present | No download, unless `force_download` is true. |

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
  instance_only: false
  optimized_storage: false
dest: /srv/backups/web1-nightly.tar.gz
size: 104857600
```

## 9. Errors

| Case | Message |
|---|---|
| The project blocks backups. | The LXD error from `restricted.backups`. |
| `dest` is in a directory that does not exist. | `directory of dest does not exist: <dir>` |

## 10. Cluster behavior

None. LXD sends the request to the member of the instance.

## 11. Tests

Fixture: `lxd/standalone`. Standard cases C1 to C3 and C10 to C12. Skip C4 to C9, because backups have no update path.

| ID | Goal | Pass when |
|---|---|---|
| IB1 | `dest` downloads a tar archive. | The file exists and holds `backup/index.yaml`. |
| IB2 | A second run does not download again. | `changed` is false. |

## 12. Hardware exceptions

None.

## 13. Open questions

1. Should the collection have a module that imports an instance backup? The plan has none. A later spec can add `source.backup_path` to `lxd_instance`.
